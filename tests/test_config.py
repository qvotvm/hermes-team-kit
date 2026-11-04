from pathlib import Path
import tempfile
import unittest
from kit_config import load

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
                         'profiles=["missing"]', 'profiles="analyst"', 'profiles=[42]'):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                text = '[mcp.hey]\nenabled=true\n'
                if not settings.startswith('url='):
                    text += 'url="https://example.com/mcp"\n'
                load(self.config(text + settings + '\n'))
