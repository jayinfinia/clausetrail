import csv
import copy
import hashlib
import io
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware
from backend import config
from backend.db import Session, Record, Job, Batch, Audit, Setting, audit, migrate, uid
from backend.domain import framework as fw
from backend.services import alerts
from backend import redaction
from backend.redaction import llm as redaction_llm
from backend import tagging
from backend.auth import user, reviewer, USERS, require_record
from backend.services.extraction import validate_value, model_status
from backend.services.parsers import spreadsheet_rows
from backend.services.queries import deadlines
from backend.services.grounded_qa import ask
from backend.services import qa_provider
from typing import Literal
from backend.services import worker

config.initialize()

@asynccontextmanager
async def lifespan(app):
    migrate()
    thread=None
    if os.getenv('RUN_WORKER','true')=='true':
        worker.STOP.clear(); thread=threading.Thread(target=worker.run,daemon=True); thread.start()
    yield
    worker.STOP.set()
    if thread: thread.join(timeout=2)

app=FastAPI(title='Clausetrail',version='1.0.0-demo',lifespan=lifespan)
app.add_middleware(SessionMiddleware,secret_key=config.SECRET,same_site='strict',https_only=False,max_age=3600)

@app.exception_handler(StaleDataError)
async def stale_record(request, exc):
    return JSONResponse({'detail':'Record changed concurrently; reload and try again'},status_code=409)

LOOPBACK={'localhost','127.0.0.1','::1'}

def allowed_origin(origin):
    """The configured origin, or the same scheme and port on another loopback name
    (uvicorn prints 127.0.0.1 while the default origin is localhost)."""
    if origin==config.ORIGIN: return True
    try: a,b=urlparse(origin),urlparse(config.ORIGIN); return a.scheme==b.scheme and a.port==b.port and a.hostname in LOOPBACK and b.hostname in LOOPBACK
    except ValueError: return False

@app.middleware('http')
async def headers(request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and not allowed_origin(origin):
            return JSONResponse({'detail':f'This page was opened from {origin}, which the app does not accept. Open {config.ORIGIN} instead.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    return response

class Login(BaseModel):
    username: str

@app.get('/api/auth')
def auth_state(request:Request):
    identity=USERS.get(request.session.get('user'))
    return {'user':identity,'csrf':request.session.get('csrf'),'demo':True,'users':[{'id':u['id'],'name':u['name'],'role':u['role'],'groups':u['groups']} for u in USERS.values()]}

@app.post('/api/auth/demo')
def login(body:Login,request:Request):
    if not config.DEMO_MODE or body.username not in USERS: raise HTTPException(403,'Unavailable')
    request.session.clear(); request.session.update({'user':body.username,'csrf':secrets.token_hex(24)})
    return {'user':USERS[body.username],'csrf':request.session['csrf']}

@app.post('/api/auth/logout')
def logout(request:Request):
    user(request); request.session.clear(); return {'ok':True}

@app.get('/health')
def health(): return {'status':'ok','mode':'fictional-data-demo'}

@app.get('/api/status')
def status(request:Request):
    identity=user(request)
    return {'mode':'private-local-copy' if PRIVATE_LOCAL else 'fictional-data-demo','external_cloud':'disabled','model':model_status(),'scopes':identity['groups'],'sharepoint':'not connected','retention':'Company records retained locally; temporary processing copies cleaned after each job.','production':'blocked pending company acceptance'}

def records_for(db,identity):
    return list(db.scalars(select(Record).where(Record.deleted==False,Record.scope.in_(identity['groups'])).order_by(Record.created.desc())))

PRIVATE_LOCAL=os.getenv('PRIVATE_LOCAL','false').lower()=='true'

def fact(r,field):
    return (r.approved or {}).get(field,{}).get('value')

def derived(r):
    """Framework view of a record: reference ID, standard file name and folder, end date."""
    labels=r.labels or {}
    kind=fact(r,'agreement_type') or labels.get('kind') or 'OTHER'
    party=fact(r,'counterparty') or labels.get('party') or ''
    eff=fact(r,'effective_date') or labels.get('eff')
    status=labels.get('status') or ('Executed' if r.executed else '')
    primary=(labels.get('confirmed') and labels.get('primaryType')) or fw.KINDS.get(kind,fw.KINDS['OTHER'])[1]
    name,warnings=fw.file_name(party,primary,eff,status,Path(r.filename).suffix)
    rule=labels.get('endRule') or 'fixed'
    try: end,floor=fw.effective_end(rule,eff,fact(r,'expiration_date'),labels.get('floor'),labels.get('relEnd'))
    except ValueError: end,floor=None,None
    return {'ref_id':labels.get('ref_id'),'relationship':labels.get('rel') or fw.UNCLASSIFIED,'owner':labels.get('owner') or '',
            'kind':kind,'counterparty':party,'standard_name':name,'standard_folder':fw.folder_path(labels.get('rel'),party),
            'name_warnings':warnings,'end_rule':rule,'end_date':end.isoformat() if end else None,'floor':floor.isoformat() if floor else None,
            'open_ended':rule=='later5' and end is None}

def summary(r):
    return {'id':r.id,'filename':r.filename,'scope':r.scope,'status':r.status,'approved':r.approved,'revision':r.revision,'executed':r.executed,'created':r.created.isoformat(),'parent_id':r.parent_id,'source_version':r.source_version,'labels':r.labels or {},'rel_path':r.rel_path or '','framework':derived(r)}

@app.get('/api/agreements')
def agreements(request:Request,q:str='',kind:str='',rel:str='',owner:str=''):
    identity=user(request)
    with Session() as db:
        rows=records_for(db,identity)
        if q: rows=[r for r in rows if q.lower() in (r.filename+' '+str(r.approved)+' '+str(r.labels or {})).lower()]
        if kind: rows=[r for r in rows if r.approved.get('agreement_type',{}).get('value')==kind]
        if rel: rows=[r for r in rows if (r.labels or {}).get('rel')==rel]
        if owner: rows=[r for r in rows if ((r.labels or {}).get('owner') or 'Unassigned')==owner]
        return [summary(r) for r in rows]

@app.get('/api/dashboard')
def dashboard(request:Request):
    identity=user(request)
    with Session() as db:
        rows=records_for(db,identity); due=deadlines(rows)
        by_rel={t:0 for t in fw.RELATIONSHIP_TYPES}; by_owner={o:0 for o in (*fw.OWNERS,'Unassigned')}
        for r in rows:
            labels=r.labels or {}
            rel=labels.get('rel') or fw.UNCLASSIFIED; by_rel[rel]=by_rel.get(rel,0)+1
            owner=labels.get('owner') or 'Unassigned'; by_owner[owner]=by_owner.get(owner,0)+1
        return {'by_relationship':by_rel,'by_owner':by_owner,'open_ended':sum(derived(r)['open_ended'] for r in rows),'unconfirmed_labels':sum(not (r.labels or {}).get('confirmed') for r in rows),'total':len(rows),'review':sum(r.status=='needs_review' for r in rows),'executed':sum(r.executed for r in rows),'unknown_expiration':sum(r.executed and not r.approved.get('expiration_date',{}).get('value') for r in rows),'overdue':sum(d['days']<0 for d in due),'upcoming':sum(0<=d['days']<=90 for d in due),'deadlines':due,'failed':sum(r.status=='failed' for r in rows)}

@app.get('/api/agreements/{rid}')
def agreement(rid:str,request:Request):
    identity=user(request)
    with Session() as db:
        r=require_record(db,rid,identity)
        events=list(db.scalars(select(Audit).where(Audit.record_id==rid).order_by(Audit.created.desc()).limit(100)))
        return {**summary(r),'proposals':r.proposals,'blocks':r.blocks,'history':[{'actor':e.actor,'action':e.action,'detail':e.detail,'created':e.created.isoformat()} for e in events]}

@app.get('/api/agreements/{rid}/source')
def source(rid:str,request:Request):
    identity=user(request)
    with Session() as db:
        r=require_record(db,rid,identity)
        if not Path(r.path).exists(): raise HTTPException(404,'Source unavailable')
        return FileResponse(r.path,filename=r.filename,media_type='application/octet-stream')

@app.get('/api/agreements/{rid}/evidence/{bid}')
def evidence(rid:str,bid:str,request:Request,revision:int|None=None,digest:str|None=None,version:str|None=None):
    identity=user(request)
    with Session() as db:
        r=require_record(db,rid,identity)
        if (revision is not None and revision!=r.revision) or (digest is not None and digest!=r.digest) or (version is not None and version!=r.source_version):
            raise HTTPException(409,'Source changed since this answer. Ask the question again.')
        if bid=='review':
            from backend.services.grounded_qa import review_citation
            return {**review_citation(r,1),'approved':r.approved}
        block=next((b for b in r.blocks if b['id']==bid),None)
        if not block: raise HTTPException(404,'Evidence not found')
        return {**block,'version':r.source_version,'filename':r.filename,'revision':r.revision,'digest':r.digest,'reviewed':r.executed}

async def bounded(upload):
    data=await upload.read(config.MAX_BYTES+1)
    await upload.close()
    if len(data)>config.MAX_BYTES: raise HTTPException(413,'File exceeds 25 MB')
    if not data: raise HTTPException(422,'Empty file')
    return data

def redact_upload(data,name,rel_path,policy):
    """Run the local redaction stage; only the redacted copy is ever stored."""
    try: detector=redaction_llm.detector()
    except redaction_llm.Unavailable: detector=None
    try: red,report,texts=redaction.redact_file(data,name,policy,detector)
    except Exception as exc: raise ValueError(f'Redaction failed, file not imported: {exc}')
    report.pop('by_source',None)
    return red,report,redaction.redact_path_segments(rel_path,texts,policy)

def ingest(db,data,name,scope,actor,rel_path='',redaction_report=None):
    suffix=Path(name).suffix.lower()
    if suffix not in ('.pdf','.docx','.xlsx','.csv','.txt'): raise ValueError('Unsupported file type')
    if suffix=='.pdf' and not data.startswith(b'%PDF'): raise ValueError('Invalid PDF signature')
    if suffix in ('.docx','.xlsx') and not data.startswith(b'PK'): raise ValueError('Invalid Office signature')
    digest=hashlib.sha256(data).hexdigest()
    existing=db.scalar(select(Record).where(Record.digest==digest,Record.scope==scope,Record.deleted==False))
    if existing: return {'id':existing.id,'duplicate':True,'filename':existing.filename}
    rid=uid(); path=config.DATA/'originals'/rid
    path.write_bytes(data)
    rel_path=str(rel_path or '').replace('\\','/')[:500]
    filename=Path(name.replace('\\','/')).name[:250]
    labels=fw.suggest_labels(rel_path or filename,filename)
    if redaction_report: labels['redaction']=redaction_report
    r=Record(id=rid,filename=filename,scope=scope,digest=digest,path=str(path),status='queued',labels=labels,rel_path=rel_path)
    try:
        db.add(r); db.add(Job(record_id=rid)); audit(db,actor,'imported',rid); db.commit()
    except Exception:
        db.rollback(); path.unlink(missing_ok=True); raise
    return {'id':rid,'duplicate':False,'filename':r.filename}

@app.post('/api/imports')
async def imports(request:Request,files:list[UploadFile]=File(...),scope:str=Form(...),paths:list[str]=Form(default=[]),redact:str=Form('off')):
    identity=reviewer(request)
    if scope not in identity['groups']: raise HTTPException(403,'Scope not allowed')
    if len(files)>50: raise HTTPException(422,'Maximum 50 files per batch')
    if paths and len(paths)!=len(files): raise HTTPException(422,'Folder paths must match the files')
    if redact not in ('off',*redaction.POLICIES): raise HTTPException(422,'Unknown redaction policy')
    results=[]
    with Session() as db:
        for index,upload in enumerate(files):
            name=upload.filename or 'unknown'
            try:
                data=await bounded(upload)
                rel=paths[index] if paths else ''; report=None
                if redact!='off':
                    data,report,rel=redact_upload(data,name,rel,redact)
                    if rel: name=Path(rel).name  # strict mode may have removed a person's name from it
                result=ingest(db,data,name,scope,identity['id'],rel,report)
                if report: result['redaction']={'redactions':report['redactions'],'engine':report['engine']}
                if not result.get('duplicate'):
                    result['suggested']={k:db.get(Record,result['id']).labels.get(k) for k in ('rel','party','kind')}
                results.append(result)
            except (ValueError,HTTPException) as exc:
                results.append({'filename':name,'error':str(exc.detail if isinstance(exc,HTTPException) else exc)})
    return {'results':results}

@app.get('/api/jobs')
def jobs(request:Request):
    identity=user(request)
    with Session() as db:
        rows=db.execute(select(Job,Record).join(Record,Record.id==Job.record_id).where(Record.deleted==False,Record.scope.in_(identity['groups'])).order_by(Job.updated.desc()).limit(100))
        return [{'id':j.id,'agreement_id':r.id,'filename':r.filename,'status':j.status,'error':j.error,'attempts':j.attempts} for j,r in rows]

@app.post('/api/agreements/{rid}/retry')
def retry(rid:str,request:Request):
    identity=reviewer(request)
    with Session() as db:
        r=require_record(db,rid,identity,True)
        if r.status!='failed': raise HTTPException(409,'Only failed processing can be retried')
        r.status='queued'; db.add(Job(record_id=rid)); audit(db,identity['id'],'retried',rid); db.commit()
    return {'ok':True}

class Decision(BaseModel):
    value: str | int | None=None
    evidence: str | None=None
    note: str=Field(default='',max_length=2000)
    source_agreement_id: str | None=None

class Review(BaseModel):
    revision:int
    executed:bool
    fields:dict[str,Decision]

@app.post('/api/agreements/{rid}/review')
def review(rid:str,body:Review,request:Request):
    identity=reviewer(request)
    with Session() as db:
        r=require_record(db,rid,identity,True)
        if r.revision!=body.revision: raise HTTPException(409,'Record changed; reload before reviewing')
        if r.status not in ('needs_review','reviewed'): raise HTTPException(409,'Processing must finish first')
        approved=dict(r.approved)
        for field,decision in body.fields.items():
            if field not in config.FIELDS: raise HTTPException(422,'Unknown field')
            source_record=require_record(db,decision.source_agreement_id,identity) if decision.source_agreement_id else r
            if source_record.scope != r.scope: raise HTTPException(422,'Evidence must share the agreement access scope')
            block=next((b for b in source_record.blocks if b['id']==decision.evidence),None)
            if decision.value is not None and str(decision.value).strip() and not block and not decision.note.strip():
                raise HTTPException(422,'Every approved fact needs source evidence or a reviewer explanation')
            try: value=validate_value(field,decision.value) if decision.value is not None and str(decision.value).strip() else None
            except ValueError as exc: raise HTTPException(422,str(exc))
            approved[field]={'value':value,'evidence':decision.evidence if block else None,'note':decision.note,'reviewer':identity['id'], 'source_agreement_id':source_record.id if source_record.id!=r.id else None}
        r.approved=approved; r.executed=body.executed; r.revision+=1; r.status='reviewed'
        assign_reference_id(db,r,identity)
        audit(db,identity['id'],'reviewed',rid,{'revision':r.revision,'fields':list(body.fields),'executed':body.executed}); db.commit()
        return summary(r)

def assign_reference_id(db,r,identity):
    labels=dict(r.labels or {})
    if labels.get('ref_id'): return
    kind=fact(r,'agreement_type') or labels.get('kind') or 'OTHER'
    eff=fact(r,'effective_date') or labels.get('eff')
    year=int(str(eff)[:4]) if eff else r.created.year
    existing=[(x.labels or {}).get('ref_id') for x in db.scalars(select(Record))]
    labels['ref_id']=fw.reference_id(kind,year,existing); labels['kind']=kind
    r.labels=labels
    audit(db,identity['id'],'labels_changed',r.id,{'changes':[{'field':'ref_id','old':None,'new':labels['ref_id']}]})

class LabelChange(BaseModel):
    revision:int
    changes:dict[str,str|list[str]|None]

@app.get('/api/framework')
def framework(request:Request):
    user(request)
    return {'organization':fw.ORGANIZATION,'relationship_types':fw.RELATIONSHIP_TYPES,'components':fw.COMPONENTS,'alert_roles':fw.ALERT_ROLES,
            'directions':fw.DIRECTIONS,'statuses':fw.STATUSES,'owners':fw.OWNERS,'kinds':{k:{'code':v[0],'primary':v[1]} for k,v in fw.KINDS.items()},
            'private_local':PRIVATE_LOCAL}

@app.patch('/api/agreements/{rid}/labels')
def labels(rid:str,body:LabelChange,request:Request):
    identity=reviewer(request)
    with Session() as db:
        r=require_record(db,rid,identity,True)
        if r.revision!=body.revision: raise HTTPException(409,'Record changed; reload before editing labels')
        old=dict(r.labels or {})
        try: new=fw.validate_labels(old,body.changes)
        except (ValueError,TypeError) as exc: raise HTTPException(422,str(exc))
        new['confirmed']=True; new['suggestedFrom']=[]
        changes=[{'field':k,'old':old.get(k),'new':new.get(k)} for k in sorted(set(old)|set(new)) if k not in ('confirmed','suggestedFrom') and old.get(k)!=new.get(k)]
        before=derived(r)['end_date']
        r.labels=new; r.revision+=1
        after=derived(r)['end_date']
        if before!=after: changes.append({'field':'end date','old':before,'new':after})
        audit(db,identity['id'],'labels_changed' if changes else 'labels_confirmed',rid,{'changes':changes,'revision':r.revision}); db.commit()
        return summary(r)

SETTINGS_KEY='alert_settings'

def alert_settings(db):
    row=db.get(Setting,SETTINGS_KEY)
    return alerts.validate(row.value if row else {})

@app.get('/api/alerts')
def alert_preview(request:Request):
    identity=user(request)
    with Session() as db:
        rows=records_for(db,identity); by_id={r.id:r for r in rows}
        due=deadlines(rows)
        exp=[{**d,'status':d.get('label_status')} for d in due if d['kind']=='expiration']
        settings=alert_settings(db)
        result=alerts.preview(exp,settings)
        notice={d['agreement_id']:d for d in due if d['kind']=='notice'}
        today=date.today(); urgent=settings['urgent']
        result['items']=[{**e,'kind_label':derived(by_id[e['agreement_id']])['kind'],'notice_date':notice.get(e['agreement_id'],{}).get('date'),
                          'notice_days':notice.get(e['agreement_id'],{}).get('days'),'urgent_send':(date.fromisoformat(e['date'])-timedelta(days=urgent)).isoformat(),
                          'urgent_in':e['days']-urgent,'past_send':(date.fromisoformat(e['date'])+timedelta(days=1)).isoformat()} for e in exp if e['status'] not in alerts.INACTIVE]
        result['open_ended']=[{'agreement_id':r.id,'counterparty':derived(r)['counterparty'],'floor':derived(r)['floor']} for r in rows if r.executed and derived(r)['open_ended']]
        return result

class AlertSettings(BaseModel):
    day:int; time:str='08:00'; urgent:int; pastDue:bool; rec:dict[str,bool]; extra:list[str]=Field(default_factory=list,max_length=10)

@app.put('/api/alerts/settings')
def save_alert_settings(body:AlertSettings,request:Request):
    identity=reviewer(request)
    with Session() as db:
        old=alert_settings(db)
        try: new=alerts.validate(body.model_dump())
        except ValueError as exc: raise HTTPException(422,str(exc))
        row=db.get(Setting,SETTINGS_KEY)
        if row: row.value=new
        else: db.add(Setting(key=SETTINGS_KEY,value=new))
        changes=[{'field':k,'old':old.get(k),'new':new.get(k)} for k in new if old.get(k)!=new.get(k)]
        if changes: audit(db,identity['id'],'alert_settings',SETTINGS_KEY,{'changes':changes})
        db.commit(); return new

@app.get('/api/log')
def edit_log(request:Request):
    identity=user(request)
    with Session() as db:
        visible={r.id:r for r in records_for(db,identity)}
        events=db.scalars(select(Audit).order_by(Audit.created.desc()).limit(2000))
        out=[]
        for e in events:
            if e.record_id!=SETTINGS_KEY and e.record_id not in visible: continue
            r=visible.get(e.record_id)
            out.append({'ts':e.created.isoformat(),'editor':e.actor,'action':e.action,'agreement_id':e.record_id if r else None,
                        'ref_id':(r.labels or {}).get('ref_id') if r else '—','name':derived(r)['counterparty'] or r.filename if r else 'Alert settings',
                        'changes':(e.detail or {}).get('changes') or []})
            if len(out)>=500: break
        return out

class Link(BaseModel):
    parent_id:str
    revision:int
    fields:list[str]

@app.post('/api/agreements/{rid}/amend')
def amend(rid:str,body:Link,request:Request):
    identity=reviewer(request)
    with Session() as db:
        child=require_record(db,rid,identity,True); parent=require_record(db,body.parent_id,identity,True)
        if child.id==parent.id or child.scope!=parent.scope: raise HTTPException(422,'Parent must be distinct and in the same access scope')
        if not child.executed or not parent.executed: raise HTTPException(422,'Both agreements must be reviewed and executed')
        if child.approved.get('agreement_type',{}).get('value')!='AMENDMENT': raise HTTPException(422,'Child must be a reviewed amendment')
        if parent.revision!=body.revision: raise HTTPException(409,'Parent changed; reload')
        if not body.fields or any(f not in config.FIELDS or f not in child.approved for f in body.fields): raise HTTPException(422,'Choose approved amendment fields')
        # Evidence stays attached to its actual amendment document.
        parent.approved={**parent.approved,**{f:{**child.approved[f],'source_agreement_id':child.id} for f in body.fields}}
        parent.revision+=1; child.parent_id=parent.id
        audit(db,identity['id'],'amendment_applied',parent.id,{'revision':parent.revision,'amendment':child.id,'fields':body.fields}); db.commit()
        return summary(parent)

@app.delete('/api/agreements/{rid}')
def delete(rid:str,request:Request):
    identity=reviewer(request)
    with Session() as db:
        r=require_record(db,rid,identity,True)
        parents=records_for(db,identity)
        if any(any(v.get('source_agreement_id')==rid for v in parent.approved.values()) for parent in parents):
            raise HTTPException(409,'This document supports an approved amendment. Review parent facts before deleting it.')
        removed_counterparty=str(r.approved.get('counterparty',{}).get('value') or '')
        r.deleted=True; r.blocks=[]; r.proposals={}; r.approved={}; r.executed=False; r.status='deleted'; r.revision+=1
        for j in db.scalars(select(Job).where(Job.record_id==rid)): j.status='cancelled'
        # Remove spreadsheet derivatives that refer to the record; raw preview batches are short-lived.
        for b in db.scalars(select(Batch)):
            b.changes=[c for c in b.changes if c.get('id')!=rid]
            b.rows=[row for row in b.rows if rid not in row.get('values',{}).values() and not (removed_counterparty and removed_counterparty in row.get('values',{}).values())]
        audit(db,identity['id'],'deleted',rid); db.commit()
        Path(r.path).unlink(missing_ok=True)
    return {'ok':True,'note':'Active app copies removed. Backup retention is governed separately.'}

@app.get('/api/export')
def export(request:Request):
    identity=user(request)
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(['agreement_id','ref_id','relationship','owner','standard_name','standard_folder','filename',*config.FIELDS])
    def safe(value):
        text=str(value if value is not None else '')
        return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
    with Session() as db:
        for r in records_for(db,identity):
            d=derived(r)
            writer.writerow([r.id,safe(d['ref_id']),safe(d['relationship']),safe(d['owner']),safe(d['standard_name']),safe(d['standard_folder']),safe(r.filename),*[safe(r.approved.get(f,{}).get('value')) for f in config.FIELDS]])
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=agreement-register.csv'})

class Question(BaseModel):
    question:str=Field(min_length=2,max_length=1000)
    mode:Literal['auto','ai','evidence']='auto'
    agreement_ids:list[str]=Field(default_factory=list,max_length=20)

@app.get('/api/qa/status')
def qa_status(request:Request):
    user(request)
    return {**qa_provider.readiness(),'cloud_fallback':False,'history_retained':False}

@app.post('/api/questions')
def questions(body:Question,request:Request):
    identity=user(request)
    with Session() as db:
        accessible=records_for(db,identity)
        if body.agreement_ids:
            allowed={r.id for r in accessible}
            if any(rid not in allowed for rid in body.agreement_ids): raise HTTPException(404,'Selected agreement not found')
            rows=[r for r in accessible if r.id in body.agreement_ids]
        else: rows=accessible
        snapshot={r.id:(r.revision,r.digest,r.scope) for r in rows}
    try:
        result=ask(body.question,rows,mode=body.mode)
    except qa_provider.ModelUnavailable as exc:
        raise HTTPException(503,str(exc))
    except qa_provider.ModelResponseError as exc:
        raise HTTPException(502,str(exc))
    with Session() as db:
        current={r.id:(r.revision,r.digest,r.scope) for r in records_for(db,identity)}
        if any(current.get(rid)!=state for rid,state in snapshot.items()):
            raise HTTPException(409,'Sources or access changed while answering. Please ask again.')
    result['coverage']={'accessible_documents':len(accessible),'selected_documents':len(rows),'pending_or_failed':sum(r.status not in ('reviewed','needs_review') for r in rows),'unreviewed':sum(not r.executed for r in rows)}
    return result

@app.post('/api/spreadsheets')
async def sheet_upload(request:Request,file:UploadFile=File(...),scope:str=Form(...)):
    identity=reviewer(request)
    if scope not in identity['groups']: raise HTTPException(403,'Scope not allowed')
    data=await bounded(file)
    try: headers,rows=spreadsheet_rows(data,Path(file.filename or '').suffix.lower())
    except Exception: raise HTTPException(422,'Unreadable spreadsheet; use CSV or XLSX with unique headers')
    with Session() as db:
        b=Batch(actor=identity['id'],scope=scope,filename=Path(file.filename or 'tracker').name,rows=rows)
        db.add(b); db.commit(); return {'id':b.id,'headers':headers,'rows':rows[:30],'total':len(rows)}

class Mapping(BaseModel):
    mapping:dict[str,str]

class Selections(BaseModel):
    rows:list[int]

def get_batch(db,bid,identity):
    b=db.get(Batch,bid)
    if not b or b.actor!=identity['id'] or b.scope not in identity['groups']: raise HTTPException(404,'Import not found')
    return b

@app.post('/api/spreadsheets/{bid}/preview')
def sheet_preview(bid:str,body:Mapping,request:Request):
    identity=reviewer(request)
    if any(f not in (*config.FIELDS,'agreement_id') for f in body.mapping): raise HTTPException(422,'Unknown mapped field')
    with Session() as db:
        b=get_batch(db,bid,identity)
        if b.status!='preview': raise HTTPException(409,'Batch already committed')
        records=[r for r in records_for(db,identity) if r.scope==b.scope]
        changes=[]
        for row in b.rows:
            values={field:row['values'].get(column,'') for field,column in body.mapping.items()}
            aid=values.pop('agreement_id','').strip()
            if aid: candidates=[r for r in records if r.id==aid]
            else:
                cp=values.get('counterparty','').strip().casefold()
                candidates=[r for r in records if cp and str(r.approved.get('counterparty',{}).get('value','')).casefold()==cp]
            change={'row':row['row'],'sheet':row['sheet'],'state':'unmatched','values':values,'candidates':[{'id':r.id,'filename':r.filename} for r in candidates]}
            if len(candidates)==1:
                r=candidates[0]; change.update({'state':'ready','id':r.id,'revision':r.revision,'previous_proposals':r.proposals,'previous_status':r.status,'conflicts':[]})
                for f,v in values.items():
                    try: parsed=validate_value(f,v) if v else None
                    except ValueError: change['state']='invalid'; continue
                    current=r.approved.get(f,{}).get('value')
                    if current is not None and current!=parsed: change['conflicts'].append({'field':f,'approved':current,'spreadsheet':parsed})
            elif len(candidates)>1: change['state']='ambiguous'
            changes.append(change)
        b.changes=changes; db.commit()
        return {'id':bid,'changes':[{k:v for k,v in c.items() if k!='previous_proposals'} for c in changes]}

@app.post('/api/spreadsheets/{bid}/commit')
def sheet_commit(bid:str,body:Selections,request:Request):
    identity=reviewer(request)
    with Session() as db:
        b=get_batch(db,bid,identity)
        if b.status!='preview': raise HTTPException(409,'Batch already committed')
        chosen=copy.deepcopy([c for c in b.changes if c['row'] in body.rows])
        if not chosen or any(c['state']!='ready' for c in chosen): raise HTTPException(422,'Select matched valid rows only')
        if len({c['id'] for c in chosen})!=len(chosen): raise HTTPException(422,'Multiple selected rows target one agreement')
        for c in chosen:
            r=require_record(db,c['id'],identity,True)
            if r.revision!=c['revision']: raise HTTPException(409,'Agreement changed; generate preview again')
            proposals=dict(r.proposals)
            for f,v in c['values'].items():
                if v:
                    proposals[f]={'value':validate_value(f,v),'state':'proposed','evidence':None,'method':'spreadsheet','raw':v,'source':{'batch':bid,'sheet':c['sheet'],'row':c['row'],'filename':b.filename}}
            r.proposals=proposals; r.revision+=1; r.status='needs_review'; c['applied_revision']=r.revision
            audit(db,identity['id'],'spreadsheet_proposals',r.id,{'batch':bid,'revision':r.revision})
        b.changes=chosen; b.status='committed'; b.rows=[]; db.commit()
        return {'count':len(chosen),'status':'committed; requires review'}

@app.post('/api/spreadsheets/{bid}/rollback')
def sheet_rollback(bid:str,request:Request):
    identity=reviewer(request)
    with Session() as db:
        b=get_batch(db,bid,identity)
        if b.status!='committed': raise HTTPException(409,'No committed batch to undo')
        for c in b.changes:
            r=require_record(db,c['id'],identity,True)
            if r.revision!=c['applied_revision']: raise HTTPException(409,'Later edits exist; rollback would overwrite them')
            r.proposals=c['previous_proposals']; r.revision+=1; r.status=c.get('previous_status','needs_review')
            audit(db,identity['id'],'spreadsheet_rollback',r.id,{'batch':bid})
        b.status='rolled_back'; b.changes=[]; db.commit()
        return {'ok':True}

from scripts.demo_corpus import FOLDERS as FICTIONAL_FOLDERS

@app.get('/api/redaction/status')
def redaction_status(request:Request):
    user(request)
    import shutil
    return {'policies':{'standard':[redaction.CATEGORY_NAMES[c] for c in redaction.POLICIES['standard']],'strict':[redaction.CATEGORY_NAMES[c] for c in redaction.POLICIES['strict']]},
            'llm':redaction_llm.status(),'ocr':bool(shutil.which('tesseract')),'tagging':tagging.status(),'default':'standard' if PRIVATE_LOCAL else 'off'}

@app.post('/api/demo/seed')
def seed(request:Request):
    identity=reviewer(request)
    from scripts.demo_corpus import generate
    folder=config.DATA/'demo-fixtures'; generate(folder)
    results=[]
    with Session() as db:
        for path in sorted(folder.glob('*.txt')):
            scope='legal' if 'restricted' in path.name else 'research'
            if scope in identity['groups']: results.append(ingest(db,path.read_bytes(),path.name,scope,identity['id'],FICTIONAL_FOLDERS.get(path.name,'')))
    return {'results':results}

@app.get('/api/demo/tracker')
def tracker(request:Request):
    user(request)
    from scripts.demo_corpus import generate
    folder=config.DATA/'demo-fixtures'; generate(folder)
    return FileResponse(folder/'tracker.csv',filename='fictional-tracker.csv')

web=Path(__file__).resolve().parents[2]/'frontend'/'dist'
if web.exists():
    app.mount('/',StaticFiles(directory=web,html=True),name='frontend')
