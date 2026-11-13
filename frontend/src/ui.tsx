import React,{useState} from 'react';
import type {RecordItem,Framework} from './types';

export const label=(s:string)=>s.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
export function dt(iso?:string|null){if(!iso)return '—';const d=new Date(String(iso).slice(0,10)+'T12:00:00');return isNaN(+d)?String(iso):d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}
export function daysFrom(iso?:string|null){if(!iso)return null;const t=new Date();t.setHours(12,0,0,0);return Math.round((+new Date(iso.slice(0,10)+'T12:00:00')-+t)/864e5)}

export function Pill({k,children}:{k:'bad'|'warn'|'good'|'idle'|'info';children:React.ReactNode}){return <span className={'pill p-'+k}>{children}</span>}
export function StatusPill({s}:{s?:string|null}){if(!s)return <Pill k="idle">No status</Pill>;const k=({Executed:'good',Expired:'idle',Terminated:'idle'} as Record<string,'good'|'idle'>)[s]||'info';return <Pill k={k}>{s}</Pill>}
const PROC:Record<string,['bad'|'warn'|'good'|'idle'|'info',string]>={queued:['idle','Processing'],running:['idle','Processing'],needs_review:['warn','Needs review'],reviewed:['good','Reviewed'],failed:['bad','Processing failed'],deleted:['idle','Deleted']};
export function ProcPill({s}:{s:string}){const [k,t]=PROC[s]||['idle',label(s)];return <Pill k={k}>{t}</Pill>}

export function party(r:RecordItem){return String(r.approved.counterparty?.value||r.framework?.counterparty||r.filename)}
export function kindOf(r:RecordItem){return String(r.approved.agreement_type?.value||r.labels?.kind||'OTHER')}
export function endOf(f?:Framework){if(!f)return '—';if(f.open_ended)return `Open-ended, at least to ${dt(f.floor)}`;return f.end_date?dt(f.end_date):'—'}

/** Alert rule: executed, still active, and past expiration / notice deadline passed / within 90 days. */
export function alertOf(r:RecordItem,noticeDays?:number|null):{k:'bad'|'warn';t:string}|null{
 if(!r.executed||['Expired','Terminated'].includes(r.labels?.status||''))return null;
 const d=daysFrom(r.framework?.end_date); if(d===null)return null;
 if(d<0)return {k:'bad',t:'Past expiration, update status'};
 const n=noticeDays??(typeof r.approved.notice_days?.value==='number'?r.approved.notice_days.value as number:null);
 if(n!==null&&d-n<0)return {k:'bad',t:'Renewal notice deadline passed'};
 if(d<=90)return {k:'warn',t:'Expiring within 90 days'};
 return null;
}
export function DaysCell({iso,bad,warn}:{iso?:string|null;bad?:boolean;warn?:boolean}){const d=daysFrom(iso);if(d===null)return <span className="days muted">—</span>;return <span className={'days '+(bad||d<0?'d-bad':warn||d<=90?'d-warn':'')}>{d<0?`${-d} days ago`:`${d} days`}</span>}

export function Copy({text}:{text:string}){const [done,setDone]=useState(false);return <button className="btn ghost" style={{padding:'4px 10px',fontSize:12.5}} onClick={()=>{navigator.clipboard?.writeText(text).then(()=>{setDone(true);setTimeout(()=>setDone(false),1500)}).catch(()=>{})}}>{done?'Copied':'Copy'}</button>}
export function Empty({children}:{children:React.ReactNode}){return <p className="empty">{children}</p>}
