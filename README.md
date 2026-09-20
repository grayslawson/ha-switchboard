# HA Switchboard

HA Switchboard is a small, local-first control layer for [Home Assistant](https://www.home-assistant.io/). It adds a bounded Jev decision path behind Home Assistant's existing conversation surfaces while preserving the interfaces people already use: Assist, conversation agents, voice satellites, dashboards, and companion applications.

The goal is simple: make everyday home control quick and inexpensive, then hand genuinely open-ended requests to a user-approved traditional LLM when policy says that is appropriate.

> **Project status: experimental**
>
> The gateway, Supervisor discovery path, Core integration lifecycle, profile model, policy checks, and packaging paths are available in this checkout and locally tested. Read [Current limitations and roadmap](#current-limitations-and-roadmap) before deploying this to a real home.

This checkout declares the coordinated source version `0.2.0`. It is a source
release candidate, not a published or complete release: the App is still
marked experimental and the external/runtime gates remain open. A source
version alone is not proof of publication; check the matching public tag,
multi-architecture image, and GitHub Release before installing.

Version policy is intentionally strict: the App config/image, Python package,
Core manifest, and changelog must carry the same semantic version. A `v0.2.0`
tag, public mirror, GHCR digest, and GitHub Release must all identify the same
protected source revision before anyone describes the artifact as public.
See [docs/RELEASE.md](docs/RELEASE.md) for migration, rollback, provenance,
canary, and external-dependency evidence requirements.

The local source authorities currently agree on `0.2.0`:

| Artifact | Source authority |
| --- | --- |
| Supervisor App and image | `app/config.yaml`, `app/Dockerfile` |
| Gateway package | `app/ha_switchboard/__init__.py`, `pyproject.toml` |
| Home Assistant Core integration | `custom_components/ha_switchboard/manifest.json` |
| Human-readable release history | `app/CHANGELOG.md` |

This table describes checked-in source metadata only. It is not an installed
App version, image digest, public tag, HACS result, or live App/Core result.

### Verification status

Local E2E, image, and host-test results describe this checkout and its
disposable harness only. They do not prove a public release, a configured HACS
installation, or deployment of the current source to an existing Supervisor
installation.

For a disposable local Home Assistant with representative lights, switches,
fans, media, climate, cover, garage, lock, sensor, motion, area, label, and
Assist-pipeline fixtures, start with the [release checklist](docs/RELEASE.md#evidence-states).
The detailed fixture harness is maintained in the private checkout at
`tools/local-fixtures/README.md`; it is intentionally excluded from the public
mirror. The fixture installer is fail-closed to the named `busy_cohen`
container and localhost port `7123`; it never resets a Core volume, changes
App credentials, or contacts an external provider. Run its `verify` command
after an integration install or upgrade to capture secret-free config-entry
evidence.

The source manifest sets `hassio_api: true` because scoped Supervisor
self-information and discovery are required. This is not broad Home Assistant
API access. A running installation can still use a cached manifest; refresh or
reinstall the App before calling its live permission set current.

## Why Switchboard?

Home Assistant is the source of truth and remains the authority that executes actions. Switchboard adds an intelligence and routing layer around it:

- **Native fast path:** Home Assistant handles clear built-in intents through its own Conversation/Assist matching, and the Core integration can answer eligible local read-only questions without a provider call.
- **Bounded routing path:** when a request is intentionally sent to Switchboard, Jev receives a bounded request and capability context, then returns a typed decision such as read, control, clarify, delegate, or refuse.
- **Cheap path:** routine commands do not need a large general-purpose model or a long tool-planning loop.
- **Safe path:** opaque capability IDs, allowlists, confidence and ambiguity thresholds, confirmation policy, idempotency, and post-action verification sit between a decision and a Home Assistant write.
- **Fallback path:** a more capable model can receive one bounded handoff for requests outside Jev's scope, subject to privacy, cost, latency, complexity, and response-type policy.
- **Compatible path:** Switchboard enhances existing Home Assistant surfaces instead of replacing them.

## How it works

```text
Voice, text, Assist, dashboard, or conversation agent
                         |
              Home Assistant Core integration
       (credentials, entity IDs, execution, verification)
                         |
                   HA Switchboard gateway
          (redaction, profile freshness, policy, routing)
                 /                         \
        Jev typed decision              Optional handoff
      (fast routine path)            (traditional LLM route)
                 \                         /
              bounded result or proposal
                         |
              re-check, execute, verify
                         |
                    Home Assistant
```

The gateway does not execute Home Assistant services. The companion integration owns that boundary. The gateway stores a redacted, versioned capability profile, and profile changes make the profile stale until a complete replacement snapshot is reconciled.

### Bounded Jev routing

In this project, Jev is used as a typed decision boundary rather than as a prose chatbot. The App can use the direct TypeSafe System One contract, OpenRouter's native Decisions contract, or a generic Switchboard-compatible typed Jev endpoint. The native OpenRouter adapter translates route and capability choices for parameter-free controls; it does not extract target temperatures, brightness levels, or other action values. A compatible typed service may return typed `parameters`, which the Core integration validates before execution.

If Jev selects `delegate`, Switchboard chooses an eligible downstream route by policy. A traditional model may return bounded prose or one typed capability proposal. Any proposal re-enters the same freshness, confirmation, allowlist, execution, and verification checks. Handoffs are limited to one level to prevent loops.

### 0.2.0 support boundary

This is the implementation boundary in this checkout, not the target state in
`specs/001-ha-switchboard-completeness/`:

| Area | Supported now | Not supported or not proven yet |
| --- | --- | --- |
| Conversation | Local read-only answers; bounded single-target proposals; verified results and reason-specific refusals | A general Home Assistant agent; every natural-language request |
| Controls | Exposed light, switch, fan, media-player, climate, lock, cover, and garage rows when the corresponding service exists; exposed script/scene routines may be represented in the profile for visibility | Script/scene `activate` rows are currently held out of Core execution; unsupported domains and service shapes are omitted, not emulated |
| Parameters | Core validates brightness (0–100%), volume (0–1), temperature (5–35°C before per-entity bounds), and HVAC enums supplied by an adapter | Native OpenRouter Decisions does not extract action values; a compatible typed Jev service must supply them |
| Multi-device | Explicit on/off groups for exposed lights, switches, and fans; at most 32 targets; preflight, sequential execution, and partial-result reporting | Atomic batches, toggle batches, parameterized batches, and general area/label/group semantics |
| Follow-up turns | Pending clarification/confirmation is Core-local, short-lived, bound to the conversation and user, and consumed once; expiry or mismatch cannot authorize a write | Full fixture Assist/E2E proof of every follow-up path is not yet recorded |
| Profile lifecycle | Core startup scan, periodic refresh, registry invalidation, restart/manual-scan recovery, bounded state cache, and atomic replacement | Complete discovery of every Home Assistant registry, Assist surface, integration, automation, script, and scene shape |
| Providers | Compatible typed Jev HTTP; native OpenRouter Decisions for parameter-free choices; optional OpenRouter chat or typed HTTP fallback | Provider credentials, arbitrary HA-agent execution, or unbounded tool delegation |

The provider contracts are intentionally separate:

| Route | Configuration boundary | Wire behavior and limit |
| --- | --- | --- |
| Direct TypeSafe System One | App option `jev_provider: typesafe` plus `jev_endpoint`, `jev_api_key`, and `jev_model`; standalone/runtime clients may use `JEV_PROVIDER`, `JEV_BASE_URL` or `JEV_ENDPOINT`, `JEV_API_KEY`, and `JEV_MODEL` | Normalizes the base URL to `/v1/systemone` and exchanges typed `answers`; typed parameter questions are available when the capability schema can express them. |
| OpenRouter Decisions | App options: exact `jev_endpoint` `https://openrouter.ai/api/alpha/decisions`, `jev_model`, and `jev_api_key`; use `jev_hosted_allowed` | Translates OpenRouter `answers` into one bounded route/capability proposal. The native adapter is parameter-free and clarifies parameterized actions. |
| Generic typed Jev | A custom `jev_endpoint` plus `jev_api_key` | Must return Switchboard's typed `decision` contract. It is not an OpenAI chat-completions endpoint. |
| OpenAI-compatible fallback | `fallback_provider: openrouter` or `openai_compatible`, `fallback_endpoint`, `fallback_api_key`, and `fallback_model` | Uses a chat-completions base URL or full path, normalizes `/chat/completions`, rejects tool calls, and returns bounded prose or one offered capability proposal. |

The checked-in Supervisor manifest exposes the Jev provider selector, endpoint,
model/key, and fallback fields. `JEV_BASE_URL` remains a runtime environment
input for an explicitly managed client path; the App uses `jev_endpoint` for
the configured TypeSafe base URL or other Jev endpoint. A fallback is never a
Home Assistant agent: it
cannot call services, invent capability IDs, or bypass Core validation.

## Supported interfaces

| Interface | How Switchboard fits |
| --- | --- |
| Home Assistant OS / Supervisor | Install the `HA Switchboard` App. It hosts the gateway behind Supervisor ingress. |
| Home Assistant Core | Install the `ha_switchboard` custom integration through HACS or manually. It provides the Conversation entity and execution boundary. |
| Home Assistant Assist | The integration exposes a native conversation surface that can be selected by an Assist pipeline when configured in Home Assistant. |
| Wyoming, ESPHome, voice satellites, and STT/TTS | Keep using the existing voice pipeline. Those surfaces feed Home Assistant; Switchboard operates behind the conversation layer. |
| Dashboards and companion apps | Keep using existing cards, dashboards, and apps. Text can continue to enter Home Assistant's conversation surface. |
| Home Assistant Container | Run the same gateway image with `standalone/compose.yaml`; connect it to a separately managed Home Assistant instance. |
| HACS | HACS is a custom-integration store. On Home Assistant OS/Supervised, its separate `Get HACS` App is a one-shot bootstrapper that installs the HACS integration; HACS itself does not manage Supervisor Apps. |

Switchboard is not a dashboard, wake-word engine, STT engine, TTS engine, Wyoming server, or replacement for Home Assistant Assist.

## Native Home Assistant fast path

Home Assistant remains the front door and the authority for built-in intent
matching. Switchboard does not replace native Home Assistant Conversation or
Assist handling, and Jev is not required for every simple command. A clear
native intent can complete through Home Assistant's own fast path; a local
read-only answer inside the Switchboard Conversation entity also bypasses a
provider call.

Switchboard is an additional bounded routing layer for requests that need more
judgment. Jev is most useful for ambiguous, compound, or higher-risk requests:
it chooses among the opaque capabilities already offered by Core, while Core
still validates, confirms, executes, and verifies. An eligible fallback is for
open-ended requests Jev cannot answer; it returns bounded prose or one
proposal, never an alternate Home Assistant agent or service executor.

Native channels remain in place around this boundary:

- Assist pipelines used by the Home Assistant mobile app and dashboard;
- voice satellites and Wyoming/ESPHome pipelines;
- Home Assistant's native Conversation entity; and
- the `conversation.process` service/API used by dashboards, companion apps,
  and other integrations.

Choose **HA Switchboard** as the Conversation agent only for the Assist
pipeline or Conversation calls that should use this routing layer. Other native
intent handlers and conversation agents remain independent.

## Install on Home Assistant OS

The App and Core integration are intentionally separate artifacts.

1. After the App release is published, add
   `https://github.com/grayslawson/ha-switchboard` in **Settings → Apps → App
   store → ⋮ → Repositories**, then install and start **HA Switchboard**. The
   local `0.2.0` source candidate is not proof that this App repository or its
   image is currently installable. For local development, use the disposable
   harness described below instead.
2. Configure the App as described in [app/DOCS.md](app/DOCS.md): use `adapter_only`, keep `ingress_only: true`, set a long random `gateway_token`, and start with `local_only` privacy.
3. Install the separate `ha_switchboard` Core integration through HACS or by copying `custom_components/ha_switchboard/`. HACS requires the exported GitHub repository to be reachable; manual copy is the local source path. Add it from **Settings → Devices & services → Add integration** and accept Supervisor discovery. If discovery is unavailable, use the discovered App host and port with the same token.
4. In **Settings → Voice assistants**, choose **HA Switchboard** as the Conversation agent for an Assist pipeline.
5. Open the App Web UI, choose **Scan Home Assistant now**, and wait for profile status to become `active`.
6. Send a read-only test request first, then a low-risk exposed-device request. The App alone is not an Assist agent and does not create Home Assistant device entities.

The App uses Supervisor ingress on port `8099`, stores its data under `/data`, and is declared for `amd64` and `aarch64`. It does not copy the integration into `custom_components` for you.

## Install the Core integration (optional for App-only use)

HACS is not required to install or run the Supervisor App. It is one way to
install the separate `ha_switchboard` Core integration, which is required only
for the full Conversation/Assist path. Until that integration is accepted into
HACS's default catalog, add [`grayslawson/ha-switchboard`](https://github.com/grayslawson/ha-switchboard) as a HACS **Integration** custom repository, or install `custom_components/ha_switchboard/` manually.

The repository metadata is deliberately minimal: `hacs.json` enables README
rendering and release-archive installation, while `repository.yaml` names the
repository, URL, and maintainer. Those files make the source HACS-shaped; they
do not prove HACS validation, default-catalog acceptance, or a public GitHub
release. HACS installs the Core integration only; it does not install or update
the Supervisor App.

Install **HA Switchboard**, restart Home Assistant, and add it from **Settings → Devices & services → Add integration**. The integration stores the gateway URL and token in a Home Assistant config entry; do not put either value in YAML committed to source control.

For HACS packaging and release expectations, see [`hacs.json`](hacs.json) and [docs/RELEASE.md](docs/RELEASE.md).

## Run standalone with Compose

This path is for Home Assistant Container or users who want to run the gateway separately. It uses the same image as the App and does not provide Supervisor ingress.

```bash
git clone https://github.com/grayslawson/ha-switchboard.git
cd ha-switchboard

# Set values in your shell or an untracked .env file. Do not commit them.
export JEV_ENDPOINT=""
export JEV_API_KEY=""
export JEV_MODEL="typesafe/jev-1.13"
export PRIVACY_MODE="local_only"
export FALLBACK_PROVIDER="disabled"
export FALLBACK_ENDPOINT=""
export FALLBACK_MODEL=""
export FALLBACK_API_KEY=""
export GATEWAY_TOKEN="$(openssl rand -hex 32)"

docker compose -f standalone/compose.yaml up -d
curl http://127.0.0.1:8099/healthz
```

Compose passes `JEV_MODEL`, `PRIVACY_MODE`, and the separate
`FALLBACK_PROVIDER`, `FALLBACK_ENDPOINT`, `FALLBACK_MODEL`, and
`FALLBACK_API_KEY` settings. `PRIVACY_MODE` defaults to `local_only`, so a
hosted Jev endpoint remains blocked unless you explicitly choose a hosted
privacy mode. Hosted fallback also requires `hosted_allowed`; `local_only`
blocks hosted Jev and hosted fallback, while `jev_hosted_allowed` permits
hosted Jev but not hosted fallback. `fallback_provider: disabled` sends no
fallback request. Protect the published port with your own network boundary
and gateway token; Compose has no Supervisor ingress boundary.

The configured App image reference is
[`ghcr.io/grayslawson/ha-switchboard`](https://ghcr.io/grayslawson/ha-switchboard).
This checkout does not prove that a matching public tag or digest exists, is
multi-architecture, or carries the current source revision. Verify those
external artifacts before installing; an image reference in `app/config.yaml`
is not publication evidence.

## Configuration

### App options

The Supervisor App exposes these options. The full values-and-troubleshooting
guide is in [app/DOCS.md](app/DOCS.md).

| Option | Purpose |
| --- | --- |
| `ingress_only` | Keep `true`. The WebUI is ingress-only; direct `/v1/*` Core calls require the matching `gateway_token` and do not require this option to be disabled. |
| `gateway_mode` | Use `adapter_only`. `supervisor_read_only` is a legacy persisted value; startup migration normalizes it to `adapter_only` and records an internal compatibility marker. It is not a current schema choice. |
| `jev_provider` | `disabled` by default; choose `typesafe`, `openrouter`, or `compatible` to match the Jev wire contract. |
| `jev_endpoint` | For `typesafe`, use a TypeSafe base URL or `/v1/systemone`; for `openrouter`, use `https://openrouter.ai/api/alpha/decisions`; for `compatible`, use a service that returns Switchboard's typed decision contract. A public image may predate the native adapter; verify the target tag. |
| `jev_model` | `typesafe/jev-1.13` for OpenRouter Decisions or the configured TypeSafe model; compatible typed services may ignore it. |
| `jev_api_key` | Credential for the configured Jev service; leave blank with no endpoint. This is not the gateway token. |
| `gateway_token` | A long random bearer token for the Core integration and other direct callers. Use the same value in the Integration configuration. |
| `profile_refresh_minutes` | Use `15`; accepted range is 1–1440. The Core integration reads this App setting and schedules complete-profile reconciliation. Use **Scan Home Assistant now** for an explicit scan. |
| `privacy_mode` | Use `local_only` by default. `jev_hosted_allowed` is for a working hosted Jev adapter; `hosted_allowed` also permits hosted downstream routes. |
| `fallback_provider` | `disabled` by default. Choose `openrouter` or `openai_compatible` for the generic OpenAI-compatible chat-completions adapter, or `typed_http` for a Switchboard-compatible route endpoint. |
| `fallback_endpoint` / `fallback_model` / `fallback_api_key` | Configure the chosen fallback separately from Jev. For OpenRouter, use `https://openrouter.ai/api/v1/chat/completions`, a chat-model ID, and its API key. A typed HTTP route uses the Switchboard handoff contract. The legacy persisted `fallback_base_url` name is migrated to `fallback_endpoint`; it is not a current App option. |

Keep credentials in Supervisor options or the deployment's runtime secret mechanism. Never commit them to Compose files, fixtures, logs, or the repository.

The App is the gateway, but `gateway_token` protects HTTP calls into that
gateway. Supervisor ingress authenticates the App UI; the Core integration
calls the discovered internal URL and sends the token. The token is not an
OpenRouter key. Generate one with
`openssl rand -hex 32` and copy the same value into the App and the HA
Switchboard Integration.

### OpenRouter and Jev

OpenRouter's Jev Decisions endpoint is `https://openrouter.ai/api/alpha/decisions`.
The native adapter in this worktree sends its required model, `state`, and
typed `questions`, then translates `answers` into one bounded route and
capability proposal. Set `jev_model` to `typesafe/jev-1.13`, supply an
OpenRouter key in `jev_api_key`, and select `jev_hosted_allowed` privacy mode.
Only parameter-free controls are supported through this adapter. Unsupported
or ambiguous requests need a configured eligible fallback or clarification. A
public image may predate this adapter; verify the target tag. Do not use
`/api/v1/chat/completions` as `jev_endpoint`. See the
[OpenRouter API specification](https://openrouter.ai/openapi.json),
[Typesafe model page](https://openrouter.ai/typesafe), and the [App guide](app/DOCS.md).

Fallback is opt-in. The `openrouter` fallback is a generic OpenAI-compatible
chat-completions adapter; its default endpoint is
`https://openrouter.ai/api/v1/chat/completions`, and it requires
`fallback_model` plus `fallback_api_key` when the service requires
authentication. It also requires `privacy_mode: hosted_allowed`;
`jev_hosted_allowed` permits hosted Jev but not a hosted fallback. You can
instead configure a local typed HTTP route subject to the
same bounded proposal checks. Switchboard cannot safely call an arbitrary Home
Assistant conversation agent as a fallback: that agent might execute its own
actions outside Switchboard's checks. It needs a typed adapter that returns a
proposal or prose to Switchboard, not independent device control.

### Gateway API

The current gateway exposes a deliberately small HTTP surface:

```text
GET  /healthz                 liveness
GET  /readyz                  profile and monitor readiness
GET  /v1/profile/status       profile revision and stale sections
POST /v1/profile/reconcile   atomically replace the sanitized profile
POST /v1/profile/invalidate   mark affected profile sections stale
POST /v1/assist/process      process one bounded conversation request
```

The Core integration uses the status, reconcile, and process endpoints. Adapter authors can use the profile endpoints to connect another discovery or event source, but raw Home Assistant entity IDs must remain on the adapter side.

## First-use examples

Once a profile is current and a compatible Jev service is configured, ordinary requests can follow the normal Home Assistant conversation flow:

```text
“Turn on the kitchen lights.”
“Turn all the lights on.”
“Pause the living-room media player.”
“What is the current state of the office switch?”
```

The exact result depends on the current profile, exposed capabilities, Home Assistant state, and policy. A request may execute, answer, ask for clarification or confirmation, delegate, or refuse. If the profile is stale, Switchboard refuses writes until the adapter reconciles a complete current snapshot.

Parameterized controls such as “set the bedroom temperature to 20 degrees”
are supported by the Core capability schema and execution checks, but the
current Jev question set does not elicit those values. They require a
compatible Jev service that returns the typed parameters (or another adapter
that supplies them); an OpenRouter Decisions endpoint alone is not enough.

For a low-level contract test without a live Home Assistant instance:

```bash
python3 -m compileall app/ha_switchboard custom_components/ha_switchboard
pytest -q tests
```

## Keeping the capability profile current

The profile is versioned and fingerprinted by section. Changes to entity or device registries, areas, floors, labels, exposed entities, services, routines, Assist surfaces, reconnects, and restarts can invalidate affected sections. The gateway reports pending invalidations through `/v1/profile/status`.

The Core integration reads the App's refresh interval and reconciles the
profile on that schedule. For first use, **Open Web UI → Scan Home Assistant now** requests a full
reconciliation; wait for the profile to return to `active`. This requires the
Core integration to be installed and running.

An adapter should:

1. observe Home Assistant registry/state/Assist changes;
2. call `/v1/profile/invalidate` with the relevant event;
3. read a fresh, complete snapshot from Home Assistant; and
4. call `/v1/profile/reconcile` to activate one atomic replacement profile.

The checked-in read-only scanner demonstrates the intended discovery boundary. It reads `/api/config`, `/api/states`, and `/api/services`, keeps the token in memory, and emits a compiled profile without a write method:

```bash
python3 tools/ha-switchboard-scan.py \
  --url http://homeassistant.local:8123 \
  --token-file /run/secrets/ha_token \
  --read-only \
  --output profile.json
```

The scanner is a development/adapter utility, not a replacement for a production Home Assistant integration lifecycle.

## Security and privacy boundaries

- Home Assistant credentials, entity IDs, registry access, service execution, and post-action verification belong to the Core integration or another adapter.
- The gateway receives sanitized snapshots, opaque capability identifiers, bounded context, and minimized state.
- Jev and downstream routes receive only the bounded payload permitted by the selected privacy mode and route policy.
- A downstream model cannot choose a provider by name, invent arbitrary capabilities, or bypass confirmation and freshness checks.
- Supervisor App Web UI/static ingress accepts the Supervisor source address only; health/readiness checks remain available for liveness. The App is non-privileged and does not use host networking. Its source manifest does not grant broad Home Assistant API access; runtime discovery and option loading use only the scoped Supervisor self-information and discovery endpoints.
- The standalone deployment has no Supervisor boundary; secure it with your own network controls and a gateway token.

The App follows Home Assistant's [App security guidance](https://developers.home-assistant.io/docs/apps/security/):
no host networking or privileged devices, broad Home Assistant/Supervisor API
access disabled in the source manifest, an unprivileged serving process, a
custom AppArmor profile, and ingress restricted to `172.30.32.2`. See Home
Assistant's [App presentation guidance](https://developers.home-assistant.io/docs/apps/presentation/)
for the AppArmor and ingress requirements.

See [app/DOCS.md](app/DOCS.md) for App-specific behavior and [docs/RELEASE.md](docs/RELEASE.md) for the packaging and acceptance checklist.

## Current limitations and roadmap

The repository intentionally does not claim more than the current implementation provides:

- The direct TypeSafe System One client, OpenRouter Decisions adapter, and generic typed Jev client have different wire contracts. The Supervisor App options select OpenRouter Decisions by its exact URL or a generic typed Jev endpoint; direct TypeSafe selection is an explicitly managed runtime environment path rather than an App-store option.
- The native OpenRouter adapter handles parameter-free controls only. Parameterized controls have Core-side schemas and validation, but the current question flow does not collect their values; a compatible typed service or future value-extraction stage must supply them.
- Explicit plural on/off requests for exposed lights, switches, or fans can form a bounded group of at most 32 targets. Core preflights every member and executes sequentially; a mid-batch failure can leave earlier verified actions in place. Other multi-device actions are not yet supported.
- Clarification, parameter, and confirmation follow-ups are stored only in the Core integration's bounded in-memory context store. Entries are matched to the Home Assistant conversation and user, expire after a short TTL, and are consumed before the follow-up can authorize execution. The current unit coverage proves the store lifecycle; a complete live Assist/E2E acceptance run remains open.
- Exposed script and scene routines can be present in the sanitized profile and offered as descriptive rows, but Core's execution boundary rejects their `activate` operation. They are not an execution claim or a substitute for direct Home Assistant script/scene services.
- OpenRouter and typed HTTP fallback routes are configurable in the App but disabled by default. An arbitrary Home Assistant conversation agent is not a safe drop-in fallback without a typed adapter. If no eligible fallback is configured, Switchboard asks for clarification or refuses an unsafe action.
- The current Core integration provides Supervisor discovery, a Conversation entity, startup/periodic/recovery profile reconciliation, registry invalidation, and the execution/verification boundary. The profile adapter intentionally covers a bounded capability surface rather than every Home Assistant integration.
- The read-only scanner and Core profile adapter cover a useful baseline of entities, services, areas, floors, labels, routines, and exposure state; they do not yet model every Home Assistant integration, automation, device, or Assist surface.
- Voice hardware, dashboards, HACS, Wyoming, ESPHome, and companion apps are compatibility targets—not bundled components.
- The App is marked experimental and has not been presented as a production-ready Home Assistant App or accepted into the default HACS catalog.

The following release gates remain open unless separately recorded with
matching evidence: complete live Assist/E2E coverage, AppArmor enforcement on
the installed App, protected-master ancestry, public mirror/tag and GitHub
Release, GHCR immutable multi-architecture digest and source labels, HACS and
Hassfest validation on the exported tree, provider acceptance, and an
installed App/Core update-and-rollback canary. Local tests, fixtures, metadata,
or a local image cannot close those gates.

Planned work includes richer Home Assistant discovery and change subscriptions, provider adapters with explicit privacy/cost controls, profile management in the App UI, broader capability coverage, and compatibility testing across established voice and dashboard projects.

## Development

Use the official Home Assistant Apps devcontainer for the Supervisor/App loop.
The checked-in `.devcontainer/` configuration runs Supervisor and Home
Assistant locally, with AppArmor enabled when the host kernel supports it.
The repository also includes `.vscode/tasks.json` for starting Supervisor,
installing the local App, rebuilding it, and following its logs.

For a release-safe local build without editing `app/config.yaml`, use the
wrapper below. It copies the worktree to a disposable staging directory,
comments out only the staged `image:` setting (the Home Assistant local-build
requirement), and builds `local_ha_switchboard` under Supervisor:

```bash
tools/local-dev.sh up
tools/local-dev.sh start-ha
# In another terminal:
tools/local-dev.sh wait
tools/local-dev.sh install
tools/local-dev.sh e2e
tools/local-dev.sh logs
# After changing app/**:
tools/local-dev.sh rebuild
```

For repeatable local tests, put literal `NAME=value` lines in an ignored
`.env.local` file at the repository root, for example
`HA_SWITCHBOARD_JEV_ENDPOINT=https://openrouter.ai/api/alpha/decisions` and
`HA_SWITCHBOARD_PRIVACY_MODE=jev_hosted_allowed`. The `configure` and `e2e`
commands load only the documented `HA_SWITCHBOARD_*` option names; explicit
exported variables take precedence. The staging copy excludes `.env.local`.
Do not commit provider keys or gateway tokens. `e2e` applies options and
restarts only the App when these values are present; it does not rebuild
Home Assistant Core or remove its Docker volume.

The local harness can also exercise the same [HACS OS/Supervised download
flow](https://www.hacs.xyz/docs/use/download/download/) used on Home Assistant
OS/Supervised. `install-hacs` adds HACS's official App repository, installs and
runs the one-shot `Get HACS` App, waits for it to write HACS into the disposable
Home Assistant config, and restarts Core. This is layered on the official
[Home Assistant local app testing](https://developers.home-assistant.io/docs/apps/testing/)
devcontainer flow:

```bash
tools/local-dev.sh install-hacs
```

Then open `http://localhost:7123/`, clear the browser cache if needed, and use
`Settings -> Devices & services -> Add integration` to configure HACS with the
GitHub device-auth flow. In HACS, add
`https://github.com/grayslawson/ha-switchboard` as a custom repository of type
`Integration`, then install `HA Switchboard` from HACS. HACS downloads
integrations into the Core config's `custom_components/` directory; it does not
install or update the Switchboard Supervisor App.

For fast iteration on the current checkout, use the explicit local sync after
the HACS setup:

```bash
tools/local-dev.sh sync-integration
```

That copies the current worktree's `custom_components/ha_switchboard/` into the
disposable Core config and restarts Core. It is intentionally separate from
HACS: it tests the current unpushed source, while the HACS UI flow tests the
published repository/release artifact. The HACS bootstrap App can be stopped
or uninstalled after it completes; HACS remains installed as a Core
integration.

The local Supervisor/Core configuration lives in a Docker volume. Removing or
recreating the devcontainer can attach a fresh volume and make Home Assistant
look unconfigured even when the old volume still exists. `rebuild` now uses the
existing container and rebuilds only the App. `down` and `clean` refuse to
remove the container unless `HA_SWITCHBOARD_ALLOW_DEV_RESET=1` is explicitly
set. Take and verify a volume snapshot before using either command. The
release manifest and published-image configuration in the real worktree are
never modified by the local-build staging flow.

For an App/Core update, record the current App digest, Core config entry,
profile status, and verified snapshot first. Update the matching App and Core
artifacts together, refresh the App so Supervisor does not retain a cached
manifest, reconcile the profile, and test a read-only request before a
low-risk control. If migration fails, restore the known snapshot and the
matching previous App/Core pair; do not reset the local volume or roll back
only one half of the pair. This is recovery guidance, not live-canary proof.

The scan button returns an acknowledgement, not a completed profile. Wait for
`profile_reconciled` and an `active` profile before attempting a write. A
healthy `/healthz` or `/readyz` response alone does not prove that Core is
connected or that Assist is configured. During source-only validation, do not
invoke `tools/local-dev.sh` commands that restart/rebuild Core, remove a
volume, or reset the harness; use the compile, test, and release-boundary
checks instead.

With the harness running, open Home Assistant at
`http://localhost:7123/`. The devcontainer maps host port `7123` to the local
Core web server on container port `80`; mapping it to Supervisor's `8123`
endpoint returns a redirect to `http://localhost/` instead of the onboarding
page. The Supervisor observer remains available at `http://localhost:7357/`.
The first run presents Home Assistant's normal onboarding flow. Complete it
only with throwaway local credentials if you want to use the UI; this instance
is disposable and is separate from any production Home Assistant account.
`tools/local-dev.sh e2e` checks Supervisor readiness, both local web endpoints,
the App's `started` state, and the gateway health path from the Supervisor
network source address.

Run the fast local checks with `tools/local-dev.sh check`. The public release
does not need to ship the development-only harness; it includes the source,
tests, and packaging checks instead.

Run the fast local checks:

```bash
python3 -m compileall app/ha_switchboard custom_components/ha_switchboard
python3 -m pytest -q tests
# Private Forgejo checkout: lint the self-hosted workflows.
actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml
python3 tools/check_release_boundary.py
tools/app-image-smoke.sh
```

The image smoke harness needs Podman or Docker and exercises the App locally
without Home Assistant or provider credentials. It verifies root-owned `/data`
preparation followed by a non-root serving process, health/readiness transitions, gateway-token protection,
sanitized profile persistence, and fail-closed state after a container
recreation. The public release tree is intentionally limited to the App, Core
integration, standalone deployment, tests, public CI, and user-facing tooling. See
[docs/RELEASE.md](docs/RELEASE.md) for App/HACS release checks.

The actionlint command applies to the private Forgejo source checkout; the
public export intentionally omits the private `.forgejo/` workflows and their
runner configuration.

## Documentation and license

- [App documentation](app/DOCS.md)
- [App introduction and changelog](app/README.md) · [app/CHANGELOG.md](app/CHANGELOG.md)
- [Release and portability checklist](docs/RELEASE.md)
- [Apache License 2.0](LICENSE)

HA Switchboard is licensed under Apache 2.0.
