"""Bounded lexical retrieval with original offsets and deterministic ranking."""
import math
import re
from collections import Counter

STOP={'the','and','for','what','which','does','can','are','how','that','this','with','from','about','please','tell','under','have','has','our','their','agreement','agreements'}
SYNONYMS=[{'redistribute','redistribution','transfer','share','sharing','third','parties'}, {'confidential','confidentiality','disclose','disclosure','secret'}, {'end','expiration','expire','expiry','term','termination'}, {'return','destroy','destruction','dispose','disposal'}, {'consent','approval','permission','permitted'}, {'renew','renewal','extend','extension'}, {'use','uses','purpose','permitted','evaluation','research'}, {'restrictions','restriction','obligations','obligation','recipient','must','prohibited','confidentiality','renewal','permitted'}]

def terms(text):
    return [word for word in re.findall(r'[a-z0-9]{2,}',text.casefold()) if word not in STOP]

def retrieve(question,records,limit=40,budget=20000,per_doc_limit=None,lead_chars=1500):
    """Rank passages for a question within a character budget.

    per_doc_limit caps passages per document in each round-robin pass; None spreads the passage limit over the
    documents that matched (3 per document for large collections, more when only a few documents are in scope).
    lead_chars reserves roughly that many characters from the start of each matched document, where titles,
    parties and dates usually sit and lexical scoring rarely reaches. It is reserved up front when only a few
    documents are in scope, and added after ranking (within the per-document cap) for larger collections.
    Both defaults were chosen on the CUAD dev split (see docs/EVALUATION.md)."""
    q=set(terms(question))
    expanded=set(q)
    for group in SYNONYMS:
        if q & group: expanded.update(group)
    chunks=[]; record_map={r.id:r for r in records}
    for record in records:
        for block in record.blocks:
            text=block['text']
            for start in range(0,len(text),1400):
                passage=text[start:start+1800]
                if not passage.strip():continue
                chunks.append({'agreement_id':record.id,'filename':record.filename,'block_id':str(block['id']),'locator':block['locator'],'text':passage,'start':start,'end':start+len(passage),'version':record.source_version,'digest':record.digest,'revision':record.revision,'executed':record.executed,'parent_id':record.parent_id,'reviewed_facts':record.approved,'tokens':Counter(terms(passage))})
    if not chunks:return [],{'passages_total':0,'passages_sent':0,'truncated':False}
    avg=sum(sum(c['tokens'].values()) for c in chunks)/len(chunks) or 1
    df={word:sum(word in c['tokens'] for c in chunks) for word in expanded}
    named_ids=set()
    # A counterparty word also names an agreement ("the Elm MTA") when it is distinctive in the corpus.
    doc_terms={r.id:set(terms(' '.join(b['text'] for b in r.blocks))) for r in records}
    for r in records:
        name=str(r.approved.get('counterparty',{}).get('value') or r.proposals.get('counterparty',{}).get('value') or '')
        key=set(terms(name)) - {'fictional','example','demo','labs','lab','research'}
        distinctive={t for t in key & q if len(t)>=3 and sum(t in d for d in doc_terms.values())<=2}
        if (key and key<=q) or distinctive or r.filename.casefold() in question.casefold():named_ids.add(r.id)
    if named_ids:
        named_ids.update(r.id for r in records if r.parent_id in named_ids)
    # Preserve whole short documents: lexical matches alone lose qualifications
    # and broad summaries when a parser emits one block per line.
    focused=[c for c in chunks if c['agreement_id'] in named_ids] if named_ids else chunks
    complete_context=len(focused)<=64 and sum(len(c['text']) for c in focused)<=budget
    for c in chunks:
        length=sum(c['tokens'].values())
        score=0.0
        for word in expanded:
            tf=c['tokens'][word]
            if not tf:continue
            idf=math.log(1+(len(chunks)-df[word]+.5)/(df[word]+.5))
            score+=idf*tf*2.2/(tf+1.2*(.25+.75*length/avg))*(1 if word in q else .45)
        if c['agreement_id'] in named_ids:score+=8
        c['score']=score
    ranked=sorted((c for c in chunks if c['score']>0),key=lambda c:(-c['score'],c['agreement_id'],c['block_id'],c['start']))
    # With explicit document scope, let the model inspect a small source even with low lexical overlap.
    if len(records)==1 and not ranked:ranked=chunks
    selected=list(focused) if complete_context else []; used=sum(len(c['text']) for c in selected); per_doc=Counter(c['agreement_id'] for c in selected)
    # Round-robin by rank so repeated clauses across many agreements do not crowd out other documents.
    rounds={}
    for c in ([] if complete_context else ranked):
        rounds.setdefault(c['agreement_id'],[]).append(c)
    if per_doc_limit is None:
        per_doc_limit=max(3,limit//max(1,len(rounds)))
    def opening(aid):
        out,size=[],0
        for c in chunks:
            if c['agreement_id']!=aid or size>=lead_chars:continue
            out.append(c);size+=len(c['text'])
        return out
    reserve=lead_chars and not complete_context and per_doc_limit>3
    if reserve:
        for aid in rounds:
            for c in opening(aid):
                if len(selected)>=limit or used+len(c['text'])>budget:break
                selected.append(c);used+=len(c['text'])
    for level in range(per_doc_limit):
        for c in [items[level] for items in rounds.values() if len(items)>level]:
            if len(selected)>=limit or used+len(c['text'])>budget or any(x is c for x in selected):continue
            selected.append(c);used+=len(c['text']);per_doc[c['agreement_id']]+=1
    # Larger collections: add opening passages after ranking, within the per-document cap.
    if lead_chars and not complete_context and not reserve:
        for aid in list(dict.fromkeys(c['agreement_id'] for c in selected)):
            for lead in opening(aid):
                if any(x is lead for x in selected) or per_doc[aid]>=per_doc_limit or used+len(lead['text'])>budget:continue
                selected.append(lead);used+=len(lead['text']);per_doc[aid]+=1
    # Add the reviewed amendment's cited block if a selected parent's facts reference it.
    for c in list(selected):
        for fact in c['reviewed_facts'].values():
            source=record_map.get(fact.get('source_agreement_id'))
            if not source:continue
            extra=next((x for x in chunks if x['agreement_id']==source.id and x['block_id']==str(fact.get('evidence'))),None)
            if extra and not any(x['agreement_id']==extra['agreement_id'] and x['block_id']==extra['block_id'] for x in selected) and len(selected)<limit+3 and used+len(extra['text'])<=budget:
                selected.append(extra);used+=len(extra['text'])
    for i,c in enumerate(selected):
        c['source_id']=f'S{i+1}';c.pop('tokens',None);c.pop('score',None)
    return selected,{'passages_total':len(chunks),'passages_sent':len(selected),'documents_total':len(records),'documents_sent':len({c['agreement_id'] for c in selected}),'truncated':len(selected)<len(chunks),'strategy':'complete source context' if complete_context else 'ranked passages'}
