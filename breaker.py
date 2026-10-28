#!/usr/bin/env python3
"""Manual desk stop, rolling hourly ledger cap and daily key budgets."""
import argparse
from contextlib import contextmanager
import fcntl
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time
import urllib.request
from kit_config import load
from ledger import events, append


@contextmanager
def control_lock(config):
    """Serialize stop/reset with the final dispatch check and launch."""
    path = Path(config['paths']['ledger']).with_suffix('.breaker.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        path.chmod(0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def manual_state(rows):
    state = None
    for row in rows:
        if row.get('type') == 'breaker_stop':
            state = row
        elif row.get('type') == 'breaker_reset':
            state = None
    return state


def trip(config, profile, reason, now=None, owner=False):
    roles = {p.stem for p in (Path(__file__).parent / 'profiles').glob('*.md')}
    if owner:
        if profile not in config.get('telegram', {}).get('owner_ids', []):
            raise PermissionError('owner only')
    elif profile not in roles:
        raise PermissionError('unknown desk profile')
    with control_lock(config):
        append(config['paths']['ledger'], {'type': 'breaker_stop', 'event_id': secrets.token_hex(16),
               'task_id': 'breaker', 'by': profile, 'reason': reason, 'ts': time.time() if now is None else now})


def reset_manual(config, owner_id, reason, now=None):
    if owner_id not in config.get('telegram', {}).get('owner_ids', []):
        raise PermissionError('owner only')
    with control_lock(config):
        append(config['paths']['ledger'], {'type': 'breaker_reset', 'event_id': secrets.token_hex(16),
               'task_id': 'breaker', 'by': owner_id, 'reason': reason, 'ts': time.time() if now is None else now})


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('invalid usage value')
    return float(value)


def window(now, hour=0):
    start = datetime.fromtimestamp(now, timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)
    if start.timestamp() > now:
        start -= timedelta(days=1)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def remote_usage(url, key):
    if not url.startswith('https://'):
        raise ValueError('usage endpoint must use HTTPS')
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key})
    # Do not forward a credential to a redirect destination.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as reply:
        data = json.loads(reply.read(65537))
    return data


def evaluate(config, now=None, fetch=remote_usage):
    now = time.time() if now is None else now
    limits = config.get('limits', {})
    threshold = numeric(limits.get('breaker_threshold', .8))
    if not 0 < threshold <= 1:
        raise ValueError('breaker_threshold must be in (0, 1]')
    start, reset = window(now, limits.get('reset_hour_utc', 0))
    rows = list(events(config['paths']['ledger']))
    manual = manual_state(rows)
    hourly_cap = numeric(limits.get('hourly_usd', 0))
    recent = [r for r in rows if r.get('type') == 'finished' and now - 3600 < r['ts'] <= now]
    hourly_spend = sum(numeric(r['dollars']) for r in recent if r.get('dollars') is not None)
    hourly_unknown = any(r.get('dollars') is None for r in recent)
    hourly_paused = hourly_cap > 0 and (hourly_unknown or hourly_spend >= hourly_cap)
    reason = 'manual stop' if manual else 'hourly cap' if hourly_paused else None
    groups = {}
    for name, seat in config.get('seats', {}).items():
        provider = {**config.get('provider', {}), **seat}
        cap = seat.get('daily_cap_usd')
        spend = sum(numeric(r['dollars']) for r in rows if r.get('type') == 'finished'
                    and start <= r['ts'] <= now and r.get('group') == name and r.get('dollars') is not None)
        unknown = any(r.get('type') == 'finished' and start <= r['ts'] <= now
                      and r.get('group') == name and r.get('dollars') is None for r in rows)
        source = 'ledger'
        group_reset = reset
        if provider.get('usage_url'):
            try:
                usage = fetch(provider['usage_url'], os.environ.get(provider.get('api_key_env', ''), ''))
                reply_cap, reply_spend = numeric(usage['daily_cap_usd']), numeric(usage['spent_usd'])
                reset_time = datetime.fromisoformat(usage['reset_at'].replace('Z', '+00:00'))
                if reset_time.tzinfo is None:
                    raise ValueError('usage reset needs a timezone')
                if reset_time.timestamp() <= now:
                    raise ValueError('stale usage reply')
                # Only a reply that passed every check replaces the ledger figures.
                cap, spend, group_reset = reply_cap, reply_spend, reset_time.timestamp()
                source, unknown = 'endpoint', False
            except (OSError, ValueError, KeyError, TypeError):
                source = 'ledger-fallback'
        cap = numeric(cap) if cap is not None else None
        daily_paused = cap is not None and (unknown or spend >= threshold * cap)
        paused = bool(manual or hourly_paused or daily_paused)
        groups[name] = {'profiles': seat['profiles'], 'daily_cap_usd': cap, 'spent_usd': spend,
                        'remaining_usd': None if cap is None else max(0, cap * threshold - spend),
                        'paused': paused, 'reason': reason or ('daily cap' if daily_paused else None), 'unknown_cost': unknown, 'reset_at': group_reset, 'source': source}
    return {'ts': now, 'groups': groups, 'tripped': bool(manual or hourly_paused),
            'reason': reason, 'manual': manual, 'hourly_usd': hourly_cap,
            'hourly_spent_usd': hourly_spend, 'hourly_unknown_cost': hourly_unknown}


def enforce(snapshot, command, state_path):
    """Park ready cards on paused groups; release only cards this breaker parked."""
    state_path = Path(state_path)
    held = json.loads(state_path.read_text()) if state_path.exists() else {}
    paused = {p for v in snapshot["groups"].values() if v["paused"] for p in v["profiles"]}
    cards = json.loads(command("list", "--json"))
    for card in cards:
        cid, profile = card["id"], card.get("assignee")
        if (snapshot.get("tripped") or profile in paused) and card["status"] == "ready":
            held[cid] = profile
            state_path.write_text(json.dumps(held))  # Intent survives a crash after scheduling.
            command("schedule", cid, snapshot.get("reason") or "daily key budget breaker")
        elif cid in held and not snapshot.get("tripped") and profile not in paused:
            if card["status"] == "scheduled":
                command("unblock", cid)
            del held[cid]
            state_path.write_text(json.dumps(held))
    return held


def update(config, now=None, fetch=remote_usage):
    snapshot = evaluate(config, now, fetch)
    out = Path(config['paths']['out'])
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=out, prefix='breaker-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(snapshot, allow_nan=False))
    try:
        temporary.replace(out / 'breaker.json')
    finally:
        temporary.unlink(missing_ok=True)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description='Inspect the breaker or stop the desk. Reset is owner-only in Telegram.')
    parser.add_argument('command', choices=['status', 'stop'], nargs='?', default='status')
    parser.add_argument('--profile')
    parser.add_argument('--reason')
    args = parser.parse_args()
    config = load()
    if args.command == 'stop':
        if not args.profile or not args.reason:
            parser.error('stop needs --profile and --reason')
        trip(config, args.profile, args.reason)
    print(json.dumps(update(config), indent=2))

if __name__ == '__main__':
    main()
