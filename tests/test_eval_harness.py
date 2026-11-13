"""The CUAD evaluation harness runs end to end on a tiny fictional file in CUAD's format."""
import json
import tempfile
import unittest
from pathlib import Path

from eval import cuad_eval

TEXT = ('MASTER SUPPLY AGREEMENT\nThis Agreement is made on January 5, 2024 between Oriole Fictional Labs and Northwind Labs.\n'
        + 'Filler clause about deliveries and invoices.\n' * 400
        + 'This Agreement shall be governed by the laws of the State of Delaware.\n'
        + 'Payment to Account Number: 000123456789 at the bank listed above.\n')


def cuad_file(folder):
    gov = TEXT.index('This Agreement shall be governed')
    item = {'title': 'Fictional Supply', 'paragraphs': [{'context': TEXT, 'qas': [
        {'id': 'x__Governing Law', 'is_impossible': False,
         'question': 'Highlight the parts (if any) of this contract related to "Governing Law" that should be reviewed by a lawyer. Details: Which state/country\'s law governs the interpretation of the contract?',
         'answers': [{'text': 'This Agreement shall be governed by the laws of the State of Delaware', 'answer_start': gov}]},
        {'id': 'x__Parties', 'is_impossible': False,
         'question': 'Highlight the parts (if any) of this contract related to "Parties" that should be reviewed by a lawyer. Details: The two or more parties who signed the contract',
         'answers': [{'text': 'Oriole Fictional Labs', 'answer_start': TEXT.index('Oriole')}]},
        {'id': 'x__Non-Compete', 'is_impossible': True,
         'question': 'Highlight the parts (if any) of this contract related to "Non-Compete" that should be reviewed by a lawyer. Details: Is there a non-compete?',
         'answers': []}]}]}
    for name in ('test.json', 'CUADv1.json'):
        (Path(folder) / name).write_text(json.dumps({'data': [item]}))


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); cuad_file(self.dir)
        self.contracts = cuad_eval.load(self.dir)

    def test_blocks_keep_original_offsets(self):
        for b in cuad_eval.blocks_like_txt_parser(TEXT):
            self.assertEqual(TEXT[b['offset']:b['offset'] + len(b['text'])], b['text'])

    def test_retrieval_finds_far_clause_and_opening(self):
        result = cuad_eval.eval_retrieval(self.contracts)
        self.assertEqual(result['answerable_questions'], 2)
        self.assertEqual(result['summary']['clausetrail']['question_hit_rate'], 100.0)

    def test_quote_guard_and_redaction_and_extraction_run(self):
        quotes = cuad_eval.eval_quotes(self.contracts)
        self.assertEqual(quotes['variants']['verbatim']['accept_rate'], 100.0)
        self.assertEqual(quotes['variants']['negation_inserted']['accept_rate'], 0.0)
        red = cuad_eval.eval_redaction(self.contracts)
        self.assertEqual(red['clean_contracts']['by_category'], {'FIN_ACCOUNT': 1})
        self.assertGreater(red['injected']['overall_recall'], 90)
        self.assertEqual(cuad_eval.eval_extraction(self.contracts)['contracts'], 1)

    def test_dev_split_excludes_test_contracts(self):
        self.assertEqual(cuad_eval.load(self.dir, 'dev'), [])


if __name__ == '__main__':
    unittest.main()
