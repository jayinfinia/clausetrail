"""Import hardening: block segmentation, locators, OCR warnings, Word structure, trackers and unreadable files.

Every file is generated here from fictional text; no binary fixtures are committed."""
import os
import shutil
import tempfile
from pathlib import Path
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='tracking-tests-'))
os.environ.setdefault('RUN_WORKER', 'false')
os.environ.setdefault('SESSION_SECRET', 'test-secret-not-for-deployment')
import unittest
from backend.services.parsers import parse, parse_document, ParseError, split_long, join_lines, tracker_columns
from backend.services.extraction import extract
from backend.services.grounded_qa import exact_quote

OCR = bool(shutil.which('tesseract') and shutil.which('pdftoppm'))
CLAUSES = [
    '1. Definitions. "Confidential Information" means information that one party discloses to the other for the '
    'evaluation, whether oral or written, and that is marked as confidential when it is disclosed.',
    '(a) Exclusions. Confidential Information does not include information that becomes public through no fault of '
    'the receiving party.',
    '2. Term. This Agreement continues for two years and may be renewed by a written agreement signed by both parties '
    'within 30 days of expiry.',
    'Each party shall protect the other party\'s information with reasonable care, and in no event with less care than '
    'it uses for its own information of similar importance.',
]

def wrap(text, width=78):
    import textwrap
    return textwrap.wrap(text, width)

def text_pdf(path, paragraphs, pages=1, header=True, hyphen=False):
    from reportlab.pdfgen.canvas import Canvas
    canvas = Canvas(str(path), pagesize=(612, 792))
    for page in range(pages):
        if header:
            canvas.setFont('Helvetica', 8)
            canvas.drawString(60, 760, 'Fictional Mutual NDA - Northwind Labs / Example Co. - CONFIDENTIAL')
            canvas.drawString(290, 30, f'Page {page + 1} of {pages}')
        y = 700
        canvas.setFont('Helvetica', 11)
        for p in paragraphs:
            lines = wrap(p)
            if hyphen and p.startswith('2.'):
                lines = ['2. Term. This Agreement continues for two years and may be renewed by a written agree-',
                         'ment signed by both parties within 30 days of expiry.']
            for line in lines:
                canvas.drawString(60 + (18 if p.startswith('(') else 0), y, line); y -= 14
            y -= 10
        canvas.showPage()
    canvas.save()

def scanned_pdf(path, paragraphs, angle=0, blur=False):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    image = Image.new('L', (1700, 2200), 255); draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30); y = 150
    for p in paragraphs:
        for line in wrap(p, 70):
            draw.text((120, y), line, fill=0, font=font); y += 42
        y += 30
    if angle:
        image = image.rotate(angle, fillcolor=255)
    if blur:
        image = image.resize((566, 733)).resize((1700, 2200)).filter(ImageFilter.GaussianBlur(2.4))
    canvas = Canvas(str(path), pagesize=(612, 792))
    canvas.drawImage(ImageReader(image.convert('RGB')), 0, 0, width=612, height=792); canvas.save()

class PdfBlocksTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='import-tests-'))
    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_text_pdf_paragraph_blocks_without_running_headers(self):
        text_pdf(self.dir / 'a.pdf', CLAUSES, pages=2, hyphen=True)
        result = parse_document(self.dir / 'a.pdf', '.pdf')
        blocks = result['blocks']
        self.assertEqual(result['engine'], 'pdf-text')
        self.assertEqual([b['locator'] for b in blocks[:4]], [f'Page 1, paragraph {n}' for n in range(1, 5)])
        self.assertEqual(blocks[4]['locator'], 'Page 2, paragraph 1')
        self.assertEqual(len(blocks), 8)
        self.assertTrue(blocks[0]['text'].startswith('1. Definitions.') and blocks[0]['text'].endswith('when it is disclosed.'))
        self.assertTrue(blocks[1]['text'].startswith('(a) Exclusions.'))
        self.assertIn('a written agreement signed by both parties', blocks[2]['text'])   # hyphenated break re-joined
        text = ' '.join(b['text'] for b in blocks)
        self.assertNotIn('CONFIDENTIAL', text); self.assertNotIn('of 2', text)
        # A quote that crosses a wrapped line in the PDF still passes the exact-quote check against its block.
        self.assertIsNotNone(exact_quote('whether oral or written, and that is marked as confidential', blocks[0]['text']))

    def test_label_lines_stay_separate_for_exact_label_extraction(self):
        lines = ['FICTIONAL DEMO DOCUMENT', 'Agreement type: MTA', 'Counterparty: Elm Fictional University', 'Expiration date: 2027-03-01',
                 'The recipient must not redistribute materials to third parties.']
        from reportlab.pdfgen.canvas import Canvas
        canvas = Canvas(str(self.dir / 'l.pdf'))
        for i, line in enumerate(lines):
            canvas.drawString(40, 800 - i * 22, line)
        canvas.save()
        blocks = parse(self.dir / 'l.pdf', '.pdf')
        self.assertEqual(len(blocks), 5)
        found = extract(blocks)
        self.assertEqual(found['counterparty']['value'], 'Elm Fictional University')
        self.assertEqual(found['expiration_date']['value'], '2027-03-01')
        self.assertEqual(found['counterparty']['evidence'], '3')

    def test_paragraph_continuing_on_next_page_is_one_block(self):
        from reportlab.pdfgen.canvas import Canvas
        canvas = Canvas(str(self.dir / 'c.pdf'), pagesize=(612, 792))
        canvas.drawString(60, 700, '1. Payment. Client will pay each correct invoice within forty-five days of receipt')
        canvas.showPage()
        canvas.drawString(60, 700, 'and late amounts accrue interest at one percent per month.')
        canvas.drawString(60, 670, '2. Governing law. Delaware law governs this Agreement.')
        canvas.save()
        blocks = parse(self.dir / 'c.pdf', '.pdf')
        self.assertEqual(blocks[0]['locator'], 'Page 1, paragraph 1 (continues on page 2)')
        self.assertTrue(blocks[0]['text'].endswith('one percent per month.'))
        self.assertEqual(blocks[1]['locator'], 'Page 2, paragraph 2')

    def test_password_protected_pdf_has_a_clear_code(self):
        from reportlab.pdfgen.canvas import Canvas
        canvas = Canvas(str(self.dir / 'p.pdf'), encrypt='fictional-secret')
        canvas.drawString(60, 700, 'Fictional protected agreement text.'); canvas.save()
        with self.assertRaises(ParseError) as caught:
            parse_document(self.dir / 'p.pdf', '.pdf')
        self.assertIn('password_protected', str(caught.exception))

    def test_damaged_and_empty_pdf(self):
        (self.dir / 'd.pdf').write_bytes(b'%PDF-1.7 damaged'); (self.dir / 'e.pdf').write_bytes(b'')
        with self.assertRaisesRegex(ParseError, 'damaged'):
            parse_document(self.dir / 'd.pdf', '.pdf')
        with self.assertRaisesRegex(ParseError, 'empty'):
            parse_document(self.dir / 'e.pdf', '.pdf')

@unittest.skipUnless(OCR, 'Tesseract and Poppler are required for OCR tests')
class OcrTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='ocr-tests-'))
    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_scan_becomes_paragraph_blocks(self):
        scanned_pdf(self.dir / 's.pdf', CLAUSES)
        result = parse_document(self.dir / 's.pdf', '.pdf')
        self.assertEqual(result['engine'], 'pdf-ocr'); self.assertEqual(result['warnings'], [])
        self.assertEqual([b['locator'] for b in result['blocks']], [f'Page 1, paragraph {n}' for n in range(1, 5)])
        self.assertIn('within 30 days of expiry', result['blocks'][2]['text'])

    def test_slightly_skewed_scan_is_straightened_and_noted(self):
        scanned_pdf(self.dir / 'k.pdf', CLAUSES, angle=2.5)
        result = parse_document(self.dir / 'k.pdf', '.pdf')
        self.assertEqual(len(result['blocks']), 4)
        self.assertTrue(any('tilted' in w for w in result['warnings']))

    def test_low_confidence_is_a_warning_not_a_failure(self):
        scanned_pdf(self.dir / 'b.pdf', CLAUSES, blur=True)
        result = parse_document(self.dir / 'b.pdf', '.pdf')
        self.assertTrue(result['blocks'])
        self.assertTrue(any('low OCR confidence' in w for w in result['warnings']), result['warnings'])

class WordTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='docx-tests-'))
    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def build(self, tracked=False):
        from docx import Document
        from docx.oxml import parse_xml
        ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        doc = Document()
        doc.sections[0].header.paragraphs[0].text = 'Fictional Example Co. internal'
        doc.sections[0].footer.paragraphs[0].text = '7'
        doc.add_heading('SERVICES AGREEMENT', 0)
        doc.add_paragraph('This agreement is between Example Co. and Northwind Labs.')
        doc.add_heading('Payment', 1)
        doc.add_paragraph('Fees are due within 45 days.', style='List Number')
        doc.add_paragraph('Late fees accrue at 1% per month.', style='List Number')
        table = doc.add_table(rows=3, cols=3)
        for row, values in zip(table.rows, [('Milestone', 'Fee', 'Due'), ('Design', 'USD 5,000', '2026-03-01'), ('Build', 'USD 7,500', '2026-06-01')]):
            for cell, value in zip(row.cells, values):
                cell.text = value
        p = doc.add_paragraph('The term is ')
        if tracked:
            p._p.append(parse_xml(f'<w:del {ns} w:id="1" w:author="Fictional" w:date="2026-01-01T00:00:00Z"><w:r><w:delText>one year</w:delText></w:r></w:del>'))
            p._p.append(parse_xml(f'<w:ins {ns} w:id="2" w:author="Fictional" w:date="2026-01-01T00:00:00Z"><w:r><w:t>two years</w:t></w:r></w:ins>'))
        else:
            p.add_run('two years')
        p.add_run('.')
        doc.save(self.dir / 'w.docx')
        return self.dir / 'w.docx'

    def test_structure_numbering_tables_and_headers(self):
        result = parse_document(self.build(), '.docx')
        by_text = {b['text']: b['locator'] for b in result['blocks']}
        self.assertEqual(result['blocks'][0]['locator'], 'Paragraph 1')
        self.assertEqual(by_text['1. Fees are due within 45 days.'], 'Paragraph 4 (under "Payment")')
        self.assertIn('2. Late fees accrue at 1% per month.', by_text)
        self.assertEqual(by_text['Milestone: Design | Fee: USD 5,000 | Due: 2026-03-01'], 'Table 1, row 2')
        self.assertNotIn('Milestone | Fee | Due', by_text)
        self.assertEqual(by_text['Fictional Example Co. internal'], 'Page header')
        self.assertNotIn('7', by_text)                         # a bare page number is noise
        self.assertEqual(result['warnings'], [])

    def test_tracked_changes_use_accepted_text_and_warn(self):
        result = parse_document(self.build(tracked=True), '.docx')
        texts = [b['text'] for b in result['blocks']]
        self.assertIn('The term is two years.', texts)
        self.assertNotIn('one year', ' '.join(texts))
        self.assertTrue(any('tracked changes' in w for w in result['warnings']))

class TextAndRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='text-tests-'))
    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_non_utf8_and_utf16_text(self):
        (self.dir / 'a.txt').write_bytes('Counterparty: Société Fictive\n'.encode('cp1252'))
        result = parse_document(self.dir / 'a.txt', '.txt')
        self.assertEqual(result['blocks'][0]['text'], 'Counterparty: Société Fictive')
        self.assertTrue(any('Windows-1252' in w for w in result['warnings']))
        (self.dir / 'b.txt').write_bytes('Counterparty: Fictional Labs\n'.encode('utf-16'))
        self.assertEqual(parse(self.dir / 'b.txt', '.txt')[0]['text'], 'Counterparty: Fictional Labs')

    def test_huge_single_line_is_split_into_cited_parts(self):
        (self.dir / 'h.txt').write_text('The recipient shall keep fictional information confidential. ' * 5000)
        blocks = parse(self.dir / 'h.txt', '.txt')
        self.assertGreater(len(blocks), 100)
        self.assertEqual(blocks[1]['locator'], 'Line 1, part 2')
        self.assertTrue(all(len(b['text']) <= 2000 for b in blocks))
        self.assertTrue(all(b['text'].endswith('.') for b in blocks[:-1]))   # split at sentence boundaries

    def test_empty_whitespace_and_binary_text(self):
        (self.dir / 'e.txt').write_bytes(b''); (self.dir / 'w.txt').write_text(' \n\n  '); (self.dir / 'b.txt').write_bytes(b'\x00\x01binary')
        for name, code in (('e.txt', 'empty'), ('w.txt', 'no_readable_text'), ('b.txt', 'binary')):
            with self.assertRaisesRegex(ParseError, code):
                parse_document(self.dir / name, '.txt')

    def test_split_and_join_helpers(self):
        self.assertEqual(split_long('short'), ['short'])
        self.assertEqual(join_lines(['the agree-', 'ment is non-', 'commercial']), 'the agreement is non-commercial')

    def test_tracker_detection(self):
        self.assertEqual(tracker_columns(b'Counterparty,Expiration,Owner\nAster Fictional Labs,2027-01-01,Alex Morgan\n', '.csv'),
                         ['Counterparty', 'Expiration', 'Owner'])
        self.assertIsNone(tracker_columns(b'Counterparty,Fictional Workbook\nformula,1\n', '.csv'))
        self.assertIsNone(tracker_columns(b'Name,Role,Team\nAlex Morgan,Lead,Research\n', '.csv'))
        self.assertIsNone(tracker_columns(b'Counterparty,Expiration,Owner\n', '.csv'))   # headers only, no rows

class ImportApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from backend.api.main import app
        from backend.db import Base, engine, migrate
        migrate(); Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
        self.client = TestClient(app); self.client.__enter__()
        result = self.client.post('/api/auth/demo', json={'username': 'alex'})
        self.client.headers['X-CSRF-Token'] = result.json()['csrf']
    def tearDown(self):
        self.client.__exit__(None, None, None)
    def send(self, name, data):
        result = self.client.post('/api/imports', files=[('files', (name, data, 'application/octet-stream'))], data={'scope': 'research'})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['results'][0]

    def test_tracker_is_routed_to_reconciliation_without_a_record(self):
        from openpyxl import Workbook
        import io
        wb = Workbook(); ws = wb.active; ws.title = 'Tracker'
        ws.append(['Counterparty', 'Agreement', 'Expiration', 'Owner']); ws.append(['Lark Fictional Biosciences', 'MTA', '2027-09-02', 'Research'])
        buffer = io.BytesIO(); wb.save(buffer)
        for name, data in (('tracker.xlsx', buffer.getvalue()), ('tracker.csv', b'Counterparty,Expiration,Owner\nAster Fictional Labs,2027-01-01,Alex Morgan\n')):
            result = self.send(name, data)
            self.assertIn('Reconcile an existing tracker', result['error'])
            self.assertNotIn('id', result)
        self.assertEqual(self.client.get('/api/agreements').json(), [])
        # The same file still works in reconciliation.
        sheet = self.client.post('/api/spreadsheets', files={'file': ('tracker.xlsx', buffer.getvalue())}, data={'scope': 'research'})
        self.assertEqual(sheet.status_code, 200, sheet.text); self.assertEqual(sheet.json()['total'], 1)

    def test_unsupported_and_protected_office_files_have_clear_messages(self):
        self.assertIn('save it as .docx', self.send('old.doc', b'\xd0\xcf\x11\xe0 fictional')['error'])
        self.assertIn('.rtf', self.send('memo.rtf', b'{\\rtf1 fictional}')['error'])
        self.assertIn('Apple Pages', self.send('deal.pages', b'PK fictional')['error'])
        self.assertIn('password-protected', self.send('locked.docx', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 fictional')['error'])
        self.assertIn('Empty file', self.send('blank.txt', b'   \n')['error'])

    def test_worker_records_parse_codes_and_warnings(self):
        from backend.services.worker import process_one
        from reportlab.pdfgen.canvas import Canvas
        import io
        buffer = io.BytesIO(); canvas = Canvas(buffer, encrypt='fictional-secret'); canvas.drawString(60, 700, 'Fictional locked text.'); canvas.save()
        rid = self.send('locked.pdf', buffer.getvalue())['id']; self.assertTrue(process_one())
        job = next(j for j in self.client.get('/api/jobs').json() if j['agreement_id'] == rid)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['error'], 'pdf_is_password_protected_remove_the_password_and_import_again')
        rid = self.send('note.txt', 'Counterparty: Société Fictive\n'.encode('cp1252'))['id']; self.assertTrue(process_one())
        record = self.client.get('/api/agreements/' + rid).json()
        self.assertEqual(record['labels']['import']['engine'], 'text')
        self.assertTrue(record['labels']['import']['warnings'])
        self.assertEqual(record['blocks'][0]['text'], 'Counterparty: Société Fictive')

if __name__ == '__main__':
    unittest.main()
