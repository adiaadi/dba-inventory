import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import monitor
import transfer_metrics as t


class TransferMetricsTests(unittest.TestCase):
    def test_idle_cycles_keep_last_real_copy(self):
        measured = dict(bytes_received=1000, duration_seconds=4, bytes_per_second=250,
                        attempts=1, completed_at=100)
        current, last = monitor.retain_last_copy(measured, None)
        idle = dict(bytes_received=0, duration_seconds=0, bytes_per_second=None,
                    attempts=0, completed_at=200)
        current, last = monitor.retain_last_copy(idle, last)
        self.assertEqual(current['attempts'], 0)
        self.assertEqual(current['last_copy']['bytes_per_second'], 250)
        self.assertEqual(current['last_copy']['completed_at'], 100)
        current, last = monitor.retain_last_copy(None, last)
        self.assertIsNone(current)
        self.assertEqual(last['completed_at'], 100)

    def test_rsync_receive_counter_and_elapsed_time(self):
        run = Mock(return_value=SimpleNamespace(returncode=0,
            stdout='Total bytes received: 31,268,352\n', stderr=''))
        with contextlib.redirect_stdout(io.StringIO()):
            rc, count, seconds = t.measure(['-a', 'source', 'target'], run, iter([10.0, 12.5]).__next__)
        self.assertEqual((rc, count, seconds), (0, 31268352, 2.5))
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')
        self.assertEqual(run.call_args.args[0][:2], ['rsync', '--stats'])

    def test_missing_or_ambiguous_statistics_are_unknown(self):
        self.assertIsNone(t.received_bytes('rsync failed'))
        self.assertIsNone(t.received_bytes('Total bytes received: 1\nTotal bytes received: 2\n'))

    def test_average_uses_total_time_and_bytes(self):
        data = t.finish(dict(duration_seconds=4, bytes_received=1000, attempts=2, valid=True))
        self.assertEqual(data['bytes_per_second'], 250)
        self.assertTrue(data['complete'])

    def test_idle_cycle_does_not_invent_rate(self):
        data = t.finish(dict(duration_seconds=0, bytes_received=0, attempts=0, valid=True))
        self.assertIsNone(data['bytes_per_second'])

    def test_old_failed_or_incomplete_report_is_not_reused(self):
        for report in ({}, dict(complete=True, valid=True, started_at=90),
                       dict(complete=True, valid=False, started_at=110)):
            with patch.object(monitor, 'load', return_value=report):
                self.assertIsNone(monitor.transfer_report(100))

    def test_valid_report(self):
        report = dict(complete=True, valid=True, started_at=100, completed_at=104,
                      bytes_received=1000, duration_seconds=4, attempts=1, bytes_per_second=250)
        with patch.object(monitor, 'load', return_value=report):
            self.assertEqual(monitor.transfer_report(100)['duration_seconds'], 4)
