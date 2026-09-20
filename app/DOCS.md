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

This checkout is a `0.2.0` release candidate. Local E2E, image, and host-test
results cover this checkout and its disposable harness. They do not prove a
public release or a working HACS install/update path.

The source manifest sets `hassio_api: true` because the App needs scoped
Supervisor self-information and discovery. That is narrower than broad Home
Assistant API access. Refresh or reinstall an installed App before treating
its cached manifest as proof of the current source permissions.

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

## App options: what to enter

This is the safe starting configuration for version `0.2.0`. Check for the
matching public tag and image before installing it from the App store:

| Option | Recommended value | What it means |
| --- | --- | --- |
| `ingress_only` | `true` | Supervisor ingress may use the UI and API without a second token. Direct Core/adapter API calls are also accepted when they present the matching `gateway_token`; the option does not need to be disabled for the normal Core integration. |
| `gateway_mode` | `adapter_only` | The normal mode. The Core integration or another adapter supplies sanitized profiles and owns Home Assistant execution. `supervisor_read_only` is accepted by the schema but currently inert; it does not enable a separate read-only runtime. |
| `jev_endpoint` | Leave unset, or use `https://openrouter.ai/api/alpha/decisions` in this worktree | The App selects its native OpenRouter adapter for that exact URL. Other endpoints must implement Switchboard's typed Jev contract. A public image may predate this adapter; verify the target tag. Because this URL is optional, do not save an empty string in raw App options. |
| `jev_model` | `typesafe/jev-1.13` | Model sent to OpenRouter's Decisions API; ignored by other Jev services. |
| `jev_api_key` | Leave blank when `jev_endpoint` is blank | The API key for the configured Jev service. This is sent as a Bearer credential to that service and is not the gateway token. Do not put it in documentation, YAML committed to Git, logs, or screenshots. |
| `fallback_provider` | `disabled` until you choose a second model | `openrouter` calls an OpenRouter chat model; `typed_http` calls a Switchboard-compatible typed handoff service. No fallback is sent while disabled. |
| `fallback_endpoint` | Leave unset for OpenRouter; required for typed HTTP | OpenRouter defaults to its chat-completions URL. A typed HTTP service must return bounded prose or a typed proposal, not execute devices itself. |
| `fallback_model` | An OpenRouter chat-model ID when using OpenRouter fallback | The exact model to receive eligible fallback requests. This is separate from the Jev model. |
| `fallback_api_key` | The chosen fallback service key | Kept separate from `jev_api_key`; it may have the same value if both routes use your OpenRouter account. |
| `gateway_token` | A long random value | Bearer credential used by the Core integration to call the protected gateway endpoints. Use the exact same value in the HA Switchboard Integration configuration. |
| `profile_refresh_minutes` | `15` | The Core integration reads this App setting and schedules complete-profile reconciliation. For first use, request an explicit scan from the Web UI and wait for `active`. |
| `privacy_mode` | `local_only` | Blocks calls to hosted Jev endpoints. Set `jev_hosted_allowed` to use OpenRouter's hosted Jev. `hosted_allowed` also permits hosted downstream routes when configured. |

Privacy and fallback behavior at a glance:

| Privacy mode | Jev | Hosted fallback |
| --- | --- | --- |
| `local_only` | Local/compatible endpoints only; hosted Jev is blocked | Blocked |
| `jev_hosted_allowed` | Hosted Jev is allowed | Blocked |
| `hosted_allowed` | Hosted Jev is allowed | Allowed only for an explicitly configured eligible fallback |

Fallback is opt-in. `disabled` sends no fallback request. OpenRouter fallback
uses Chat Completions; `typed_http` must return a bounded response or typed
proposal and must not execute Home Assistant actions itself.

The Configuration page now supplies plain-language labels and inline field
descriptions. If you still see raw option names, refresh the App repository
and update the installed App; merely rebuilding its image does not replace the
installed Supervisor manifest. Choose `hosted_allowed` only if you want an
explicitly configured hosted fallback to receive bounded request context.

For a local smoke test without a compatible Jev service, the options should
look like this. Replace the token placeholder with a value generated locally;
do not paste a real secret into a public issue or README:

```yaml
ingress_only: true
gateway_mode: adapter_only
jev_api_key: ""
gateway_token: "<long-random-token>"
profile_refresh_minutes: 15
privacy_mode: local_only
```

With no `jev_endpoint`, the App makes no Jev request. Decision-dependent
conversation requests fail closed; do not describe an empty endpoint as a
working provider.

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

## Gateway token and Supervisor ingress

The App is the gateway. The token protects the gateway; it does not indicate a
second gateway or another service that must be installed.

There are two independent paths:

| Caller | Path | Authentication boundary |
| --- | --- | --- |
| A person opening the App UI | Supervisor ingress → App | Home Assistant/Supervisor session; the App does not need a second user login for ingress. |
| Home Assistant Core integration or an adapter | Direct HTTP → App gateway | `Authorization: Bearer <gateway_token>` when a token is configured. |

`/healthz` and `/readyz` remain available for health checks. The root WebUI and
static UI paths require Supervisor's ingress source address `172.30.32.2`.
`/v1/*` accepts either Supervisor ingress or a matching
`Authorization: Bearer <gateway_token>` header. Unauthenticated direct API
requests are rejected. The standalone Compose path explicitly disables the
Supervisor-only source restriction and must have its own network boundary and
token.

The Core integration stores its gateway URL and token in a Home Assistant
config entry. Do not put either value in committed YAML.

## OpenRouter and Jev

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

Explicit plural on/off requests for exposed lights, switches, and fans can
select an opaque group of up to 32 members. The Core integration preflights
every member, then executes and verifies them sequentially; partial completion
is possible if a later member fails. Other multi-device requests remain
unsupported. A
clarification or confirmation reply does not retain the pending action across
chat turns, so start a new, fully specified request instead of answering it
with a bare device name or “yes.”

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
behind this button.

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
Core-side adapter has reconciled a profile. A blank Jev endpoint also leaves
the gateway fail-closed for conversation requests.

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
- ingress accepts only Supervisor's `172.30.32.2` source address;
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
entrypoint. The fix is in this local release candidate; build the local App for
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

## License

HA Switchboard is distributed under the Apache License 2.0. Read the complete
terms in the repository [`LICENSE`](../LICENSE) file.
