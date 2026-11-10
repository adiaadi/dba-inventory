import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.services import replication as r
from app.services.zabbix import ZabbixApiError, ZabbixClient


def sample(engine="oracle"):
    return next(p for p in r.read_config("config/replication.example.json").pairs if p.engine == engine)


def good_items(pair, now=10000):
    items = {}
    for key, mapping in pair.metrics.items():
        healthy = r.METRICS[pair.engine][key][4]
        value = sorted(healthy)[0] if healthy else "0"
        if key == "patroni_nodes":
            value = str(pair.expected_patroni_nodes)
        items[mapping.itemid] = {"itemid": mapping.itemid, "lastvalue": value, "lastclock": str(now), "state": "0", "status": "0", "value_type": "1" if healthy else "3"}
    return items


class ReplicationTests(unittest.TestCase):
    def test_optional_transfer_statistics(self):
        import json
        pair = sample()
        pair.metrics['transfer_stats'] = r.ItemMapping(itemid='99998')
        items = good_items(sample())
        stats = dict(bytes_received=1024, duration_seconds=2, attempts=1, completed_at=10000)
        items['99998'] = dict(status='0', state='0', lastclock='10000', lastvalue=json.dumps(stats))
        result = r.build_pair(pair, items, 10000)
        self.assertEqual(result['transfer_stats']['bytes_per_second'], 512)
        self.assertEqual(result['status'], 'healthy')
        for change in ({'duration_seconds':0}, {'bytes_received':-1}, {'completed_at':1}):
            items['99998']['lastvalue'] = json.dumps(dict(stats, **change))
            self.assertIsNone(r.build_pair(pair, items, 10000)['transfer_stats'])
        items['99998']['lastvalue'] = 'null'
        self.assertIsNone(r.build_pair(pair, items, 10000)['transfer_stats'])

    def test_optional_archive_file_metadata(self):
        import json
        pair = sample()
        pair.metrics['archive_file'] = r.ItemMapping(itemid='99999')
        items = good_items(sample())
        items['99999'] = dict(status='0', state='0', lastclock='10000',
            lastvalue=json.dumps({'name':'16756_1_1204738459.arc','size_bytes':31268352}))
        result = r.build_pair(pair, items, 10000)
        self.assertEqual(result['status'], 'healthy')
        self.assertEqual(result['archive_file']['size_bytes'], 31268352)
        for value in ('null', '{}', '{"name":"../bad","size_bytes":1}'):
            items['99999']['lastvalue'] = value
            self.assertIsNone(r.build_pair(pair, items, 10000)['archive_file'])
        items['99999']['lastvalue'] = json.dumps({'name':'1_42_123.dbf','size_bytes':7})
        items['99999']['lastclock'] = '1'
        self.assertIsNone(r.build_pair(pair, items, 10000)['archive_file'])

    def test_all_engines_healthy(self):
        for engine in r.METRICS:
            p = sample(engine)
            self.assertEqual(r.build_pair(p, good_items(p), 10000)["status"], "healthy")

    def test_warning_gap_and_failed_apply(self):
        p = sample()
        items = good_items(p)
        items[p.metrics["archive_gap"].itemid]["lastvalue"] = "3"
        self.assertEqual(r.build_pair(p, items, 10000)["status"], "warning")
        items[p.metrics["apply_job"].itemid]["lastvalue"] = "1"
        del items[p.metrics["copied_seq"].itemid]
        self.assertEqual(r.build_pair(p, items, 10000)["status"], "critical")

    def test_sql_minutes_and_restore_failure(self):
        p = sample("sqlserver")
        items = good_items(p)
        items[p.metrics["restore_age"].itemid]["lastvalue"] = "42"
        result = r.build_pair(p, items, 10000)
        metric = next(m for m in result["metrics"] if m["key"] == "restore_age")
        self.assertEqual(metric["value"], 2520)
        self.assertEqual(result["status"], "warning")
        items[p.metrics["restore_job"].itemid]["lastvalue"] = "0"
        self.assertEqual(r.build_pair(p, items, 10000)["status"], "critical")

    def test_patroni_missing_node(self):
        p = sample("postgresql")
        items = good_items(p)
        items[p.metrics["patroni_nodes"].itemid]["lastvalue"] = "2"
        self.assertEqual(r.build_pair(p, items, 10000)["status"], "critical")

    def test_missing_disabled_unsupported_invalid_stale(self):
        p = sample()
        key = p.metrics["archive_gap"].itemid
        cases = [({"state": "1"}, "unknown"), ({"status": "1"}, "unknown"), ({"lastvalue": "NaN"}, "unknown"), ({"lastvalue": "-1"}, "unknown"), ({"lastvalue": "null"}, "unknown"), ({"lastclock": "0"}, "unknown"), ({"lastclock": "11000"}, "unknown"), ({"lastclock": "9000"}, "stale")]
        for change, expected in cases:
            with self.subTest(change=change):
                items = good_items(p)
                items[key].update(change)
                self.assertEqual(r.build_pair(p, items, 10000)["status"], expected)
        self.assertEqual(r.build_pair(p, {}, 10000)["status"], "unknown")

    def test_unknown_job_is_not_healthy(self):
        p = sample()
        items = good_items(p)
        items[p.metrics["apply_job"].itemid]["lastvalue"] = "42"
        self.assertEqual(r.build_pair(p, items, 10000)["status"], "unknown")

    def test_exact_threshold(self):
        p = sample("postgresql")
        items = good_items(p)
        items[p.metrics["replay_lag"].itemid]["lastvalue"] = "60"
        self.assertEqual(r.build_pair(p, items, 10000)["status"], "critical")

    def test_config_validation(self):
        data = sample().model_dump()
        data["metrics"]["archive_gap"]["warning"] = 11
        with self.assertRaises(ValidationError):
            r.ReplicationPair.model_validate(data)
        with self.assertRaises(ValidationError):
            r.ReplicationConfig(pairs=[sample(), sample()])
        with self.assertRaises(ValidationError):
            r.ItemMapping(itemid="not-an-id")
        self.assertEqual(r.read_config("").pairs, [])

    def setUp(self):
        r._cached = None
        r._cached_at = 0

    def test_snapshot_cache_batch_history_and_factor(self):
        p = sample("sqlserver")
        client = Mock()
        client.get_replication_items.return_value = list(good_items(p).values())
        client.get_replication_history.return_value = [{"itemid": p.metrics["restore_age"].itemid, "clock": "9999", "value": "2"}]
        settings = Mock(replication_config_file="config", zabbix_url="https://example.test", zabbix_api_token="secret", zabbix_verify_ssl=True, zabbix_ca_file=None)
        with patch.object(r, "get_settings", return_value=settings), patch.object(r, "read_config", return_value=r.ReplicationConfig(pairs=[p])), patch.object(r, "ZabbixClient", return_value=client), patch.object(r.time, "time", return_value=10000):
            first = r.get_snapshot()
            second = r.get_snapshot()
        self.assertIs(first, second)
        client.get_replication_items.assert_called_once()
        client.get_replication_history.assert_called_once()
        self.assertEqual(first["pairs"][0]["trend"], [{"clock": 9999, "value": 120}])

    def test_zabbix_failure_does_not_show_healthy_or_leak_error(self):
        settings = Mock(replication_config_file="config", zabbix_url="https://example.test", zabbix_api_token="secret", zabbix_verify_ssl=True, zabbix_ca_file=None)
        with patch.object(r, "get_settings", return_value=settings), patch.object(r, "read_config", return_value=r.ReplicationConfig(pairs=[sample()])), patch.object(r, "ZabbixClient", side_effect=ZabbixApiError("sensitive upstream error")), self.assertLogs(r.log, level="ERROR"):
            result = r.get_snapshot()
        self.assertEqual(result["pairs"][0]["status"], "unknown")
        self.assertNotIn("sensitive", str(result))

    def test_api_parameters(self):
        client = ZabbixClient("https://example.test", "secret")
        with patch.object(client, "_call", return_value=[]) as call:
            client.get_replication_items(["1"])
            self.assertTrue(call.call_args.args[1]["monitored"])
            self.assertIn("lastclock", call.call_args.args[1]["output"])
            client.get_replication_history(["1"], "3", 100, 200)
            self.assertEqual(call.call_args.args[1]["sortorder"], "DESC")

    def test_key_mapping_validation(self):
        for data in ({}, {"itemid": "1", "key": "metric"}):
            with self.assertRaises(ValidationError):
                r.ItemMapping(**data)
        data = sample().model_dump()
        data["metrics"]["archive_gap"] = {"key": "gap"}
        with self.assertRaises(ValidationError):
            r.ReplicationPair.model_validate(data)

    def test_key_resolution_and_missing_item(self):
        config = r.read_config("config/replication.cbsetl.json")
        client = Mock()
        client.get_replication_items_by_keys.return_value = [
            {"itemid": "42", "key_": "db.replication.oracle.archive_gap", "lastvalue": "3",
             "lastclock": "10000", "status": "0", "state": "0", "value_type": "3"}
        ]
        resolved, items = r.resolve_items(config, client)
        self.assertIsNone(config.pairs[0].metrics["archive_gap"].itemid)
        self.assertEqual(resolved.pairs[0].metrics["archive_gap"].itemid, "42")
        result = r.build_pair(resolved.pairs[0], items, 10000)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(next(m for m in result["metrics"] if m["key"] == "archive_gap")["status"], "warning")
        self.assertEqual(client.get_replication_items_by_keys.call_args.args[0], "ora-dr-db")
        client.get_replication_items.assert_not_called()

    def test_key_api_scopes_exact_keys_to_host(self):
        client = ZabbixClient("https://example.test", "secret")
        with patch.object(client, "_call", side_effect=[[{"hostid": "17"}], []]) as call:
            client.get_replication_items_by_keys("ora-dr-db", ["exact.key"])
            self.assertEqual(call.call_args_list[0].args[1]["filter"], {"host": ["ora-dr-db"]})
            self.assertEqual(call.call_args.args[1]["hostids"], ["17"])
            self.assertEqual(call.call_args.args[1]["filter"], {"key_": ["exact.key"]})
        with patch.object(client, "_call", return_value=[]) as call:
            self.assertEqual(client.get_replication_items_by_keys("missing", ["key"]), [])
            call.assert_called_once()

    def test_key_snapshot_history_uses_resolved_id(self):
        config = r.read_config("config/replication.cbsetl.json")
        client = Mock()
        client.get_replication_items_by_keys.return_value = [{
            "itemid": "42", "key_": "db.replication.oracle.archive_gap", "lastvalue": "0",
            "lastclock": "10000", "state": "0", "status": "0", "value_type": "3"}]
        client.get_replication_history.return_value = [{"itemid": "42", "clock": "9999", "value": "2"}]
        settings = Mock(replication_config_file="config", zabbix_url="https://example.test", zabbix_api_token="secret", zabbix_verify_ssl=True, zabbix_ca_file=None)
        with patch.object(r, "get_settings", return_value=settings), patch.object(r, "read_config", return_value=config), patch.object(r, "ZabbixClient", return_value=client), patch.object(r.time, "time", return_value=10000):
            result = r.get_snapshot()
        client.get_replication_history.assert_called_once_with(["42"], "3", 6400, 10000)
        self.assertEqual(result["pairs"][0]["trend"], [{"clock": 9999, "value": 2}])


class RouteTests(unittest.TestCase):
    def test_session_protection_page_and_api(self):
        from app.main import app
        from app.core.config import get_settings
        from itsdangerous import TimestampSigner
        import base64
        import json
        settings = get_settings()
        with patch("app.main.load_request_ui_texts", return_value={}), TestClient(app) as client:
            for path in ("/replication", "/replication/api"):
                self.assertEqual(client.get(path, follow_redirects=False).status_code, 303)
            cookie = TimestampSigner(settings.session_secret).sign(base64.b64encode(json.dumps({"portal_user": settings.portal_username}).encode())).decode()
            client.cookies.set("session", cookie)
            response = client.get("/replication")
            self.assertEqual(response.status_code, 200)
            self.assertIn("replication.js", response.text)
            with patch("app.routers.replication.get_snapshot", return_value={"pairs": [], "error": None}):
                response = client.get("/replication/api")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["pairs"], [])
                self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
