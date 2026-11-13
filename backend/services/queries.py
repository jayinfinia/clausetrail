import re
from datetime import date, timedelta
from backend.domain.deadlines import add_calendar_months
from backend.domain.framework import effective_end

MONTHS={m:i+1 for i,m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'])}
DATE_TERMS=re.compile(r'\b(?:due|expir\w*|end|ends|ending|deadlines?|notice|notices)\b')
# Words allowed around a period in a report question; any other word (a condition, a party) means
# the question asks for more than a date report and goes to evidence analysis instead.
REPORT_WORDS=set('how many my which what list show count the of our are is will be do does we have that there all any me give get number total in during for coming up reviewed executed renewal agreements agreement contracts contract cdas cda mtas mta deadlines deadline due expire expires expiring expiration expirations end ends ending notice notices dates date'.split())

def period(text, today):
    """Parse one explicit reporting period. Returns (start, end, phrase) or None."""
    text=text.lower()
    m=re.search(r'\b(?:in|during|for)?\s*(?:the )?next (\d{1,3}) days\b|\bin (\d{1,3}) days\b',text)
    if m:return today,today+timedelta(days=int(m.group(1) or m.group(2))),m.group(0)
    m=re.search(r'\b(?:before|by) (\d{4}-\d{2}-\d{2})\b',text)
    if m:return today,date.fromisoformat(m.group(1)),m.group(0)
    m=re.search(r'\b(?:in|during|for) ('+'|'.join(MONTHS)+r')(?: (\d{4}))?\b',text)
    if m:
        year=int(m.group(2) or today.year); month=MONTHS[m.group(1)]; first=date(year,month,1)
        return first,add_calendar_months(first,1)-timedelta(days=1),m.group(0)
    m=re.search(r'\b(?:in|during|for)? ?(20\d{2})\b',text)
    if m:return date(int(m.group(1)),1,1),date(int(m.group(1)),12,31),m.group(0)
    for phrase,offset in (('this year',0),('next year',1)):
        if phrase in text:return date(today.year+offset,1,1),date(today.year+offset,12,31),phrase
    for phrase,offset in (('this month',0),('next month',1)):
        if phrase in text:
            first=add_calendar_months(date(today.year,today.month,1),offset)
            return first,add_calendar_months(first,1)-timedelta(days=1),phrase
    for phrase,offset in (('this quarter',0),('next quarter',3)):
        if phrase in text:
            first=add_calendar_months(date(today.year,((today.month-1)//3)*3+1,1),offset)
            return first,add_calendar_months(first,3)-timedelta(days=1),phrase
    if 'overdue' in text or 'past due' in text:return date(1900,1,1),today-timedelta(days=1),'overdue'
    return None

def is_deadline_report(question, today=None):
    text=question.lower().strip().rstrip('?.!')
    found=period(text,today or date.today())
    if not found or not (DATE_TERMS.search(text) or found[2]=='overdue'):return False
    rest=text.replace(found[2],' ')
    for filler in ('past due','overdue','coming up'):rest=rest.replace(filler,' ')
    return all(word in REPORT_WORDS for word in re.findall(r"[a-z]+",rest))

def deadlines(records, today=None):
    today=today or date.today()
    rows=[]
    for record in records:
        if not record.executed or record.approved.get('agreement_type',{}).get('value')=='AMENDMENT':
            continue
        facts=record.approved
        values={k:v.get('value') for k,v in facts.items()}
        labels=getattr(record,'labels',None) or {}
        if labels.get('endRule')=='later5':
            # Later of 5 years or end of relationship: open-ended (no expiration alerts) until the relationship ends.
            end,_floor=effective_end('later5',values.get('effective_date') or labels.get('eff'),None,labels.get('floor'),labels.get('relEnd'))
            values['expiration_date']=end.isoformat() if end else None
        candidates=[('expiration',values.get('expiration_date')),('confidentiality',values.get('confidentiality_end')),('return',values.get('return_date'))]
        expiry=values.get('expiration_date'); notice=values.get('notice_days')
        if expiry and notice is not None:
            candidates.append(('notice',(date.fromisoformat(expiry)-timedelta(days=int(notice))).isoformat()))
        for kind, value in candidates:
            if not value: continue
            due=date.fromisoformat(value); delta=(due-today).days
            rows.append({'id':f'{record.id}:{record.revision}:{kind}:{value}', 'agreement_id':record.id,'filename':record.filename,'counterparty':values.get('counterparty') or 'Unreviewed counterparty','kind':kind,'date':value,'days':delta,'status':'overdue' if delta<0 else 'soon' if delta<=30 else 'upcoming','revision':record.revision,'ref_id':labels.get('ref_id'),'owner':labels.get('owner') or '','relationship':labels.get('rel'),'label_status':labels.get('status')})
    return sorted(rows,key=lambda r:r['date'])

def answer(question,records,today=None):
    today=today or date.today()
    text=question.lower()
    kind='CDA' if re.search(r'\bcdas?\b',text) else 'MTA' if re.search(r'\bmtas?\b',text) else None
    selected=[r for r in records if not kind or r.approved.get('agreement_type',{}).get('value')==kind]
    citations=[]
    def cite(record,block_id,quote=None):
        block=next((b for b in record.blocks if b['id']==str(block_id)),None)
        if block:
            citations.append({'agreement_id':record.id,'filename':record.filename,'block_id':block['id'],'locator':block['locator'],'text':quote or block['text'][:1600],'version':record.source_version})
    found=period(text,today) if DATE_TERMS.search(text) or 'overdue' in text else None
    if found or any(word in text for word in ('expir','deadline','renewal notice','due')):
        start,end,_=found or (today,today+timedelta(days=90),'')
        only_expiration=bool(re.search(r'\bexpir',text)) and not re.search(r'\b(?:due|deadlines?|notice)\b',text)
        rows=[r for r in deadlines(selected,today) if start.isoformat()<=r['date']<=end.isoformat() and (r['kind']=='expiration' if only_expiration else True)]
        for row in rows:
            record=next(r for r in selected if r.id==row['agreement_id'])
            field={'expiration':'expiration_date','notice':'expiration_date','confidentiality':'confidentiality_end','return':'return_date'}[row['kind']]
            fact=record.approved.get(field,{})
            source=next((r for r in records if r.id==fact.get('source_agreement_id')),record)
            cite(source,fact.get('evidence'))
        agreements=len({r['agreement_id'] for r in rows})
        kinds={}
        for r in rows:kinds[r['kind']]=kinds.get(r['kind'],0)+1
        breakdown=' ('+', '.join(f'{n} {k}' for k,n in kinds.items())+')' if len(kinds)>1 else ''
        what='expiration date(s)' if only_expiration else 'reviewed deadline(s)'
        return {'answer':f'{len(rows)} {what}{breakdown} across {agreements} agreement(s) between {start} and {end}. Only reviewer-confirmed executed agreements are counted; unreviewed or unknown dates are excluded.','rows':rows,'citations':citations,'mode':'reviewed database query'}
    if 'how many' in text or 'count' in text:
        approved=[r for r in selected if r.executed]
        return {'answer':f'{len(approved)} accessible, reviewer-confirmed executed agreement(s)'+(f' of type {kind}.' if kind else '.'),'rows':[{'agreement_id':r.id,'filename':r.filename} for r in approved],'citations':[],'mode':'reviewed database query'}
    terms=set(re.findall(r'[a-z]{3,}',text)) - {'which','what','does','have','with','that','agreements','agreement','the','are','and','can','for'}
    scored=[]
    for record in selected:
        for block in record.blocks:
            words=set(re.findall(r'[a-z]{3,}',block['text'].lower()))
            score=len(terms & words)
            if score: scored.append((score,record,block))
    scored.sort(key=lambda item:item[0],reverse=True)
    for _,record,block in scored[:6]: cite(record,block['id'])
    return {'answer':'Relevant source passages below. These are document excerpts, not a reviewed legal conclusion.' if citations else 'I could not find supporting passages in your accessible documents. This does not establish that the obligation is absent.','rows':[],'citations':citations,'mode':'local evidence search'}
