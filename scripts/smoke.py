"""Exercise an already running disposable demo. Usage: python -m scripts.smoke URL"""
import sys,time
import httpx
base=sys.argv[1] if len(sys.argv)>1 else 'http://localhost:8000'
with httpx.Client(base_url=base,trust_env=False) as c:
    assert c.get('/').status_code==200
    auth=c.post('/api/auth/demo',json={'username':'alex'}).json(); c.headers['X-CSRF-Token']=auth['csrf']
    seed=c.post('/api/demo/seed'); assert seed.status_code==200,seed.text
    for _ in range(80):
        rows=c.get('/api/agreements').json()
        if len(rows)>=12 and all(r['status'] in ('needs_review','reviewed') for r in rows): break
        time.sleep(.5)
    assert len(rows)>=12 and all(r['status'] in ('needs_review','reviewed') for r in rows)
    rid=next(r['id'] for r in rows if r['filename']=='01-cda-aster.txt')
    detail=c.get('/api/agreements/'+rid).json()
    facts={k:{'value':v['value'],'evidence':v['evidence']} for k,v in detail['proposals'].items() if v['value'] is not None}
    review=c.post('/api/agreements/'+rid+'/review',json={'revision':detail['revision'],'executed':True,'fields':facts});assert review.status_code==200,review.text
    assert c.get('/api/dashboard').json()['executed']>=1
    result=c.post('/api/questions',json={'question':'How many CDAs are executed?'}).json();assert len(result['rows'])>=1
    sam=c.post('/api/auth/demo',json={'username':'sam'}).json();c.headers['X-CSRF-Token']=sam['csrf']
    assert all(r['scope']=='research' for r in c.get('/api/agreements').json())
print('Live HTTP acceptance passed: built UI served, 12 background imports, review, dashboard, questions, access switch.')
