# HA Switchboard App

HA Switchboard is the gateway process for the companion Home Assistant Core
integration. Install both pieces when you want to use it as a Conversation
agent:

```text
Home Assistant Assist / voice / dashboard
             |
             v
Home Assistant Core integration
             |  HTTP + optional gateway bearer token
             v
HA Switchboard App (this App: gateway, policy, profile store)
             |  bounded request + optional Jev API credential
             v
Jev decision service
```

The App does not execute Home Assistant services. The Core integration owns
Home Assistant credentials, entity IDs, discovery, execution, and
post-action verification. The App receives only the sanitized profile and
bounded request data described by the gateway contract.

## Current verification status

This checkout is an experimental `0.2.1` source release candidate. Local E2E,
image, and host-test results cover this checkout and its disposable harness.
They do not prove a public release, a working HACS install/update path, or a
live App/Core canary. Keep the App, image, Python package, Core manifest, and
changelog on one semantic version; see [`docs/RELEASE.md`](../docs/RELEASE.md)
for the complete provenance and rollback contract.

The source manifest sets `hassio_api: true` because the App needs scoped
Supervisor self-information and discovery. That is narrower than broad Home
Assistant API access. Refresh or reinstall an installed App before treating
its cached manifest as proof of the current source permissions.

The App is useful by itself for its health, readiness, profile, and ingress UI,
but it is not an Assist agent. The companion Core integration is required for
Home Assistant discovery, profile construction, Conversation registration,
service execution, and post-action verification.

## Install

1. Add `https://github.com/grayslawson/ha-switchboard` as a Home Assistant
   App repository from **Settings → Apps → App store → ⋮ → Repositories**.
2. Install **HA Switchboard**, start it, and wait for the App to report that it
   is running.
3. Configure the App options below.
4. Install `custom_components/ha_switchboard/` through HACS as an Integration
   custom repository, or install it manually. This is the separate Core
   integration; installing the App does not copy it into `custom_components`.
5. Restart Home Assistant if the integration was copied manually. The running
   App registers a Supervisor discovery record containing its actual runtime
   hostname, port, and gateway token. In **Settings → Devices & services → Add
   integration**, add **HA Switchboard** and accept the discovered gateway.
6. If discovery is not offered, use the manual flow with the gateway URL
   shown by Supervisor for the installed App. Do not guess a hostname from the
   repository name: local Apps and GitHub Apps use different network aliases.
   Enter the same gateway token configured in the App.
7. Select the resulting Switchboard conversation agent in an Assist pipeline.
8. Open the App Web UI and choose **Scan Home Assistant now**. Wait for profile
   status to become `active`.
9. Test a read-only request first, then a low-risk exposed-device request.

The App's **Open Web UI** button uses Supervisor ingress. Ingress authenticates
the Home Assistant user; it is separate from the Core integration's direct
HTTP calls to the gateway.

If App options change after a discovery confirmation screen is already open,
dismiss that screen and restart Home Assistant Core to start a fresh discovery
flow. The pending screen retains the earlier gateway token and may otherwise
report `cannot_connect` even though the current App is healthy.

## App versus Core integration

The Supervisor App and the `ha_switchboard` Core integration are separate
artifacts. Installing the App alone is enough to run and test the gateway
behind Supervisor ingress. It does not add a Conversation entity, reconcile a
Home Assistant capability profile, or execute Home Assistant actions.

For the complete Assist flow, install the Core integration through HACS or
copy `custom_components/ha_switchboard/` manually—even when Home Assistant is
running as Home Assistant OS. HACS itself manages Core custom integrations,
not Supervisor Apps. On Home Assistant OS/Supervised, HACS provides a separate
one-shot **Get HACS** App that bootstraps the HACS integration; it can be
stopped or removed after the download completes. That bootstrapper is not the
Switchboard App. Home Assistant Container users cannot install Supervisor Apps
and should use the standalone Compose deployment plus the same Core integration.

## Native Home Assistant fast path

Home Assistant remains the front door and the authority for built-in intent
matching. Switchboard does not replace Home Assistant's native Conversation or
Assist handling, and Jev is not required for every simple command. Clear
native intents can be handled by Home Assistant's own fast path; within the
Switchboard agent, local read-only state answers also avoid a provider call.

Switchboard is useful when a request reaches its Conversation entity and needs
bounded routing: Jev can choose among the offered capabilities for ambiguous,
compound, or higher-risk requests, while Core still validates and executes the
result. An eligible fallback is for open-ended requests that Jev cannot answer;
it returns bounded prose or one proposal and is never an alternate Home
Assistant agent.

The native channels remain available around this boundary:

- Home Assistant Assist pipelines, including the Home Assistant mobile app and
  dashboard Assist surfaces;
- voice satellites and Wyoming/ESPHome pipelines that hand text to Home
  Assistant;
- Home Assistant's Conversation entity and `conversation.process` API; and
- ordinary dashboard or companion-app text that uses Home Assistant's
  conversation service.

Select **HA Switchboard** as the Conversation agent only for the Assist
pipeline or Conversation calls that should use this bounded routing layer.
Home Assistant's built-in intent handlers and other conversation agents remain
independent and are not copied into the App.

## App options: what to enter

This is the safe starting configuration for version `0.2.1`. Check for the
matching public tag and image before installing it from the App store:

| Option | Recommended value | What it means |
| --- | --- | --- |
| `ingress_only` | `true` | Supervisor ingress may use the UI and API without a second token. Direct Core/adapter API calls are also accepted when they present the matching `gateway_token`; the option does not need to be disabled for the normal Core integration. |
| `gateway_mode` | `adapter_only` | The normal mode. The Core integration or another adapter supplies sanitized profiles and owns Home Assistant execution. `supervisor_read_only` is a legacy persisted value; startup migration normalizes it to `adapter_only` and records an internal compatibility marker. It is not a current schema choice. |
| `jev_provider` | `disabled` | Select `typesafe` for direct TypeSafe System One, `openrouter` for OpenRouter Decisions, or `compatible` for Switchboard's generic typed Jev contract. TypeSafe and OpenRouter have documented defaults; `compatible` needs an endpoint. |
| `jev_endpoint` | Leave unset when disabled, or to use the TypeSafe/OpenRouter default | TypeSafe accepts a base URL or `/v1/systemone`; OpenRouter must use `https://openrouter.ai/api/alpha/decisions`; compatible endpoints must implement Switchboard's typed Jev contract. A public image may predate this adapter; verify the target tag. |
| `jev_model` | `typesafe/jev-1.13` for OpenRouter | Model for OpenRouter Decisions or the direct TypeSafe client; compatible typed services may ignore it. The TypeSafe client supplies its documented default when blank. |
| `jev_api_key` | Leave blank unless the Jev service requires one | The API key for the configured Jev service. This is sent as a Bearer credential to that service and is not the gateway token. Do not put it in documentation, YAML committed to Git, logs, or screenshots. |
| `fallback_provider` | `disabled` until you choose a second model | `openrouter` and `openai_compatible` use the generic OpenAI-compatible chat-completions adapter; `openrouter` defaults to OpenRouter. `typed_http` calls a Switchboard-compatible typed handoff service. No fallback is sent while disabled. |
| `fallback_endpoint` | Leave unset for OpenRouter; required for `openai_compatible` and `typed_http` | OpenRouter defaults to its chat-completions URL. `openai_compatible` accepts a provider base URL or full `/chat/completions` URL and normalizes the path. A typed HTTP service needs its compatible handoff URL and must return bounded prose or a typed proposal, not execute devices itself. Runtime `FALLBACK_BASE_URL` and the legacy persisted `fallback_base_url` name are accepted as compatibility aliases; `fallback_endpoint` is the current App option. |
| `fallback_model` | A chat-model ID for `openrouter` or `openai_compatible` | Required by both generic OpenAI-compatible fallback providers. This is separate from the Jev model. |
| `fallback_api_key` | Leave blank unless the fallback service requires one | Optional Bearer key for the fallback service. Keep it separate from `jev_api_key`; it may have the same value if both routes use your OpenRouter account. |
| `gateway_token` | A long random value | Bearer credential used by the Core integration to call the protected gateway endpoints. Use the exact same value in the HA Switchboard Integration configuration. |
| `profile_refresh_minutes` | `15` | The Core integration reads this App setting and schedules complete-profile reconciliation. For first use, request an explicit scan from the Web UI and wait for `active`. |
| `privacy_mode` | `local_only` | Blocks hosted Jev and hosted fallback routes. Set `jev_hosted_allowed` to use OpenRouter's hosted Jev without hosted fallback. `hosted_allowed` also permits an explicitly configured hosted fallback. |

Privacy and fallback behavior at a glance:

| Privacy mode | Jev | Hosted fallback |
| --- | --- | --- |
| `local_only` | Local/compatible endpoints only; hosted Jev is blocked | Blocked |
| `jev_hosted_allowed` | Hosted Jev is allowed | Blocked |
| `hosted_allowed` | Hosted Jev is allowed | Allowed only for an explicitly configured eligible fallback |

Fallback is opt-in. `disabled` sends no fallback request. The `openrouter` and
`openai_compatible` routes use the generic OpenAI-compatible Chat Completions
adapter. OpenRouter supplies the default endpoint; a compatible provider needs
its own base URL or full `/chat/completions` URL. Both require
`fallback_model`; `fallback_api_key` is only needed when the service requires
authentication. `typed_http` uses a separate Switchboard handoff contract and
must return a bounded response or typed proposal, never execute Home Assistant
actions itself.

The Configuration page now supplies plain-language labels and inline field
descriptions. If you still see raw option names, refresh the App repository
and update the installed App; merely rebuilding its image does not replace the
installed Supervisor manifest. Choose `hosted_allowed` only if you want an
explicitly configured hosted fallback to receive bounded request context.

For a local smoke test without a compatible Jev service, omit the provider
endpoint and keep the gateway token in the Supervisor options UI. Generate it
locally with `openssl rand -hex 32`; do not paste a real secret into a public
issue or README:

```yaml
ingress_only: true
gateway_mode: adapter_only
jev_api_key: ""
profile_refresh_minutes: 15
privacy_mode: local_only
```

With `jev_provider: disabled` and no runtime override, the App makes no Jev
request. Decision-dependent conversation requests fail closed; do not describe
an empty endpoint as a working provider. If `typesafe` or `openrouter` is
selected, their documented default endpoint is used when `jev_endpoint` is
blank.

Keep `ingress_only: true` for the normal Home Assistant OS arrangement. The
name means that the browser UI is ingress-only; the Core integration uses the
discovered internal hostname and its matching gateway token for `/v1/*` API
calls. Setting it to `false` is only useful for a standalone or separately
managed adapter network and does not replace the token.

Generate a suitable gateway token on a trusted machine with:

```bash
openssl rand -hex 32
```

The gateway token is required for the companion Core integration's direct
calls, regardless of `ingress_only`. It can be omitted only when there are no
direct callers and every request comes through authenticated Supervisor
ingress. It is not an OpenRouter API key and must not be reused as one.

## Updating and local recovery

Before an update, record the installed App image tag/digest, Core config entry,
profile status, and a verified Supervisor backup or volume snapshot. Keep the
existing Supervisor/Core volume and fixtures intact; the normal local rebuild
path replaces only the App. Refresh or reinstall the App after changing its
manifest so a cached Supervisor copy cannot be mistaken for current source.

Install the matching Core integration artifact, wait for App `readyz` and a
complete `profile_reconciled` state, then run a read-only Assist/Conversation
request before one low-risk exposed-device action. If migration fails, restore
the verified snapshot and the exact previous App/Core pair. Do not reset the
fixture, uninstall the running environment, or roll back only one side. Record
the command, source/image revision, observed state, and timestamp without
tokens, API keys, entity IDs, utterances, or provider response bodies.

This local recovery sequence is not a live-canary or public-release check. The
release still needs external App repository, HACS/Hassfest, GHCR/mirror, and
provider acceptance evidence.

## Gateway token and Supervisor ingress

The App is the gateway. The token protects the gateway; it does not indicate a
second gateway or another service that must be installed.

There are two independent paths:

| Caller | Path | Authentication boundary |
| --- | --- | --- |
| A person opening the App UI | Supervisor ingress → App | Home Assistant/Supervisor session; the App does not need a second user login for ingress. |
| Home Assistant Core integration or an adapter | Direct HTTP → App gateway | `Authorization: Bearer` with the matching gateway token when a token is configured. |

`/healthz` and `/readyz` remain available for health checks. The root WebUI and
static UI paths require Supervisor's ingress source address `172.30.32.2`.
`/v1/*` accepts either Supervisor ingress or an `Authorization: Bearer` header
carrying the matching gateway token. Unauthenticated direct API
requests are rejected. The standalone Compose path explicitly disables the
Supervisor-only source restriction and must have its own network boundary and
token.

The Core integration stores its gateway URL and token in a Home Assistant
config entry. Do not put either value in committed YAML.

## Provider architecture

The three decision-service paths use different wire contracts. Do not point a
client at a URL merely because the service is described as “Jev”; select the
adapter that matches the service and provide its base URL, API key, and model
through the supported runtime boundary.

### Direct TypeSafe System One

The direct TypeSafe client uses `POST /v1/systemone` and the TypeSafe `answers`
contract. With no custom endpoint, it defaults to
`https://api.typesafe.ai/v1/systemone`. The App selects it with
`jev_provider: typesafe`, `jev_endpoint`,
`jev_api_key`, and `jev_model`; an explicitly managed runtime can use
`JEV_PROVIDER=typesafe`, `JEV_BASE_URL` (or `JEV_ENDPOINT`), `JEV_API_KEY`, and
`JEV_MODEL` instead. The client defaults to the documented TypeSafe endpoint
and model when those runtime values are absent. It normalizes a base URL to
`/v1/systemone`, sends bounded state and questions, and can translate typed
choice parameters when the capability schema supports them.

The current Supervisor App manifest exposes `jev_provider` and uses
`jev_endpoint` for the selected provider. It does not expose the environment
variable name `JEV_BASE_URL`; use the App option for the TypeSafe base URL or
the runtime variable in a separately managed client. The App can select
TypeSafe directly; runtime variables are only an alternative for separately
managed clients.

### OpenRouter Decisions

OpenRouter currently exposes Jev through its Decisions API at:

```text
https://openrouter.ai/api/alpha/decisions
```

The OpenRouter request must include a model such as
`typesafe/jev-1.13` or `~typesafe/jev-latest`, plus `state` and
`questions`. OpenRouter returns `answers` rather than the Switchboard
`decision` object. See the [OpenRouter Decisions API specification](https://openrouter.ai/openapi.json)
and [Typesafe model documentation](https://openrouter.ai/typesafe).

The adapter in this worktree sends OpenRouter's required model, `state`, and
typed `questions`. It asks Jev to choose a route and one capability from the
current sanitized allowlist, then translates the `answers` into a proposal.
The gateway still checks confidence, ambiguity, exposure, profile freshness,
risk, confirmation, and allowed parameters before Home Assistant Core can
execute anything. A public image may predate this adapter; verify the target
tag before configuring it.

To try it after building this source, set `jev_endpoint` to the Decisions URL
above, `jev_model` to `typesafe/jev-1.13`, `jev_api_key` to an OpenRouter API
key, and `privacy_mode` to `jev_hosted_allowed`. Keep the separate
`gateway_token` set for Core-to-App calls. Do not use
`https://openrouter.ai/api/v1/chat/completions` as a Jev endpoint.

The typed decision can contain `parameters`, and the Core integration validates
those values against the capability schema before execution. That supports
controls such as setting a target temperature only when a compatible Jev
service or adapter supplies the value. Native OpenRouter Decisions still do
not supply exact action values. The adapter asks for clarification on
parameterized controls rather than guessing. The Core integration can answer
bounded read-only state questions from its current local snapshot, without a
provider call. An optional OpenRouter chat-model fallback or compatible typed
HTTP fallback can return bounded prose or a typed proposal; every proposed
action re-enters the gateway policy and Core execution checks. Configure
`fallback_provider`, `fallback_endpoint`, `fallback_model` (OpenRouter), and
`fallback_api_key` separately from Jev. Hosted OpenRouter fallback requires
`privacy_mode: hosted_allowed`; `jev_hosted_allowed` is insufficient. A local
typed HTTP route may be used without authorizing hosted fallback. An arbitrary
Home Assistant conversation agent must not be treated as a typed route because
it may act independently of Switchboard's checks.

### Generic typed Jev

When `jev_endpoint` is not the OpenRouter Decisions URL, the App uses the
generic typed Jev client. The service must accept Switchboard's bounded
request and return a typed `decision` object with an offered capability and
optional validated parameters. A generic endpoint is not assumed to implement
TypeSafe System One or OpenAI Chat Completions; document its exact contract
and use HTTPS when credentials or Home Assistant context are sent.

### OpenAI-compatible fallback

The `openrouter` and `openai_compatible` fallback names select the generic
OpenAI-compatible chat-completions adapter. Its `fallback_endpoint` may be a
provider base URL or a complete `/chat/completions` URL; the adapter normalizes
the path. Supply `fallback_model` and `fallback_api_key` independently from Jev. The response
must be bounded prose or one of the opaque capabilities Switchboard offered;
tool calls, arbitrary service JSON, provider selection, and action claims are
rejected. `typed_http` is different: it uses the explicit
`ha-switchboard-fallback/v1` handoff contract and may be local or hosted
according to endpoint and privacy policy.

For the generic chat-completions routes, Switchboard first sends the optional
OpenAI JSON-Schema response hint. If the provider returns HTTP 400 for that
optional feature, it makes one bounded retry without the hint and still
requires the same strict JSON response contract. Other transport or HTTP
failures fail closed and can be routed to another eligible fallback; the
adapter never accepts provider tool calls or arbitrary service payloads.

Explicit plural on/off requests for exposed lights, switches, and fans can
select an opaque group of up to 32 members. The request may target the whole
exposed domain or one unambiguous known area, floor, or label. The Core
integration preflights every member, then executes and verifies them
sequentially; partial completion is possible if a later member fails. Home
Assistant group membership is supported for one explicitly named, validated
group of exposed light, switch, and fan on/off members. Unknown, malformed,
unsafe, unavailable, or unsupported members fail closed. Atomic, toggle,
parameterized, and other multi-device operations remain unsupported.

Clarification, parameter, and confirmation replies use the Core-local
`ConversationContextStore`. A pending entry is short-lived, matched to the
Home Assistant conversation and authenticated user, and consumed once before
it can authorize execution. Expired, replayed, or cross-user replies do not
execute the original request. The checked-in unit tests cover the store's TTL,
user binding, and one-time-consumption behavior; complete live Assist/E2E
follow-up evidence is still a release gap.

The profile may include exposed script and scene routine rows for sanitized
visibility, but the Core execution boundary currently rejects their
`activate` operation. Do not treat those rows as executable Switchboard
controls; use Home Assistant's own script/scene services when appropriate.

## Profile readiness

The App deliberately refuses writes until it has a complete current profile.
An adapter must:

1. observe Home Assistant's official entity, device, area, floor, and label
   registry events;
2. call `POST /v1/profile/invalidate` for the affected registry sections;
3. read a fresh complete snapshot; and
4. call `POST /v1/profile/reconcile` with that replacement snapshot.

State changes do not invalidate the whole profile. The Core integration keeps
an allowlisted, opaque-ID-keyed state cache and sends that bounded state with
the next conversation request. This avoids a full registry scan for every
light or sensor update.

The Core integration schedules refreshes and recovers after App restarts. For first
use, the App's **Open Web UI** page provides **Scan Home Assistant now**. It
marks the current profile stale and asks Core to build a complete replacement;
the button acknowledges the request but does not mean the scan has finished.
Watch the profile status and App log for a subsequent `profile_reconciled`
event. Without a running Core integration, there is no Home Assistant scanner
behind this button. The scan response is an acknowledgement, not a completion
result: refresh profile status and wait for `active`; a healthy `/healthz`
response alone does not authorize writes.

The endpoints are:

```text
GET  /healthz
GET  /readyz
GET  /v1/profile/status
POST /v1/profile/scan
POST /v1/profile/reconcile
POST /v1/profile/invalidate
POST /v1/assist/process
```

`/readyz` being degraded immediately after installation is expected until the
Core-side adapter has reconciled a profile and the provider status is ready.
In the current gateway, that requires a configured Jev provider; a fallback
alone does not make `/readyz` ready. Provider status is not an automatic
reachability probe. Health is liveness only; it does not prove profile or
provider compatibility.

## Web UI and logs

Open the App through Supervisor's **Open Web UI** action. The dashboard is an
operator console, not a device-control UI. It shows liveness/readiness, profile
freshness and capability count, Core connection state, privacy and fallback
configuration state, bounded provider status, scan state, and redacted
diagnostic events. Provider status is configuration/circuit state only:
reachability is deliberately shown as unverified unless a separate bounded
compatibility probe is run. It does not show endpoint URLs, API keys, gateway
tokens, raw entity IDs, raw utterances, or provider response bodies.

Use **Refresh status** for current state and **Scan Home Assistant now** to
request one Core reconciliation. The scan button returns an acknowledgement;
wait for the scan state and profile status to settle to `active`. Use the
diagnostic severity/event filters and pagination to investigate bounded events.
The UI polls for a finite period and preserves the last known profile if the
scan does not finish within that window. Provider status is configuration and
circuit state; reachability remains unverified unless a separate bounded
compatibility probe is run.

For App process logs, use Home Assistant's App log view or the local harness's
`tools/local-dev.sh logs`. Logs contain bounded event codes, route class,
outcome, counts, timing, and safe error categories. They deliberately omit
credentials, raw request bodies, raw utterances, query strings, and provider
content. Redact hostnames and private values before sharing AppArmor audit
records or logs.

Common log events have these meanings:

| Event/code | Meaning | Operator action |
| --- | --- | --- |
| `startup` / `configuration` | The App loaded its options and selected provider routes. | Confirm the provider is intentional; an empty or disabled provider is valid for local/native-only use. |
| `profile_reconciled` | Core supplied a complete replacement profile. | Confirm status is `active` before attempting a write. |
| `profile_stale` / `profile_scan_requested` | A registry change or manual scan invalidated the previous profile. | Wait for the next `profile_reconciled`; do not infer write readiness from capability count alone. |
| `decision` | A bounded native, Jev, fallback, clarification, or refusal route completed. | Use the route/outcome fields; request bodies and provider text are intentionally absent. |
| `provider_structured_output_retry` | A compatible chat provider rejected the optional JSON-Schema hint with HTTP 400, so the adapter made its single bounded compatibility retry. | Confirm the provider still returns the documented bounded JSON contract; repeated failures are fail-closed. |
| `provider_http_error` / `jev_invalid_response` | A configured provider failed transport or did not meet its typed contract. | Check endpoint/provider/privacy-mode compatibility, then retry or use a configured eligible fallback. |
| `execution` / `verification` | Core executed and checked a proposed action. | Treat the verified count and reason code as authoritative; App logs never contain raw entity IDs. |

The expected first-use sequence is: App `startup` → Core
`profile_scan_requested` → `profile_reconciled` → `decision` → Core
`execution`/`verification`. A missing `profile_reconciled` means the Core
integration is not connected or the scan failed; a healthy App endpoint alone
does not prove that Assist is ready. A completed scan still does not prove
that the selected Jev/fallback endpoint is compatible or that an Assist
pipeline selected HA Switchboard.

For a visual UI walkthrough, use the **Info**, **Configuration**, **Log**, and
**Open Web UI** tabs in the Supervisor App page. The dashboard is intentionally
an operator console: **Refresh status** reads current state, **Scan Home
Assistant now** requests a scan, and the log filters narrow bounded events.
It is not a device-control dashboard.

## Security model

The App follows Home Assistant's [App security guidance](https://developers.home-assistant.io/docs/apps/security/):

- it runs without host networking or privileged devices; the source manifest
  disables broad Home Assistant and Supervisor API access in the default
  adapter-only mode, while the runtime uses only the scoped self-information
  and discovery endpoints needed for options and registration;
- startup briefly runs as root to make Supervisor's root-owned `/data`
  directory writable, then drops to UID/GID 65532 before opening the server;
  the root-only `options.json` remains private and is read through the scoped
  `/addons/self/info` API;
- it has a custom `apparmor.txt` profile;
- it stores only the profile and redacted operational state under `/data`;
- Web UI/static ingress accepts only Supervisor's `172.30.32.2` source address;
- direct adapter mode requires a gateway token for non-ingress callers; and
- external credentials remain in Supervisor options or the deployment's secret
  mechanism rather than source control.

Home Assistant's app presentation guidance also covers [AppArmor and ingress](https://developers.home-assistant.io/docs/apps/presentation/).
The App's custom profile must allow its shell entrypoint, Python runtime, and
`/data` persistence while denying unrelated Home Assistant host paths.

## Troubleshooting

### `/bin/sh: can't open '/run.sh': Permission denied`

This means the installed public App image is older than the startup-permission
fix, or Supervisor is still using a cached image. The App's custom AppArmor profile
must allow `/run.sh`, `/bin/sh`, the Alpine BusyBox shell, and the Python
entrypoint. The fix is in this local source tree; build the local App for
local testing or wait for a matching public release before telling users to
update. If
Supervisor still reports the old image after a published update, stop the App,
refresh the repository, update/reinstall the App, and start it again.

If the error persists on the repaired image, inspect the host's AppArmor audit
events:

```bash
journalctl _TRANSPORT=audit -g 'apparmor='
```

Do not solve this by disabling AppArmor or protection mode. Home Assistant
recommends a custom profile and least-privilege defaults for secure Apps.

### `libpython3.12.so.1.0: No such file or directory` or `Py_BytesMain: symbol not found`

When these errors appear together with the `/run.sh` permission error, the
library is normally present in the image but AppArmor is denying the dynamic
loader's read or executable memory mapping. The repaired profile in the local
App source
allows read-only mappings for `/lib/**`, `/usr/lib/**`, and `/usr/local/lib/**`,
which covers Alpine's musl loader, `libpython`, and Python's native extension
modules. Update/reinstall the App and restart it; do not install a second
Python package or disable AppArmor.

If the failure persists after the update, inspect the AppArmor audit events and
look for denied paths under those three library trees:

```bash
journalctl _TRANSPORT=audit -g 'apparmor='
```

The `name=` field in a denial identifies the path that still needs to be
compared with the installed App version. Capture the diagnostic only after
redacting hostnames, tokens, and other private values.

### Gateway unavailable from the Core integration

Confirm that the Integration was created from Supervisor discovery, or use
the hostname and port shown by Supervisor for the installed App. Do not use a
hardcoded `ha-switchboard` hostname: local and GitHub App repositories have
different network aliases. Keep `ingress_only: true`; direct Core API calls
are authorized by the matching gateway token. Health and readiness do not
prove that the protected conversation endpoint accepts the Integration's
credentials, so verify the token as well.

### Jev unavailable or invalid response

The public App may lag this source. Builds from this worktree accept the exact
OpenRouter Decisions URL above, but not Chat Completions. Check the App log for
a `decision` event and its bounded
`code`: `privacy_mode_denied` means hosted Jev is disabled,
`jev_unavailable` means the request could not complete, and
`jev_invalid_response` means the reply did not meet the adapter contract.
The log omits utterances, credentials, request bodies, and query strings.

For the complete 0.2.1 support boundary—including supported domains,
parameter limitations, batch restrictions, and Core-local follow-up context—see the support matrix in the repository [README](../README.md)
and the generated-spec evidence in
`specs/001-ha-switchboard-completeness/traceability.md`.

## License

HA Switchboard is distributed under the Apache License 2.0. Read the complete
terms in the repository [`LICENSE`](../LICENSE) file.
