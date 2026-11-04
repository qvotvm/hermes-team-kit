# Operation and accounting

Use `/pending`, `/tasks`, `/status`, `/task`, `/pause`, `/resume` and `/help`, or the
persistent keyboard. Reports being deepened leave review until a child report
arrives. A report's **ok** marks the task accepted for accounting; it does not
publish anything. `/pause` stops dispatch; already running cards finish.

```sh
python3 ledger.py report --days 7
python3 breaker.py
```

The append-only JSONL ledger stores task/card identifiers, profile, model,
provider, tokens, dollars and duration. Unknown values remain `null` or `unknown`.
Accepted tasks are distinct task IDs, counted per profile over the same period
as spend; the numerator includes all finished work in that period, including
rejected work. A profile with missing cost information has an unknown rate.

Hermes run `metadata` may supply `cost_usd`, `tokens`, `model`, `provider` and
`duration`; these fields can also be top-level run fields. The kit records all
ended runs on a completed task. If your Hermes version omits usage, supply
completion events through `ledger.py append` from your accounting integration.
Use stable event IDs to avoid duplicates. No model call is made to estimate cost.

The breaker uses a configured HTTPS usage URL when available. Its adapter expects
`daily_cap_usd`, `spent_usd` and an ISO timestamp `reset_at`; map a provider's own
schema to this contract if necessary. Otherwise it sums local ledger spending
since `reset_hour_utc`. At 80% it defers new tasks and parks ready cards for that
group, releasing only cards it parked after reset. It never interrupts a running
card. Unknown local costs pause a capped group until accurate accounting is
available or the daily window resets. Uncapped keys need no usage endpoint.
The optional status **key balance** is the total remaining dispatch allowance
up to the breaker threshold, from a snapshot no older than ten minutes.

Do not run another dispatcher on the same board: it can bypass the timer's
breaker enforcement. This is a cooperative scheduling guard; a provider-side
cap is needed for a hard spending limit. Native fallback is configured in
Hermes profiles; budget exhaustion normally routes to an available group's
profile, while provider failures can use the profile's secondary provider.

Guests have a generic `ref https://example.com/article [note]` command, their
own report history and an optional deeper pass. Private/local URLs are refused;
retrieved content remains untrusted. Guest reports contain only handoff sections,
not raw run summaries or artifact paths. UI and handoff language default to
English; set `telegram.locale = "ru"` to use the preserved Russian UI.

## HEY research MCP (optional)

HEY Research Lab provides read-only tools for chain project research over
Streamable HTTP, with no account or API key. The default research endpoint,
`https://heyresearch.xyz/mcp/research`, exposes eight research tools. The full
endpoint, `https://heyresearch.xyz/mcp`, exposes fourteen tools including token
market tools.

Set `mcp.hey.enabled = true` in `config.toml`, choose the profile names in
`mcp.hey.profiles`, and run the installer again. Only those profiles receive
the server configuration. Manually edited profile configs remain preserved;
add the server there yourself if needed. Set `enabled = false` and rerun the
installer to remove it from unmodified generated configs.

The optional `mcp.hey.integration` value must contain 1 to 40 lowercase letters,
digits or hyphens. When set, it is sent as the `x-hey-integration` header:
calls are counted under that name and answers link with attribution. Leave
it empty to omit the header. No model credentials are sent in that header.

## Locale support

English is the default UI and handoff language. Set `telegram.locale = "ru"`
for the preserved Russian UI; `TEAM_LOCALE` can override it. Russian text in
`gate/gate.py` is used by the locale dictionaries and translation lookup keys.
The dispatcher also keeps Russian routing keywords, language detection,
`ru.md` handoff sections and the Russian summary recovery path. These are
compatibility features, not deployment data. The gate and dispatcher suites
run in Russian mode to verify that compatibility; `tests/test_locale.py` and
the local smoke test check the default English path.
