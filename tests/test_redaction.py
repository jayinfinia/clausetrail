"""Redaction stage: detection, file engines, scoring, local-model guard and app import. Fictional data only."""
import io
import os
import shutil
import tempfile
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='tracking-tests-'))
os.environ.setdefault('RUN_WORKER', 'false')
os.environ.setdefault('SESSION_SECRET', 'test-secret-not-for-deployment')
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db import Base, engine, migrate
from backend.redaction import detect, engines, evaluate, llm
from scripts import make_redaction_samples as samples

FORM = 'Member Name: Avery Q. Fictional\nPrint: Avery Q. Fictional\n412-55-0198\nFed. Tax ID/Social Security Number\n' \
       'Address: 18 Imaginary Trail, Ste 4\nSampletown, VA 22901\nEmail: avery@example.com\nDate of birth: 04/05/1980\n' \
       'Routing number: 021000021\nEffective 2023-05-16, 20,000 Units, $0.00.'


def found(text, policy='standard', model=None):
    spans, _ = detect.find(text, policy, model)
    return [(text[s:e], c) for s, e, c, _ in spans]


class DetectTests(unittest.TestCase):
    def test_standard_policy_scope(self):
        got = found(FORM)
        self.assertIn(('412-55-0198', 'GOV_ID'), got); self.assertIn(('04/05/1980', 'DOB'), got); self.assertIn(('021000021', 'FIN_ACCOUNT'), got)
        self.assertFalse([v for v, c in got if c in ('PERSON', 'EMAIL', 'ADDRESS')])  # names, address, email stay
        self.assertFalse([v for v, _ in got if '2023' in v or 'Units' in v or '$' in v])  # dates, units, money stay

    def test_birth_date_written_as_phrase(self):
        got = found('The Consultant, born on March 4, 1985, resides in Sampletown. The Effective Date is March 4, 2024.')
        self.assertIn(('March 4, 1985', 'DOB'), got)
        self.assertNotIn(('March 4, 2024', 'DOB'), got)  # an ordinary agreement date is kept

    def test_strict_adds_people_and_contacts(self):
        cats = {c for _, c in found(FORM, 'strict')}
        self.assertTrue({'PERSON', 'EMAIL', 'ADDRESS', 'GOV_ID'} <= cats)
        self.assertNotIn(('Avery Q. Fictional\nPrint', 'PERSON'), found(FORM, 'strict'))

    def test_ids_need_shape_or_context(self):
        self.assertEqual(found('Order 123456789 shipped'), [])
        self.assertEqual(found('Taxpayer identification number: 123456789'), [('123456789', 'GOV_ID')])
        self.assertEqual(found('EIN 54-1234567'), [('54-1234567', 'GOV_ID')])
        self.assertEqual(found('Card 4111 1111 1111 1111 ok'), [('4111 1111 1111 1111', 'FIN_ACCOUNT')])
        self.assertEqual(found('Card 4111 1111 1111 1112 ok'), [])  # fails Luhn
        self.assertEqual(found('Part 000-12-3456 shipped'), [])  # invalid SSN area, no ID label

    def test_model_output_must_exist_in_text_and_policy(self):
        fake = lambda text, cats: [('Avery Q. Fictional', 'PERSON'), ('999-99-9999', 'GOV_ID'), ('Sampletown', 'ADDRESS')]
        self.assertNotIn('Avery Q. Fictional', [v for v, _ in found(FORM, 'standard', fake)])  # PERSON not in standard
        got = found(FORM, 'strict', fake)
        self.assertEqual(sum(1 for v, _ in got if v == 'Avery Q. Fictional'), 2)  # both occurrences
        self.assertNotIn('999-99-9999', [v for v, _ in got])  # invented value ignored

    def test_model_failure_falls_back_to_rules(self):
        def broken(text, cats): raise RuntimeError('offline')
        spans, warnings = detect.find(FORM, 'standard', broken)
        self.assertTrue(spans); self.assertIn('Local model step skipped', warnings[0])


class LocalModelGuardTests(unittest.TestCase):
    def test_only_loopback_ollama(self):
        old = os.environ.get('OLLAMA_URL')
        try:
            for bad in ('https://api.example.com', 'http://10.0.0.5:11434', 'http://user:pw@localhost:11434'):
                os.environ['OLLAMA_URL'] = bad
                with self.assertRaises(llm.Unavailable): llm.base_url()
            os.environ['OLLAMA_URL'] = 'http://127.0.0.1:1'  # nothing listening
            self.assertFalse(llm.status()['ready'])
        finally:
            if old is None: os.environ.pop('OLLAMA_URL', None)
            else: os.environ['OLLAMA_URL'] = old


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp()); samples.main(cls.dir)

    def run_file(self, rel, policy='standard'):
        p = self.dir / rel; red, report, texts = engines.redact_file(p.read_bytes(), p.name, policy)
        return p.read_bytes(), red, report, texts

    def test_docx_table_labels_and_no_leak(self):
        orig, red, report, texts = self.run_file('Investors/Riley Sample/Riley Sample - Investor Information Form.docx')
        self.assertEqual(report['redactions'], 4)
        out = evaluate.extract_text(red, 'x.docx')
        for value in ('587-21-0934', '03/14/1979', '011000015', '9876543210'): self.assertNotIn(value, out)
        self.assertIn('Riley Sample', out); self.assertIn('[REDACTED SSN / tax ID]', out)

    def test_xlsx_whole_cell_and_scores(self):
        rel = 'Admin/Member Roster.xlsx'
        orig, red, report, texts = self.run_file(rel)
        ref = (self.dir / 'Admin/Member Roster Redacted.xlsx').read_bytes()
        score = evaluate.text_pair(orig, ref, texts, rel)
        self.assertEqual((score['recall'], score['precision']), (1.0, 1.0))
        self.assertNotIn('601-44-7720', evaluate.extract_text(red, rel))

    def test_text_pdf_removes_text_not_just_covers(self):
        orig, red, report, _ = self.run_file('Investors/Riley Sample/Riley Sample - Wire Instructions.pdf')
        self.assertEqual(report['engine'], 'pdf-text')
        text = evaluate.extract_text(red, 'x.pdf')
        self.assertNotIn('0012345678', text); self.assertIn('Example Community Bank', text)

    def test_txt_without_identifiers_is_untouched(self):
        orig, red, report, _ = self.run_file('Suppliers/Aster Fictional Labs/Aster Fictional Labs - Northwind Labs - CDA - 20260101 - EXECUTED.txt')
        self.assertEqual((report['redactions'], red), (0, orig))

    def test_strict_pseudonyms_and_paths(self):
        _, red, report, texts = self.run_file('Investors/Riley Sample/Riley Sample - Investor Information Form.docx', 'strict')
        out = evaluate.extract_text(red, 'x.docx')
        self.assertIn('[PERSON 1]', out); self.assertNotIn('Riley Sample', out)
        self.assertEqual(engines.redact_path_segments('Investors/Riley Sample/Riley Sample - Form.docx', texts, 'strict'),
                         'Investors/REDACTED/REDACTED - Form.docx')

    def test_unsupported_and_bad_policy(self):
        with self.assertRaises(ValueError): engines.redact_file(b'x', 'a.pptx')
        with self.assertRaises(ValueError): engines.redact_file(b'x', 'a.txt', 'loose')

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract not installed')
    def test_scanned_pdf_burns_pixels_and_matches_reference(self):
        rel = 'Investors/Avery Fictional/Avery Fictional - Membership Signature Page.pdf'
        orig, red, report, _ = self.run_file(rel)
        self.assertEqual((report['engine'], report['by_category']), ('pdf-ocr', {'GOV_ID': 1}))
        import pymupdf
        self.assertEqual(pymupdf.open(stream=red, filetype='pdf')[0].get_text().strip(), '')  # image only, no hidden text
        self.assertEqual(evaluate.leak_check(red, 'x.pdf', 'standard')['still_visible'], 0)
        self.assertIn('Avery', evaluate.extract_text(red, 'x.pdf'))  # standard policy keeps names
        ref = (self.dir / rel.replace('.pdf', ' Redacted.pdf')).read_bytes()
        score = evaluate.image_pair(orig, ref, red)
        self.assertEqual((score['reference_boxes'], score['reference_boxes_covered']), (1, 1))
        self.assertGreater(score['pixel_precision'], 0.8)

    def test_reference_naming(self):
        self.assertTrue(evaluate.is_reference('X - Signature Page_Redacted.pdf'))
        self.assertEqual(evaluate.base_name('MEMBER PAGE - X (002)_Redacted.pdf'), evaluate.base_name('MEMBER PAGE - X.pdf'))


class AppImportTests(unittest.TestCase):
    def setUp(self):
        migrate(); Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
        self.c = TestClient(app); self.c.__enter__()
        r = self.c.post('/api/auth/demo', json={'username': 'alex'}); self.c.headers['X-CSRF-Token'] = r.json()['csrf']

    def tearDown(self): self.c.__exit__(None, None, None)

    def test_only_redacted_copy_is_stored(self):
        doc = b'Agreement type: CDA\nCounterparty: Oriole Fictional Labs\nTaxpayer identification number: 412-55-0198\n'
        r = self.c.post('/api/imports', files=[('files', ('form.txt', doc, 'text/plain'))],
                        data={'scope': 'research', 'redact': 'standard', 'paths': ['Set/Investors/Oriole Fictional Labs/form.txt']})
        res = r.json()['results'][0]; self.assertEqual(res['redaction']['redactions'], 1)
        stored = self.c.get(f"/api/agreements/{res['id']}/source").content
        self.assertNotIn(b'412-55-0198', stored); self.assertIn(b'Oriole Fictional Labs', stored)
        rec = self.c.get('/api/agreements/' + res['id']).json()
        self.assertEqual(rec['labels']['redaction']['by_category'], {'GOV_ID': 1})
        self.assertNotIn('412-55-0198', str(rec['labels']))

    def test_status_and_bad_policy(self):
        st = self.c.get('/api/redaction/status').json()
        self.assertIn('SSN / tax ID', st['policies']['standard']); self.assertIn('ready', st['llm'])
        r = self.c.post('/api/imports', files=[('files', ('a.txt', b'x', 'text/plain'))], data={'scope': 'research', 'redact': 'everything'})
        self.assertEqual(r.status_code, 422)


if __name__ == '__main__':
    unittest.main()
