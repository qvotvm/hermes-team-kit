#!/usr/bin/env python3
"""Idempotent local setup. JSON profile config is also valid YAML."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kit_config import load, ROOT


PRIORS_READ_TOOLS = (
    "agent_record", "score_of", "credit_history", "pool_stats", "recent_activity",
    "desk_record", "find_agent_by_x", "agent_page", "find_agents", "find_services",
    "find_sellers", "facilitator_info", "how_to_connect", "stock_assets",
)


def seed(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)


def managed_seed(path, text):
    """Refresh our own unmodified profile config; preserve manual edits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = path.parent / '.team-config.sha256'
    previous = marker.read_text().strip() if marker.exists() else None
    current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if current is not None and current != previous:
        print('Preserved customized profile config: ' + path.parent.name)
        return
    path.write_text(text)
    path.chmod(0o600)
    marker.write_text(hashlib.sha256(text.encode()).hexdigest() + '\n')
    marker.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(ROOT / 'config.toml'))
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11+ is required (Debian 12+ or Ubuntu 24.04+)')
    config_file = Path(args.config).expanduser().resolve()
    if not config_file.exists():
        shutil.copyfile(ROOT / 'config.example.toml', config_file)
        config_file.chmod(0o600)
    config = load(config_file)
    for name in ('gate', 'out', 'work', 'keys'):
        Path(config['paths'][name]).mkdir(parents=True, exist_ok=True)
    gate, out = Path(config['paths']['gate']), Path(config['paths']['out'])
    gate.chmod(0o700)
    for folder in ('approved', 'decisions', 'tasks'):
        (gate / folder).mkdir(exist_ok=True)
    for folder in ('proposals', 'tasks'):
        (out / folder).mkdir(exist_ok=True)
    Path(config['paths']['ledger']).parent.mkdir(parents=True, exist_ok=True)
    command = config.get('hermes', {}).get('command', 'hermes')
    if not shutil.which(command):
        parser.error('Hermes is required; install it separately, then set hermes.command')
    profiles_home = Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes'))) / 'profiles'
    groups = {p: group for group in config.get('seats', {}).values() for p in group['profiles']}
    for template in sorted((ROOT / 'profiles').glob('*.md')):
        profile = profiles_home / template.stem
        provider = {**config['provider'], **groups.get(template.stem, {})}
        primary = {'name': 'primary', 'base_url': provider['base_url'],
                   'key_env': provider['api_key_env'], 'model': provider['model']}
        settings = {'model': {'provider': 'primary', 'default': provider['model']},
                    'custom_providers': [primary]}
        fallback = config.get('fallback', {})
        if fallback.get('base_url') and fallback.get('model'):
            settings['custom_providers'].append({'name': 'fallback', 'base_url': fallback['base_url'],
                                                'key_env': fallback['api_key_env'], 'model': fallback['model']})
            settings['fallback_model'] = {'provider': 'fallback', 'model': fallback['model']}
        hey = config.get('mcp', {}).get('hey', {})
        if hey.get('enabled', False) and template.stem in hey.get('profiles', []):
            server = {'url': hey['url'], 'timeout': 60, 'connect_timeout': 15}
            if hey.get('integration'):
                server['headers'] = {'x-hey-integration': hey['integration']}
            settings['mcp_servers'] = {'hey': server}
        priors = config.get('mcp', {}).get('priors', {})
        if priors.get('enabled', False) and template.stem in priors.get('profiles', ['researcher']):
            settings.setdefault('mcp_servers', {})['priors'] = {
                'url': priors['url'], 'timeout': 60, 'connect_timeout': 15,
                'tools': {'include': list(PRIORS_READ_TOOLS)}}
        seed(profile / 'SOUL.md', template.read_text().replace('{{KIT_ROOT}}', str(ROOT)).replace('{{TEAM_CONFIG}}', str(config_file)))
        managed_seed(profile / 'config.yaml', json.dumps(settings, indent=2) + '\n')
        # Only model credentials enter profiles; no bot token or owner IDs.
        env_names = {provider['api_key_env']}
        if fallback.get('base_url'):
            env_names.add(fallback['api_key_env'])
        env_text = ''
        for name in sorted(env_names):
            value = os.environ.get(name, '')
            if '\n' in value or '\r' in value:
                parser.error('credentials must be single-line')
            if value:
                env_text += name + '=' + value + '\n'
        seed(profile / '.env', env_text)
    seed(ROOT / 'service.env', '# Add TELEGRAM_BOT_TOKEN and model keys here; keep mode 600.\n')
    print('Local files and profile templates ready. Existing files were preserved.')
    print('Edit config.toml and service.env, then follow README.md to start the services.')

if __name__ == '__main__':
    main()
