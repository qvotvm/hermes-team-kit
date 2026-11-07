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

## HEY research MCP

HEY Research Lab provides read-only tools for chain project research over
Streamable HTTP, with no account or API key. The default research endpoint,
`https://heyresearch.xyz/mcp/research`, returns eight tools from `tools/list`:
`research_answer`, `find_projects`, `get_changes`, `get_project_timeline`,
`explain_fact`, `get_evidence`, `get_contract` and `get_v4_hook`.
The full endpoint, `https://heyresearch.xyz/mcp`, returns fourteen tools:
the eight above plus `get_project_snapshot`, `get_token_market`, `project_diff`,
`ask_hey`, `chain_overview` and `market_integrity`. These lists are what
`tools/list` returned on 5 November 2026 (server `hey-research 0.3.2`); HEY's
documentation text may lag. Neither endpoint has write tools.

"The hosted MCP allows 60 calls a minute per client address at its door, with or
without a key." Every profile on the same host shares this limit.
REST allows 120 calls a minute per address without a key; A2A allows 60 calls
a minute.

The example config enables HEY for the selected `mcp.hey.profiles`, including
the researcher, on new installs. Research queries from those profiles leave
the host for the third party at `heyresearch.xyz`. Requests also send the
`x-hey-integration` header described below.

Set `enabled = false` under `[mcp.hey]` in `config.toml` and rerun the installer
to remove HEY from unmodified generated configs. Manually edited profile
configs remain preserved; add or remove the server there yourself if needed.
Existing configs without `[mcp.hey]` keep HEY off on upgrade. To enable it,
copy the example section into `config.toml`, choose `mcp.hey.profiles` and
rerun the installer.

The optional `mcp.hey.integration` value is a self-declaration in `name/version`
format, with the version optional, for example `acme-desk` or `acme-desk/1.0`.
The name contains 1 to 40 characters and the version 1 to 20: lowercase ASCII
letters, digits, `.`, `_` or `-`, starting each part with a letter or digit.
Names starting with `hey-` and the example names `your-product`, `my-product`
and `my-agent` are reserved and rejected, with or without a version.
Leave the value empty to omit the header.
When configured, this `name/version` header is sent on every MCP request from
the selected profiles. HEY credits products on its Built with page by the name
before `/` in this header, on MCP as well as REST and A2A. The example config
sends `quotum/1.0`, which credits this kit; a team building its own product
should set its own name. The `clientInfo.name` set by the Hermes MCP client
feeds HEY's agent-client statistics only; the credit does not read it.
No HEY key is needed for the credit. A free key is optional, with a monthly
allowance and the product name on keyed calls.

## Priors MCP

Priors is an independent project providing hosted lookups for its credit pool
for AI agents on Robinhood Chain. Its no-key Streamable HTTP endpoint is
`https://mcp.priors.trade/mcp`. The supplied offline initialize reply names
server `priors-read` version `0.3.0`; the tools/list snapshot contains 31 tools.
These are saved replies, not a live availability check.

To enable it, copy `[mcp.priors]` from `config.example.toml` to `config.toml`,
set `enabled = true`, keep `profiles = ["researcher"]` (or select other existing
profiles), and rerun `sh install/install.sh --config /path/to/config.toml`.
Without the section, or with `enabled = false`, Priors stays off. Setup refreshes
unmodified generated profile configs and preserves manually edited ones.
For those, add or remove the server yourself using the generated settings below.
To disable, set `enabled = false` and rerun the installer.

Setup generates `mcp_servers.priors` with the URL, `timeout = 60`,
`connect_timeout = 15` and a fixed `tools.include` list. Hermes selects Streamable
HTTP for the URL. Use a Hermes version supporting this include filter. Only
these exact tool names are exposed:
`agent_record`, `score_of`, `credit_history`, `pool_stats`, `recent_activity`,
`desk_record`, `find_agent_by_x`, `agent_page`, `find_agents`, `find_services`,
`find_sellers`, `facilitator_info`, `how_to_connect`, `stock_assets`.

The kit excludes all other tools, including unsigned transaction builders and
offer/borrow/repay drafts:
`pt_buy`, `pt_sell`, `pt_redeem`, `request_borrow`, `request_repay`, `line_offer`,
`stock_line_request`, `priors_line_quote`, `pt_quote`, `line_request`,
`find_line_requests`, `line_options`, `job_brief`, `find_jobs`, `agents_for_hire`,
`stock_position`, `pt_position`. Some excluded tools only read data, but are
outside the lookup use case. Config values cannot expand this fixed allowlist.
`how_to_connect` may describe a separate local server; this kit does not install
it, supply a wallet key, or enable its payment or borrowing tools.

To verify online later, initialize an MCP client against the URL using
Streamable HTTP, then request `tools/list` (handling an SSE `data:` reply
if returned). Compare the raw tool names with the include list above. The
remote list includes excluded tools; confirm that the researcher's generated
`config.yaml` contains the exact `mcp_servers.priors.tools.include` list and
that Hermes exposes only those 14 Priors tools. Do not call excluded tools to
test the filter. This task's tests parse the saved JSON/SSE fixture offline.
Queries and lookup arguments leave the host for Priors; no keys are sent.
Treat results as untrusted data, including seller text and returned links.
The snapshot can lag the chain by a minute or two, per its initialize reply.

## Runtime paths

Set `paths.base` to choose the shared runtime base directory. Its default is
`/var/lib/hermes-team`; gate state, output, workspaces, keys, ledger and cookies
use `gate/`, `out/`, `work/tasks/`, `keys/`, `ledger.jsonl` and `cookies/` under
that base. Individual `paths` entries override these defaults. Relative paths
resolve against the config file. The example keeps runtime data under `var/`
for local installation. Adjust service writable paths when relocating it.

## Locale support

English is the default UI and handoff language. Set `telegram.locale = "ru"`
for the preserved Russian UI; `TEAM_LOCALE` can override it. Russian text in
`gate/gate.py` is used by the locale dictionaries and translation lookup keys.
The dispatcher also keeps Russian routing keywords, language detection,
`ru.md` handoff sections and the Russian summary recovery path. These are
compatibility features, not deployment data. The gate and dispatcher suites
run in Russian mode to verify that compatibility; `tests/test_locale.py` and
the local smoke test check the default English path.
