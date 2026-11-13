"""Read-only Graph adapter. No production connection is enabled by the demo.

Token acquisition and current-user source authorization belong to the organization
identity integration. This adapter accepts an existing short-lived Graph token.
"""
from dataclasses import dataclass
from urllib.parse import urlparse, quote
import httpx

GRAPH='https://graph.microsoft.com/v1.0'

@dataclass(frozen=True)
class SourceItem:
    id: str
    name: str
    version: str
    deleted: bool
    metadata: dict

class SharePointConnector:
    def __init__(self, drive_id, token, allowed_download_hosts, transport=None):
        if not drive_id or not token:
            raise ValueError('Drive ID and short-lived token required')
        self.drive_id=drive_id
        self.hosts=set(allowed_download_hosts)
        self.client=httpx.Client(headers={'Authorization':f'Bearer {token}'},transport=transport,timeout=30,follow_redirects=False,trust_env=False)
        self.download_client=httpx.Client(transport=transport,timeout=60,follow_redirects=False,trust_env=False)

    def close(self):
        self.client.close(); self.download_client.close()

    def _graph_url(self,url):
        p=urlparse(url)
        if p.scheme!='https' or p.hostname!='graph.microsoft.com' or p.port not in (None,443) or p.username:
            raise ValueError('Untrusted Graph continuation URL')
        prefix='/v1.0/drives/'+quote(self.drive_id,safe='')+'/'
        if not p.path.startswith(prefix):
            raise ValueError('Continuation escaped approved drive')
        return url

    def changes(self,checkpoint=None):
        url=checkpoint or GRAPH+'/drives/'+quote(self.drive_id,safe='')+'/root/delta'
        result=[]; seen=set()
        while url:
            if url in seen or len(seen)>=1000:
                raise ValueError('Invalid pagination')
            seen.add(url)
            response=self.client.get(self._graph_url(url)); response.raise_for_status(); payload=response.json()
            for item in payload.get('value',[]):
                if 'folder' in item: continue
                result.append(SourceItem(item['id'],item.get('name',''),item.get('eTag',''),'deleted' in item,item))
            url=payload.get('@odata.nextLink')
            if not url:
                checkpoint=payload.get('@odata.deltaLink')
                if not checkpoint: raise ValueError('Missing checkpoint')
                self._graph_url(checkpoint)
        return result,checkpoint

    def read(self,item,max_bytes=25*1024*1024):
        if item.deleted: raise ValueError('Deleted source')
        response=self.client.get(GRAPH+'/drives/'+quote(self.drive_id,safe='')+'/items/'+quote(item.id,safe='')+'/content')
        if response.status_code in (301,302,303,307,308):
            url=response.headers.get('location',''); p=urlparse(url)
            if p.scheme!='https' or p.hostname not in self.hosts or p.username or p.port not in (None,443):
                raise ValueError('Unapproved download host')
            # Authorization header is never forwarded to a signed download URL.
            with self.download_client.stream('GET',url) as download:
                download.raise_for_status(); content=bytearray()
                for chunk in download.iter_bytes():
                    content.extend(chunk)
                    if len(content)>max_bytes: raise ValueError('File exceeds limit')
                return bytes(content)
        response.raise_for_status()
        if len(response.content)>max_bytes: raise ValueError('File exceeds limit')
        return response.content
