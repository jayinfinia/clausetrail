"""Claude tagging (mocked) and the redaction fixes found on a real e-signed CDA. Fictional data only."""
import os
import tempfile
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='tracking-tests-'))
os.environ.setdefault('RUN_WORKER', 'false')
os.environ.setdefault('SESSION_SECRET', 'test-secret-not-for-deployment')
import unittest
from unittest import mock
from fastapi.testclient import TestClient
from backend import tagging
from backend.api.main import app
from backend.db import Base, engine, migrate
from backend.redaction import detect, engines, evaluate
from backend.services.extraction import validate_value
from backend.services.worker import process_one

CDA = ('CONFIDENTIALITY AGREEMENT\nNorthwind Labs, LLC ("we") may provide the undersigned ("you") with information about us.\n'
       '9. This Agreement will terminate in two (2) years from the last date below, and is governed by Delaware law.\n'
       'Northwind Labs Confidentiality Agreement-Investor Form\nUndersigned: Oriole Q. Fictional\nDate: 2023-05-03\n')
BLOCKS = [{'id': 'b1', 'locator': 'Page 1', 'text': CDA}]


def fake_result(quote='terminate in two (2) years from the last date below'):
    return {'facts': {
        'agreement_type': {'value': 'CDA', 'passage': 'p1', 'quote': 'CONFIDENTIALITY AGREEMENT'},
        'counterparty': {'value': 'Oriole Q. Fictional', 'passage': 'p1', 'quote': 'Undersigned: Oriole Q. Fictional'},
        'effective_date': {'value': '2023-05-03', 'passage': 'p1', 'quote': 'Date: 2023-05-03'},
        'expiration_date': {'value': '2025-05-03', 'passage': 'p1', 'quote': quote, 'note': 'Two years after 2023-05-03.'},
        'notice_days': {'value': 'thirty', 'passage': 'p1', 'quote': 'x'},  # invalid type: dropped
        'renewal': {'value': None}},
        'labels': {'relationship_type': 'Investor', 'primary_type': 'Confidential Disclosure Agreement', 'direction': 'Outbound',
                   'status': 'Executed', 'components': ['Confidentiality'], 'owner': None, 'end_rule': 'fixed'}}


class TaggingUnitTests(unittest.TestCase):
    def test_grounded_proposals(self):
        _, ids = tagging.build_payload(BLOCKS, 'x.pdf', '')
        props = tagging.to_proposals(fake_result(), ids, validate_value)
        self.assertEqual(props['expiration_date'], {'value': '2025-05-03', 'evidence': 'b1', 'state': 'proposed', 'method': 'claude', 'note': 'Two years after 2023-05-03.'})
        self.assertEqual(props['counterparty']['value'], 'Oriole Q. Fictional')
        self.assertNotIn('notice_days', props); self.assertNotIn('renewal', props)

    def test_quote_not_in_text_needs_evidence(self):
        _, ids = tagging.build_payload(BLOCKS, 'x.pdf', '')
        props = tagging.to_proposals(fake_result(quote='expires on a date we made up'), ids, validate_value)
        self.assertEqual((props['expiration_date']['state'], props['expiration_date']['evidence']), ('needs_evidence', None))

    def test_labels_merge_and_respect_confirmation(self):
        changes = tagging.to_labels(fake_result())
        merged = tagging.merge_labels({'rel': 'Unclassified', 'confirmed': False, 'redaction': {'x': 1}}, changes)
        self.assertEqual((merged['rel'], merged['kind'], merged['status'], merged['party'], merged['eff']),
                         ('Investor', 'CDA', 'Executed', 'Oriole Q. Fictional', '2023-05-03'))
        self.assertIn('Claude', merged['suggestedFrom']); self.assertIn('redaction', merged)
        confirmed = {'rel': 'Funder', 'confirmed': True}
        self.assertEqual(tagging.merge_labels(confirmed, changes), confirmed)

    def test_redacted_party_not_used(self):
        r = fake_result(); r['facts']['counterparty']['value'] = '[PERSON 1]'
        self.assertNotIn('party', tagging.to_labels(r))

    def test_real_documents_must_be_redacted_first(self):
        self.assertFalse(tagging.allowed({}, private_local=True))
        self.assertTrue(tagging.allowed({'redaction': {'policy': 'standard'}}, private_local=True))
        self.assertTrue(tagging.allowed({}, private_local=False))  # fictional demo data

    def test_destination_fixed_and_off_by_default(self):
        self.assertTrue(tagging.API_URL.startswith('https://api.anthropic.com/'))
        with mock.patch.dict(os.environ, {'CLAUDE_TAGGING': 'off', 'ANTHROPIC_API_KEY': 'k'}):
            self.assertFalse(tagging.enabled())
        with mock.patch.dict(os.environ, {'CLAUDE_TAGGING': 'on'}, clear=False):
            os.environ.pop('ANTHROPIC_API_KEY', None)
            self.assertFalse(tagging.enabled())


class WorkerTaggingTests(unittest.TestCase):
    def setUp(self):
        migrate(); Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
        self.c = TestClient(app); self.c.__enter__()
        r = self.c.post('/api/auth/demo', json={'username': 'alex'}); self.c.headers['X-CSRF-Token'] = r.json()['csrf']

    def tearDown(self): self.c.__exit__(None, None, None)

    def upload(self, redact):
        r = self.c.post('/api/imports', files=[('files', ('cda.txt', CDA.encode(), 'text/plain'))], data={'scope': 'research', 'redact': redact})
        return r.json()['results'][0]['id']

    def test_worker_fills_fields_and_labels(self):
        rid = self.upload('standard')
        env = {'CLAUDE_TAGGING': 'on', 'ANTHROPIC_API_KEY': 'test', 'PRIVATE_LOCAL': 'true'}
        with mock.patch.dict(os.environ, env), mock.patch.object(tagging, 'call_claude', return_value=fake_result()) as call:
            process_one()
        sent = call.call_args[0][0]
        self.assertIn('PASSAGES', sent)
        rec = self.c.get('/api/agreements/' + rid).json()
        self.assertEqual(rec['proposals']['expiration_date']['value'], '2025-05-03')
        self.assertEqual(rec['proposals']['agreement_type']['method'], 'claude')
        self.assertEqual(rec['labels']['rel'], 'Investor'); self.assertEqual(rec['labels']['tagging']['status'], 'done')
        self.assertEqual(rec['approved'], {})  # still proposals until a reviewer approves

    def test_unredacted_real_document_is_never_sent(self):
        rid = self.upload('off')
        env = {'CLAUDE_TAGGING': 'on', 'ANTHROPIC_API_KEY': 'test', 'PRIVATE_LOCAL': 'true'}
        with mock.patch.dict(os.environ, env), mock.patch.object(tagging, 'call_claude') as call:
            process_one()
        call.assert_not_called()
        self.assertEqual(self.c.get('/api/agreements/' + rid).json()['labels']['tagging']['status'], 'skipped')

    def test_claude_failure_keeps_document_reviewable(self):
        rid = self.upload('standard')
        env = {'CLAUDE_TAGGING': 'on', 'ANTHROPIC_API_KEY': 'test', 'PRIVATE_LOCAL': 'true'}
        with mock.patch.dict(os.environ, env), mock.patch.object(tagging, 'call_claude', side_effect=tagging.TaggingUnavailable('Could not reach Claude')):
            process_one()
        rec = self.c.get('/api/agreements/' + rid).json()
        self.assertEqual((rec['status'], rec['labels']['tagging']['status']), ('needs_review', 'failed'))


class RedactionFixTests(unittest.TestCase):
    def test_esign_audit_trail_names_and_ips(self):
        t = ('Document approved by Jordan B. EXample (jordan@example.com)\nSigner entered name at signing as Jordan B. EXample\n'
             'P.Q.Example, Jr. (May 3, 2023 18:01 EDT)\nP.Q.Example, Jr.\nIP address: 71.62.10.205\nVersion 1.2.3')
        spans, _ = detect.find(t, 'strict'); got = [(t[a:b], c) for a, b, c, _ in spans]
        self.assertEqual(sum(1 for v, c in got if v == 'Jordan B. EXample'), 2)
        self.assertEqual(sum(1 for v, c in got if v == 'P.Q.Example, Jr.'), 2)
        self.assertIn(('71.62.10.205', 'IP'), got); self.assertNotIn('1.2.3', [v for v, _ in got])
        self.assertEqual(detect.find(t, 'standard')[0], [])  # standard keeps names so reviewers can read the parties

    def test_text_pdf_boxes_do_not_clip_neighbouring_words(self):
        import pymupdf
        d = pymupdf.open(); p = d.new_page()
        p.insert_text((72, 72), 'Document emailed to jordan@example.com for approval', fontsize=11)
        p.insert_text((72, 90), 'Signed: Jordan Example', fontsize=11)
        red, report, _ = engines.redact_file(d.tobytes(), 'x.pdf', 'strict')
        text = evaluate.extract_text(red, 'x.pdf')
        self.assertIn('for approval', text); self.assertIn('Signed:', text)
        self.assertNotIn('jordan@example.com', text); self.assertNotIn('Jordan Example', text)


if __name__ == '__main__':
    unittest.main()
