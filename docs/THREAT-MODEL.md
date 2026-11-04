# Trust boundaries

The gate trusts its configured owner IDs, its bot token, its own state and
clock, and the local filesystem. It accepts only private-chat updates where the
sender ID equals the chat ID. Guest IDs have only guest command access; they
cannot approve owner proposals or see other guests' reports. Guest inputs,
agent proposals and downloaded pages are untrusted data. The gate never calls
an LLM and never executes a proposal or guest URL.

## Decisions and replay

Proposal filenames and slugs are validated. Files must be regular, bounded in
size, and opened without following symlinks. Approval validates the file's
SHA-256 hash, expiry and single-use nonce. A changed proposal cannot be approved
with an old nonce, and a final decision cannot be replayed. Callback tokens let
long slugs fit Telegram's limit. Owner text commands `no` and `hold` deliberately
need no nonce; `ok` does. Preserve state across restarts; restoring an old state
backup can resurrect outstanding nonces and must be accompanied by invalidating
old proposals. Multiple gate instances must never share one state directory.

## Stolen bot token

A token holder can read or impersonate the bot, leak chat content, manipulate
messages or disrupt polling. Telegram still supplies user IDs, but the token
compromise destroys confidentiality and can mislead an owner into approving the
wrong work. Revoke the token, stop the service, secure the account/filesystem,
rotate secrets and invalidate outstanding proposals before restarting. The gate
redacts its token in logs; task bodies and metadata are still sensitive.

## Malicious guest link

The gate validates HTTP(S) URLs and refuses private addresses and local hosts.
It does not fetch pages itself. The agent's downloader must also reject private
IP destinations after DNS resolution and redirects; syntactic URL filtering
alone cannot stop DNS rebinding. Use network isolation for a downloader that
handles hostile links. Never evaluate guest notes or downloaded content as code
or instructions. Public-source prompt injection can still manipulate an agent's
report. Output filtering is defense in depth, not proof that secrets cannot leak.
Guest reports use only the requested handoff sections; raw run summaries, costs,
server paths and artifacts never serve as a guest fallback.

The optional HEY MCP exposes read-only tools only. Its third-party tool output
is untrusted text in the agent's context and adds a prompt injection surface.
Treat research results as data, never as instructions. Owner review through
the gate still applies to anything published.

## Local account and deployment modes

The default `security.trusted_same_user = true` permits the gate to read proposals
owned by the same OS user, because the non-root installer runs everything under
one account. Any process with that account's permissions can alter gate state,
decisions, configuration and code or read bot credentials. The nonce protocol
protects Telegram decisions, not a compromised local account. Agent role prompts
and the cooperative budget breaker do not create OS security boundaries.

For a hardened installation, set `trusted_same_user = false`, put the gate code
in a root-owned read-only directory, and run the gate as a dedicated user.
That user owns its 700 state and credential directories. Give the agent user
read/traverse access only to `tasks/`, `approved/`, `decisions/` and `PAUSE`, never
the token or state; a 711 parent plus 755 output directories can provide this.
The agent account owns proposal and artifact directories; the gate needs only
traverse/read access. The gate rejects proposals owned by its own UID in this
mode. Adjust systemd `User`, directory permissions and writable paths accordingly.
The supplied root script intentionally installs the convenience single-user
units; it does not claim to establish this stronger isolation.

## Budget and accounting

Ledger events are local records, not provider invoices. Missing costs are
unknown, and a capped group pauses when local usage is incomplete. Endpoint
errors fall back to the ledger; a custom adapter must not log credentials.
Usage requests require HTTPS and refuse redirects to avoid forwarding bearer
credentials. Breaker snapshots contain only numeric usage, profile names and
reset times. Ready cards park at the threshold; in-flight work may overshoot it.
Keep independent dispatchers off this board and set a provider cap if hard
limits matter. A native fallback provider can incur separate costs.

Source hashes detect accidental corruption of files from a trusted checkout.
They are not a signature: an attacker who changes source and the manifest can
bypass them. Git metadata and private generated configuration are outside the
packaged-source scrub scan. The original task text was sanitized to remove its
own literal legacy identifiers while preserving the requirements.
