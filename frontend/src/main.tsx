// Clausetrail interface: register, review queue, evidence, cited Q&A, alerts and edit log.
import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {api,setCsrf} from './api';
import type {Ctx} from './ctx';
import type {User,Vocab,RecordItem,Dash,Job} from './types';
import {Home,Agreements,Review,Deadlines,Import,Log,Settings} from './pages';
import {Detail,Ask,Alerts} from './pages2';

const NAV:[string,string][]=[['home','Home'],['agreements','Agreements'],['review','Review queue'],['deadlines','Obligations'],['alerts','Expiration alerts'],['ask','Ask agreements'],['import','Add agreements'],['log','Edit log'],['settings','Settings']];
const FILTERS={q:'',type:'',status:'',special:'',rel:'',owner:''};

function useHash(){const [h,setH]=useState(location.hash||'#home');useEffect(()=>{const f=()=>{setH(location.hash||'#home');window.scrollTo(0,0)};addEventListener('hashchange',f);return()=>removeEventListener('hashchange',f)},[]);return h}

function App(){
 const [user,setUser]=useState<User|null>(null),[users,setUsers]=useState<User[]>([]),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[toastMsg,setToast]=useState('');
 const [vocab,setVocab]=useState<Vocab|null>(null),[records,setRecords]=useState<RecordItem[]>([]),[dash,setDash]=useState<Dash|null>(null),[jobs,setJobs]=useState<Job[]>([]),[filters,setF]=useState(FILTERS);
 const hash=useHash(); const timer=useRef<number>(0);
 const toast=(m:string)=>{setToast(m);clearTimeout(timer.current);timer.current=window.setTimeout(()=>setToast(''),3500)};
 async function refresh(){const [r,d,j]=await Promise.all([api<RecordItem[]>('/agreements'),api<Dash>('/dashboard'),api<Job[]>('/jobs')]);setRecords(r);setDash(d);setJobs(j)}
 async function act(fn:()=>Promise<unknown>,ok?:string){setBusy(true);setError('');try{await fn();if(ok)toast(ok);await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 async function signIn(id:string){setBusy(true);setError('');try{const x=await api<{user:User;csrf:string}>('/auth/demo',{method:'POST',body:JSON.stringify({username:id})});setCsrf(x.csrf);setUser(x.user);setF(FILTERS)}catch(e){setError('Sign-in failed: '+(e as Error).message)}finally{setBusy(false)}}
 async function signOut(){try{await api('/auth/logout',{method:'POST'})}catch{}setCsrf('');setUser(null);setRecords([]);setDash(null);location.hash='#home'}
 useEffect(()=>{api<{user:User|null;csrf:string;users:User[]}>('/auth').then(x=>{setUser(x.user);setUsers(x.users);setCsrf(x.csrf||'')}).catch(e=>setError('Could not reach the app server: '+e.message)).finally(()=>setLoading(false))},[]);
 useEffect(()=>{if(!user)return;api<Vocab>('/framework').then(setVocab).catch(()=>{});refresh().catch(e=>setError(e.message));const id=setInterval(()=>refresh().catch(()=>{}),4000);return()=>clearInterval(id)},[user]);
 useEffect(()=>{document.title=vocab?.private_local?'Clausetrail · PRIVATE LOCAL COPY':'Clausetrail'},[vocab]);

 if(loading)return <div className="login"><p className="muted">Opening Clausetrail…</p></div>;
 if(!user)return <div className="login"><section className="panel">
  <div className="brand">Clausetrail<small>Source-cited agreement review</small></div>
  <div><h1>Sign in</h1><p className="sub">Pick a demo identity. Each one sees different agreements, so you can show how access works.</p></div>
  {error&&<div className="banner err" role="alert">{error}</div>}
  {users.map(u=><button key={u.id} className="account" disabled={busy} onClick={()=>signIn(u.id)}><span><b>{u.name}</b><small>{u.role==='viewer'?'Can look, not change':u.role==='admin'?'Restricted legal collection only':'Reviewer · can import, review and label'} · {u.groups.join(' + ')}</small></span><span className="pill p-info">{u.role}</span></button>)}
  {!users.length&&!error&&<p className="muted">No demo identities are available.</p>}
  <p className="small muted" style={{margin:0}}>Demo identities for testing only. This is not real sign-in.</p>
 </section></div>;

 const editable=user.role!=='viewer';
 const go=(h:string)=>{if(location.hash===h)window.scrollTo(0,0);else location.hash=h};
 const c:Ctx={user,users,vocab,records,dash,jobs,editable,busy,act,refresh,go,toast,setError,filters,setFilters:f=>setF(x=>({...x,...f})),switchUser:signIn};
 const view=hash.slice(1).split('/')[0]||'home', detail=hash.startsWith('#a/')?hash.slice(3):'';
 const counts:Record<string,[number,boolean]>={agreements:[records.length,false],review:[dash?.review||0,!!dash?.review],deadlines:[(dash?.deadlines||[]).filter(d=>d.days<=30).length,(dash?.overdue||0)>0],alerts:[(dash?.deadlines||[]).filter(d=>d.kind==='expiration'&&d.days<=14).length,false]};
 return <div className="app">
  <aside className="rail">
   <div className="brand">Clausetrail<small>{vocab?.organization||''}{vocab?.private_local?' · private copy':' · demo'}</small></div>
   <nav className="nav">{NAV.map(([k,t])=>{const n=counts[k];return <a key={k} href={'#'+k} className={view===k||(detail&&k==='agreements')?'on':''} onClick={()=>{if(k==='agreements')setF(FILTERS)}}>{t}{n&&n[0]>0&&<span className={'count'+(n[1]?' hot':'')}>{n[0]}</span>}</a>})}</nav>
   <div className="note">
    <div className="who"><span>Signed in as</span><select aria-label="Switch demo identity" value={user.id} disabled={busy} onChange={e=>signIn(e.target.value)}>{users.map(u=><option key={u.id} value={u.id}>{u.name} · {u.role}</option>)}</select><button className="link small" onClick={signOut}>Sign out</button></div>
    <span>{vocab?.private_local?'Private local copy with real documents. Stays on this computer; do not share.':'Every name, date and agreement here is made up to show how the platform works.'}</span>
   </div>
  </aside>
  <main>
   <div className={vocab?.private_local?'banner err':'proto'}>{vocab?.private_local?'PRIVATE LOCAL COPY · real documents on this computer only. Do not share, screenshot for others, or deploy.':'Demo with fictional data. Facts read from documents stay proposed until someone reviews them. No emails are sent.'}</div>
   {error&&<div className="banner err" role="alert"><span>{error}</span><button onClick={()=>setError('')} aria-label="Dismiss">×</button></div>}
   {detail?<Detail c={c} id={detail}/>:view==='agreements'?<Agreements c={c}/>:view==='review'?<Review c={c}/>:view==='deadlines'?<Deadlines c={c}/>:view==='alerts'?<Alerts c={c}/>:view==='ask'?<Ask c={c}/>:view==='import'?<Import c={c}/>:view==='log'?<Log c={c}/>:view==='settings'?<Settings c={c}/>:<Home c={c}/>}
  </main>
  {toastMsg&&<div className="toast" role="status">{toastMsg}</div>}
 </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
