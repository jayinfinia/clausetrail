import os
import unittest
from unittest.mock import patch
from backend.services.extraction import model_extract, local_generate

class ModelTests(unittest.TestCase):
    def test_supported_quote_accepts_proposal(self):
        blocks=[{'id':'1','locator':'Page 1','text':'The parties are Northwind Demo and Fictional Research.'}]
        with patch.dict(os.environ,{'OLLAMA_MODEL':'fixture-model'}),patch('backend.services.extraction.local_generate',return_value={'fields':{'counterparty':{'value':'Fictional Research','evidence':'1','quote':'Fictional Research'}}}):
            result=model_extract(blocks)
        self.assertEqual(result['counterparty']['value'],'Fictional Research')
        self.assertEqual(result['counterparty']['state'],'proposed')
    def test_missing_quote_abstains(self):
        blocks=[{'id':'1','locator':'Page 1','text':'Fictional source without an expiration.'}]
        with patch.dict(os.environ,{'OLLAMA_MODEL':'fixture-model'}),patch('backend.services.extraction.local_generate',return_value={'fields':{'expiration_date':{'value':'2030-01-01','evidence':'1','quote':'made up quote'}}}):
            result=model_extract(blocks)
        self.assertIsNone(result['expiration_date']['value'])
    def test_external_model_host_rejected(self):
        with patch.dict(os.environ,{'OLLAMA_MODEL':'fixture-model','OLLAMA_URL':'https://external.invalid'}):
            with self.assertRaises(ValueError):local_generate('fictional')
