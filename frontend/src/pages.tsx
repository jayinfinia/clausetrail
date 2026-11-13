import React,{useEffect,useRef,useState} from 'react';
import {api} from './api';
import type {Ctx} from './ctx';
import {IN_PROGRESS,FIELDS,type RecordItem,type RedactionStatus} from './types';
import {Pill,StatusPill,ProcPill,DaysCell,Empty,dt,party,kindOf,endOf,alertOf,label} from './ui';

const KIND_TEXT:Record<string,string>={expiration:'Agreement expires',notice:'Renewal notice deadline',confidentiality:'Confidentiality obligation ends',return:'Return or destroy materials'};

export function Home({c}:{c:Ctx}){
 const {records,dash}=c;
 const active=records.filter(r=>r.executed&&!['Expired','Terminated'].includes(r.labels?.status||''));
 const attention=records.map(r=>({r,a:alertOf(r)})).filter(x=>x.a).sort((x,y)=>String(x.r.framework.end_date).localeCompare(String(y.r.framework.end_date)));
 const inprog=records.filter(r=>IN_PROGRESS.includes(r.labels?.status||''));
 const due=(dash?.deadlines||[]).filter(d=>d.kind!=='expiration'&&d.days<=30&&d.days>=-30);
 const review=records.filter(r=>r.status==='needs_review');
 const byRel=dash?.by_relationship||{}, max=Math.max(1,...Object.values(byRel));
 return <>
  <div className="head"><div><h1>Overview</h1><p className="sub">Here's where {c.vocab?.organization||'your'}'s agreements stand today, {dt(new Date().toISOString())}.</p></div>
   {c.editable&&<a className="btn" href="#import">Add agreements</a>}</div>
  <div className="stats">
   <a className="stat" href="#agreements" onClick={()=>c.setFilters({special:'active'})}><b>{active.length}</b><span>Active agreements</span></a>
   <a className={'stat '+(attention.length?'alert':'')} href="#agreements" onClick={()=>c.setFilters({special:'attention'})}><b>{attention.length}</b><span>Need attention</span></a>
   <a className={'stat '+(review.length?'warnc':'')} href="#review"><b>{review.length}</b><span>Waiting for review</span></a>
   <a className={'stat '+(due.length?'warnc':'')} href="#deadlines"><b>{due.length}</b><span>Obligations due in 30 days</span></a>
  </div>
  <div className="cols">
   <section className="panel"><h2>Needs attention</h2><div className="list">{attention.length?attention.map(({r,a})=><button key={r.id} className="item" onClick={()=>c.go('#a/'+r.id)}><span className="t">{party(r)} · {kindOf(r)}</span><span className="m"><span className="mono">{r.labels.ref_id||'No ID yet'}</span> · {r.framework.end_date&&daysFromText(r.framework.end_date)} · owner {r.labels.owner||'unassigned'}</span><span className="r"><Pill k={a!.k}>{a!.t}</Pill></span></button>):<Empty>Nothing needs attention.</Empty>}</div></section>
   <section className="panel"><h2>Obligations due soon</h2><div className="list">{due.length?due.map(d=><button key={d.id} className="item" onClick={()=>c.go('#a/'+d.agreement_id)}><span className="t">{KIND_TEXT[d.kind]||label(d.kind)}</span><span className="m">{d.counterparty} · {d.owner||'unassigned'}</span><span className="r"><DuePill days={d.days} date={d.date}/></span></button>):<Empty>Nothing due in the next 30 days.</Empty>}</div></section>
  </div>
  <div className="cols even">
   <section className="panel"><div className="head"><h2>By relationship type</h2><span className="small muted">{dash?.unconfirmed_labels||0} with unconfirmed labels</span></div>
    <div className="bars">{Object.entries(byRel).map(([k,v])=><button key={k} onClick={()=>{c.setFilters({rel:k});c.go('#agreements')}}><span>{k}</span><span className="bar"><i style={{width:`${v/max*100}%`}}/></span><b>{v}</b></button>)}</div></section>
   <section className="panel"><div className="head"><h2>Owner assignments</h2><span className="small muted">{dash?.open_ended||0} open-ended</span></div>
    <div className="owners">{Object.entries(dash?.by_owner||{}).map(([k,v])=><button key={k} className={k==='Unassigned'&&v?'warn':''} onClick={()=>{c.setFilters({owner:k});c.go('#agreements')}}><b>{v}</b><span>{k}</span></button>)}</div></section>
  </div>
  <section className="panel"><h2>Agreements in progress</h2>
   <div className="pipe">{IN_PROGRESS.map(s=><div className="step" key={s}><b>{inprog.filter(r=>r.labels.status===s).length}</b><span>{s}</span></div>)}</div>
   <div className="list">{inprog.map(r=><button key={r.id} className="item" onClick={()=>c.go('#a/'+r.id)}><span className="t">{party(r)} · {kindOf(r)}</span><span className="m"><StatusPill s={r.labels.status}/> &nbsp;Waiting on <b>{r.labels.waiting||'—'}</b></span><span className="r mono">{r.labels.ref_id||''}</span></button>)}</div>
   {!inprog.length&&<Empty>No agreements are in progress. Set an agreement's status to Requested, Drafting, In review or Out for signature in its Labels.</Empty>}
  </section>
 </>
}
function daysFromText(iso:string){const d=Math.round((+new Date(iso+'T12:00:00')-Date.now())/864e5);return d<0?`expired ${dt(iso)}`:`expires ${dt(iso)}`}
export function DuePill({days,date}:{days:number;date:string}){if(days<0)return <Pill k="bad">{-days}d overdue</Pill>;if(days<=30)return <Pill k="warn">Due in {days}d</Pill>;return <Pill k="idle">Due {dt(date)}</Pill>}

export function Agreements({c}:{c:Ctx}){
 const f=c.filters,v=c.vocab;
 const q=f.q.toLowerCase();
 const rows=c.records.filter(r=>(!q||[r.labels.ref_id,party(r),r.filename,r.labels.owner,r.framework.relationship].join(' ').toLowerCase().includes(q))
  &&(!f.type||kindOf(r)===f.type)&&(!f.rel||r.labels.rel===f.rel)&&(!f.owner||(r.labels.owner||'Unassigned')===f.owner)&&(!f.status||r.labels.status===f.status)
  &&(f.special!=='attention'||alertOf(r))&&(f.special!=='progress'||IN_PROGRESS.includes(r.labels.status||''))&&(f.special!=='active'||(r.executed&&!['Expired','Terminated'].includes(r.labels.status||'')))&&(f.special!=='review'||r.status==='needs_review'))
  .sort((x,y)=>(x.framework.end_date||'9999').localeCompare(y.framework.end_date||'9999'));
 const any=Object.values(f).some(Boolean);
 return <>
  <div className="head"><div><h1>Agreements</h1><p className="sub">Search by counterparty, ID, file name or owner. Click a row to open it.</p></div>
   <div className="row"><a className="btn ghost" href="/api/export">Export CSV</a>{c.editable&&<a className="btn" href="#import">Add agreements</a>}</div></div>
  <div className="filters">
   <input type="search" placeholder="Search agreements" aria-label="Search agreements" value={f.q} onChange={e=>c.setFilters({q:e.target.value})}/>
   <select aria-label="Relationship type" value={f.rel} onChange={e=>c.setFilters({rel:e.target.value})}><option value="">All relationship types</option>{v?.relationship_types.map(t=><option key={t}>{t}</option>)}</select>
   <select aria-label="Type" value={f.type} onChange={e=>c.setFilters({type:e.target.value})}><option value="">All types</option>{Object.keys(v?.kinds||{}).map(t=><option key={t}>{t}</option>)}</select>
   <select aria-label="Owner" value={f.owner} onChange={e=>c.setFilters({owner:e.target.value})}><option value="">All owners</option>{[...(v?.owners||[]),'Unassigned'].map(t=><option key={t}>{t}</option>)}</select>
   <select aria-label="Status" value={f.special||f.status} onChange={e=>{const x=e.target.value;const sp=['attention','progress','active','review'].includes(x);c.setFilters({special:sp?x:'',status:sp?'':x})}}><option value="">All statuses</option><option value="attention">Needs attention</option><option value="progress">In progress</option><option value="active">Active</option><option value="review">Waiting for review</option>{v?.statuses.map(s=><option key={s}>{s}</option>)}</select>
   {any&&<button className="btn ghost" onClick={()=>c.setFilters({q:'',type:'',status:'',special:'',rel:'',owner:''})}>Clear</button>}
  </div>
  <div className="tablewrap"><table><thead><tr><th>Agreement ID</th><th>Counterparty</th><th>Relationship</th><th>Type</th><th>Status</th><th>Ends</th><th>Time left</th><th>Owner</th></tr></thead>
   <tbody>{rows.length?rows.map(r=>{const a=alertOf(r);return <tr key={r.id} className="click" tabIndex={0} onClick={()=>c.go('#a/'+r.id)} onKeyDown={e=>{if(e.key==='Enter')c.go('#a/'+r.id)}}>
    <td className="mono">{r.labels.ref_id||'—'}</td>
    <td><b>{party(r)}</b><div className="alerttext muted">{r.filename}</div></td>
    <td>{r.framework.relationship}{!r.labels.confirmed&&<div className="alerttext" style={{color:'var(--warn)'}}>Suggested</div>}</td>
    <td>{kindOf(r)}</td>
    <td>{r.status==='reviewed'?<StatusPill s={r.labels.status||(r.executed?'Executed':null)}/>:<ProcPill s={r.status}/>}{a&&<div className="alerttext" style={{color:`var(--${a.k})`,marginTop:4}}>{a.t}</div>}</td>
    <td className="mono">{endOf(r.framework)}</td><td>{r.framework.open_ended?<span className="days muted">open</span>:<DaysCell iso={r.framework.end_date}/>}</td>
    <td>{r.labels.owner||<span className="muted">Unassigned</span>}</td></tr>}):<tr><td colSpan={8} className="empty" style={{padding:16}}>{c.records.length?'No agreements match. Try clearing a filter.':'No agreements yet. Add some from Add agreements.'}</td></tr>}</tbody></table></div>
 </>
}

export function Review({c}:{c:Ctx}){
 const queue=c.records.filter(r=>r.status==='needs_review'), failed=c.records.filter(r=>r.status==='failed'), processing=c.records.filter(r=>['queued','running'].includes(r.status));
 const unconfirmed=c.records.filter(r=>r.status==='reviewed'&&!r.labels.confirmed);
 const count=(r:RecordItem)=>Object.values(r.proposals||{}).filter(p=>p.value!==null).length;
 return <>
  <div className="head"><div><h1>Review queue</h1><p className="sub">Facts read from each document stay proposed until someone checks them against the source and confirms the agreement is executed. Only reviewed agreements count toward deadlines and alerts.</p></div></div>
  <section className="panel"><div className="head"><h2>Waiting for review · {queue.length}</h2>{processing.length>0&&<span className="small muted">{processing.length} still processing</span>}</div>
   <div className="list">{queue.length?queue.map(r=><button key={r.id} className="item" onClick={()=>c.go('#a/'+r.id)}><span className="t">{party(r)} · {kindOf(r)}</span><span className="m">{r.filename} · {r.framework.relationship}{!r.labels.confirmed&&' (suggested)'}</span><span className="r"><Pill k="warn">{count(r)} of {FIELDS.length} fields found</Pill></span></button>):<Empty>Nothing is waiting for review.</Empty>}</div></section>
  {unconfirmed.length>0&&<section className="panel"><h2>Reviewed, labels not confirmed · {unconfirmed.length}</h2><div className="list">{unconfirmed.map(r=><button key={r.id} className="item" onClick={()=>c.go('#a/'+r.id)}><span className="t">{party(r)}</span><span className="m">Suggested {r.framework.relationship} from the {(r.labels.suggestedFrom||[]).join(' and ')||'file'}</span><span className="r mono">{r.labels.ref_id}</span></button>)}</div></section>}
  {failed.length>0&&<section className="panel"><h2>Could not be read · {failed.length}</h2><div className="list">{failed.map(r=><div key={r.id} className="ob"><div><b>{r.filename}</b><div className="alerttext muted">Check the file format. Scanned PDFs need Tesseract and Poppler installed.</div></div>{c.editable&&<button className="btn ghost" disabled={c.busy} onClick={()=>c.act(()=>api('/agreements/'+r.id+'/retry',{method:'POST'}),'Queued again')}>Retry</button>}</div>)}</div></section>}
 </>
}

export function Deadlines({c}:{c:Ctx}){
 const rows=(c.dash?.deadlines||[]).slice().sort((a,b)=>a.days-b.days);
 return <>
  <div className="head"><div><h1>Obligations & deadlines</h1><p className="sub">Expiration, renewal notice, confidentiality and return dates from reviewed, executed agreements. Unreviewed or unknown dates are left out.</p></div></div>
  <section className="panel"><div className="list">{rows.length?rows.map(d=><div key={d.id} className="ob"><div><b>{KIND_TEXT[d.kind]||label(d.kind)}</b><div className="alerttext muted"><button className="link" onClick={()=>c.go('#a/'+d.agreement_id)}>{d.counterparty}{d.ref_id?' · '+d.ref_id:''}</button> · owner {d.owner||'unassigned'} · due {dt(d.date)}</div></div><DuePill days={d.days} date={d.date}/></div>):<Empty>No reviewed deadlines yet. Review an agreement to start tracking its dates.</Empty>}</div></section>
 </>
}

type Res={filename:string;error?:string;duplicate?:boolean;suggested?:{rel?:string}};
export function Import({c}:{c:Ctx}){
 const files=useRef<HTMLInputElement>(null),folder=useRef<HTMLInputElement>(null);
 const [scope,setScope]=useState(c.user.groups[0]),[over,setOver]=useState(false),[progress,setProgress]=useState(''),[summary,setSummary]=useState('');
 const [rs,setRs]=useState<RedactionStatus|null>(null),[redact,setRedact]=useState('off');
 useEffect(()=>{api<RedactionStatus>('/redaction/status').then(x=>{setRs(x);setRedact(x.default)}).catch(()=>{})},[]);
 const [sheet,setSheet]=useState<{id:string;headers:string[];total:number}|null>(null),[mapping,setMapping]=useState<Record<string,string>>({}),[changes,setChanges]=useState<any[]>([]),[checked,setChecked]=useState<number[]>([]),[committed,setCommitted]=useState(false);
 async function upload(list:File[]){if(!list.length)return;await c.act(async()=>{const out:Res[]=[];for(let i=0;i<list.length;i+=50){const chunk=list.slice(i,i+50);setProgress(`Uploading ${Math.min(i+50,list.length)} of ${list.length}…`);const form=new FormData();chunk.forEach(f=>form.append('files',f));const paths=chunk.map(f=>(f as File&{webkitRelativePath?:string}).webkitRelativePath||'');if(paths.some(Boolean))paths.forEach(p=>form.append('paths',p));form.append('scope',scope);form.append('redact',redact);out.push(...(await api<{results:Res[]}>('/imports',{method:'POST',body:form})).results)}
  const redN=out.reduce((n,x)=>n+((x as Res&{redaction?:{redactions:number}}).redaction?.redactions||0),0);const err=out.filter(x=>x.error),dup=out.filter(x=>x.duplicate),ok=out.filter(x=>!x.error&&!x.duplicate),by:Record<string,number>={};ok.forEach(x=>{const k=x.suggested?.rel||'Not sure yet';by[k]=(by[k]||0)+1});
  setSummary(`${ok.length} added`+(Object.keys(by).length?`: ${Object.entries(by).map(([k,v])=>`${v} ${k}`).join(', ')}`:'')+(dup.length?`. ${dup.length} already imported`:'')+(redact!=='off'?`. ${redN} confidential item${redN===1?'':'s'} redacted before storing (${redact} policy)`:'')+(err.length?`. ${err.length} rejected: ${err.slice(0,5).map(x=>x.filename+' ('+x.error+')').join('; ')}`:'')+'.')}).finally(()=>setProgress(''))}
 if(!c.editable)return <><h1>Add agreements</h1><section className="panel"><Empty>Your viewer role can look at agreements but can't add them. Switch to a reviewer in the rail.</Empty></section></>;
 return <>
  <div className="head"><div><h1>Add agreements</h1><p className="sub">Import signed documents. The app reads each one, proposes its facts for review, and suggests labels from the folder it came from.</p></div></div>
  <div className={'drop'+(over?' over':'')} onDragOver={e=>{e.preventDefault();setOver(true)}} onDragLeave={()=>setOver(false)} onDrop={e=>{e.preventDefault();setOver(false);upload(Array.from(e.dataTransfer.files))}}>
   <p><b>Import a folder to get labels for free.</b> A folder laid out as <span className="mono">category / counterparty / files</span>, like the sample set, sets the relationship type from the category folder and the counterparty from the next folder. PDF, Word, Excel, CSV or text, up to 25 MB each. Folders upload in batches of 50.</p>
   <div className="row"><button className="btn" disabled={c.busy} onClick={()=>folder.current?.click()}>Import folder</button><button className="btn ghost" disabled={c.busy} onClick={()=>files.current?.click()}>Choose files</button></div>
   <input hidden multiple ref={files} type="file" accept=".pdf,.docx,.xlsx,.csv,.txt" onChange={e=>{upload(Array.from(e.target.files||[]));e.target.value=''}}/>
   <input hidden multiple ref={folder} type="file" {...{webkitdirectory:'',directory:''} as React.InputHTMLAttributes<HTMLInputElement>} onChange={e=>{upload(Array.from(e.target.files||[]));e.target.value=''}}/>
  </div>
  <section className="panel"><h2>Redact before import</h2>
   <p className="small muted" style={{margin:0}}>Confidential values are removed on this computer before anything is stored. Only the redacted copy enters Clausetrail; the original is never saved.</p>
   <div className="row"><label className="chk">Policy <select aria-label="Redaction policy" value={redact} onChange={e=>setRedact(e.target.value)}><option value="off">Off (fictional examples only)</option><option value="standard">Standard: tax IDs, account numbers, dates of birth</option><option value="strict">Strict: also names and contact details</option></select></label></div>
   {redact!=='off'&&rs&&<span className="small muted">Removes: {rs.policies[redact].join(', ')}.</span>}
   {rs&&<div className="row"><Pill k={rs.llm.ready?'good':'warn'}>{rs.llm.ready?`Local Llama: ${rs.llm.model}`:'Local Llama off'}</Pill><Pill k={rs.ocr?'good':'warn'}>{rs.ocr?'OCR ready for scans':'OCR missing: scanned PDFs will fail'}</Pill>{rs.tagging&&<Pill k={rs.tagging.ready?'good':'warn'}>{rs.tagging.ready?`Tagging: Claude ${rs.tagging.model} (redacted text only)`:'Claude tagging off'}</Pill>}{!rs.llm.ready&&<span className="small muted">{rs.llm.reason} Rules still run.</span>}{rs.tagging&&!rs.tagging.ready&&<span className="small muted">{rs.tagging.reason}</span>}</div>}
  </section>
  <div className="row"><label className="chk">Access collection <select value={scope} onChange={e=>setScope(e.target.value)}>{c.user.groups.map(g=><option key={g}>{g}</option>)}</select></label>
   {!c.vocab?.private_local&&<button className="btn ghost" disabled={c.busy} onClick={()=>c.act(async()=>{const r=await api<{results:unknown[]}>('/demo/seed',{method:'POST'});setSummary(`${r.results.length} fictional examples added or already present.`)})}>Load fictional examples</button>}</div>
  {progress&&<div className="proto">{progress}</div>}{summary&&<div className="banner ok">{summary}<button onClick={()=>setSummary('')} aria-label="Dismiss">×</button></div>}
  <section className="panel"><h2>Reconcile an existing tracker</h2><p className="small muted">Match spreadsheet rows to agreements already here, preview the differences and import them as proposals for review.</p>
   <div className="row"><label className="btn ghost">Choose CSV or XLSX<input hidden type="file" accept=".csv,.xlsx" onChange={e=>{const f=e.target.files?.[0];e.target.value='';if(f)c.act(async()=>{const form=new FormData();form.append('file',f);form.append('scope',scope);const r=await api<{id:string;headers:string[];total:number}>('/spreadsheets',{method:'POST',body:form});setSheet(r);setChanges([]);setCommitted(false);setMapping({counterparty:r.headers.find(h=>/counterparty/i.test(h))||'',expiration_date:r.headers.find(h=>/expir/i.test(h))||'',owner:r.headers.find(h=>/owner/i.test(h))||''})})}}/></label>{!c.vocab?.private_local&&<a href="/api/demo/tracker">Download the fictional tracker</a>}</div>
   {sheet&&<><h3>Map {sheet.total} rows</h3><div className="grid2">{['agreement_id',...FIELDS].map(f=><label key={f}>{label(f)}<select value={mapping[f]||''} onChange={e=>setMapping({...mapping,[f]:e.target.value})}><option value="">Skip</option>{sheet.headers.map(h=><option key={h}>{h}</option>)}</select></label>)}</div>
    <div className="row"><button className="btn" disabled={c.busy||committed} onClick={()=>c.act(async()=>{const r=await api<{changes:any[]}>('/spreadsheets/'+sheet.id+'/preview',{method:'POST',body:JSON.stringify({mapping:Object.fromEntries(Object.entries(mapping).filter(([,v])=>v))})});setChanges(r.changes);setChecked(r.changes.filter(x=>x.state==='ready').map(x=>x.row))})}>Preview changes</button></div>
    {changes.length>0&&<><div className="list">{changes.map(x=><label key={x.row} className="ob" style={{cursor:'pointer'}}><div className="chk" style={{alignItems:'flex-start'}}><input type="checkbox" disabled={x.state!=='ready'||committed} checked={checked.includes(x.row)} onChange={e=>setChecked(e.target.checked?[...checked,x.row]:checked.filter(n=>n!==x.row))}/><div><b>Row {x.row}</b> · {x.candidates?.map((r:any)=>r.filename).join(', ')||'No matching agreement'}{x.conflicts?.map((f:any)=><div key={f.field} className="alerttext" style={{color:'var(--warn)'}}>{label(f.field)}: {String(f.approved)} → {String(f.spreadsheet)}</div>)}</div></div><Pill k={x.state==='ready'?'good':x.state==='invalid'?'bad':'idle'}>{x.state}</Pill></label>)}</div>
    <div className="row"><button className="btn" disabled={c.busy||committed||!checked.length} onClick={()=>c.act(async()=>{await api('/spreadsheets/'+sheet.id+'/commit',{method:'POST',body:JSON.stringify({rows:checked})});setCommitted(true)},'Tracker values saved as proposals. Review them before they affect deadlines.')}>Import selected as proposals</button>{committed&&<button className="btn ghost" disabled={c.busy} onClick={()=>c.act(async()=>{await api('/spreadsheets/'+sheet.id+'/rollback',{method:'POST'});setSheet(null);setChanges([])},'Batch undone')}>Undo batch</button>}</div></>}</>}
  </section>
  <section className="panel"><h2>Processing activity</h2><div className="list">{c.jobs.length?c.jobs.slice(0,30).map(j=><div key={j.id} className="ob"><div><button className="link" onClick={()=>c.go('#a/'+j.agreement_id)}>{j.filename}</button>{j.error&&<div className="alerttext muted">{j.error.replaceAll('_',' ')}</div>}</div><Pill k={j.status==='completed'?'good':j.status==='failed'?'bad':'idle'}>{j.status}</Pill></div>):<Empty>No imports yet.</Empty>}</div></section>
 </>
}

type LogRow={ts:string;editor:string;action:string;agreement_id:string|null;ref_id:string|null;name:string;changes:{field:string;old:unknown;new:unknown}[]};
const FIELD_NAMES:Record<string,string>={rel:'Relationship type',owner:'Owner',kind:'Agreement kind',primaryType:'Primary type',dir:'Direction',status:'Status',components:'Components',party:'Counterparty',eff:'Effective date',endRule:'End rule',floor:'5-year floor',relEnd:'Relationship ended',waiting:'Waiting on',ref_id:'Agreement ID','end date':'End date',day:'Weekly day',time:'Time',urgent:'Urgent alert days',pastDue:'Past-due email',rec:'Recipients',extra:'Extra recipients'};
const show=(v:unknown)=>v==='later5'?'later of 5 years':v==='fixed'?'fixed date':v===null||v===undefined||v===''?'—':Array.isArray(v)?(v.join(', ')||'—'):typeof v==='object'?Object.entries(v as object).filter(([,x])=>x).map(([k])=>k.toUpperCase()).join(', '):String(v);
export function Log({c}:{c:Ctx}){
 const [rows,setRows]=useState<LogRow[]|null>(null),[q,setQ]=useState('');
 useEffect(()=>{api<LogRow[]>('/log').then(setRows).catch(e=>c.setError(e.message))},[c.records.length]);
 const names=Object.fromEntries(c.users.map(u=>[u.id,u.name]));
 const list=(rows||[]).filter(r=>JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));
 return <>
  <div className="head"><div><h1>Edit log</h1><p className="sub">Every change, with who made it, when, and the old and new value. Newest first.</p></div></div>
  <div className="filters"><input type="search" placeholder="Filter by agreement, field or person" value={q} onChange={e=>setQ(e.target.value)}/></div>
  <div className="tablewrap"><table><thead><tr><th>When</th><th>Who</th><th>Agreement</th><th>Change</th></tr></thead><tbody>{rows===null?<tr><td colSpan={4}>Loading…</td></tr>:list.length?list.map((r,i)=><tr key={i}>
   <td className="mono">{new Date(r.ts+'Z').toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</td><td>{names[r.editor]||r.editor}</td>
   <td>{r.agreement_id?<button className="link" onClick={()=>c.go('#a/'+r.agreement_id)}>{r.name}</button>:r.name}<div className="mono muted">{r.ref_id&&r.ref_id!=='—'?r.ref_id:''}</div></td>
   <td>{r.changes.length?r.changes.map((x,j)=><div key={j} className="change"><b>{FIELD_NAMES[x.field]||label(x.field)}</b> {show(x.old)} → {show(x.new)}</div>):<span className="muted">{label(r.action)}</span>}</td></tr>):<tr><td colSpan={4} className="empty" style={{padding:16}}>No changes yet.</td></tr>}</tbody></table></div>
 </>
}

export function Settings({c}:{c:Ctx}){
 const [status,setStatus]=useState<unknown>(null);
 return <>
  <div className="head"><div><h1>Settings</h1><p className="sub">How this copy of the app handles documents.</p></div></div>
  <section className="panel"><h2>This copy</h2><dl>
   <dt>Documents</dt><dd>{c.vocab?.private_local?'Private local copy: real documents, this computer only. Do not share or deploy.':'Fictional documents only'}</dd>
   <dt>Processing</dt><dd>On this computer. External cloud AI is off.</dd><dt>SharePoint</dt><dd>Not connected</dd><dt>Email alerts</dt><dd>Previews only. Nothing is sent.</dd>
   <dt>Your access</dt><dd>{c.user.name} · {c.user.role} · {c.user.groups.join(' + ')}</dd></dl>
   <div className="row"><button className="btn ghost" onClick={()=>c.act(async()=>setStatus(await api('/status')))}>Show processing status</button></div>{status!==null&&<pre className="statusjson">{JSON.stringify(status,null,2)}</pre>}</section>
  <section className="panel"><h2>Try a different access level</h2><p className="small muted">These demo identities show how access changes. They are not real sign-in.</p><div className="row">{c.users.map(u=><button key={u.id} className="btn ghost" disabled={c.busy||u.id===c.user.id} onClick={()=>c.switchUser(u.id)}>{u.name} · {u.role}</button>)}</div></section>
 </>
}
