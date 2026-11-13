"""Reproducible fictional corpus. Every organization, person and term is made up."""
from pathlib import Path
import csv
import json

SPECS=[
 ('01-cda-aster.txt','CDA','Aster Fictional Labs','2026-11-30','2029-11-30',''),
 ('02-cda-perpetual.txt','CDA','Bluebird Example Research','perpetual','perpetual',''),
 ('03-cda-mutual.txt','CDA','Cedar Demo Sciences','2027-02-15','2030-02-15',''),
 ('04-cda-ambiguous.txt','CDA','Delta Imaginary Institute','03/04/27','unknown',''),
 ('05-mta-return.txt','MTA','Elm Fictional University','2027-03-01','2029-03-01','2027-03-31'),
 ('06-mta-trigger.txt','MTA','Fern Example Materials','2027-04-01','unknown','30 days after project completion'),
 ('07-mta-restricted.txt','MTA','Grove Private Demo Lab','2027-05-01','2030-05-01',''),
 ('08-services.txt','SERVICES','Harbor Sample Services','2026-12-15','2029-12-15',''),
 ('09-collaboration.txt','COLLABORATION','Iris Fictional Group','2027-06-30','2032-06-30',''),
 ('10-amendment.txt','AMENDMENT','Aster Fictional Labs','2027-11-30','2029-11-30',''),
 ('11-scan-source.txt','CDA','Juniper Scan Example','2027-01-31','2030-01-31',''),
 ('12-unsigned.txt','CDA','Kite Unsigned Example','2027-07-01','2029-07-01',''),
]

# Clause-style agreements whose terms differ, for comparison, amendment, conflict and payment questions.
# Header labels feed exact-label extraction; operative terms are prose, as in real agreements.
HEADER='FICTIONAL DEMO DOCUMENT — NOT A LEGAL AGREEMENT\n'
VARIED={
 '13-mta-consent.txt':(HEADER+"""Agreement type: MTA
Counterparty: Lark Fictional Biosciences
Internal owner: Priya Shah
Effective date: 2026-03-01
Expiration date: 2027-02-28
Notice days: 30
1. Materials. Provider will supply the fictional cell line LFB-7 and related data (the "Materials").
2. Use. Recipient may use the Materials solely for in vitro research in Recipient's own laboratory. The Materials must not be used in humans or for any commercial purpose.
3. Transfer. Recipient may transfer the Materials to a third party only with Provider's prior written consent, and any permitted recipient must accept terms at least as protective as this Agreement.
4. Publication. Recipient may publish results after giving Provider 30 days to review the manuscript for Provider confidential information.
5. End of use. Within 60 days after this Agreement ends, Recipient must, at Provider's election, either return all unused Materials or destroy them and certify the destruction in writing.
6. Confidentiality. Recipient's confidentiality obligations continue for three years after this Agreement ends.
7. Renewal. This Agreement may be extended only by a written amendment signed by both parties.
Signatures: Fictional signatures for demonstration only. Reviewer must verify execution.
""",'MTA','Lark Fictional Biosciences','2027-02-28'),
 '14-cda-autorenew.txt':(HEADER+"""Agreement type: CDA
Counterparty: Maple Example Analytics
Internal owner: Jordan Lee
Effective date: 2026-02-01
Expiration date: 2027-01-31
1. Purpose. The parties will exchange confidential information solely to evaluate a possible fictional data-analysis collaboration.
2. Term and renewal. This Agreement has an initial term of one year and renews automatically for successive one-year periods unless either party gives written notice of non-renewal at least 60 days before the end of the then-current term.
3. Obligations. The receiving party must protect confidential information with at least reasonable care and may disclose it only to employees who need to know it for the purpose.
4. Survival. Confidentiality obligations continue for five years after the date of each disclosure, except that trade secrets remain protected for as long as they remain trade secrets.
5. Return. On request, the receiving party must promptly return or destroy confidential information, except one archival copy kept by legal counsel.
Signatures: Fictional signatures for demonstration only. Reviewer must verify execution.
""",'CDA','Maple Example Analytics','2027-01-31'),
 '15-mta-destroy.txt':(HEADER+"""Agreement type: MTA
Counterparty: Nimbus Imaginary Therapeutics
Internal owner: Alex Morgan
Effective date: 2026-04-15
Expiration date: 2026-12-31
1. Use. Recipient may use the fictional compound NIT-22 only to run the screening study described in Attachment A.
2. Modifications. Recipient may create derivatives for the study but must not use the compound or any derivative for commercial purposes.
3. Third parties. Recipient must not transfer the compound or any derivative to any third party.
4. Disposal. Upon completion of the study, Recipient must destroy all remaining compound and derivatives. Return to Provider is not required.
5. Confidentiality. Study results are confidential until Provider approves their release in writing.
Signatures: Fictional signatures for demonstration only. Reviewer must verify execution.
""",'MTA','Nimbus Imaginary Therapeutics','2026-12-31'),
 '16-amendment-lark.txt':(HEADER+"""Agreement type: AMENDMENT
Counterparty: Lark Fictional Biosciences
Internal owner: Priya Shah
Effective date: 2027-01-15
Parent reference: 13-mta-consent.txt
Expiration date: 2028-02-29
Notice days: 45
1. Term. The expiration date of the Material Transfer Agreement is extended from 2027-02-28 to 2028-02-29.
2. Notice. The notice period is changed from 30 days to 45 days.
3. Additional site. Recipient may also use the Materials at Orchid Demo Institute, provided Orchid Demo Institute agrees in writing to the use restrictions of the original Agreement.
4. All other terms of the original Agreement remain unchanged.
Signatures: Fictional signatures for demonstration only. Reviewer must verify execution.
""",'AMENDMENT','Lark Fictional Biosciences','2028-02-29'),
 '17-cda-conflict.txt':(HEADER+"""Agreement type: CDA
Counterparty: Pine Sample Partners
Internal owner: Sam Rivera
Effective date: 2026-05-01
Expiration date: 2027-09-30
1. Purpose. Information is disclosed only to discuss a fictional equipment-sharing arrangement.
2. Term. This Agreement terminates on 2027-10-31 unless terminated earlier by either party on 30 days' written notice.
3. Survival. Confidentiality obligations survive termination for two years.
Signatures: Fictional signatures for demonstration only. Reviewer must verify execution.
""",'CDA','Pine Sample Partners','2027-09-30'),
 '18-services-payment.txt':(HEADER+"""Agreement type: SERVICES
Counterparty: Quarry Fictional Labs
Internal owner: Alex Morgan
Effective date: 2026-06-01
Expiration date: 2027-05-31
Notice days: 30
1. Services. Quarry Fictional Labs will perform fictional assay-validation services described in Schedule 1.
2. Fees. Northwind Labs will pay a fixed fee of USD 12,500 for each completed milestone, up to three milestones.
3. Invoicing. Quarry Fictional Labs will invoice after each milestone, and payment is due within 45 days of a correct invoice.
4. Materials. Quarry Fictional Labs must return all Northwind Labs samples within 15 days after the services are complete.
5. Confidentiality. Quarry Fictional Labs must keep Northwind Labs information confidential during the term and for four years afterwards.
Signatures: Fictional signatures for demonstration only. Reviewer must verify execution.
""",'SERVICES','Quarry Fictional Labs','2027-05-31'),
}

# Fictional folder layout: <relationship type>/<counterparty>/<file>. The seed passes these paths so folder-based
# classification is shown with fictional data only.
ROOT='Fictional Sample Set'
FOLDERS={
 '01-cda-aster.txt':f'{ROOT}/Suppliers/Aster Fictional Labs/01-cda-aster.txt',
 '02-cda-perpetual.txt':f'{ROOT}/Investors/Bluebird Example Research/02-cda-perpetual.txt',
 '03-cda-mutual.txt':f'{ROOT}/Service Providers/Cedar Demo Sciences/03-cda-mutual.txt',
 '04-cda-ambiguous.txt':f'{ROOT}/Unclassified/Delta Imaginary Institute/04-cda-ambiguous.txt',
 '05-mta-return.txt':f'{ROOT}/Research Partners/Elm Fictional University/05-mta-return.txt',
 '06-mta-trigger.txt':f'{ROOT}/Suppliers/Fern Example Materials/06-mta-trigger.txt',
 '07-mta-restricted.txt':f'{ROOT}/Research Partners/Grove Private Demo Lab/07-mta-restricted.txt',
 '08-services.txt':f'{ROOT}/Service Providers/Harbor Sample Services/08-services.txt',
 '09-collaboration.txt':f'{ROOT}/Research Partners/Iris Fictional Group/09-collaboration.txt',
 '10-amendment.txt':f'{ROOT}/Suppliers/Aster Fictional Labs/10-amendment.txt',
 '11-scan-source.txt':f'{ROOT}/Investors/Juniper Scan Example/11-scan-source.txt',
 '12-unsigned.txt':f'{ROOT}/Unclassified/Kite Unsigned Example/12-unsigned.txt',
 '13-mta-consent.txt':f'{ROOT}/Research Partners/Lark Fictional Biosciences/13-mta-consent.txt',
 '14-cda-autorenew.txt':f'{ROOT}/Consultants/Maple Example Analytics/14-cda-autorenew.txt',
 '15-mta-destroy.txt':f'{ROOT}/Suppliers/Nimbus Imaginary Therapeutics/15-mta-destroy.txt',
 '16-amendment-lark.txt':f'{ROOT}/Research Partners/Lark Fictional Biosciences/16-amendment-lark.txt',
 '17-cda-conflict.txt':f'{ROOT}/Funders/Pine Sample Partners/17-cda-conflict.txt',
 '18-services-payment.txt':f'{ROOT}/Suppliers/Quarry Fictional Labs/18-services-payment.txt',
}

def generate(folder):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    expected=[]
    for filename,kind,party,expiry,conf,ret in SPECS:
        content=f'''FICTIONAL DEMO DOCUMENT — NOT A LEGAL AGREEMENT
Agreement type: {kind}
Counterparty: {party}
Internal owner: Alex Morgan
Effective date: 2026-01-01
Expiration date: {expiry}
Notice days: 30
Confidentiality end: {conf}
Permitted use: Evaluation of fictional research materials only.
Renewal: Written agreement required; no automatic renewal.
The recipient must not redistribute materials to third parties.
Confidentiality obligations survive expiration as separately stated above.
'''
        if ret: content+=f'Return date: {ret}\n'
        if kind=='AMENDMENT': content+='Parent reference: 01-cda-aster.txt\nThis amendment changes expiration only; other terms remain unchanged.\n'
        content+= 'Signatures: NOT SIGNED\n' if 'unsigned' in filename else 'Signatures: Fictional signatures for demonstration only. Reviewer must verify execution.\n'
        (folder/filename).write_text(content)
        expected.append({'filename':filename,'type':kind,'counterparty':party,'expiration_raw':expiry,'review_execution': 'unsigned' not in filename})
    for filename,(content,kind,party,expiry) in VARIED.items():
        (folder/filename).write_text(content)
        expected.append({'filename':filename,'type':kind,'counterparty':party,'expiration_raw':expiry,'review_execution':True})
    with (folder/'tracker.csv').open('w',newline='') as f:
        w=csv.writer(f); w.writerow(['Counterparty','Expiration','Owner'])
        w.writerow(['Aster Fictional Labs','2027-01-01','Alex Morgan'])
        w.writerow(['Elm Fictional University','2027-03-01','Alex Morgan'])
        w.writerow(['Unknown Fictional Entity','2028-01-01','Alex Morgan'])
    (folder/'expected.json').write_text(json.dumps(expected,indent=2))
    return folder

if __name__=='__main__':
    import sys
    generate(sys.argv[1] if len(sys.argv)>1 else 'demo/fixtures')
