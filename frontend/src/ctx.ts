import type {User,Vocab,RecordItem,Dash,Job} from './types';
export type Ctx={user:User;users:User[];vocab:Vocab|null;records:RecordItem[];dash:Dash|null;jobs:Job[];editable:boolean;busy:boolean;
 act:(fn:()=>Promise<unknown>,ok?:string)=>Promise<void>;refresh:()=>Promise<void>;go:(hash:string)=>void;toast:(m:string)=>void;setError:(m:string)=>void;
 filters:{q:string;type:string;status:string;special:string;rel:string;owner:string};setFilters:(f:Partial<Ctx['filters']>)=>void;switchUser:(id:string)=>Promise<void>};
