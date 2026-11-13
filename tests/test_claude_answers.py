"""Claude as the answer model: fictional demo only, fixed destination, daily cap. The API is mocked."""
import os
import tempfile
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='clausetrail-tests-'))
import unittest
from unittest.mock import MagicMock, patch

from backend import config
from backend.services import qa_provider
from backend.services.grounded_qa import Draft

ENV = {'QA_PROVIDER': 'claude', 'ANTHROPIC_API_KEY': 'test-key-not-real', 'PRIVATE_LOCAL': 'false', 'QA_DAILY_LIMIT': '3'}


def reply(payload):
    r = MagicMock(); r.status_code = 200
    r.json.return_value = {'content': [{'type': 'tool_use', 'name': 'respond', 'input': payload}]}
    return r


class ClaudeProviderTests(unittest.TestCase):
    def setUp(self):
        config.DATA.mkdir(parents=True, exist_ok=True)
        qa_provider._usage_path().unlink(missing_ok=True)

    def test_off_unless_selected(self):
        with patch.dict(os.environ, {'QA_PROVIDER': '', 'ANTHROPIC_API_KEY': 'x', 'QA_MODEL': ''}, clear=False):
            self.assertEqual(qa_provider.provider(), 'ollama'); self.assertEqual(qa_provider.model_name(), '')

    def test_refused_for_real_documents(self):
        with patch.dict(os.environ, {**ENV, 'PRIVATE_LOCAL': 'true'}):
            self.assertFalse(qa_provider.readiness()['ready'])
            with patch('httpx.Client.post') as post, self.assertRaises(qa_provider.ModelUnavailable):
                qa_provider.chat('s', {}, {'type': 'object'})
            post.assert_not_called()

    def test_needs_key(self):
        with patch.dict(os.environ, {**ENV, 'ANTHROPIC_API_KEY': ''}):
            status = qa_provider.readiness()
            self.assertFalse(status['configured']); self.assertEqual(qa_provider.model_name(), '')

    def test_fixed_destination_inlined_schema_and_cap(self):
        schema = Draft.model_json_schema()
        draft = {'relevant_source_ids': ['S1'], 'claims': [], 'not_stated': [], 'conflicting': False}
        with patch.dict(os.environ, ENV), patch('httpx.Client.post', return_value=reply(draft)) as post:
            for _ in range(3):
                self.assertEqual(qa_provider.chat('system', {'question': 'q'}, schema), draft)
            url = post.call_args.args[0]; body = post.call_args.kwargs['json']
            self.assertEqual(url, 'https://api.anthropic.com/v1/messages')
            self.assertNotIn('$ref', str(body['tools'][0]['input_schema']))
            self.assertEqual(body['tool_choice'], {'type': 'tool', 'name': 'respond'})
            self.assertFalse(qa_provider.readiness()['ready'])  # limit of 3 reached
            with self.assertRaises(qa_provider.ModelUnavailable):
                qa_provider.chat('system', {}, schema)
            self.assertEqual(post.call_count, 3)

    def test_http_error_shows_only_anthropic_reason(self):
        bad = MagicMock(); bad.status_code = 400
        bad.json.return_value = {'type': 'error', 'error': {'type': 'invalid_request_error',
                                 'message': 'Your credit balance is too low to access the Anthropic API.'}}
        with patch.dict(os.environ, ENV), patch('httpx.Client.post', return_value=bad):
            with self.assertRaises(qa_provider.ModelUnavailable) as ctx:
                qa_provider.chat('s', {'question': 'secret document text'}, {'type': 'object'})
        self.assertIn('credit balance is too low', str(ctx.exception))
        self.assertNotIn('secret document text', str(ctx.exception))
        odd = MagicMock(); odd.status_code = 500; odd.json.side_effect = ValueError
        self.assertEqual(qa_provider.api_error_reason(odd), '')


if __name__ == '__main__':
    unittest.main()
