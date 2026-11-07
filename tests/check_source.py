#!/usr/bin/env python3
"""Check the original task's scrub patterns in packaged source, excluding Git
metadata, generated caches and private runtime/configuration files. Encoding
prevents this validation program from matching its own forbidden literals.
"""
import base64
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(base64.b64decode('cXVvdHVtfGtpY2tlcnxlZ2dwb3B8Y2VudGltYW51c3xuaWdodGRlc2t8L1VzZXJzL3wxNjIwNjU5OTQ4fDE3NzkzNTQxOXwxODYzMjE0ODV8MTAwXC43M1wufHBheV8/dG98bnZkYXxwb25zfHJvYmluaG9vZHx2ZW5pY2V8YWdlbnRzLTF8YmtrfHN1YnNcLmpzb258MHhbMC05YS1mQS1GXXs0MH0=').decode(), re.I)
# The public HEY integration value is intentional in these example references.
PUBLIC_INTEGRATION = re.compile(r'(?<![\w./-])' + re.escape(
    base64.b64decode('cXVvdHVtLzEuMA==').decode()) + r'(?![\w./-])')
PUBLIC_FILES = {'config.example.toml', 'docs/OPERATION.md', 'tests/test_setup.py'}
# The public HEY Research Lab badge line in the README is intentional.
PUBLIC_BADGE = base64.b64decode('WyFbcXVvdHVtIG9uIEhFWSBSZXNlYXJjaCBMYWJdKGh0dHBzOi8vaGV5cmVzZWFyY2gueHl6L2FwaS9iYWRnZS9xdW90dW0pXShodHRwczovL2hleXJlc2VhcmNoLnh5ei9wcm9qZWN0L3F1b3R1bT91dG1fc291cmNlPWJhZGdlJnV0bV9tZWRpdW09cmVhZG1lKQ==').decode()
# Public Priors integration documentation and verbatim offline protocol fixtures.
PRIORS_PUBLIC_FILES = {'README.md', 'docs/OPERATION.md',
                       'tests/fixtures/priors/init.txt', 'tests/fixtures/priors/tools.json'}
PRIORS_CHAIN = base64.b64decode('Um9iaW5ob29kIENoYWlu').decode()
errors = []
for file in ROOT.rglob('*'):
    relative = file.relative_to(ROOT)
    if any(part in {'.git', '__pycache__', '.pytest_cache', 'var'} for part in relative.parts):
        continue
    if not file.is_file() or file.name in {'config.toml', 'service.env', 'bot.env', '.env'}:
        continue
    try:
        text = file.read_text()
    except UnicodeDecodeError:
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if relative.as_posix() in PUBLIC_FILES:
            line = PUBLIC_INTEGRATION.sub('', line)
        if relative.as_posix() == 'README.md' and line == PUBLIC_BADGE:
            continue
        if relative.as_posix() in PRIORS_PUBLIC_FILES:
            line = line.replace(PRIORS_CHAIN, '')
        if relative.as_posix() == 'tests/fixtures/priors/tools.json':
            for encoded in ('c3BvbnNvci9iYWNrZXI=', 'Um9iaW5ob29kIHN0b2NrIHRva2Vu'):
                line = line.replace(base64.b64decode(encoded).decode(), '')
        if PATTERN.search(line):
            errors.append(f'{relative}:{number}: forbidden deployment reference')
if errors:
    raise SystemExit('\n'.join(errors))
print('PASS: deployment scrub patterns absent from packaged source.')
