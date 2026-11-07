from pathlib import Path
import tempfile
import unittest
from kit_config import load, runtime_paths

class ConfigTest(unittest.TestCase):
    def config(self, text):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'config.toml'
        path.write_text(text)
        return path

    def test_paths_resolve_against_config_not_working_directory(self):
        path = self.config('[paths]\ngate="var/gate"\n')
        self.assertEqual(load(path)['paths']['gate'], str(path.resolve().parent / 'var/gate'))

    def test_duplicate_profile_and_key_groups_are_rejected(self):
        for text in ('[seats.A]\nprofiles=["builder"]\n[seats.B]\nprofiles=["builder"]\n',
                     '[seats.A]\nprofiles=["builder"]\napi_key_env="KEY"\n[seats.B]\nprofiles=["tester"]\napi_key_env="KEY"\n'):
            with self.assertRaises(ValueError):
                load(self.config(text))

    def test_invalid_locale_and_profile_are_rejected(self):
        for text in ('[telegram]\nlocale="xx"\n', '[seats.A]\nprofiles=["missing"]\n'):
            with self.assertRaises(ValueError):
                load(self.config(text))

    def test_invalid_hey_settings_are_rejected_when_enabled(self):
        for settings in ('url="http://example.com/mcp"', 'url="https:///mcp"',
                         'url=42', 'integration="Uppercase"', 'integration="has space"',
                         'integration="' + 'a' * 41 + '"', 'integration=42',
                         'profiles=["missing"]', 'profiles="reviewer"', 'profiles=[42]'):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                text = '[mcp.hey]\nenabled=true\n'
                if not settings.startswith('url='):
                    text += 'url="https://example.com/mcp"\n'
                load(self.config(text + settings + '\n'))

    def test_hey_integration_accepts_optional_version_and_allowed_characters(self):
        prefix = '[mcp.hey]\nenabled=true\nurl="https://example.com/mcp"\n'
        for value in ('', 'acme-desk', 'acme-desk/1.0', 'a/1.2.3', '0',
                      'a' * 40, 'a' * 40 + '/' + 'v' * 20,
                      'my_team.v2/1.0-beta_2', 'team/1', 'team/v1.0',
                      'team/1.2.3.4', 'team/1.', 'your-productivity',
                      'my-product-tools', 'my-agent-tools', 'hey'):
            with self.subTest(value=value):
                config = load(self.config(prefix + 'integration="' + value + '"\n'))
                self.assertEqual(config['mcp']['hey']['integration'], value)
        for value in ('/1.0', 'a' * 41, 'a' * 41 + '/1.0', 'Team/1.0',
                      'team/' + 'v' * 21, 'my team/1.0', 'team/',
                      '.team', '_team', '-team', 'team/.1', 'team/_1', 'team/-1',
                      'team/V1', 'team/1.0/2.0', 'team/1.0 ', 'team\\n',
                      'team/١.٠', 'téam/1.0', 'team/1.0\\n', 'team:1.0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load(self.config(prefix + 'integration="' + value + '"\n'))

    def test_hey_integration_rejects_reserved_names_with_clear_error(self):
        prefix = '[mcp.hey]\nenabled=true\nurl="https://example.com/mcp"\n'
        for name in ('hey-', 'hey-research', 'your-product', 'my-product', 'my-agent'):
            for suffix in ('', '/1.0', '/v2_beta'):
                value = name + suffix
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'name is reserved'):
                    load(self.config(prefix + 'integration="' + value + '"\n'))

    def test_runtime_paths_default_base_and_overrides(self):
        expected = {'base': '/var/lib/hermes-team',
                    'gate': '/var/lib/hermes-team/gate',
                    'out': '/var/lib/hermes-team/out',
                    'work': '/var/lib/hermes-team/work/tasks',
                    'keys': '/var/lib/hermes-team/keys',
                    'ledger': '/var/lib/hermes-team/ledger.jsonl',
                    'cookies': '/var/lib/hermes-team/cookies'}
        self.assertEqual(runtime_paths({}), expected)
        self.assertEqual(load(self.config(''))['paths'], expected)
        path = self.config('[paths]\nbase="data"\nout="separate"\n')
        paths = load(path)['paths']
        for key, suffix in (('gate', 'gate'), ('work', 'work/tasks'), ('keys', 'keys'),
                            ('ledger', 'ledger.jsonl'), ('cookies', 'cookies')):
            self.assertEqual(paths[key], str(path.resolve().parent / 'data' / suffix))
        self.assertEqual(paths['out'], str(path.resolve().parent / 'separate'))

    def test_gate_and_router_share_configured_base(self):
        import os
        import subprocess
        import sys
        from kit_config import ROOT
        path = self.config('[paths]\nbase="data"\n')
        env = {key: value for key, value in os.environ.items() if not key.startswith('TAKE_')}
        env['TEAM_CONFIG'] = str(path)
        script = r'''import importlib.util
from pathlib import Path
from kit_config import load
paths = load()['paths']
modules = []
for name, source in (('gate', 'gate/gate.py'), ('router', 'take-tasks/take-tasks.py')):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    modules.append(module)
gate, router = modules
assert gate.GATE_DIR == router.GATE_DIR == paths['gate']
assert gate.OUT_DIR == router.OUT_ROOT == paths['out']
assert gate.WORK_TASKS == router.WORK_DIR == paths['work']
assert router.OUT_DIR == str(Path(paths['out']) / 'tasks')
assert router.PROPOSALS == str(Path(paths['out']) / 'proposals')
assert router.KEYS_DIR == paths['keys']
assert router.COOKIES == paths['cookies']
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_priors_settings_are_rejected_when_enabled(self):
        for settings in ('url="http://example.com/mcp"', 'url="https:///mcp"',
                         'url=42', 'profiles=["missing"]', 'profiles="researcher"',
                         'profiles=[42]'):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                text = '[mcp.priors]\nenabled=true\n'
                if not settings.startswith('url='):
                    text += 'url="https://example.com/mcp"\n'
                load(self.config(text + settings + '\n'))
