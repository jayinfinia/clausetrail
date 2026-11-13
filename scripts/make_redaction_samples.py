"""Generate FICTIONAL documents plus reference redactions for scoring the redaction stage.

The reference redactions follow a common manual practice: black out the SSN / tax ID
field with one box drawn over the whole field and leave name, address and email
visible. That lets the pipeline be scored offline against a "human" redaction.
Every organization, name, number and address here is made up.

  python scripts/make_redaction_samples.py OUT_DIR
"""
import io
import sys
from pathlib import Path

import pymupdf

SERIF = 'tiro'


def _page(doc, lines, start=72):
    page = doc.new_page(width=612, height=792); y = start; rects = {}
    for item in lines:
        text, size, key = (item + (None,))[:3] if isinstance(item, tuple) else (item, 11, None)
        if text == '':
            y += size; continue
        page.insert_text((72, y), text, fontsize=size, fontname=SERIF)
        if key:
            rects[key] = pymupdf.Rect(72, y - size, 72 + pymupdf.get_text_length(text, SERIF, size), y + 3)
        y += size * 1.6
    return page, rects


def _scan(text_doc, boxes=None, dpi=150):
    """Rasterize like a scanner; optionally burn black boxes (page index -> [Rect]) first."""
    out = pymupdf.open()
    for i, page in enumerate(text_doc):
        for r in (boxes or {}).get(i, []):
            page.draw_rect(r, color=(0, 0, 0), fill=(0, 0, 0))
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=pix.tobytes('png'))
    return out.tobytes(garbage=4, deflate=True)


def signature_page(name, ssn, street, city, email, date):
    def build():
        d = pymupdf.open()
        _, r = _page(d, [('NORTHWIND LABS, LLC  (FICTIONAL SAMPLE)', 13), ('MEMBER SIGNATURE PAGE', 13), ('', 8),
                         'In consideration for the sale of LLC Units in Northwind Labs, LLC, the undersigned agrees to be bound',
                         'by the terms of the Operating Agreement of the LLC, as amended.', ('', 8),
                         f'Effective Date: {date}', ('', 6), 'Member Name:', f'Print: {name}', 'Signed: ________________________',
                         ('', 6), (f'{ssn}', 11, 'ssn'), ('Fed. Tax ID/Social Security Number', 10, 'cap'), ('', 6),
                         'Address:', street, city, ('', 6), 'Email Address:', email, ('', 12),
                         'Accepted on behalf of Northwind Labs, LLC', 'By: ________________   Jordan Example, President'])
        return d, r
    d, _ = build(); original = _scan(d)
    d, r = build(); box = pymupdf.Rect(70, r['ssn'].y0 - 4, 300, r['cap'].y0 - 1)  # whole field, like a manual redaction
    return original, _scan(d, {0: [box]})


def election_83b(name, ssn, street, city):
    def build():
        d = pymupdf.open()
        _, r = _page(d, [('Form 83(b) Election  (FICTIONAL SAMPLE)', 13), ('', 8),
                         'This statement is made under Section 83(b) of the Internal Revenue Code.', ('', 6),
                         '(1) The person who performed the services ("Recipient") is:', f'      Name:      {name}',
                         f'      Address:   {street}', f'                     {city}',
                         (f'      Taxpayer identification number: {ssn}', 11, 'tin'), ('', 6),
                         '(2) The property is 20,000 Class A Membership Units (Profits Interest) in Northwind Labs, LLC.',
                         '(3) The property was transferred on September 16, 2025.',
                         '(6) The amount paid for such property is $0.00.', ('', 20), f'{name}'])
        return d, r
    d, _ = build(); original = _scan(d)
    d, r = build(); box = pymupdf.Rect(70, r['tin'].y0 - 4, 420, r['tin'].y1 + 3)
    return original, _scan(d, {0: [box]})


def wire_letter():
    lines = ['FICTIONAL SAMPLE - Wire instructions for capital contribution', '',
             'Bank: Example Community Bank', 'Routing number: 021000021', 'Account number: 0012345678',
             'Beneficiary: Northwind Labs, LLC', 'Reference: Member contribution, Example Investor', '',
             'Questions: Jordan Example, (434) 555-0142, jordan@example.com']
    def build(redact):
        d = pymupdf.open(); p = d.new_page(); y = 72
        for line in lines:
            p.insert_text((72, y), line, fontsize=11); y += 18
        if redact:
            for v in ('021000021', '0012345678'):
                for r in p.search_for(v):
                    p.add_redact_annot(r, fill=(0, 0, 0))
            p.apply_redactions()
        return d.tobytes()
    return build(False), build(True)


def investor_form():
    import docx
    def build(redact):
        d = docx.Document(); blk = '█' * 9
        d.add_heading('Investor Information Form (FICTIONAL SAMPLE)', 1)
        rows = [('Investor name', 'Riley Sample'), ('Taxpayer ID (SSN)', '587-21-0934' if not redact else blk),
                ('Date of birth', '03/14/1979' if not redact else blk), ('Mailing address', '22 Placeholder Road, Exampleville, VA 22903'),
                ('Email', 'riley.sample@example.com'), ('Bank routing number', '011000015' if not redact else blk),
                ('Bank account number', '9876543210' if not redact else blk), ('Units subscribed', '25,000 Class A Units')]
        t = d.add_table(rows=0, cols=2)
        for k, v in rows:
            c = t.add_row().cells; c[0].text = k; c[1].text = v
        d.add_paragraph('Signed: Riley Sample, effective May 16, 2023.')
        b = io.BytesIO(); d.save(b); return b.getvalue()
    return build(False), build(True)


def roster():
    import openpyxl
    def build(redact):
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Members'
        ws.append(['Member', 'SSN / EIN', 'Units', 'Bank account', 'Email', 'Admitted'])
        for name, tid, units, acct, email, date in [
                ('Casey Placeholder', '601-44-7720', 50000, 'Account 4455667788', 'casey@example.com', '2023-05-02'),
                ('Morgan Fictitious', '532-18-4406', 20000, 'Account 1122334455', 'morgan@example.org', '2023-06-12'),
                ('Example Holdings LLC', '86-1234567', 200000, 'Account 9988776655', 'ops@example.net', '2023-07-01')]:
            ws.append([name, None if redact else tid, units, None if redact else acct, email, date])
        b = io.BytesIO(); wb.save(b); return b.getvalue()
    return build(False), build(True)


def cda_text():
    t = ('FICTIONAL SAMPLE CONFIDENTIAL DISCLOSURE AGREEMENT\nAgreement type: CDA\nCounterparty: Aster Fictional Labs\n'
         'Effective date: 2026-01-01\nExpiration date: 2027-01-01\nNotice: written notice to Aster Fictional Labs, 18 Imaginary Trail, '
         'Sampletown, VA 22901.\nNo personal identifiers appear in this agreement.\n')
    return t.encode(), t.encode()


def main(out):
    out = Path(out); (out / 'Investors' / 'Avery Fictional').mkdir(parents=True, exist_ok=True)
    (out / 'Investors' / 'Riley Sample').mkdir(parents=True, exist_ok=True); (out / 'Admin').mkdir(parents=True, exist_ok=True)
    (out / 'Suppliers' / 'Aster Fictional Labs').mkdir(parents=True, exist_ok=True)
    pairs = {
        'Investors/Avery Fictional/Avery Fictional - Membership Signature Page.pdf': signature_page('Avery Q. Fictional', '412-55-0198', '18 Imaginary Trail, Ste 4', 'Sampletown, VA 22901', 'avery@example.com', 'May 16, 2023'),
        'Investors/Avery Fictional/Avery Fictional - PIU-99 - 83b Election.pdf': election_83b('Avery Q. Fictional', '412-55-0198', '18 Imaginary Trail, Ste 4', 'Sampletown, VA 22901'),
        'Investors/Riley Sample/Riley Sample - Membership Signature Page.pdf': signature_page('Riley Sample', '587-21-0934', '22 Placeholder Road', 'Exampleville, VA 22903', 'riley.sample@example.com', 'June 1, 2023'),
        'Investors/Riley Sample/Riley Sample - Investor Information Form.docx': investor_form(),
        'Investors/Riley Sample/Riley Sample - Wire Instructions.pdf': wire_letter(),
        'Admin/Member Roster.xlsx': roster(),
        'Suppliers/Aster Fictional Labs/Aster Fictional Labs - Northwind Labs - CDA - 20260101 - EXECUTED.txt': cda_text(),
    }
    for rel, (orig, ref) in pairs.items():
        p = out / rel; p.write_bytes(orig)
        p.with_name(p.stem + ' Redacted' + p.suffix).write_bytes(ref)
    print(f'Wrote {len(pairs)} fictional originals and {len(pairs)} reference redactions to {out}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.local/redaction-samples')
