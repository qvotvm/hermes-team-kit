"""Shared TOML configuration. Relative paths resolve against the config file."""
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent

def load(path=None):
    path = Path(path or os.environ.get('TEAM_CONFIG', ROOT / 'config.toml')).expanduser().resolve()
    if not path.exists():
        return {}
    with path.open('rb') as stream:
        config = tomllib.load(stream)
    for name, value in config.get('paths', {}).items():
        item = Path(value).expanduser()
        config['paths'][name] = str(item if item.is_absolute() else path.parent / item)
    if config.get('telegram', {}).get('locale', 'en') not in ('en', 'ru'):
        raise ValueError('locale must be en or ru')
    roles = {p.stem for p in (ROOT / 'profiles').glob('*.md')}
    hey = config.get('mcp', {}).get('hey', {})
    if hey.get('enabled', False):
        url = hey.get('url', '')
        if not isinstance(url, str) or urlsplit(url).scheme != 'https' or not urlsplit(url).hostname:
            raise ValueError('HEY url must be https')
        integration = hey.get('integration', '')
        if not isinstance(integration, str) or (integration and not re.fullmatch('[a-z0-9-]{1,40}', integration)):
            raise ValueError('HEY integration must match [a-z0-9-]{1,40}')
        profiles = hey.get('profiles', [])
        if not isinstance(profiles, list) or any(not isinstance(p, str) or p not in roles for p in profiles):
            raise ValueError('unknown HEY profile')
    seen = set()
    key_groups = set()
    for group in config.get('seats', {}).values():
        key = group.get('api_key_env')
        if key and key in key_groups:
            raise ValueError('profiles sharing a key must use one seat group')
        if key:
            key_groups.add(key)
        for profile in group.get('profiles', []):
            if profile not in roles:
                raise ValueError('unknown profile: ' + profile)
            if profile in seen:
                raise ValueError('profile assigned to multiple groups: ' + profile)
            seen.add(profile)
    return config
