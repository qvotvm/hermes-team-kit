"""Exercise profile generation in an isolated local tree, no network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'install').mkdir()
        for name in ('install/setup.py', 'kit_config.py'):
            shutil.copyfile(ROOT / name, self.root / name)
        shutil.copytree(ROOT / 'profiles', self.root / 'profiles')
        self.env = {**os.environ, 'HERMES_HOME': str(self.root / 'home'),
                    'MODEL_API_KEY': 'model-test-value',
                    'TELEGRAM_BOT_TOKEN': 'bot-test-value', 'HEY_SECRET': 'unrelated-test-value'}
        self.base = ('[paths]\ngate="var/gate"\nout="var/out"\nwork="var/work"\n'
                     'keys="var/keys"\nledger="var/ledger.jsonl"\n'
                     '[hermes]\ncommand=' + json.dumps(sys.executable) + '\n'
                     '[telegram]\nowner_ids=[42]\n'
                     '[provider]\nbase_url="https://example.com/v1"\n'
                     'api_key_env="MODEL_API_KEY"\nmodel="example"\n')
        self.baseline = (json.dumps({
            'model': {'provider': 'primary', 'default': 'example'},
            'custom_providers': [{'name': 'primary', 'base_url': 'https://example.com/v1',
                                  'key_env': 'MODEL_API_KEY', 'model': 'example'}]}, indent=2) + '\n').encode()

    def run_setup(self, section=''):
        path = self.root / 'config.toml'
        path.write_text(self.base + section)
        result = subprocess.run([sys.executable, str(self.root / 'install/setup.py'),
                                 '--config', str(path)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return {p.parent.name: p.read_bytes() for p in (self.root / 'home/profiles').glob('*/config.yaml')}

    def hey(self, integration=''):
        return ('[mcp.hey]\nenabled=true\nurl="https://heyresearch.xyz/mcp/research"\n'
                'profiles=["scout", "reviewer"]\nintegration=' + json.dumps(integration) + '\n')

    def test_absent_and_disabled_configs_are_byte_identical_to_baseline(self):
        absent = self.run_setup()
        self.assertEqual(len(absent), 10)
        self.assertTrue(all(value == self.baseline for value in absent.values()))
        disabled = self.run_setup('[mcp.hey]\nenabled=false\nurl="ignored"\n'
                                  'integration="ignored value"\nprofiles=["missing"]\n')
        self.assertEqual(disabled, absent)

    def test_only_selected_profiles_receive_exact_server_settings(self):
        for integration in ('', 'acme-desk', 'acme-desk/1.0', 'a' * 40 + '/1.2.3'):
            with self.subTest(integration=integration):
                generated = self.run_setup(self.hey(integration) +
                    'timeout=999\napi_key="unrelated-test-value"\n'
                    '[mcp.hey.env]\nHEY_SECRET="unrelated-test-value"\n')
                server = {'url': 'https://heyresearch.xyz/mcp/research',
                          'timeout': 60, 'connect_timeout': 15}
                if integration:
                    server['headers'] = {'x-hey-integration': integration}
                for profile, value in generated.items():
                    expected = json.loads(self.baseline)
                    if profile in ('scout', 'reviewer'):
                        expected['mcp_servers'] = {'hey': server}
                    self.assertEqual(json.loads(value), expected)
                    self.assertEqual((self.root / 'home/profiles' / profile / '.env').read_text(),
                                     'MODEL_API_KEY=model-test-value\n')

    def test_enabled_example_config_credits_kit_for_selected_profiles(self):
        self.base = (ROOT / 'config.example.toml').read_text().replace(
            'command = "hermes"', 'command = ' + json.dumps(sys.executable))
        configured = tomllib.loads(self.base)['mcp']['hey']
        self.assertIs(configured['enabled'], True)
        self.assertIn('researcher', configured['profiles'])
        self.assertEqual(configured['url'], 'https://heyresearch.xyz/mcp/research')
        generated = self.run_setup()
        self.assertEqual(len(generated), 10)
        self.assertTrue(set(configured['profiles']).issubset(generated))
        for profile, value in generated.items():
            settings = json.loads(value)
            if profile in configured['profiles']:
                self.assertEqual(settings['mcp_servers']['hey'], {
                    'url': configured['url'], 'timeout': 60, 'connect_timeout': 15,
                    'headers': {'x-hey-integration': 'quotum/1.0'}})
            else:
                self.assertNotIn('mcp_servers', settings)

    def test_managed_configs_refresh_and_manual_edits_are_preserved(self):
        self.run_setup()
        path = self.root / 'home/profiles/reviewer/config.yaml'
        customized = path.read_bytes() + b'\n'
        path.write_bytes(customized)
        generated = self.run_setup(self.hey('acme-desk/1.0'))
        self.assertEqual(generated['reviewer'], customized)
        self.assertIn('mcp_servers', json.loads(generated['scout']))
        self.assertEqual(json.loads(generated['scout'])['mcp_servers']['hey']['headers'],
                         {'x-hey-integration': 'acme-desk/1.0'})
        generated = self.run_setup(self.hey())
        self.assertNotIn('headers', json.loads(generated['scout'])['mcp_servers']['hey'])
        self.assertEqual(generated['reviewer'], customized)
        generated = self.run_setup('[mcp.hey]\nenabled=false\n')
        self.assertEqual(generated['reviewer'], customized)
        self.assertEqual(generated['scout'], self.baseline)


# Exact policy asserted independently of the generator's constant.
PRIORS_ALLOWED = [
    'agent_record', 'score_of', 'credit_history', 'pool_stats', 'recent_activity',
    'desk_record', 'find_agent_by_x', 'agent_page', 'find_agents', 'find_services',
    'find_sellers', 'facilitator_info', 'how_to_connect', 'stock_assets',
]
PRIORS_EXCLUDED = {
    'pt_buy', 'pt_sell', 'pt_redeem', 'request_borrow', 'request_repay', 'line_offer',
    'stock_line_request', 'priors_line_quote', 'pt_quote', 'line_request',
    'find_line_requests', 'line_options', 'job_brief', 'find_jobs', 'agents_for_hire',
    'stock_position', 'pt_position',
}


def saved_mcp_reply(text):
    """Accept a plain JSON reply or an SSE message's data lines."""
    if text.lstrip().startswith('{'):
        return json.loads(text)
    return json.loads('\n'.join(line[5:].lstrip() for line in text.splitlines()
                                if line.startswith('data:')))


class PriorsSetupTest(unittest.TestCase):
    setUp = SetupTest.setUp
    run_setup = SetupTest.run_setup

    def priors(self, extra='', profiles='["researcher"]'):
        return ('[mcp.priors]\nenabled=true\nurl="https://mcp.priors.trade/mcp"\n'
                'profiles=' + profiles + '\n' + extra)

    def test_priors_absent_and_disabled_are_identical(self):
        absent = self.run_setup()
        disabled = self.run_setup('[mcp.priors]\nenabled=false\nurl="ignored"\n'
                                  'profiles=["missing"]\n')
        self.assertEqual(absent, disabled)
        self.assertTrue(all(value == self.baseline for value in absent.values()))

    def test_priors_example_off_and_enabled_with_hey(self):
        self.base = (ROOT / 'config.example.toml').read_text().replace(
            'command = "hermes"', 'command = ' + json.dumps(sys.executable))
        configured = tomllib.loads(self.base)['mcp']['priors']
        self.assertIs(configured['enabled'], False)
        self.assertEqual(configured['profiles'], ['researcher'])
        off = self.run_setup()
        self.assertTrue(all('priors' not in json.loads(value).get('mcp_servers', {})
                            for value in off.values()))
        self.base = self.base.replace('[mcp.priors]\nenabled = false',
                                      '[mcp.priors]\nenabled = true')
        on = self.run_setup()
        for profile, value in on.items():
            actual = json.loads(value)
            previous = json.loads(off[profile])
            if profile == 'researcher':
                server = actual['mcp_servers'].pop('priors')
                self.assertEqual(server, {
                    'url': 'https://mcp.priors.trade/mcp', 'timeout': 60,
                    'connect_timeout': 15, 'tools': {'include': PRIORS_ALLOWED}})
                self.assertTrue(PRIORS_EXCLUDED.isdisjoint(server['tools']['include']))
            self.assertEqual(actual, previous)

    def test_priors_only_selected_profiles_and_no_credentials_or_overrides(self):
        generated = self.run_setup(self.priors(
            'timeout=999\napi_key="unrelated-test-value"\n'
            '[mcp.priors.tools]\ninclude=["pt_buy"]\n'
            '[mcp.priors.env]\nHEY_SECRET="unrelated-test-value"\n',
            '["researcher", "verifier"]'))
        for profile, value in generated.items():
            expected = json.loads(self.baseline)
            if profile in ('researcher', 'verifier'):
                expected['mcp_servers'] = {'priors': {
                    'url': 'https://mcp.priors.trade/mcp', 'timeout': 60,
                    'connect_timeout': 15, 'tools': {'include': PRIORS_ALLOWED}}}
            self.assertEqual(json.loads(value), expected)
            self.assertEqual((self.root / 'home/profiles' / profile / '.env').read_text(),
                             'MODEL_API_KEY=model-test-value\n')

    def test_priors_enabled_without_profiles_defaults_to_researcher(self):
        generated = self.run_setup('[mcp.priors]\nenabled=true\n'
                                   'url="https://mcp.priors.trade/mcp"\n')
        for profile, value in generated.items():
            self.assertEqual('priors' in json.loads(value).get('mcp_servers', {}),
                             profile == 'researcher')

    def test_priors_disable_refreshes_managed_and_preserves_manual_configs(self):
        self.run_setup(self.priors(profiles='["researcher", "verifier"]'))
        path = self.root / 'home/profiles/verifier/config.yaml'
        customized = path.read_bytes() + b'\n'
        path.write_bytes(customized)
        generated = self.run_setup('[mcp.priors]\nenabled=false\n')
        self.assertEqual(generated['verifier'], customized)
        self.assertEqual(generated['researcher'], self.baseline)

    def test_priors_allowlist_exists_in_saved_json_and_sse_tools_list(self):
        fixture = (ROOT / 'tests/fixtures/priors/tools.json').read_text()
        for reply in (fixture, 'event: message\ndata: ' + fixture + '\n\n'):
            with self.subTest(sse=reply.startswith('event:')):
                tools = saved_mcp_reply(reply)['result']['tools']
                names = {tool['name'] for tool in tools}
                self.assertEqual(len(tools), 31)
                self.assertEqual(len(names), 31)
                self.assertEqual(names, set(PRIORS_ALLOWED) | PRIORS_EXCLUDED)
                allowed = {tool['name'] for tool in tools
                           if tool['name'] in PRIORS_ALLOWED}
                self.assertEqual(allowed, set(PRIORS_ALLOWED))
                for tool in tools:
                    if tool['name'] in allowed:
                        self.assertIs(tool['annotations']['readOnlyHint'], True)
        initialized = saved_mcp_reply(
            (ROOT / 'tests/fixtures/priors/init.txt').read_text())
        self.assertEqual(initialized['result']['serverInfo'],
                         {'name': 'priors-read', 'version': '0.3.0'})
