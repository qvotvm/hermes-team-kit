"""Exercise profile generation in an isolated local tree, no network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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
