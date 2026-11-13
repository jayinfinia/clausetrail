"""Agreement labeling framework: pure rules plus API behavior. Fictional names only."""
import os
import tempfile
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='tracking-tests-'))
os.environ.setdefault('RUN_WORKER', 'false')
os.environ.setdefault('SESSION_SECRET', 'test-secret-not-for-deployment')
import unittest
from datetime import date
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.db import Base, engine, migrate
from backend.domain import framework as fw
from backend.services import alerts
from backend.services.worker import process_one

DOC = '''FICTIONAL TEST AGREEMENT
Agreement type: CDA
Counterparty: Oriole Fictional Labs
Effective date: 2026-01-01
Expiration date: 2027-02-28
'''


class NamingTests(unittest.TestCase):
    def test_standard_name(self):
        name, warn = fw.file_name('Oriole Fictional Labs', 'Material Transfer Agreement', '2026-03-04', 'Out for signature', 'pdf')
        self.assertEqual(name, 'Oriole Fictional Labs - Northwind Labs - Material Transfer Agreement - 20260304 - OUT FOR SIGNATURE.pdf')
        self.assertEqual(warn, [])

    def test_nodate_and_long_warning(self):
        name, warn = fw.file_name('X' * 220, 'CDA', None, 'Executed')
        self.assertIn('NODATE', name); self.assertEqual(len(warn), 2)

    def test_cleaning(self):
        self.assertEqual(fw.clean_segment('Vendor: science'), 'Vendor - science')
        self.assertEqual(fw.clean_segment('A/B\\C|D'), 'A-B-C-D')
        self.assertEqual(fw.clean_segment('Say "hi" <now>?#%'), "Say 'hi' now")
        self.assertEqual(fw.clean_segment(' ..~-Lead- '), 'Lead')
        self.assertEqual(fw.clean_segment('CON'), 'CON_')
        self.assertEqual(fw.clean_segment('a\x00b'), 'a b')

    def test_folder(self):
        self.assertEqual(fw.folder_path('Consultant / advisor', 'Wren Example Advisors'),
                         'Agreements/Consultant - advisor/Wren Example Advisors')


class EndRuleTests(unittest.TestCase):
    def test_fixed(self):
        self.assertEqual(fw.effective_end('fixed', '2026-01-01', '2027-01-01'), (date(2027, 1, 1), None))

    def test_later5_open_ended_until_relationship_ends(self):
        self.assertEqual(fw.effective_end('later5', '2026-01-01'), (None, date(2031, 1, 1)))

    def test_later5_floor_wins_or_relationship_wins(self):
        self.assertEqual(fw.effective_end('later5', '2026-01-01', relationship_end='2027-06-30')[0], date(2031, 1, 1))
        self.assertEqual(fw.effective_end('later5', '2026-01-01', relationship_end='2033-06-30')[0], date(2033, 6, 30))

    def test_leap_day_and_explicit_floor(self):
        self.assertEqual(fw.effective_end('later5', '2024-02-29')[1], date(2029, 2, 28))
        self.assertEqual(fw.effective_end('later5', '2024-02-29', floor='2030-01-01')[1], date(2030, 1, 1))


class HintTests(unittest.TestCase):
    def test_folder_hints(self):
        h = fw.hints_from_path('Fictional Set/Suppliers/Wren Example CRO/Clinical/sub/file.pdf')
        self.assertEqual((h['relationship'], h['counterparty']), ('Supplier', 'Wren Example CRO'))
        h = fw.hints_from_path('Fictional Set/Research Partners/Elm Fictional University/Lab of Dr. Ash/x.pdf')
        self.assertEqual((h['relationship'], h['counterparty']), ('Research partner', 'Elm Fictional University'))
        h = fw.hints_from_path('Fictional Set/Clients/Birch Example Health/x.pdf')
        self.assertEqual((h['relationship'], h['counterparty']), ('Customer', 'Birch Example Health'))
        self.assertEqual(fw.hints_from_path('loose-file.pdf')['relationship'], None)
        self.assertEqual(fw.hints_from_path('Set/Not Sure/Odd Doc/x.pdf')['relationship'], 'Unclassified')

    def test_file_name_hints(self):
        cases = {
            'Wren Labs - Northwind - CDA - 08.27.25 - EXECUTED.pdf': ('CDA', '2025-08-27', 'Executed'),
            'Ash, Pat - Northwind CDA-Investor 20230406 - EXECUTED.pdf': ('CDA', '2023-04-06', 'Executed'),
            'Wren CDA Amendment_20260624 - signed.pdf': ('AMENDMENT', '2026-06-24', 'Out for signature'),
            'Elm - Northwind - MTA - draft.docx': ('MTA', None, 'Drafting'),
            'Oak - Northwind NDA 03082025 - signed.pdf': ('CDA', '2025-03-08', 'Out for signature'),
            'Birch - Consulting - 2-11-2026 - EXECUTED.pdf': ('CONSULTING', '2026-02-11', 'Executed'),
            'random scan.pdf': (None, None, None),
        }
        for name, (kind, eff, status) in cases.items():
            self.assertEqual((fw.kind_from_name(name), fw.date_from_name(name), fw.status_from_name(name)), (kind, eff, status), name)

    def test_impossible_or_conflicting_dates_abstain(self):
        self.assertIsNone(fw.date_from_name('x 20251399.pdf'))
        self.assertIsNone(fw.date_from_name('x 20250101 and 20260101.pdf'))

    def test_suggest_labels_from_folder_and_name(self):
        labels = fw.suggest_labels('Set/Investors/Pat Ash/Ash - CDA-Investor 20240418 EXECUTED.pdf')
        self.assertEqual((labels['rel'], labels['kind'], labels['eff'], labels['status']), ('Investor', 'CDA', '2024-04-18', 'Executed'))
        self.assertFalse(labels['confirmed']); self.assertIn('folder', labels['suggestedFrom'])

    def test_reference_id_sequence(self):
        self.assertEqual(fw.reference_id('MTA', 2026, ['AGR-MTA-2026-002', 'AGR-CDA-2026-009', None]), 'AGR-MTA-2026-003')
        self.assertEqual(fw.reference_id('SERVICES', 2025, []), 'AGR-SVC-2025-001')

    def test_validate_labels_rules(self):
        new = fw.validate_labels({'rel': 'Investor', 'owner': 'Finance'}, {'rel': 'Research Partners', 'components': ['Research', 'Confidentiality']})
        self.assertEqual((new['rel'], new['components']), ('Research partner', ['Confidentiality', 'Research']))
        new = fw.validate_labels({'owner': 'Legal'}, {'rel': 'Investors', 'status': 'In review'})
        self.assertEqual((new['rel'], new['waiting']), ('Investor', 'Legal'))
        self.assertIsNone(fw.validate_labels(new, {'status': 'Executed'})['waiting'])
        for bad in ({'owner': 'Mallory'}, {'rel': 'Partner of the month'}, {'components': ['Telepathy']}, {'nope': 1}):
            with self.assertRaises(ValueError): fw.validate_labels({}, bad)


class AlertTests(unittest.TestCase):
    def rows(self):
        return [{'agreement_id': 'a', 'counterparty': 'Oriole', 'owner': 'Legal', 'date': '2026-11-15', 'days': 10, 'status': 'Executed'},
                {'agreement_id': 'b', 'counterparty': 'Wren', 'owner': '', 'date': '2026-10-01', 'days': -35, 'status': 'Executed'},
                {'agreement_id': 'c', 'counterparty': 'Ash', 'owner': 'Research', 'date': '2026-09-01', 'days': -65, 'status': 'Expired'},
                {'agreement_id': 'd', 'counterparty': 'Elm', 'owner': 'Research', 'date': '2027-01-20', 'days': 76, 'status': None}]

    def test_preview(self):
        p = alerts.preview(self.rows(), alerts.DEFAULTS, today=date(2026, 11, 5))
        self.assertEqual(p['weekly']['next'], '2026-11-09')  # next Monday
        self.assertEqual(p['weekly']['to'], ['Leadership', 'Finance', 'Legal', 'Research'])
        self.assertEqual([u['agreement_id'] for u in p['urgent']], ['a'])
        self.assertEqual(p['urgent'][0]['send'], '2026-11-01')
        self.assertEqual([x['agreement_id'] for x in p['pastDue']], ['b'])  # marked Expired is not past due
        self.assertFalse(p['sent'])

    def test_settings_validation(self):
        p = alerts.preview(self.rows(), {**alerts.DEFAULTS, 'urgent': 30, 'pastDue': False, 'rec': {'Leadership': True}}, today=date(2026, 11, 5))
        self.assertEqual(p['pastDue'], []); self.assertEqual(p['weekly']['to'], ['Leadership'])
        with self.assertRaises(ValueError): alerts.validate({'urgent': 10})


class FrameworkApiTests(unittest.TestCase):
    def setUp(self):
        migrate(); Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
        self.client = TestClient(app); self.client.__enter__(); self.login('alex')

    def tearDown(self): self.client.__exit__(None, None, None)

    def login(self, who):
        r = self.client.post('/api/auth/demo', json={'username': who}); self.client.headers['X-CSRF-Token'] = r.json()['csrf']

    def import_with_path(self, path, text=DOC, scope='research'):
        name = path.split('/')[-1]
        r = self.client.post('/api/imports', files=[('files', (name, text.encode(), 'text/plain'))], data={'scope': scope, 'paths': [path]})
        self.assertEqual(r.status_code, 200, r.text); return r.json()['results'][0]

    def approve(self, rid):
        rec = self.client.get('/api/agreements/' + rid).json()
        fields = {k: {'value': v['value'], 'evidence': v.get('evidence')} for k, v in rec['proposals'].items() if v['value'] is not None}
        r = self.client.post(f'/api/agreements/{rid}/review', json={'revision': rec['revision'], 'executed': True, 'fields': fields})
        self.assertEqual(r.status_code, 200, r.text); return r.json()

    def test_folder_import_suggests_labels_but_not_facts(self):
        res = self.import_with_path('Set/Research Partners/Oriole Fictional Labs/Oriole - Northwind - MTA - 20260101 - EXECUTED.txt')
        self.assertEqual(res['suggested'], {'rel': 'Research partner', 'party': 'Oriole Fictional Labs', 'kind': 'MTA'})
        rec = self.client.get('/api/agreements/' + res['id']).json()
        self.assertFalse(rec['labels']['confirmed']); self.assertEqual(rec['approved'], {})
        self.assertEqual(rec['framework']['standard_folder'], 'Agreements/Research partner/Oriole Fictional Labs')

    def test_mismatched_paths_rejected(self):
        r = self.client.post('/api/imports', files=[('files', ('a.txt', b'a', 'text/plain')), ('files', ('b.txt', b'b', 'text/plain'))],
                             data={'scope': 'research', 'paths': ['only/one.txt']})
        self.assertEqual(r.status_code, 422)

    def test_label_edit_logged_and_end_rule(self):
        rid = self.import_with_path('Set/Investors/Oriole Fictional Labs/doc.txt')['id']; process_one()
        rec = self.approve(rid)
        self.assertTrue(rec['labels']['ref_id'].startswith('AGR-CDA-2026-'))
        r = self.client.patch(f'/api/agreements/{rid}/labels', json={'revision': rec['revision'], 'changes': {'owner': 'Legal', 'endRule': 'later5'}})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json(); self.assertTrue(body['framework']['open_ended']); self.assertEqual(body['framework']['floor'], '2031-01-01')
        self.assertEqual([d for d in self.client.get('/api/dashboard').json()['deadlines'] if d['kind'] == 'expiration'], [])
        r = self.client.patch(f'/api/agreements/{rid}/labels', json={'revision': body['revision'], 'changes': {'relEnd': '2033-03-01'}})
        self.assertEqual(r.json()['framework']['end_date'], '2033-03-01')
        log = self.client.get('/api/log').json()
        fields = [c['field'] for e in log for c in e['changes']]
        for f in ('owner', 'endRule', 'relEnd', 'end date', 'ref_id'): self.assertIn(f, fields)
        self.assertTrue(all(e['editor'] == 'alex' for e in log))
        stale = self.client.patch(f'/api/agreements/{rid}/labels', json={'revision': 0, 'changes': {'owner': 'Research'}})
        self.assertEqual(stale.status_code, 409)
        bad = self.client.patch(f'/api/agreements/{rid}/labels', json={'revision': r.json()['revision'], 'changes': {'owner': 'Mallory'}})
        self.assertEqual(bad.status_code, 422)

    def test_viewer_cannot_edit_and_log_is_scoped(self):
        rid = self.import_with_path('Set/Funders/Secret Fictional Fund/doc.txt', scope='legal')['id']
        rec = self.client.get('/api/agreements/' + rid).json()
        self.client.patch(f'/api/agreements/{rid}/labels', json={'revision': rec['revision'], 'changes': {'owner': 'Finance'}})
        self.login('sam')
        self.assertEqual(self.client.patch(f'/api/agreements/{rid}/labels', json={'revision': 1, 'changes': {}}).status_code, 403)
        self.assertNotIn('Secret', str(self.client.get('/api/log').json()))

    def test_alert_settings_persist_and_log(self):
        settings = {'day': 3, 'time': '09:00', 'urgent': 30, 'pastDue': False, 'rec': {'Leadership': True, 'Finance': False, 'owner': True}, 'extra': ['ops']}
        self.assertEqual(self.client.put('/api/alerts/settings', json=settings).status_code, 200)
        preview = self.client.get('/api/alerts').json()
        self.assertEqual(preview['settings']['urgent'], 30); self.assertEqual(preview['weekly']['send'], 'Wednesdays at 09:00')
        self.assertIn('alert_settings', [e['action'] for e in self.client.get('/api/log').json()])
        self.assertEqual(self.client.put('/api/alerts/settings', json={**settings, 'urgent': 10}).status_code, 422)

    def test_dashboard_and_export_include_framework(self):
        rid = self.import_with_path('Set/Suppliers/Oriole Fictional Labs/doc.txt')['id']; process_one(); self.approve(rid)
        dash = self.client.get('/api/dashboard').json()
        self.assertEqual(dash['by_relationship']['Supplier'], 1); self.assertEqual(dash['by_owner']['Unassigned'], 1)
        csv = self.client.get('/api/export').text
        self.assertIn('standard_name', csv.splitlines()[0]); self.assertIn('Agreements/Supplier/Oriole Fictional Labs', csv)

    def test_seed_uses_fictional_folders(self):
        self.client.post('/api/demo/seed')
        rows = self.client.get('/api/agreements').json()
        rels = {r['labels']['rel'] for r in rows}
        self.assertTrue({'Research partner', 'Investor', 'Funder', 'Supplier', 'Consultant / advisor', 'Unclassified'} <= rels)
        self.assertTrue(all(r['rel_path'].startswith('Fictional Sample Set/') for r in rows))


if __name__ == '__main__':
    unittest.main()
