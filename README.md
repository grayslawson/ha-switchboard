# HA Switchboard

HA Switchboard is a small, local-first control layer for [Home Assistant](https://www.home-assistant.io/). It puts a fast, bounded Jev decision path in front of Home Assistant while preserving the interfaces people already use: Assist, conversation agents, voice satellites, dashboards, and companion applications.

The goal is simple: make everyday home control quick and inexpensive, then hand genuinely open-ended requests to a user-approved traditional LLM when policy says that is appropriate.

> **Project status: experimental (`0.1.2`)**
>
> The gateway, profile model, policy checks, Home Assistant integration contract, and packaging paths are implemented and tested. Automatic discovery, production downstream-provider adapters, and a polished end-user setup flow are still being developed. Read [Current limitations and roadmap](#current-limitations-and-roadmap) before deploying this to a real home.

## Why Switchboard?

Home Assistant is the source of truth and remains the authority that executes actions. Switchboard adds an intelligence and routing layer around it:

- **Fast path:** Jev receives a bounded request and capability context, then returns a typed decision such as read, control, clarify, delegate, or refuse.
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

### Jev-first routing

In this project, Jev is used as a typed decision boundary rather than as a prose chatbot. It is asked bounded questions about the request, available candidates, risk, ambiguity, complexity, and route. It does not produce YAML, credentials, arbitrary tool plans, or Home Assistant service JSON.

If Jev selects `delegate`, Switchboard chooses an eligible downstream route by policy. A traditional model may return bounded prose or one typed capability proposal. Any proposal re-enters the same freshness, confirmation, allowlist, execution, and verification checks. Handoffs are limited to one level to prevent loops.

## Supported interfaces

| Interface | How Switchboard fits |
| --- | --- |
| Home Assistant OS / Supervisor | Install the `HA Switchboard` App. It hosts the gateway behind Supervisor ingress. |
| Home Assistant Core | Install the `ha_switchboard` custom integration through HACS or manually. It provides the Conversation entity and execution boundary. |
| Home Assistant Assist | The integration exposes a native conversation surface that can be selected by an Assist pipeline when configured in Home Assistant. |
| Wyoming, ESPHome, voice satellites, and STT/TTS | Keep using the existing voice pipeline. Those surfaces feed Home Assistant; Switchboard operates behind the conversation layer. |
| Dashboards and companion apps | Keep using existing cards, dashboards, and apps. Text can continue to enter Home Assistant's conversation surface. |
| Home Assistant Container | Run the same gateway image with `standalone/compose.yaml`; connect it to a separately managed Home Assistant instance. |
| HACS | HACS manages only `custom_components/ha_switchboard/`. It does not install or update the Supervisor App. |

Switchboard is not a dashboard, wake-word engine, STT engine, TTS engine, Wyoming server, or replacement for Home Assistant Assist.

## Install on Home Assistant OS

The App and Core integration are intentionally separate artifacts.

1. In **Settings → Add-ons → Add-on store**, open the three-dot menu and add the App repository: [`https://github.com/grayslawson/ha-switchboard`](https://github.com/grayslawson/ha-switchboard).
2. Install **HA Switchboard**, start it, and open its Web UI if desired.
3. Configure the App using the complete [App configuration guide](app/DOCS.md). For the current release, use `adapter_only`, set `ingress_only` to `false` when the Core integration will call `http://ha-switchboard:8099` directly, leave the Jev fields blank unless you have a Switchboard-compatible Jev service, set `profile_refresh_minutes` to `15`, and use `local_only` privacy mode.
4. If you want the full Conversation/Assist path, install the separate Core integration using HACS or a manual copy. HACS is not needed for the App itself.
5. In **Settings → Devices & services → Add integration**, add **HA Switchboard** and enter the gateway URL and the same optional gateway token.
6. Select the resulting Switchboard conversation agent in the Assist pipeline you want to use.

The App uses Supervisor ingress on port `8099`, stores its data under `/data`, and is declared for `amd64` and `aarch64`. It does not copy the integration into `custom_components` for you.

## Install the Core integration (optional for App-only use)

HACS is not required to install or run the Supervisor App. It is one way to
install the separate `ha_switchboard` Core integration, which is required only
for the full Conversation/Assist path. Until that integration is accepted into
HACS's default catalog, add [`grayslawson/ha-switchboard`](https://github.com/grayslawson/ha-switchboard) as a HACS **Integration** custom repository, or install `custom_components/ha_switchboard/` manually.

Install **HA Switchboard**, restart Home Assistant, and add it from **Settings → Devices & services → Add integration**. The integration stores the gateway URL and token in a Home Assistant config entry; do not put either value in YAML committed to source control.

For HACS packaging and release expectations, see [`hacs.json`](hacs.json) and [docs/RELEASE.md](docs/RELEASE.md).

## Run standalone with Compose

This path is for Home Assistant Container or users who want to run the gateway separately. It uses the same image as the App and does not provide Supervisor ingress.

```bash
git clone https://github.com/grayslawson/ha-switchboard.git
cd ha-switchboard

# Set secrets in your shell or an untracked .env file.
export JEV_ENDPOINT="https://your-jev-endpoint.example/decide"
export JEV_API_KEY="replace-me"
export GATEWAY_TOKEN="use-a-long-random-token"

docker compose -f standalone/compose.yaml up -d
curl http://127.0.0.1:8099/healthz
```

Useful variables are `HA_SWITCHBOARD_VERSION` (default `dev`), `HA_SWITCHBOARD_PORT` (default `8099`), and `HA_SWITCHBOARD_DATA` (default `./data`). Protect the published port with your own network boundary and gateway token. The standalone Compose file explicitly disables the Supervisor-only source-address restriction.

The published App image is available at [`ghcr.io/grayslawson/ha-switchboard`](https://ghcr.io/grayslawson/ha-switchboard), with versioned tags and `latest` for the current `master` build. The image is multi-architecture (`amd64` and `arm64`) and carries the GitHub source label used by the release verification job.

## Configuration

### App options

The Supervisor App exposes these options. The full values-and-troubleshooting
guide is in [app/DOCS.md](app/DOCS.md).

| Option | Purpose |
| --- | --- |
| `ingress_only` | `true` accepts only Supervisor ingress (`172.30.32.2`). Set `false` only for direct Core/adapter calls, which then require `gateway_token`. |
| `gateway_mode` | Use `adapter_only`. `supervisor_read_only` is reserved for the separately reviewed read-only adapter path. |
| `jev_endpoint` | Leave unset unless the service implements Switchboard's typed Jev contract. The current App cannot use OpenRouter directly. |
| `jev_api_key` | Credential for the configured Jev service; leave blank with no endpoint. This is not the gateway token. |
| `gateway_token` | A long random bearer token for the Core integration and other direct callers. Use the same value in the Integration configuration. |
| `profile_refresh_minutes` | Use `15`; accepted range is 1–1440. This option does not yet create automatic Home Assistant discovery. |
| `privacy_mode` | Use `local_only` by default. `jev_hosted_allowed` is for a working hosted Jev adapter; `hosted_allowed` also permits hosted downstream routes. |

Keep credentials in Supervisor options or the deployment's runtime secret mechanism. Never commit them to Compose files, fixtures, logs, or the repository.

The App is the gateway, but `gateway_token` protects HTTP calls into that
gateway. Supervisor ingress authenticates the App UI; the Core integration
can call the App's direct internal URL when `ingress_only` is `false` and sends
the token. The token is not an OpenRouter key. Generate one with
`openssl rand -hex 32` and copy the same value into the App and the HA
Switchboard Integration.

### OpenRouter and Jev

OpenRouter's Jev Decisions endpoint is `https://openrouter.ai/api/alpha/decisions`.
It expects a model, `state`, and `questions`, and returns `answers`; the
current Switchboard client sends its own bounded payload and expects a typed
`decision` response. The App also has no model option. Consequently, do not
enter the OpenRouter Decisions URL or `/api/v1/chat/completions` directly in
`jev_endpoint` until an OpenRouter translation adapter is installed. See the
[OpenRouter API specification](https://openrouter.ai/openapi.json),
[Typesafe model page](https://openrouter.ai/typesafe), and the [App guide](app/DOCS.md).

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

Once a profile is current and Jev is configured, ordinary requests can follow the normal Home Assistant conversation flow:

```text
“Turn on the kitchen lights.”
“Set the bedroom temperature to 20 degrees.”
“Pause the living-room media player.”
“What is the current state of the office switch?”
```

The exact result depends on the current profile, exposed capabilities, Home Assistant state, and policy. A request may execute, answer, ask for clarification or confirmation, delegate, or refuse. If the profile is stale, Switchboard refuses writes until the adapter reconciles a complete current snapshot.

For a low-level contract test without a live Home Assistant instance:

```bash
python3 -m compileall app/ha_switchboard custom_components/ha_switchboard
pytest -q tests
```

## Keeping the capability profile current

The profile is versioned and fingerprinted by section. Changes to entity or device registries, areas, floors, labels, exposed entities, services, routines, Assist surfaces, reconnects, and restarts can invalidate affected sections. The gateway reports pending invalidations through `/v1/profile/status`.

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
- Supervisor App ingress accepts the Supervisor source address only. The App is non-privileged, does not use host networking, and does not request the Home Assistant or Supervisor API in its default adapter-only mode.
- The standalone deployment has no Supervisor boundary; secure it with your own network controls and a gateway token.

The App follows Home Assistant's [App security guidance](https://developers.home-assistant.io/docs/apps/security/):
no host networking or privileged devices, no Home Assistant/Supervisor API
access in the default mode, an unprivileged runtime identity, a custom
AppArmor profile, and ingress restricted to `172.30.32.2`. See Home
Assistant's [App presentation guidance](https://developers.home-assistant.io/docs/apps/presentation/)
for the AppArmor and ingress requirements.

See [app/DOCS.md](app/DOCS.md) for App-specific behavior and [docs/RELEASE.md](docs/RELEASE.md) for the packaging and acceptance checklist.

## Current limitations and roadmap

The repository intentionally does not claim more than the current implementation provides:

- The gateway has a typed Jev HTTP client, but Jev itself is an external service; no Jev model is bundled.
- The handoff protocol and policy-aware route selection are implemented, but a production traditional-LLM provider adapter and complete user-facing route configuration are not yet bundled. The default route adapter is empty, so delegation is unavailable until an adapter is supplied.
- The current Core integration provides a Conversation entity and execution boundary. Full automatic discovery/event subscription and a guided profile bootstrap flow remain work in progress.
- The read-only scanner covers a useful baseline of entities and services; it does not yet model every Home Assistant integration, automation, script, scene, area, device, or Assist surface.
- Voice hardware, dashboards, HACS, Wyoming, ESPHome, and companion apps are compatibility targets—not bundled components.
- The App is marked experimental and has not been presented as a production-ready Home Assistant App or accepted into the default HACS catalog.

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

Stop the local harness with `tools/local-dev.sh down`; remove its disposable
copy with `tools/local-dev.sh clean`. The release manifest and published-image
configuration in the real worktree are never modified by this flow.

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
without Home Assistant or provider credentials. It verifies the declared
non-root identity, health/readiness transitions, gateway-token protection,
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
