"""Bounded local parsing. Invoked in a subprocess by the worker."""
import csv
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

MAX_TEXT = 1_000_000

def zip_guard(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > 100_000_000:
            raise ValueError('archive_limits')
        if any('vbaProject' in i.filename for i in infos):
            raise ValueError('macros_rejected')

def parse(path, suffix):
    blocks = []
    def add(locator, text):
        if text and text.strip():
            blocks.append({'id': str(len(blocks) + 1), 'locator': locator, 'text': text.strip()})
        if sum(len(b['text']) for b in blocks) > MAX_TEXT:
            raise ValueError('text_limit')
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('encrypted_pdf')
        if len(reader.pages) > 200:
            raise ValueError('page_limit')
        for index, page in enumerate(reader.pages):
            content = page.extract_text() or ''
            if len(content.strip()) < 20:
                with tempfile.TemporaryDirectory(prefix='ocr-', dir=Path(path).parent) as tmp:
                    prefix = str(Path(tmp) / 'page')
                    subprocess.run(['pdftoppm', '-f', str(index+1), '-l', str(index+1), '-scale-to', '2400', '-png', '-singlefile', str(path), prefix], check=True, timeout=30, capture_output=True)
                    result = subprocess.run(['tesseract', prefix+'.png', 'stdout'], capture_output=True, text=True, check=True, timeout=30)
                    content = result.stdout
            add(f'Page {index+1}', content)
    elif suffix == '.docx':
        zip_guard(path)
        from docx import Document
        doc = Document(path)
        for index, paragraph in enumerate(doc.paragraphs):
            add(f'Paragraph {index+1}', paragraph.text)
        for i, table in enumerate(doc.tables):
            for j, row in enumerate(table.rows):
                add(f'Table {i+1}, row {j+1}', ' | '.join(cell.text for cell in row.cells))
    elif suffix in ('.txt', '.csv'):
        text = Path(path).read_text(encoding='utf-8-sig')
        for i, line in enumerate(text.splitlines()):
            add(f'Line {i+1}', line)
    elif suffix == '.xlsx':
        zip_guard(path)
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=False)
        for ws in wb:
            if ws.max_row > 10000 or ws.max_column > 100:
                raise ValueError('sheet_limit')
            for row in ws.iter_rows():
                text = ' | '.join(f'{cell.coordinate}: {cell.value}' for cell in row if cell.value is not None and cell.data_type != 'f')
                add(f'{ws.title}, row {row[0].row}', text)
        wb.close()
    else:
        raise ValueError('unsupported_type')
    if not blocks:
        raise ValueError('no_readable_text')
    return blocks

def spreadsheet_rows(data, suffix):
    if suffix == '.csv':
        rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        sheet = 'CSV'
    elif suffix == '.xlsx':
        from openpyxl import load_workbook
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > 100_000_000:
                raise ValueError('archive_limits')
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
        ws = wb.worksheets[0]
        if ws.max_row > 10000 or ws.max_column > 100:
            raise ValueError('sheet_limit')
        rows = [[None if c.data_type == 'f' else c.value for c in row] for row in ws.iter_rows()]
        sheet = ws.title
        wb.close()
    else:
        raise ValueError('CSV or XLSX required')
    if not rows or len(rows) > 10001 or len(rows[0]) > 100:
        raise ValueError('sheet_limit')
    headers = [str(v or '').strip() for v in rows[0]]
    if len(set(headers)) != len(headers) or any(not h for h in headers):
        raise ValueError('Headers must be unique and nonempty')
    return headers, [{'row': i+2, 'sheet': sheet, 'values': {h: str(v or '') for h,v in zip(headers, row)}} for i,row in enumerate(rows[1:]) if any(row)]

if __name__ == '__main__':
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (150, 150))
            resource.setrlimit(resource.RLIMIT_AS, (2_000_000_000, 2_000_000_000))
        except (ImportError, ValueError):
            pass
        result = {'blocks': parse(Path(sys.argv[1]), sys.argv[2])}
    except Exception:
        result = {'error': 'parse_failed_or_unsupported_content'}
    Path(sys.argv[3]).write_text(json.dumps(result))
