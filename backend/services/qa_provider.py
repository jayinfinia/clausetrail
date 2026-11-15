"""Answer-model transports for grounded Q&A.

Default: a local Ollama model (loopback only, no cloud or proxy fallback).

Optional: Claude, for the fictional-data demo only. It is used when QA_PROVIDER=claude and
ANTHROPIC_API_KEY are both set. The destination is fixed to api.anthropic.com in code,
environment proxies are ignored, it is refused outright in a private local copy (real
documents), and a daily call limit (QA_DAILY_LIMIT, default 200 model calls) caps spend.
"""
import html
import json
import os
import random
import re
import time
from urllib.parse import urlparse
import httpx

def api_error_reason(response):
    """Anthropic's own short error message (e.g. low credit balance, invalid model), never the request or document.
    Error messages describe the problem, not the prompt; they are still capped and stripped of anything quoted."""
    try:
        err = response.json().get('error') or {}
        message = str(err.get('message') or '') if isinstance(err, dict) else ''
    except Exception:
        return ''
    message = re.sub(r'\s+', ' ', message).strip()[:160]
    return f': {message}' if message else ''

def tool_instruction(name):
    """Newer Claude models reject a forced tool_choice, so the request uses tool_choice auto plus this instruction."""
    return (f'\n\nRespond only by calling the `{name}` tool exactly once, with your complete response as its input. '
            'Do not reply in plain text, and do not wrap the input in another object.')

# Keys a model sometimes wraps its real answer in: {"input": {...}}, {"parameters": "{...}"}, {"name": ..., "arguments": ...}.
WRAPPERS=('input','parameters','arguments','response','result','output','data')
ENVELOPE=set(WRAPPERS)|{'name','type','id'}

def _unwrap(value,keys=()):
    for _ in range(3):
        if not isinstance(value,dict) or (keys and set(keys)&value.keys()):break
        if not (keys or set(value)<=ENVELOPE):break
        inner=[value[k] for k in WRAPPERS if k in value]
        if len(inner)!=1:break
        inner=inner[0]
        if isinstance(inner,str):
            try:
                inner=json.loads(inner)
            except ValueError:
                break
        if not isinstance(inner,dict):break
        value=inner
    return value

def _json_objects(text):
    """Every JSON object that can be decoded starting at a '{' in text, outermost first (prose and fences are skipped)."""
    decoder=json.JSONDecoder(); out=[]; i=text.find('{')
    while i!=-1:
        try:
            value,end=decoder.raw_decode(text,i)
        except ValueError:
            i=text.find('{',i+1);continue
        if isinstance(value,dict):out.append(value)
        i=text.find('{',end)
    return out

def structured_reply(content,name,keys=()):
    """The input of the tool call; failing that, a JSON object written as plain text (with or without prose or a
    code fence). A single tool call under another name and answers wrapped in {"input": ...} are accepted: only one
    tool is offered and the content is validated by the caller either way. keys are the schema's required keys,
    used to pick the right object when the text holds several."""
    parts=[p for p in content or [] if isinstance(p,dict)] if isinstance(content,list) else []
    calls=[p for p in parts if p.get('type')=='tool_use' and isinstance(p.get('input'),(dict,str))]
    chosen=[p for p in calls if p.get('name')==name] or (calls if len(calls)==1 else [])
    for part in chosen:
        value=part['input']
        if isinstance(value,str):
            value=next(iter(_json_objects(value)),None)
        value=_unwrap(value,keys)
        if isinstance(value,dict) and value:return value
    text=' '.join(str(p.get('text') or '') for p in parts if p.get('type')=='text')
    found=[_unwrap(v,keys) for v in _json_objects(text)]
    found=[v for v in found if isinstance(v,dict)]
    if keys:
        found=[v for v in found if set(keys)&v.keys()] or found
    return found[0] if found else None

class ModelUnavailable(Exception):
    pass

class ModelResponseError(Exception):
    pass

CLAUDE_URL='https://api.anthropic.com/v1/messages'

def provider():
    return 'claude' if os.getenv('QA_PROVIDER','').lower()=='claude' else 'ollama'

def model_name():
    if provider()=='claude':
        return os.getenv('CLAUDE_QA_MODEL','claude-sonnet-5-5') if os.getenv('ANTHROPIC_API_KEY') else ''
    return os.getenv('QA_MODEL') or os.getenv('OLLAMA_MODEL') or ''

def private_local():
    return os.getenv('PRIVATE_LOCAL','false').lower()=='true'


def base_url():
    url=os.getenv('QA_OLLAMA_URL') or os.getenv('OLLAMA_URL','http://127.0.0.1:11434')
    parsed=urlparse(url)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1','ollama') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ModelUnavailable('Only an approved local Ollama endpoint is supported')
    return url.rstrip('/')

def require_local_model(client,model,url=None):
    if 'cloud' in model.casefold():
        raise ModelUnavailable('Cloud model names are not allowed')
    response=client.post((url or base_url())+'/api/show',json={'model':model});response.raise_for_status()
    info=response.json()
    if info.get('remote_host') or info.get('remote_model') or not info.get('model_info'):
        raise ModelUnavailable('Model must expose local model metadata; remote or unknown models are blocked')

def readiness():
    if provider()=='claude':
        return _claude_readiness()
    return _ollama_readiness()

def _ollama_readiness():
    model=model_name()
    if not model:
        return {'configured':False,'ready':False,'model':None,'reason':'Set QA_MODEL to an installed local Ollama model.','provider':'local Ollama'}
    try:
        with httpx.Client(timeout=2,trust_env=False,follow_redirects=False) as client:
            response=client.get(base_url()+'/api/tags'); response.raise_for_status()
            models=response.json().get('models',[])
            names={entry.get('name','') for entry in models}
            ready=model in names or model+':latest' in names
            if ready:require_local_model(client,model)
            return {'configured':True,'ready':ready,'model':model,'reason':None if ready else 'Configured model is not installed. Pull it in Ollama first.','provider':'local Ollama'}
    except (httpx.HTTPError,ValueError,ModelUnavailable):
        return {'configured':True,'ready':False,'model':model,'reason':'Local model service is unavailable or misconfigured.','provider':'local Ollama'}

def chat(system,payload,schema):
    if provider()=='claude':
        return _claude_chat(system,payload,schema)
    return _ollama_chat(system,payload,schema)

def _ollama_chat(system,payload,schema):
    model=model_name()
    if not model:
        raise ModelUnavailable('AI is not configured. Set QA_MODEL and run the local Ollama service.')
    request={'model':model,'stream':False,'format':schema,'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}], 'options':{'temperature':0,'num_ctx':16384,'num_predict':1800},'keep_alive':'5m'}
    try:
        # No content is written to disk; a hard response cap prevents runaway output.
        with httpx.Client(timeout=httpx.Timeout(180,connect=5),trust_env=False,follow_redirects=False) as client:
            require_local_model(client,model)
            with client.stream('POST',base_url()+'/api/chat',json=request) as response:
                response.raise_for_status(); raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>150_000: raise ModelResponseError('Model response exceeded the limit')
        envelope=json.loads(raw)
        if not envelope.get('done') or envelope.get('done_reason')=='length':
            raise ModelResponseError('Model response was incomplete')
        result=json.loads(envelope['message']['content'])
        if not isinstance(result,dict): raise ModelResponseError('Invalid model response')
        return result
    except (httpx.HTTPError,KeyError,ValueError) as exc:
        # Do not expose/log provider response bodies, prompts or source text.
        raise ModelUnavailable('Local AI request failed. Check the model service and retry.') from None


# ---------------------------------------------------------------- Claude (fictional demo only)

def _usage_path():
    from backend import config
    return config.DATA/'claude_usage.json'

def _calls_today():
    from datetime import date
    try:
        data=json.loads(_usage_path().read_text())
    except (OSError,ValueError):
        return 0
    return int(data.get(date.today().isoformat(),0))

def _record_call():
    from datetime import date
    path=_usage_path(); today=date.today().isoformat()
    path.write_text(json.dumps({today:_calls_today()+1}))

def daily_limit():
    try:
        return max(0,int(os.getenv('QA_DAILY_LIMIT','200')))
    except ValueError:
        return 200

def calls_left():
    return daily_limit()-_calls_today()

def _claude_readiness():
    base={'configured':True,'provider':'Claude (fictional demo)','model':model_name() or None}
    if private_local():
        return {**base,'ready':False,'reason':'Claude answers are disabled in a private local copy; use a local Ollama model for real documents.'}
    if not os.getenv('ANTHROPIC_API_KEY'):
        return {**base,'configured':False,'ready':False,'reason':'Set ANTHROPIC_API_KEY to use Claude answers.'}
    left=calls_left()
    if left<=0:
        return {**base,'ready':False,'reason':'Daily Claude call limit reached; evidence search still works. It resets tomorrow.'}
    return {**base,'ready':True,'reason':None,'calls_left_today':left}

def _inline_refs(schema):
    """Resolve local $ref/$defs so the tool schema is self-contained."""
    defs=schema.get('$defs',{})
    def walk(node):
        if isinstance(node,dict):
            if '$ref' in node and node['$ref'].startswith('#/$defs/'):
                return walk(defs[node['$ref'].split('/')[-1]])
            return {k:walk(v) for k,v in node.items() if k!='$defs'}
        if isinstance(node,list):
            return [walk(v) for v in node]
        return node
    return walk(schema)

RETRY_STATUS={429,500,502,503,504,529}  # rate limited, overloaded or a transient server error: not billed
MAX_ATTEMPTS=3
MAX_WAIT=30
_sleep=time.sleep

def _wait(response,attempt):
    """Seconds before the next attempt: the server's retry-after when given (capped), else exponential backoff."""
    try:
        value=float(response.headers.get('retry-after')) if response is not None else None
    except (TypeError,ValueError):
        value=None
    return min(MAX_WAIT,value if value is not None and value>=0 else 2**attempt+random.random())

def claude_messages(body,api_key,count=True):
    """POST one Messages request to the fixed Anthropic endpoint and return the decoded reply.

    Retries a rate-limited, overloaded or failed connection up to MAX_ATTEMPTS times, honouring retry-after.
    Only attempts the API accepted for processing count against the daily limit (count=True). Raises
    ModelUnavailable with a fixed message plus Anthropic's short error reason; never includes or logs request
    or response bodies."""
    headers={'x-api-key':api_key,'anthropic-version':'2023-06-01','content-type':'application/json'}
    response=None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:_sleep(_wait(response,attempt))
        try:
            with httpx.Client(timeout=httpx.Timeout(120,connect=10),trust_env=False,follow_redirects=False) as client:
                response=client.post(CLAUDE_URL,json=body,headers=headers)
        except (httpx.ConnectError,httpx.ConnectTimeout):
            response=None
            if attempt+1<MAX_ATTEMPTS:continue
            raise ModelUnavailable('Could not reach Claude. Check the network and retry.') from None
        except httpx.TimeoutException:
            if count:_record_call()  # the request was accepted and may have been processed
            raise ModelUnavailable('Claude did not respond in time. Try a narrower question or retry.') from None
        except httpx.HTTPError:
            raise ModelUnavailable('Could not reach Claude. Check the network and retry.') from None
        if response.status_code in RETRY_STATUS:
            if attempt+1<MAX_ATTEMPTS:continue
            raise ModelUnavailable(f'Claude is busy ({response.status_code}){api_error_reason(response)}. Wait a minute and retry.')
        if count:_record_call()
        if response.status_code!=200:
            raise ModelUnavailable(f'Claude request failed ({response.status_code}){api_error_reason(response)}')  # never log request bodies
        try:
            reply=response.json()
        except ValueError:
            reply=None
        if not isinstance(reply,dict):
            raise ModelResponseError('Claude returned an unreadable response')
        return reply

def _neutral(text):
    # Passage text cannot close or open the structure it sits in; everything else is sent exactly as stored.
    return re.sub(r'<(/?)(documents?|passage|question|coverage|claim|evidence)\b',r'‹\1\2',str(text),flags=re.I)

def _attr(value):
    return html.escape(str(value),quote=True)

def claude_content(payload):
    """User message for Claude: documents first as XML, the question last (Anthropic long-context guidance).
    Only the drafting payload (documents that carry passages) is laid out this way; anything else, such as the
    support check's claims and evidence, is sent as JSON so no field is dropped."""
    docs=payload.get('documents') if isinstance(payload,dict) else None
    if not isinstance(docs,list) or not any(isinstance(d,dict) and d.get('passages') for d in docs) or set(payload)-{'question','documents','coverage'}:
        return json.dumps(payload,ensure_ascii=False)
    out=['<documents>']
    for i,doc in enumerate(payload['documents'],1):
        meta={k:v for k,v in doc.items() if k not in ('document','passages')}
        out.append(f'<document index="{i}" name="{_attr(doc.get("document",""))}">')
        if meta:out.append('<document_metadata>'+_neutral(json.dumps(meta,ensure_ascii=False))+'</document_metadata>')
        for p in doc.get('passages',[]):
            out.append(f'<passage source_id="{_attr(p["source_id"])}" location="{_attr(p.get("location",""))}">\n{_neutral(p["text"])}\n</passage>')
        out.append('</document>')
    out.append('</documents>')
    if payload.get('coverage'):out.append('<coverage>'+_neutral(payload['coverage'])+'</coverage>')
    out.append('<question>'+_neutral(payload.get('question',''))+'</question>')
    out.append('Answer the question using only the passages above. Cite passages by their source_id.')
    return '\n'.join(out)

MAX_TOKENS=4096
MAX_TOKENS_RETRY=8192

def _claude_chat(system,payload,schema):
    status=_claude_readiness()
    if not status['ready']:
        raise ModelUnavailable(status['reason'])
    tool={'name':'respond','description':'Return the structured response.','input_schema':_inline_refs(schema)}
    body={'model':model_name(),'max_tokens':MAX_TOKENS,'system':system+tool_instruction('respond'),'tools':[tool],
          'tool_choice':{'type':'auto'},
          'messages':[{'role':'user','content':claude_content(payload)}]}
    reply=claude_messages(body,os.environ['ANTHROPIC_API_KEY'])
    if reply.get('stop_reason')=='max_tokens':
        # A cut-off reply is never parsed. Ask once more with room for the whole answer, within the daily limit.
        if not _claude_readiness()['ready']:
            raise ModelResponseError('Claude response was cut off and the daily limit is reached')
        reply=claude_messages({**body,'max_tokens':MAX_TOKENS_RETRY},os.environ['ANTHROPIC_API_KEY'])
        if reply.get('stop_reason')=='max_tokens':
            raise ModelResponseError('Claude response was too long; narrow the question or pick fewer agreements')
    result=structured_reply(reply.get('content'),'respond',tuple(schema.get('required') or ()))
    if result is None:
        raise ModelResponseError('Claude returned no structured response')
    return result
