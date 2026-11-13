// Agreement detail with evidence review, Ask agreements, Expiration alerts.
import React,{useEffect,useState} from 'react';
import {api} from './api';
import type {Ctx} from './ctx';
import {FIELDS,type RecordItem,type Fact,type Labels,type Citation,type Answer,type AIStatus} from './types';
import {Pill,StatusPill,ProcPill,DaysCell,Empty,Copy,dt,daysFrom,party,kindOf,endOf,alertOf,label} from './ui';

const REDACT_NAMES:Record<string,string>={GOV_ID:'SSN / tax ID',FIN_ACCOUNT:'bank or card number',DOB:'date of birth',PERSON:'person name',EMAIL:'email',PHONE:'phone',ADDRESS:'street address'};
const FIELD_HELP:Record<string,string>={agreement_type:'CDA, MTA, DUA, SERVICES, COLLABORATION, CONSULTING, GRANT, INVESTMENT, AMENDMENT or OTHER',effective_date:'YYYY-MM-DD',expiration_date:'YYYY-MM-DD',confidentiality_end:'YYYY-MM-DD',return_date:'YYYY-MM-DD',notice_days:'Number of days'};

export function Detail({c,id}:{c:Ctx;id:string}){
 const [r,setR]=useState<RecordItem|null>(null),[dec,setDec]=useState<Record<string,Fact>>({}),[executed,setExecuted]=useState(false),[focus,setFocus]=useState(''),[parent,setParent]=useState(''),[amend,setAmend]=useState<string[]>(['expiration_date']);
 const load=async()=>{const x=await api<RecordItem>('/agreements/'+id);setR(x);setExecuted(x.executed);const d:Record<string,Fact>={};FIELDS.forEach(f=>{const p=x.proposals?.[f];d[f]=x.approved[f]||{value:p?.value??null,evidence:p?.evidence??null,note:''}});setDec(d)};
 useEffect(()=>{setR(null);load().catch(e=>{c.setError(e.message);c.go('#agreements')})},[id]);
 useEffect(()=>{if(r&&['queued','running'].includes(r.status)){const t=setTimeout(()=>load().catch(()=>{}),2500);return()=>clearTimeout(t)}},[r?.status,r?.revision]);
 if(!r)return <p className="muted">Opening agreement…</p>;
 const a=alertOf(r),f=r.framework,ed=c.editable,canReview=['needs_review','reviewed'].includes(r.status);
 const save=()=>c.act(async()=>{await api('/agreements/'+r.id+'/review',{method:'POST',body:JSON.stringify({revision:r.revision,executed,fields:dec})});await load()},'Reviewed facts saved. Deadlines and alerts now use them.');
 const saveLabels=(changes:Labels)=>c.act(async()=>{await api('/agreements/'+r.id+'/labels',{method:'PATCH',body:JSON.stringify({revision:r.revision,changes})});await load()},'Labels saved and logged.');
 const notice=typeof r.approved.notice_days?.value==='number'?r.approved.notice_days.value as number:null;
 const blocks=(r.blocks||[]);
 return <>
  <button className="back" onClick={()=>history.length>1?history.back():c.go('#agreements')}>← Back</button>
  <div className="head"><div><p className="mono" style={{margin:0,color:'var(--muted)'}}>{r.labels.ref_id||'No agreement ID yet · assigned on first review'}</p><h1>{party(r)} · {kindOf(r)}</h1><p className="sub">{f.relationship}{r.labels.owner?` · owner ${r.labels.owner}`:' · no owner yet'} · {r.filename}</p></div>
   <div className="row">{r.status==='reviewed'?<StatusPill s={r.labels.status||(r.executed?'Executed':null)}/>:<ProcPill s={r.status}/>}{a&&<Pill k={a.k}>{a.t}</Pill>}</div></div>
  {r.labels.waiting&&<div className="panel" style={{flexDirection:'row',flexWrap:'wrap',gap:8,alignItems:'center'}}><span className="muted">Waiting on</span><b>{r.labels.waiting}</b></div>}
  <div className="cols">
   <div className="stack">
    <section className="panel"><div className="head"><h2>Review facts</h2><span className="small muted">Revision {r.revision}</span></div>
     {['queued','running'].includes(r.status)&&<div className="proto">Still reading this document. This page updates on its own.</div>}
     {r.status==='failed'&&<div className="banner err">This document could not be read.{ed&&<button onClick={()=>c.act(async()=>{await api('/agreements/'+r.id+'/retry',{method:'POST'});await load()},'Queued again')}>Retry</button>}</div>}
     <p className="small muted" style={{margin:0}}>Each value stays a proposal until you approve it. Pick the passage that supports it, or explain why there isn't one.</p>
     <div>{FIELDS.map(k=>{const p=r.proposals?.[k],v=dec[k]||{value:null};const odd=p?.state==='conflict'||p?.state==='ambiguous'||p?.state==='needs_evidence';return <div className="field" key={k}>
      <div className="fh"><label htmlFor={'f-'+k}>{label(k)}</label><span className={'hint'+(odd?' bad':'')}>{r.approved[k]?(r.approved[k].value!==null&&r.approved[k].value!==''?'approved':'reviewed as unknown'):p&&p.state!=='unknown'?(p.method==='claude'?(p.state==='needs_evidence'?'Claude · quote not found, check it':'proposed by Claude'):`${p.state} · ${p.method}`):'not found in the document'}</span></div>
      <input id={'f-'+k} disabled={!ed} placeholder={FIELD_HELP[k]||'Unknown / not stated'} value={v.value??''} onChange={e=>setDec({...dec,[k]:{...v,value:e.target.value||null}})}/>
      {!r.approved[k]&&(p as {note?:string}|undefined)?.note&&<span className="hint">{(p as {note?:string}).note}</span>}
      {p?.raw&&p.state==='ambiguous'&&<span className="hint bad">The document says “{p.raw}”. Don't guess the date format; check the source.</span>}
      {p?.source&&<span className="hint">From tracker {p.source.filename}, {p.source.sheet} row {p.source.row}</span>}
      <div className="ev"><select aria-label={'Evidence for '+label(k)} disabled={!ed} value={v.evidence||''} onChange={e=>{setDec({...dec,[k]:{...v,evidence:e.target.value||null}});setFocus(e.target.value)}}><option value="">Choose the supporting passage</option>{blocks.map(b=><option key={b.id} value={b.id}>{b.locator}: {b.text.slice(0,60)}</option>)}</select>
       {v.source_agreement_id?<button className="link" onClick={()=>c.go('#a/'+v.source_agreement_id)}>Amendment ↗</button>:v.evidence?<button className="link" onClick={()=>setFocus(v.evidence||'')}>Show</button>:null}</div>
      <input aria-label={'Note for '+label(k)} disabled={!ed} placeholder="Note (required when no passage supports the value)" value={v.note||''} onChange={e=>setDec({...dec,[k]:{...v,note:e.target.value}})}/>
     </div>})}</div>
     <label className="confirm"><input type="checkbox" disabled={!ed} checked={executed} onChange={e=>setExecuted(e.target.checked)}/><span><b>I checked the source and this agreement is executed.</b><br/><span className="small muted">A signature block alone doesn't prove execution. Only executed agreements count toward deadlines and alerts.</span></span></label>
     {ed&&<button className="btn" disabled={c.busy||!canReview} onClick={save}>{c.busy?'Saving…':'Approve reviewed facts'}</button>}
    </section>
    {ed&&kindOf(r)==='AMENDMENT'&&r.executed&&<section className="panel"><h2>Apply this amendment</h2><p className="small muted" style={{margin:0}}>Choose the agreement it changes and which reviewed terms it changes. The evidence stays linked to this document.</p>
     <select aria-label="Agreement this amends" value={parent} onChange={e=>setParent(e.target.value)}><option value="">Choose the agreement it changes</option>{c.records.filter(x=>x.id!==r.id&&x.executed&&x.scope===r.scope).map(x=><option key={x.id} value={x.id}>{party(x)} · {kindOf(x)} {x.labels.ref_id?'· '+x.labels.ref_id:''}</option>)}</select>
     <div className="comp">{['expiration_date','notice_days','confidentiality_end','return_date','renewal','permitted_use'].map(k=><label key={k} className="chk"><input type="checkbox" checked={amend.includes(k)} onChange={e=>setAmend(e.target.checked?[...amend,k]:amend.filter(x=>x!==k))}/>{label(k)}</label>)}</div>
     <div className="row"><button className="btn ghost" disabled={c.busy||!parent||!amend.length} onClick={()=>c.act(async()=>{const p=c.records.find(x=>x.id===parent)!;await api('/agreements/'+r.id+'/amend',{method:'POST',body:JSON.stringify({parent_id:parent,revision:p.revision,fields:amend})})},'Amendment applied. The original agreement\'s dates are updated.')}>Apply selected terms</button></div></section>}
    <section className="panel"><h2>Details</h2><dl>
     <dt>Effective date</dt><dd className="mono">{dt(String(r.approved.effective_date?.value||r.labels.eff||''))}</dd>
     <dt>Ends</dt><dd><span className="mono">{endOf(f)}</span> {f.end_date&&<>· <DaysCell iso={f.end_date}/></>}</dd>
     <dt>Renewal notice</dt><dd>{notice!==null&&f.end_date?<>{notice} days · deadline <span className="mono">{dt(new Date(+new Date(f.end_date+'T12:00:00')-notice*864e5).toISOString())}</span></>:'—'}</dd>
     <dt>Expiration alerts</dt><dd><AlertChips r={r}/></dd>
     <dt>Confidentiality ends</dt><dd className="mono">{dt(String(r.approved.confidentiality_end?.value||''))}</dd>
     <dt>Return or destroy by</dt><dd className="mono">{dt(String(r.approved.return_date?.value||''))}</dd>
     <dt>Permitted use</dt><dd>{String(r.approved.permitted_use?.value||'—')}</dd>
     <dt>Renewal</dt><dd>{String(r.approved.renewal?.value||'—')}</dd>
    </dl></section>
   </div>
   <div className="stack">
    {c.vocab&&<LabelsPanel r={r} c={c} onSave={saveLabels}/>}
    <section className="panel"><h2>Filing</h2>
     <div className="lab"><span>Standard file name</span><div className="copyrow"><code>{f.standard_name}</code><Copy text={f.standard_name}/></div></div>
     <div className="lab"><span>Folder</span><div className="copyrow"><code>{f.standard_folder}</code><Copy text={f.standard_folder}/></div></div>
     {f.name_warnings.map(w=><span key={w} className="hint bad">{w}</span>)}
     {r.labels.tagging&&<div className="lab"><span>Tagging</span><div className="row"><Pill k={r.labels.tagging.status==='done'?'good':r.labels.tagging.status==='failed'?'bad':'warn'}>{r.labels.tagging.status==='done'?`Claude · ${r.labels.tagging.model}`:r.labels.tagging.status==='failed'?'Claude tagging failed':'Not sent to Claude'}</Pill><span className="small">{r.labels.tagging.status==='done'?`${r.labels.tagging.fields} field${r.labels.tagging.fields===1?'':'s'} proposed from the redacted text. Review before approving.`:r.labels.tagging.reason}</span></div></div>}
     {r.labels.redaction?<div className="lab"><span>Redaction</span><div className="row"><Pill k="good">Redacted · {r.labels.redaction.policy}</Pill><span className="small">{r.labels.redaction.redactions} item{r.labels.redaction.redactions===1?'':'s'} removed{Object.keys(r.labels.redaction.by_category).length?`: ${Object.entries(r.labels.redaction.by_category).map(([k,v])=>`${v} ${REDACT_NAMES[k]||k}`).join(', ')}`:''}</span></div><span className="small muted">{r.labels.redaction.engine==='pdf-ocr'?`Scanned, read with OCR (${r.labels.redaction.scanned_pages} page${r.labels.redaction.scanned_pages===1?'':'s'}) · `:''}{r.labels.redaction.model?`Local model ${r.labels.redaction.model} + rules`:'Rules only (local model was off)'}. Only the redacted copy is stored.</span></div>:null}
     {r.rel_path&&<div className="lab"><span>Imported from</span><code className="mono small" style={{overflowWrap:'anywhere'}}>{r.rel_path}</code></div>}
     <div className="pdf"><b>{r.filename}</b><span>{r.labels.redaction?'The redacted copy stored here. The unredacted original was never saved.':'The original file this agreement was read from.'}</span><a className="link" href={'/api/agreements/'+r.id+'/source'}>{r.labels.redaction?'Download redacted copy ↓':'Download original ↓'}</a></div>
    </section>
    <section className="panel"><div className="head"><h2>Source text</h2>{focus&&<button className="link small" onClick={()=>setFocus('')}>Show all</button>}</div>
     {blocks.length?<div className="blocks">{blocks.filter(b=>!focus||b.id===focus).map(b=><div key={b.id} className={'block'+(b.id===focus?' on':'')}><small>{b.locator}</small><pre>{b.text}</pre></div>)}</div>:<Empty>No text yet. It appears once the document is read.</Empty>}</section>
    <section className="panel"><h2>History</h2><div className="hist">{(r.history||[]).map((h,i)=><div key={i}><span className="mono">{new Date(h.created+'Z').toLocaleDateString('en-US',{month:'short',day:'numeric'})}</span><span>{histText(h,c)}</span></div>)}</div></section>
    {ed&&<section className="panel"><h2>Remove</h2><p className="small muted" style={{margin:0}}>Removes this app's copy and everything read from it. It doesn't touch the original anywhere else.</p><div className="row"><button className="btn ghost" style={{color:'var(--bad)',borderColor:'var(--bad)'}} disabled={c.busy} onClick={()=>{if(window.confirm('Remove this agreement and everything read from it?'))c.act(async()=>{await api('/agreements/'+r.id,{method:'DELETE'});c.go('#agreements')},'Agreement removed.')}}>Remove agreement</button></div></section>}
   </div>
  </div>
 </>
}

const ACTIONS:Record<string,string>={imported:'Imported',reviewed:'Facts reviewed',labels_changed:'Labels changed',labels_confirmed:'Suggested labels confirmed',amendment_applied:'Amendment applied',spreadsheet_proposals:'Tracker values proposed',spreadsheet_rollback:'Tracker import undone',retried:'Reading retried',deleted:'Removed'};
function histText(h:{actor:string;action:string;detail:unknown},c:Ctx){const who=c.users.find(u=>u.id===h.actor)?.name||h.actor;const d=h.detail as {changes?:{field:string;new:unknown}[]}|null;const ch=d?.changes?.length?': '+d.changes.map(x=>`${x.field} → ${x.new===null||x.new===undefined||x.new===''?'—':Array.isArray(x.new)?x.new.join(', '):String(x.new)}`).join(', '):'';return `${ACTIONS[h.action]||label(h.action)} by ${who}${ch}`}

function AlertChips({r}:{r:RecordItem}){
 const f=r.framework;
 if(!r.executed)return <span className="muted">Start once the agreement is reviewed as executed</span>;
 if(f.open_ended)return <span className="muted">None while the relationship continues (later of 5 years rule)</span>;
 if(!f.end_date)return <span className="muted">No reviewed end date</span>;
 const d=daysFrom(f.end_date)!,urgent=14;
 return <span className="chips"><Pill k={d-90<=0?'idle':'info'}>Weekly summary {d-90<=0?'since':'from'} {dt(shift(f.end_date,-90))}</Pill><Pill k={d-urgent<=0?'idle':'warn'}>Urgent alert {d-urgent<=0?'due':'on'} {dt(shift(f.end_date,-urgent))}</Pill><Pill k={d<0?'idle':'bad'}>Past-due alert {d<0?'due':'on'} {dt(shift(f.end_date,1))}</Pill></span>
}
function shift(iso:string,days:number){return new Date(+new Date(iso+'T12:00:00')+days*864e5).toISOString().slice(0,10)}

function LabelsPanel({r,c,onSave}:{r:RecordItem;c:Ctx;onSave:(x:Labels)=>void}){
 const v=c.vocab!,l=r.labels,ed=c.editable;
 const [d,setD]=useState<Labels>(l);
 useEffect(()=>setD(r.labels),[r.id,r.revision]);
 const set=(k:keyof Labels,x:unknown)=>setD({...d,[k]:x});
 const keys:(keyof Labels)[]=['rel','owner','kind','primaryType','dir','status','components','endRule','floor','relEnd'];
 const changed=Object.fromEntries(keys.filter(k=>JSON.stringify(d[k]??null)!==JSON.stringify(l[k]??null)).map(k=>[k,d[k]??null]));
 const n=Object.keys(changed).length;
 const sel=(k:keyof Labels,opts:string[],blank?:string)=><select disabled={!ed} value={String(d[k]??'')} onChange={e=>set(k,e.target.value||(k==='owner'||k==='dir'?'':null))}>{blank!==undefined&&<option value="">{blank}</option>}{opts.map(o=><option key={o}>{o}</option>)}</select>;
 return <section className="panel"><div className="head"><h2>Labels</h2>{l.ref_id&&<span className="mono">{l.ref_id}</span>}</div>
  {!l.confirmed&&<div className="suggest">Suggested from the {(l.suggestedFrom||[]).join(' and ')||'file name'}{l.sourceFolder?<> (<span className="mono">{l.sourceFolder}</span>)</>:null}. Check them and save to confirm.</div>}
  <div className="labels">
   <label>Relationship type{sel('rel',v.relationship_types)}</label>
   <label>Owner{sel('owner',v.owners,'Unassigned')}</label>
   <label>Agreement kind{sel('kind',Object.keys(v.kinds))}</label>
   <label>Primary type<input disabled={!ed} value={d.primaryType||''} onChange={e=>set('primaryType',e.target.value)}/></label>
   <label>Direction{sel('dir',v.directions,'Not set')}</label>
   <label>Status{sel('status',v.statuses,'Not set')}</label>
   <label className="wide">End date rule<select disabled={!ed} value={d.endRule||'fixed'} onChange={e=>set('endRule',e.target.value)}><option value="fixed">Fixed expiration date</option><option value="later5">Later of 5 years or end of relationship</option></select></label>
   {d.endRule==='later5'&&<><label>5-year floor <span>(optional)</span><input type="date" disabled={!ed} value={d.floor||''} onChange={e=>set('floor',e.target.value||null)}/></label><label>Relationship ended<input type="date" disabled={!ed} value={d.relEnd||''} onChange={e=>set('relEnd',e.target.value||null)}/></label></>}
  </div>
  <div className="lab"><span>Components</span><div className="comp">{v.components.map(x=><label key={x} className="chk"><input type="checkbox" disabled={!ed} checked={(d.components||[]).includes(x)} onChange={e=>set('components',e.target.checked?[...(d.components||[]),x]:(d.components||[]).filter(y=>y!==x))}/>{x}</label>)}</div></div>
  {ed&&<div className="row"><button className="btn" disabled={c.busy||(!n&&!!l.confirmed)} onClick={()=>onSave(changed)}>{n?`Save ${n} change${n>1?'s':''}`:l.confirmed?'Labels confirmed':'Confirm suggested labels'}</button>{n>0&&<button className="btn ghost" onClick={()=>setD(l)}>Undo</button>}</div>}
 </section>
}

export function Ask({c}:{c:Ctx}){
 const [q,setQ]=useState('Which CDAs expire in the next 90 days?'),[mode,setMode]=useState('auto'),[scope,setScope]=useState(''),[ans,setAns]=useState<Answer|null>(null),[st,setSt]=useState<AIStatus|null>(null),[insp,setInsp]=useState<{c:Citation;text:string}|null>(null),[asking,setAsking]=useState(false);
 useEffect(()=>{api<AIStatus>('/qa/status').then(setSt).catch(()=>setSt(null))},[]);
 useEffect(()=>{if(!insp)return;const k=(e:KeyboardEvent)=>{if(e.key==='Escape')setInsp(null)};addEventListener('keydown',k);return()=>removeEventListener('keydown',k)},[insp]);
 const ask=async()=>{setAsking(true);c.setError('');setAns(null);setInsp(null);try{setAns(await api<Answer>('/questions',{method:'POST',body:JSON.stringify({question:q,mode,agreement_ids:scope?[scope]:[]})}))}catch(e){c.setError((e as Error).message)}finally{setAsking(false)}};
 const inspect=async(x:Citation)=>{try{const p=new URLSearchParams();if(x.revision!==undefined)p.set('revision',String(x.revision));if(x.digest)p.set('digest',x.digest);p.set('version',x.version);const s=await api<{text:string}>('/agreements/'+x.agreement_id+'/evidence/'+x.block_id+'?'+p);setInsp({c:x,text:s.text})}catch(e){c.setError((e as Error).message)}};
 return <>
  <div className="head"><div><h1>Ask agreements</h1><p className="sub">Answers quote the agreements they come from. If the documents don't support an answer, it says so instead of guessing.</p></div></div>
  <section className="panel ask">
   <div className="row"><Pill k={st?.ready?'good':st?.configured?'bad':'info'}>{st?.ready?'Local AI ready':st?.configured?'AI unavailable':'Evidence search'}</Pill><span className="small muted">{st?.ready?st.model:st?.reason||'Checking…'}</span></div>
   <div className="grid2"><label>Answer with<select value={mode} onChange={e=>setMode(e.target.value)}><option value="auto">Best available (AI when set up)</option><option value="ai">AI answer (needs a local model)</option><option value="evidence">Evidence only, no AI</option></select></label>
    <label>Search in<select value={scope} onChange={e=>setScope(e.target.value)}><option value="">All agreements you can see</option>{c.records.map(r=><option key={r.id} value={r.id}>{party(r)} · {kindOf(r)}</option>)}</select></label></div>
   <textarea aria-label="Question" value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)&&q.length>1)ask()}}/>
   <div className="row" style={{justifyContent:'space-between'}}><div className="suggestions">{['Which CDAs expire in the next 90 days?','How many MTAs are executed?','Can materials be shared with third parties?','What happens to confidentiality after expiration?','What deadlines are overdue?'].map(s=><button key={s} onClick={()=>setQ(s)}>{s}</button>)}</div>
    <button className="btn" disabled={asking||q.length<2} onClick={ask}>{asking?'Checking sources…':'Ask'}</button></div>
   <span className="small muted">Runs on this computer. Questions aren't saved.</span>
  </section>
  {ans&&<section className="panel" aria-live="polite">
   <div className="row"><Pill k="info">{ans.mode}</Pill>{ans.status&&<Pill k={['supported','answered'].includes(ans.status)?'good':'warn'}>{label(ans.status)}</Pill>}{ans.model&&<span className="small muted">{ans.model}</span>}</div>
   {ans.claims?.length?<div className="claims">{ans.claims.map((cl,i)=><p key={i}>{(ans.retrieval?.documents_sent??1)>1&&cl.documents?.length?<b>{cl.documents.join(', ')}: </b>:null}{cl.text}<span className="refs">{cl.citations.map(id=>{const x=ans.citations.find(y=>y.id===id);return x?<button key={id} onClick={()=>inspect(x)} aria-label={'Show source '+id}>{id}</button>:null})}</span></p>)}</div>:<p style={{margin:0,fontWeight:600}}>{ans.answer}</p>}
   {ans.warnings?.map((w,i)=><div key={i} className="proto">{w}</div>)}
   <span className="small muted">Looked at {ans.coverage.selected_documents??ans.coverage.accessible_documents} agreements · {ans.coverage.unreviewed} not yet reviewed as executed · {ans.coverage.pending_or_failed} still processing or unreadable{ans.retrieval&&ans.retrieval.passages_total>0?` · ${ans.retrieval.passages_sent} of ${ans.retrieval.passages_total} passages considered`:''}</span>
   {ans.rows.length>0&&<div className="list">{ans.rows.map((x,i)=><button key={i} className="item" onClick={()=>c.go('#a/'+String(x.agreement_id))}><span className="t">{String(x.counterparty||x.filename)}</span><span className="m">{String(x.filename)}</span><span className="r">{x.date?<span className="mono">{dt(String(x.date))} · {label(String(x.kind||''))}</span>:null}</span></button>)}</div>}
   {ans.citations.map((x,i)=><div key={i} className="cite"><button className="link" onClick={()=>inspect(x)}>[{x.id||i+1}] {x.filename} · {x.locator} ↗</button><span className="small muted">{x.reviewed?'Reviewed as executed':'Not yet reviewed as executed'} · {x.kind==='review_record'?'reviewed record':'quote from the document'}</span><pre className="quote">{x.text}</pre></div>)}
  </section>}
  {insp&&<div className="modal" onClick={()=>setInsp(null)}><section className="panel" role="dialog" aria-modal="true" aria-label="Source" onClick={e=>e.stopPropagation()}>
   <div className="head"><h2>Source {insp.c.id}</h2><button className="btn ghost" autoFocus onClick={()=>setInsp(null)}>Close</button></div>
   <b>{insp.c.filename}</b><span className="small muted">{insp.c.locator} · version {insp.c.version}{insp.c.revision!==undefined?` · revision ${insp.c.revision}`:''}</span>
   <pre className="quote">{insp.text.slice(0,insp.c.start||0)}<mark>{insp.text.slice(insp.c.start||0,insp.c.end||insp.text.length)}</mark>{insp.text.slice(insp.c.end||insp.text.length)}</pre>
   <div className="row"><button className="btn" onClick={()=>{const id=insp.c.agreement_id;setInsp(null);c.go('#a/'+id)}}>Open agreement</button><a className="btn ghost" href={'/api/agreements/'+insp.c.agreement_id+'/source'}>Download original</a></div>
  </section></div>}
 </>
}

type Settings={day:number;time:string;urgent:number;pastDue:boolean;rec:Record<string,boolean>;extra:string[]};
type Item={agreement_id:string;ref_id?:string|null;counterparty:string;owner:string;date:string;days:number;kind_label:string;notice_date?:string|null;notice_days?:number|null;urgent_send:string;urgent_in:number;past_send:string};
type Preview={settings:Settings;weekly:{to:string[];next:string;send:string};items:Item[];open_ended:{agreement_id:string;counterparty:string;floor:string|null}[]};
const DAYS=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

export function Alerts({c}:{c:Ctx}){
 const [p,setP]=useState<Preview|null>(null),[sel,setSel]=useState<string>('digest'),[add,setAdd]=useState('');
 const load=()=>api<Preview>('/alerts').then(setP).catch(e=>c.setError(e.message));
 useEffect(()=>{load()},[c.records.length]);
 if(!p)return <p className="muted">Loading alerts…</p>;
 const s=p.settings,ed=c.editable;
 const save=(n:Settings)=>{setP({...p,settings:n});c.act(async()=>{await api('/alerts/settings',{method:'PUT',body:JSON.stringify(n)});await load()},'Alert settings saved and logged.')};
 const roles=c.vocab?.alert_roles||[];
 const recips=(owner?:string)=>[...roles.filter(k=>s.rec[k]),...(s.rec.owner?[owner===undefined?'Agreement owners':owner?owner+' (owner)':'Owner (unassigned)']:[]),...s.extra];
 const items=p.items.slice().sort((a,b)=>a.days-b.days);
 const groups=[{k:'bad' as const,t:'Past expiration, status not updated',rows:items.filter(x=>x.days<0)},{k:'bad' as const,t:'Renewal notice deadline passed',rows:items.filter(x=>x.days>=0&&x.notice_days!=null&&x.notice_days<0)},{k:'warn' as const,t:'Expiring in the next 30 days',rows:items.filter(x=>x.days>=0&&x.days<=30&&!(x.notice_days!=null&&x.notice_days<0))},{k:'warn' as const,t:'Expiring in 31 to 60 days',rows:items.filter(x=>x.days>30&&x.days<=60&&!(x.notice_days!=null&&x.notice_days<0))},{k:'info' as const,t:'Expiring in 61 to 90 days',rows:items.filter(x=>x.days>60&&x.days<=90&&!(x.notice_days!=null&&x.notice_days<0))}];
 const total=new Set(groups.flatMap(g=>g.rows.map(r=>r.agreement_id))).size;
 const up=items.filter(x=>x.urgent_in>0&&x.urgent_in<=180), sent=items.filter(x=>x.urgent_in<=0||x.days<0);
 const cur=sel==='digest'?null:items.find(x=>x.agreement_id+'|'+(x.days<0?'past':'soon')===sel)||null;
 const To=({to}:{to:string[]})=>to.length?<>{to.join(', ')}</>:<b style={{color:'var(--bad)'}}>No recipients selected</b>;
 const uitem=(x:Item)=>{const key=x.agreement_id+'|'+(x.days<0?'past':'soon');return <button key={key} className={'item'+(sel===key?' sel':'')} onClick={()=>setSel(key)}><span className="t">{x.counterparty} · {x.kind_label}</span><span className="m">{x.days<0?'Past-due alert':`${s.urgent}-day urgent alert`} · expires {dt(x.date)} · to {recips(x.owner).join(', ')||'no one'}</span><span className="r">{x.days<0?<Pill k="idle">Due {dt(x.past_send)}</Pill>:x.urgent_in<=0?<Pill k="idle">Due {dt(x.urgent_send)}</Pill>:<Pill k="warn">In {x.urgent_in} days</Pill>}</span></button>};
 return <>
  <div className="head"><div><h1>Expiration alerts</h1><p className="sub">A weekly summary keeps leadership up to date. Separate urgent emails go out only when an agreement is about to expire or already has. This demo shows the emails; it doesn't send them.</p></div></div>
  <div className="cols">
   <section className="panel"><h2>Weekly summary</h2>
    <label className="chk">Send every <select disabled={!ed} value={s.day} onChange={e=>save({...s,day:+e.target.value})}>{DAYS.map((d,i)=><option key={d} value={i}>{d}</option>)}</select> at <input type="time" disabled={!ed} value={s.time} onChange={e=>e.target.value&&save({...s,time:e.target.value})}/></label>
    <p className="alerttext muted" style={{margin:0}}>Lists reviewed, executed agreements expiring within 90 days, grouped by how soon, plus anything overdue.</p>
    <h2>Urgent alerts</h2>
    <label className="chk">Email right away when an agreement is <select disabled={!ed} value={s.urgent} onChange={e=>save({...s,urgent:+e.target.value})}>{[7,14,21,30].map(n=><option key={n} value={n}>{n} days</option>)}</select> from expiring</label>
    <div className="proto"><b>To revisit before launch:</b> 14 days is a starting point. Some MTAs need 60 days' notice to renew, so a 14-day alert can arrive after the last day to act.</div>
    <label className="chk"><input type="checkbox" disabled={!ed} checked={s.pastDue} onChange={e=>save({...s,pastDue:e.target.checked})}/>Also email the day after it expires if it's still marked active</label>
    <h2>Who gets them</h2>
    <div className="ms">{[...roles,'owner'].map(k=><label key={k} className="chk"><input type="checkbox" disabled={!ed} checked={!!s.rec[k]} onChange={e=>save({...s,rec:{...s.rec,[k]:e.target.checked}})}/>{k==='owner'?'Agreement owner':k}</label>)}
     {s.extra.map((x,i)=><span key={x} className="pill p-info">{x}{ed&&<button className="x" aria-label={'Remove '+x} onClick={()=>save({...s,extra:s.extra.filter((_,j)=>j!==i)})}>×</button>}</span>)}</div>
    {ed&&<form className="addr" onSubmit={e=>{e.preventDefault();const v=add.trim();if(v&&!s.extra.includes(v)){save({...s,extra:[...s.extra,v]});setAdd('')}}}><input value={add} onChange={e=>setAdd(e.target.value)} placeholder="Add someone, e.g. General Counsel" aria-label="Add a recipient"/><button className="btn ghost" type="submit">Add</button></form>}
   </section>
   <section className="panel"><div className="head" style={{alignItems:'center'}}><h2>Email preview</h2>{cur&&<button className="back" onClick={()=>setSel('digest')}>Show weekly summary</button>}</div>
    {!cur?<div className="mail"><div className="mh"><div><span>To</span> <To to={recips()}/></div><div><span>Subject</span> <b>Agreement summary, week of {dt(p.weekly.next)}: {total} need{total===1?'s':''} attention</b></div><div><span>Sends</span> {DAYS[s.day]} {dt(p.weekly.next)}, {s.time}</div></div>
     <div className="mb"><p>Here's what's coming up across {c.vocab?.organization||'your'}'s agreements.</p>{groups.filter(g=>g.rows.length).map(g=><React.Fragment key={g.t}><p style={{margin:'12px 0 4px'}}><Pill k={g.k}>{g.t} · {g.rows.length}</Pill></p><ul>{g.rows.map(x=><li key={x.agreement_id}><b>{x.counterparty}</b> {x.kind_label} · {x.days<0?`expired ${dt(x.date)}`:`expires ${dt(x.date)}`} · owner {x.owner||'unassigned'}</li>)}</ul></React.Fragment>)}{!total&&<p>Nothing expires in the next 90 days.</p>}<p><a href="#agreements">Open Clausetrail</a></p></div></div>
    :<div className="mail"><div className="mh"><div><span>To</span> <To to={recips(cur.owner)}/></div><div><span>Subject</span> <b style={{color:'var(--bad)'}}>{cur.days<0?'Expired':'Urgent'}: {cur.counterparty} {cur.kind_label} {cur.days<0?'expired':'expires'} {dt(cur.date)}</b></div><div><span>Sends</span> {dt(cur.days<0?cur.past_send:cur.urgent_send)}</div></div>
     <div className="mb"><p>{cur.days<0?<>The {cur.kind_label} with <b>{cur.counterparty}</b> ({cur.ref_id||'no ID'}) expired on <b>{dt(cur.date)}</b> and is still marked active.</>:<>The {cur.kind_label} with <b>{cur.counterparty}</b> ({cur.ref_id||'no ID'}) expires in <b>{s.urgent} days</b>, on {dt(cur.date)}.</>}</p>
      <ul><li>Owner: {cur.owner||'unassigned'}</li>{cur.notice_date&&<li>Renewal notice deadline: {dt(cur.notice_date)}</li>}</ul>
      <p>{cur.days<0?'The owner should confirm whether it was renewed, then update its status or add the renewal.':'The owner should decide now whether to renew or let it end.'}</p><p><button className="link" onClick={()=>c.go('#a/'+cur.agreement_id)}>Open in Clausetrail</button></p></div></div>}
   </section>
  </div>
  <section className="panel"><h2>Urgent alerts coming up · next 180 days</h2><div className="list">{up.length?up.map(uitem):<Empty>No urgent alerts scheduled.</Empty>}</div></section>
  <section className="panel"><h2>Urgent and past-due alerts already due</h2><div className="list">{sent.length?sent.map(uitem):<Empty>None.</Empty>}</div></section>
  {p.open_ended.length>0&&<section className="panel"><h2>Open-ended agreements · no alerts yet</h2><div className="list">{p.open_ended.map(o=><button key={o.agreement_id} className="item" onClick={()=>c.go('#a/'+o.agreement_id)}><span className="t">{o.counterparty||'Unnamed'}</span><span className="m">Later of 5 years or end of relationship · at least to {dt(o.floor)}</span></button>)}</div></section>}
 </>
}
