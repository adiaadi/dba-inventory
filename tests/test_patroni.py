import json
import unittest

from app.services.replication import read_config, build_pair, trend_key


class PatroniTests(unittest.TestCase):
    def setUp(self):
        self.pair = read_config('collectors/patroni/replication.json').pairs[0]
        self.pair.metrics['topology'].itemid = '123'
        self.data = {'scope': 'aml-prod-cluster', 'members': [
            dict(name='aml-prod-db01', role='sync_standby', state='streaming', timeline=124, receive_lag=0, replay_lag=0),
            dict(name='aml-prod-db02', role='leader', state='running', timeline=124),
            dict(name='aml-prod-drdb', role='replica', state='streaming', timeline=124, receive_lag=0, replay_lag=0),
        ]}

    def build(self, now=10000):
        return build_pair(self.pair, {'123': dict(status='0', state='0', lastclock='10000', lastvalue=json.dumps(self.data))}, now)

    def test_healthy_and_units(self):
        result = self.build()
        self.assertEqual(result['status'], 'healthy')
        self.assertEqual(result['primary'], 'aml-prod-db02')
        self.assertEqual(trend_key(self.pair), 'wal_backlog')
        self.assertEqual(next(m for m in result['metrics'] if m['key'] == 'wal_backlog')['unit'], 'bytes')

    def test_switchover(self):
        self.data['members'][0]['role'] = 'leader'
        self.data['members'][0]['state'] = 'running'
        self.data['members'][1].update(role='sync_standby', state='streaming', receive_lag=0, replay_lag=0)
        self.assertEqual(self.build()['primary'], 'aml-prod-db01')
        self.assertEqual(self.build()['status'], 'healthy')

    def test_missing_dr_and_timeline_mismatch(self):
        self.data['members'][2]['timeline'] = 123
        self.assertEqual(self.build()['status'], 'critical')
        self.data['members'].pop()
        self.assertEqual(self.build()['status'], 'critical')

    def test_unknown_lag_and_stale(self):
        self.assertEqual(self.build(now=10200)['status'], 'stale')
        self.data['members'][2]['replay_lag'] = 'unknown'
        result = self.build()
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(next(m for m in result['metrics'] if m['key'] == 'wal_backlog')['value'])

    def test_wrong_scope_duplicate_leader(self):
        self.data['members'][0]['role'] = 'leader'
        self.assertEqual(self.build()['primary'], 'Unknown Leader')
        self.assertEqual(self.build()['status'], 'critical')
        self.data['scope'] = 'wrong-cluster'
        self.assertEqual(self.build()['status'], 'unknown')
        self.assertEqual(self.build()['topology'], [])

    def test_invalid_payload_and_large_backlog(self):
        self.data['members'][2]['replay_lag'] = 1073741824
        self.assertEqual(self.build()['status'], 'critical')
        self.data = []
        self.assertEqual(self.build()['status'], 'unknown')

    def test_config_merge_preserves_oracle_and_is_idempotent(self):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'replication.json'
            original = json.loads(Path('collectors/oracle-v3/replication.json').read_text())
            target.write_text(json.dumps(original))
            command = [sys.executable, 'collectors/patroni/enable_portal.py', str(target)]
            subprocess.run(command, check=True, capture_output=True)
            subprocess.run(command, check=True, capture_output=True)
            merged = json.loads(target.read_text())
            self.assertEqual(merged['pairs'][:-1], original['pairs'])
            self.assertEqual(len(merged['pairs']), len(original['pairs']) + 1)
            self.assertEqual(len(list(Path(folder).glob('*.bak-*'))), 1)
            read_config(str(target))

    def test_add_css_preserves_aml(self):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'replication.json'
            original = json.loads(Path('collectors/patroni/replication.json').read_text())
            target.write_text(json.dumps(original))
            command = [sys.executable, 'collectors/patroni/enable_portal.py', str(target),
                       '--scope', 'css-prod-cluster', '--dr-member', 'css-prod-drdb']
            subprocess.run(command, check=True, capture_output=True)
            subprocess.run(command, check=True, capture_output=True)
            config = read_config(str(target))
            self.assertEqual(len(config.pairs), 2)
            self.assertEqual(config.pairs[0].patroni_scope, 'aml-prod-cluster')
            self.assertEqual(config.pairs[1].patroni_scope, 'css-prod-cluster')
            self.assertEqual(config.pairs[1].standby, 'css-prod-drdb')
            self.assertEqual(config.pairs[1].zabbix_host, 'css-prod-cluster')
            self.assertEqual(json.loads(target.read_text())['pairs'][0], original['pairs'][0])
