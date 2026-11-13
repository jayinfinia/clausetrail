"""Answer-model transports for grounded Q&A.

Default: a local Ollama model (loopback only, no cloud or proxy fallback).

Optional: Claude, for the fictional-data demo only. It is used when QA_PROVIDER=claude and
ANTHROPIC_API_KEY are both set. The destination is fixed to api.anthropic.com in code,
environment proxies are ignored, it is refused outright in a private local copy (real
documents), and a daily call limit (QA_DAILY_LIMIT, default 200 model calls) caps spend.
"""
import json
import os
import re
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
    return f'\n\nRespond only by calling the `{name}` tool exactly once with your complete response. Do not reply in plain text.'

def structured_reply(content, name):
    """The input of the named tool call; failing that, a JSON object written as plain text (with or without a code fence)."""
    for part in content or []:
        if part.get('type')=='tool_use' and part.get('name')==name and isinstance(part.get('input'),dict):
            return part['input']
    text=' '.join(part.get('text','') for part in content or [] if part.get('type')=='text')
    match=re.search(r'\{.*\}',text,re.S)
    if match:
        try:
            value=json.loads(match.group())
            if isinstance(value,dict):return value
        except ValueError:
            pass
    return None

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

def _claude_readiness():
    base={'configured':True,'provider':'Claude (fictional demo)','model':model_name() or None}
    if private_local():
        return {**base,'ready':False,'reason':'Claude answers are disabled in a private local copy; use a local Ollama model for real documents.'}
    if not os.getenv('ANTHROPIC_API_KEY'):
        return {**base,'configured':False,'ready':False,'reason':'Set ANTHROPIC_API_KEY to use Claude answers.'}
    left=daily_limit()-_calls_today()
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

def _claude_chat(system,payload,schema):
    status=_claude_readiness()
    if not status['ready']:
        raise ModelUnavailable(status['reason'])
    tool={'name':'respond','description':'Return the structured response.','input_schema':_inline_refs(schema)}
    body={'model':model_name(),'max_tokens':2000,'system':system+tool_instruction('respond'),'tools':[tool],
          'tool_choice':{'type':'auto'},
          'messages':[{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]}
    _record_call()
    try:
        with httpx.Client(timeout=httpx.Timeout(120,connect=10),trust_env=False,follow_redirects=False) as client:
            response=client.post(CLAUDE_URL,json=body,headers={'x-api-key':os.environ['ANTHROPIC_API_KEY'],'anthropic-version':'2023-06-01','content-type':'application/json'})
    except httpx.HTTPError:
        raise ModelUnavailable('Could not reach Claude. Check the network and retry.') from None
    if response.status_code!=200:
        raise ModelUnavailable(f'Claude request failed ({response.status_code}){api_error_reason(response)}')  # never log request bodies
    result=structured_reply(response.json().get('content'),'respond')
    if result is None:
        raise ModelResponseError('Claude returned no structured response')
    return result
