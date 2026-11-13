import unittest
import httpx
from backend.connectors.sharepoint import SharePointConnector,SourceItem

class ConnectorTests(unittest.TestCase):
    def test_delta_and_download_strip_bearer(self):
        def handler(request):
            if request.url.host=='tenant.sharepoint.com':
                self.assertNotIn('authorization',request.headers)
                return httpx.Response(200,content=b'fictional')
            self.assertEqual(request.headers['authorization'],'Bearer fake-test-token')
            if request.url.path.endswith('/content'):
                return httpx.Response(302,headers={'Location':'https://tenant.sharepoint.com/file'})
            return httpx.Response(200,json={'value':[{'id':'item','name':'test.txt','eTag':'v1','file':{}}],'@odata.deltaLink':'https://graph.microsoft.com/v1.0/drives/drive/root/delta?token=next'})
        connector=SharePointConnector('drive','fake-test-token',['tenant.sharepoint.com'],httpx.MockTransport(handler))
        items,checkpoint=connector.changes(); self.assertIn('token=next',checkpoint)
        self.assertEqual(connector.read(items[0]),b'fictional'); connector.close()
    def test_rejects_off_drive_checkpoint(self):
        connector=SharePointConnector('drive','fake',[],httpx.MockTransport(lambda r:httpx.Response(200)))
        for url in ['https://evil.invalid/a','https://graph.microsoft.com/v1.0/drives/other/root/delta']:
            with self.assertRaises(ValueError): connector.changes(url)
        connector.close()
    def test_download_redirect_is_allowlisted(self):
        connector=SharePointConnector('drive','fake',[],httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'https://evil.invalid/file'})))
        with self.assertRaises(ValueError): connector.read(SourceItem('id','file','1',False,{}))
        connector.close()
