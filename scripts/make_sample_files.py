"""Write realistic FICTIONAL agreements in the formats people actually receive: Word, text PDF,
scanned PDF and an Excel tracker. Unlike demo/fixtures, these are written as clauses in prose with no
"Label: value" lines, so they show what Claude tagging and cited answers do on real-looking documents.

    python -m scripts.make_sample_files            # writes the "Sample files" folder
    python -m scripts.make_sample_files OUT_DIR

Every organization, person, date and term is made up. The launchers create the folder on first run.
"""
import sys
import textwrap
from pathlib import Path

LARK = ('MATERIAL TRANSFER AGREEMENT', [
    'FICTIONAL SAMPLE. NOT A LEGAL AGREEMENT.',
    'This Material Transfer Agreement (the "Agreement") is entered into as of March 2, 2026 (the "Effective Date") by and '
    'between Lark Fictional Biosciences, Inc. ("Provider") and Northwind Labs, LLC ("Recipient").',
    '1. Materials. Provider will transfer to Recipient the LFB-7 reporter cell line and related documentation (the "Materials").',
    '2. Purpose. Recipient may use the Materials solely for non-commercial evaluation of assay sensitivity in its own '
    'laboratory, and for no other purpose, including any use in humans.',
    '3. Transfer. Recipient may transfer the Materials to a third party only with Provider\'s prior written consent, and any '
    'permitted recipient must accept terms at least as protective as this Agreement.',
    '4. Term. This Agreement begins on the Effective Date and expires eighteen (18) months thereafter, unless terminated '
    'earlier by either party on thirty (30) days\' written notice.',
    '5. End of use. Within sixty (60) days after this Agreement ends, Recipient must, at Provider\'s election, either '
    'return all unused Materials or destroy them and certify the destruction in writing.',
    '6. Confidentiality. Recipient will keep Provider\'s confidential information confidential during the term and for '
    'three (3) years after this Agreement ends.',
    'IN WITNESS WHEREOF, the parties have executed this Agreement as of the Effective Date.',
    'Lark Fictional Biosciences, Inc.    By: /s/ Avery Example, Director of Licensing',
    'Northwind Labs, LLC                 By: /s/ Alex Morgan, Head of Research Operations',
])

QUARRY = ('MASTER SERVICES AGREEMENT', [
    'FICTIONAL SAMPLE. NOT A LEGAL AGREEMENT.',
    'This Master Services Agreement is made and entered into on the 15th day of April, 2026 between Northwind Labs, LLC '
    '("Client") and Quarry Fictional Labs, Inc. ("Provider").',
    '1. Services. Provider will perform the assay-validation services described in each statement of work.',
    '2. Fees. Client will pay a fixed fee of USD 12,500 for each completed milestone, up to three milestones per statement of work.',
    '3. Invoicing and payment. Provider will invoice after each milestone. Payment is due within forty-five (45) days of '
    'receipt of a correct invoice. Late amounts accrue interest at one percent (1%) per month.',
    '4. Term and renewal. The initial term is one (1) year from the date first written above. Thereafter this Agreement '
    'renews automatically for successive one-year terms unless either party gives written notice of non-renewal at least '
    'ninety (90) days before the end of the then-current term.',
    '5. Samples. Provider must return all Client samples within fifteen (15) days after the services under a statement of work are complete.',
    '6. Confidentiality. Provider must keep Client information confidential during the term and for four (4) years afterwards.',
    '7. Limitation of liability. Except for breach of Section 6, neither party\'s aggregate liability will exceed the fees '
    'paid in the twelve (12) months before the claim.',
    '8. Governing law. This Agreement is governed by the laws of the State of Delaware.',
    'Signed by authorized representatives of each party on the date first written above.',
])

WILLOW = ('MUTUAL NONDISCLOSURE AGREEMENT', [
    'FICTIONAL SAMPLE. NOT A LEGAL AGREEMENT.',
    'Northwind Labs, LLC and Willow Example Health, Inc. agree as follows, effective June 1, 2026.',
    '1. Purpose. The parties wish to evaluate a possible data-analysis collaboration.',
    '2. Use. Each party may use the other party\'s confidential information only for that purpose.',
    '3. Term. This Agreement terminates two (2) years from the effective date above.',
    '4. Survival. Obligations of confidentiality survive for five (5) years after termination; trade secrets remain protected '
    'for as long as they remain trade secrets.',
    '5. Return. On written request, each party will promptly return or destroy the other party\'s confidential information.',
    'Signed: Northwind Labs, LLC / Willow Example Health, Inc.',
])


def docx(path, title, paragraphs):
    from docx import Document
    doc = Document(); doc.add_heading(title, 1)
    for p in paragraphs:
        doc.add_paragraph(p)
    table = doc.add_table(rows=3, cols=2)
    for row, (k, v) in zip(table.rows, [('Provider contact', 'Avery Example'), ('Recipient contact', 'Alex Morgan'), ('Shipping', 'Dry ice, overnight')]):
        row.cells[0].text, row.cells[1].text = k, v
    doc.save(path)


def _text_doc(title, paragraphs):
    import pymupdf
    doc = pymupdf.open(); page = doc.new_page(width=612, height=792); y = 64
    page.insert_text((60, y), title, fontsize=13, fontname='hebo'); y += 30
    for p in paragraphs:
        for line in textwrap.wrap(p, 92):
            if y > 740:
                page = doc.new_page(width=612, height=792); y = 64
            page.insert_text((60, y), line, fontsize=10.5, fontname='helv'); y += 15
        y += 8
    return doc


def text_pdf(path, title, paragraphs):
    _text_doc(title, paragraphs).save(str(path))


def scanned_pdf(path, title, paragraphs):
    """Pages rendered to grayscale images, so the PDF has no text layer and must be read with OCR."""
    import pymupdf
    source = _text_doc(title, paragraphs); out = pymupdf.open()
    for page in source:
        pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=pix.tobytes('png'))
    out.save(str(path), garbage=4, deflate=True)


def tracker(path):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = 'Tracker'
    ws.append(['Counterparty', 'Agreement', 'Expiration', 'Owner'])
    ws.append(['Lark Fictional Biosciences', 'MTA', '2027-09-02', 'Research'])
    ws.append(['Quarry Fictional Labs', 'Services', '2027-04-15', 'Operations'])
    ws.append(['Willow Example Health', 'NDA', '2028-06-30', 'Legal'])  # disagrees with the document on purpose
    wb.save(path)


def make(out='Sample files'):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    docx(out / 'Lark Fictional Biosciences - Material Transfer Agreement.docx', *LARK)
    text_pdf(out / 'Quarry Fictional Labs - Master Services Agreement.pdf', *QUARRY)
    scanned_pdf(out / 'Willow Example Health - Mutual NDA (scanned).pdf', *WILLOW)
    tracker(out / 'Agreement tracker.xlsx')
    (out / 'README.txt').write_text(
        'FICTIONAL sample agreements for trying Clausetrail.\n\n'
        'Drag the three agreements onto Add agreements. The scanned PDF needs OCR (on macOS: brew install tesseract poppler).\n'
        'The Excel tracker is for Add agreements > spreadsheet reconciliation; its Willow date disagrees with the document on purpose.\n'
        'Questions to try: "Can the recipient give the Lark cell line to another lab?", "When must Quarry be paid?",\n'
        '"How do we stop the Quarry agreement from renewing?", "How long does confidentiality last under the Willow NDA?"\n')
    return out


if __name__ == '__main__':
    print(make(sys.argv[1] if len(sys.argv) > 1 else 'Sample files'))
