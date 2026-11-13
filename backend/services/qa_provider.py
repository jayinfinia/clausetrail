"""Local-only, bounded Ollama chat transport. No cloud or proxy fallback."""
import json
import os
from urllib.parse import urlparse
import httpx

class ModelUnavailable(Exception):
    pass

class ModelResponseError(Exception):
    pass

def model_name():
    return os.getenv('QA_MODEL') or os.getenv('OLLAMA_MODEL') or ''

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
