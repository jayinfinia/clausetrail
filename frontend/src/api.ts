let csrf='';
export function setCsrf(token:string){csrf=token}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const headers=new Headers(options.headers); if(csrf)headers.set('X-CSRF-Token',csrf);
 if(options.body && !(options.body instanceof FormData))headers.set('Content-Type','application/json');
 const res=await fetch('/api'+path,{...options,headers});
 if(!res.ok){let detail='Request failed';try{const j=await res.json();detail=typeof j.detail==='string'?j.detail:JSON.stringify(j.detail)}catch{}throw new Error(detail)}
 return res.json();
}
