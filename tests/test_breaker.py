from pathlib import Path
import tempfile
import unittest
from breaker import evaluate, enforce, trip, reset_manual, update, control_lock
from ledger import append


class BreakerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'ledger.jsonl'
        self.config = {'paths': {'ledger': str(self.path), 'out': str(Path(self.tmp.name) / 'out')}, 'telegram': {'owner_ids': [42]}, 'limits': {'breaker_threshold': .8},
                       'seats': {'A': {'profiles': ['builder'], 'daily_cap_usd': 10}}}

    def spend(self, dollars):
        append(self.path, {'type': 'finished', 'event_id': str(dollars), 'card_id': 'c', 'task_id': 't',
                           'profile': 'builder', 'model': 'example', 'provider': 'custom',
                           'dollars': dollars, 'duration': 1, 'group': 'A', 'ts': 100})

    def test_threshold_and_daily_resume(self):
        self.spend(7.99)
        self.assertFalse(evaluate(self.config, 200)['groups']['A']['paused'])
        self.spend(.01)
        self.assertTrue(evaluate(self.config, 200)['groups']['A']['paused'])
        self.assertFalse(evaluate(self.config, 86400)['groups']['A']['paused'])

    def test_endpoint_cap_overrides_config_and_falls_back_on_error(self):
        self.config['provider'] = {'usage_url': 'https://example.com/usage', 'api_key_env': 'TEST_KEY'}
        def fetch(url, key):
            return {'daily_cap_usd': 5, 'spent_usd': 4, 'reset_at': '1970-01-02T00:00:00Z'}
        row = evaluate(self.config, 200, fetch)['groups']['A']
        self.assertTrue(row['paused'])
        self.assertEqual(row['source'], 'endpoint')
        self.spend(8)
        def fail(*args):
            raise OSError('offline')
        row = evaluate(self.config, 200, fail)['groups']['A']
        self.assertTrue(row['paused'])
        self.assertEqual(row['source'], 'ledger-fallback')

    def test_stale_endpoint_reply_falls_back_to_ledger_figures(self):
        self.config['provider'] = {'usage_url': 'https://example.com/usage', 'api_key_env': 'TEST_KEY'}
        self.spend(9)
        def stale(url, key):
            return {'daily_cap_usd': 100, 'spent_usd': 0, 'reset_at': '1970-01-01T00:00:00Z'}
        row = evaluate(self.config, 200, stale)['groups']['A']
        self.assertEqual(row['source'], 'ledger-fallback')
        self.assertEqual((row['daily_cap_usd'], row['spent_usd']), (10, 9))
        self.assertTrue(row['paused'])

    def test_unknown_local_cost_pauses_capped_group(self):
        self.spend(None)
        self.assertTrue(evaluate(self.config, 200)['groups']['A']['paused'])

    def test_uncapped_key_does_not_need_usage(self):
        del self.config['seats']['A']['daily_cap_usd']
        self.assertFalse(evaluate(self.config, 200)['groups']['A']['paused'])

    def test_only_owned_scheduled_cards_resume_and_running_cards_finish(self):
        self.spend(8)
        cards = [{'id': 'c', 'assignee': 'builder', 'status': 'ready'},
                 {'id': 'live', 'assignee': 'builder', 'status': 'running'},
                 {'id': 'manual', 'assignee': 'builder', 'status': 'scheduled'}]
        calls = []
        def command(*args):
            import json
            calls.append(args)
            if args[0] == 'list':
                return json.dumps(cards)
            cards[0]['status'] = 'scheduled' if args[0] == 'schedule' else 'ready'
        path = Path(self.tmp.name) / 'held.json'
        enforce(evaluate(self.config, 200), command, path)
        enforce(evaluate(self.config, 86400), command, path)
        self.assertEqual([c for c in calls if c[0] != 'list'],
                         [('schedule', 'c', 'daily key budget breaker'), ('unblock', 'c')])

    def test_manual_stop_survives_daily_reset_and_owner_reset_is_logged(self):
        trip(self.config, 'builder', 'bad tool result', 150)
        self.assertTrue(update(self.config, 86400)['tripped'])
        with self.assertRaises(PermissionError):
            reset_manual(self.config, 99, 'try reset', 86401)
        with self.assertRaises(PermissionError):
            trip(self.config, 'outsider', 'try stop', 86401)
        reset_manual(self.config, 42, 'reviewed tools', 86402)
        self.assertFalse(evaluate(self.config, 86403)['tripped'])
        from ledger import events
        rows = list(events(self.path))
        self.assertEqual([(r['type'], r['by'], r['reason']) for r in rows],
                         [('breaker_stop', 'builder', 'bad tool result'),
                          ('breaker_reset', 42, 'reviewed tools')])

    def test_manual_stop_parks_ungrouped_ready_only(self):
        self.config['seats'] = {}
        trip(self.config, 'tester', 'check failed', 100)
        cards = [{'id': 'ready', 'assignee': 'writer', 'status': 'ready'},
                 {'id': 'live', 'assignee': 'writer', 'status': 'running'},
                 {'id': 'held', 'assignee': 'writer', 'status': 'scheduled'}]
        calls = []
        def command(*args):
            import json
            if args[0] == 'list':
                return json.dumps(cards)
            calls.append(args)
            cards[0]['status'] = 'scheduled' if args[0] == 'schedule' else 'ready'
        path = Path(self.tmp.name) / 'held.json'
        enforce(evaluate(self.config, 200), command, path)
        reset_manual(self.config, 42, 'safe again', 201)
        enforce(evaluate(self.config, 202), command, path)
        self.assertEqual(calls, [('schedule', 'ready', 'manual stop'), ('unblock', 'ready')])

    def test_hourly_window_across_groups_and_midnight(self):
        self.config['limits']['hourly_usd'] = 5
        self.spend(5)
        self.config['seats'] = {'other': {'profiles': ['writer']}}
        snapshot = evaluate(self.config, 3699)
        self.assertEqual(snapshot['reason'], 'hourly cap')
        self.assertTrue(snapshot['groups']['other']['paused'])
        self.assertFalse(evaluate(self.config, 3700)['tripped'])
        from ledger import events
        row = list(events(self.path))[0]
        row.update(event_id='midnight', ts=86399)
        append(self.path, row)
        self.assertTrue(evaluate(self.config, 86401)['tripped'])
        self.assertFalse(evaluate(self.config, 89999)['tripped'])

    def test_hourly_off_unknown_cost_and_manual_priority(self):
        self.spend(None)
        self.assertFalse(evaluate(self.config, 200)['tripped'])
        self.config['limits']['hourly_usd'] = 5
        self.assertEqual(evaluate(self.config, 200)['reason'], 'hourly cap')
        trip(self.config, 'analyst', 'review needed', 201)
        self.assertEqual(evaluate(self.config, 3700)['reason'], 'manual stop')
        reset_manual(self.config, 42, 'review complete', 3701)
        self.assertFalse(evaluate(self.config, 3702)['tripped'])

    def test_owner_reset_does_not_clear_daily_cap(self):
        self.spend(8)
        trip(self.config, 'builder', 'pause', 201)
        reset_manual(self.config, 42, 'continue', 202)
        self.assertTrue(evaluate(self.config, 203)['groups']['A']['paused'])

    def test_hourly_uses_ledger_even_with_daily_endpoint(self):
        self.config['limits']['hourly_usd'] = 5
        self.config['provider'] = {'usage_url': 'https://example.com/usage'}
        self.spend(5)
        result = evaluate(self.config, 200, lambda *args: {
            'daily_cap_usd': 100, 'spent_usd': 0, 'reset_at': '1970-01-02T00:00:00Z'})
        self.assertEqual(result['groups']['A']['source'], 'endpoint')
        self.assertEqual(result['reason'], 'hourly cap')

    def test_stop_requires_reason(self):
        with self.assertRaises(ValueError):
            trip(self.config, 'builder', ' ', 100)
        self.assertFalse(evaluate(self.config, 200)['tripped'])
