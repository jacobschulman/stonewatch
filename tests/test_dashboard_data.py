import csv
import json
import os
import subprocess
import textwrap
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import run_history
from scripts.publish_availability import FIELDS, publish


class DashboardDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous = os.getcwd()
        os.chdir(self.directory.name)
        run_history._active.clear()

    def tearDown(self):
        run_history._active.clear()
        os.chdir(self.previous)
        self.directory.cleanup()

    def test_run_history_is_bounded_and_keeps_counts(self):
        for index in range(run_history.MAX_RUNS + 1):
            run_id = run_history.create({'run_type': 'base', 'config': {'party_sizes': [2, 4]}})
            for _ in range(55):
                run_history.event(run_id, action='SUPPRESSED', slot_key='sample')
            run_history.event(run_id, action='NOTIFIED', slot_key='notification')
            run_history.complete(run_id, status='success', notifications_sent=1, slots_suppressed=55)
        history = json.loads(Path('dashboard/base-runs.json').read_text())
        self.assertEqual(len(history['runs']), 200)
        self.assertEqual(history['runs'][0]['id'], run_id)
        for run in history['runs']:
            self.assertEqual(run['status'], 'success')
            self.assertEqual(run['total_events'], 56)
            self.assertEqual(len(run['events']), 50)
            self.assertTrue(any(event['action'] == 'NOTIFIED' for event in run['events']))

    def test_incomplete_run_is_recorded_as_error(self):
        run_history.create({'run_type': 'vip'})
        run_history.record_interrupted_runs()
        history = json.loads(Path('dashboard/vip-runs.json').read_text())
        self.assertEqual(history['runs'][0]['status'], 'error')
        self.assertIsNotNone(history['runs'][0]['completed_at'])

    def write_buffer(self, rows):
        path = Path('availability_log.csv')
        with path.open('w', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({**dict.fromkeys(FIELDS, ''), **row})

    def test_monthly_updates_preserve_history_and_do_not_rewrite_untouched_months(self):
        january = dict(slot_at_iso='2026-02-01T02:00:00Z', seen_at_iso='2026-01-30T12:00:00Z', party_size='2', service='Dinner', merchant_id='278278', lead_hours='38')
        february = {**january, 'slot_at_iso': '2026-02-02T22:00:00Z', 'seen_at_iso': '2026-02-01T12:00:00Z'}
        self.write_buffer([january, february])
        self.assertEqual(publish(), (2, 2, 2))
        self.assertFalse(Path('availability_log.csv').exists())
        # UTC February 1 is January 31 in New York, so it belongs to January.
        january_path = Path('data/availability/2026-01.csv')
        before = january_path.read_bytes(), january_path.stat().st_mtime_ns
        self.write_buffer([{**february, 'seen_at_iso': '2026-02-02T12:00:00Z', 'lead_hours': '10'}, {**february, 'party_size': '4'}])
        self.assertEqual(publish(), (2, 1, 3))
        self.assertEqual(before, (january_path.read_bytes(), january_path.stat().st_mtime_ns))
        with Path('data/availability/2026-02.csv').open() as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(rows[0]['seen_at_iso'], february['seen_at_iso'])
        manifest = Path('data/availability/index.json').read_bytes()
        self.write_buffer([february])
        self.assertEqual(publish(), (1, 0, 3))
        self.assertEqual(Path('data/availability/index.json').read_bytes(), manifest)

    def test_monthly_manifest_tracks_corrected_first_sightings_and_rejects_bad_input(self):
        slot = dict(slot_at_iso='2026-02-01T22:00:00Z', seen_at_iso='2026-02-01T12:00:00Z', party_size='2', service='Dinner', merchant_id='278278')
        self.write_buffer([slot])
        publish()
        self.write_buffer([{**slot, 'seen_at_iso': '2026-01-31T12:00:00Z'}])
        publish()
        path = Path('data/availability/index.json')
        self.assertEqual(json.loads(path.read_text())['months'][0]['last_seen'], '2026-01-31T12:00:00+00:00')
        before = path.read_bytes()
        self.write_buffer([{**slot, 'slot_at_iso': 'invalid'}])
        with self.assertRaises(ValueError):
            publish()
        self.assertEqual(before, path.read_bytes())
        self.assertTrue(Path('availability_log.csv').exists())

    def test_watcher_logging_flows_publish_without_database_or_notifications(self):
        # Exercise the actual logging wrappers without invoking the monitoring loops.
        with patch.dict('sys.modules', {'requests': Mock()}):
            import watcher
            import vip_watcher
        from datetime import datetime
        run_id = watcher.create_run_record()
        watcher.log_slot_event(datetime.fromisoformat('2026-09-28T18:00:00-04:00'),
                               datetime.fromisoformat('2026-09-28T12:00:00+00:00'), 'Dinner', 2)
        watcher.log_run_event(run_id, 'sample', '2026-09-28T18:00:00-04:00', 'Dinner', 2, 0, 'SUPPRESSED', 'COOLDOWN')
        watcher.complete_run_record(run_id, slots_checked=1, slots_suppressed=1)
        self.assertEqual(publish(), (1, 1, 1))
        history = json.loads(Path('dashboard/base-runs.json').read_text())
        self.assertEqual(history['runs'][0]['events'][0]['action'], 'SUPPRESSED')
        vip_id = vip_watcher.create_run_record()
        vip_watcher.complete_run_record(vip_id, api_calls_made=1)
        history = json.loads(Path('dashboard/vip-runs.json').read_text())
        self.assertEqual(history['runs'][0]['api_calls_made'], 1)

    def test_workflows_fail_after_three_rejected_uploads(self):
        root = Path(__file__).resolve().parents[1]
        Path('data/availability').mkdir(parents=True)
        Path('data/availability/index.json').write_text('{}')
        bin_dir = Path('bin').resolve()
        bin_dir.mkdir()
        fake_git = bin_dir / 'git'
        fake_git.write_text('#!/bin/sh\necho "$1" >> "$TEST_GIT_LOG"\ncase "$1" in push|diff) exit 1;; esac\nexit 0\n')
        fake_git.chmod(0o755)
        for name in ['hillstone-nyc.yml', 'vip-watcher.yml']:
            workflow = (root / '.github/workflows' / name).read_text()
            script = textwrap.dedent(workflow.split('        run: |\n')[-1])
            log = Path(name + '.log').resolve()
            result = subprocess.run(['bash', '-e', '-c', script], capture_output=True, text=True,
                                    env={**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'TEST_GIT_LOG': str(log)})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('::error::', result.stdout)
            self.assertEqual(log.read_text().splitlines().count('push'), 3)


if __name__ == '__main__':
    unittest.main()
