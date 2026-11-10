import json
import unittest
from pathlib import Path
from unittest.mock import patch

import archives
import monitor


class MultiDatabaseTests(unittest.TestCase):
    def tearDown(self):
        monitor.configure('CBSETL')

    def test_profiles_isolate_paths_hosts_and_names(self):
        for sid, host, name, remote in (
            ('CBSETL', 'cbs-prod-db', '1_42_123.dbf', '/oradata/backup/CBSETL_seed'),
            ('CAPETL', 'cap-prod-db', '42_1_123.arc', '/oradata/backup/CAPETL_seed'),
            ('DWH', 'dwh-prod-db', '1_42_123.dbf', '/oradata/archive'),
        ):
            monitor.configure(sid)
            self.assertEqual(monitor.STATE.as_posix(), f'/var/lib/db-inv-oracle/{sid}/state-v3.json')
            self.assertEqual(monitor.MANIFEST.parent, monitor.STATE.parent)
            self.assertEqual(archives.archive_name(42, 123), name)
            self.assertEqual(archives.REMOTE, remote)
            self.assertEqual(archives.SSH[-1], 'oracle@' + host)
            self.assertEqual(archives.LOCAL.name, sid + '_seed')

    def test_unknown_sid_rejected(self):
        with self.assertRaises(ValueError):
            monitor.configure('CBSETL; echo unsafe')

    def test_unpinned_run_cannot_execute(self):
        with patch('sys.argv', ['monitor.py', 'run', '--sid', 'CAPETL']), patch.object(monitor, 'cycle') as cycle:
            with self.assertRaises(SystemExit) as error:
                monitor.main()
            self.assertEqual(error.exception.code, 2)
            cycle.assert_not_called()

    def test_primary_sql_targets_selected_sid(self):
        monitor.configure('DWH')
        with patch.object(monitor.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{}'
            monitor.sql_output('SELECT', True)
            command = run.call_args.args[0]
            self.assertIn('oracle@dwh-prod-db', command)
            self.assertIn('ORACLE_SID=DWH;', command[-1])

    def test_default_read_path_tracks_selected_database(self):
        monitor.configure('CAPETL')
        with patch.object(Path, 'read_text', autospec=True, return_value='{}') as read:
            monitor.load()
            self.assertEqual(read.call_args.args[0], monitor.STATE)

    def test_sql_failure_reports_ssh_and_oracle_diagnostics(self):
        monitor.configure('CAPETL')
        for rc, stdout, stderr, expected in (
            (255, '', 'Permission denied (publickey).', 'Permission denied'),
            (1, 'ORA-01034: ORACLE not available', '', 'ORA-01034'),
            (0, 'SP2-0640: Not connected', '', 'SP2-0640'),
        ):
            with self.subTest(expected=expected), patch.object(monitor.subprocess, 'run') as run:
                run.return_value.returncode = rc
                run.return_value.stdout = stdout
                run.return_value.stderr = stderr
                with self.assertRaises(ValueError) as error:
                    monitor.sql_output('SELECT', True)
                self.assertIn(expected, str(error.exception))
                self.assertIn('cap-prod-db', str(error.exception))
                self.assertIn('SID=CAPETL', str(error.exception))

    def test_sql_diagnostics_are_bounded(self):
        with patch.object(monitor.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stdout = 'x' * 10000
            run.return_value.stderr = ''
            with self.assertRaises(ValueError) as error:
                monitor.sql_output('SELECT')
            self.assertLess(len(str(error.exception)), 2100)

    def test_templates_match_portal_and_have_unique_ids(self):
        base = Path(__file__).parent
        templates = json.loads((base / 'zabbix-template-8.0.json').read_text())['zabbix_export']['templates']
        pairs = json.loads((base / 'replication.json').read_text())['pairs']
        keys = set()
        uuids = []
        for template in templates:
            uuids.append(template['uuid'])
            local = {i['key'] for i in template['items']}
            self.assertTrue(keys.isdisjoint(local))
            keys.update(local)
            for item in template['items']:
                uuids.append(item['uuid'])
                if 'master_item' in item:
                    self.assertIn(item['master_item']['key'], local)
                for trigger in item.get('triggers', []):
                    uuids.append(trigger['uuid'])
                    self.assertIn('/' + template['template'] + '/', trigger['expression'])
        self.assertEqual(len(uuids), len(set(uuids)))
        for pair in pairs:
            self.assertEqual(len(pair['metrics']), 8)
            for metric in pair['metrics'].values():
                self.assertIn(metric['key'], keys)


if __name__ == '__main__':
    unittest.main()
