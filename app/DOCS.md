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

## Install

1. Add `https://github.com/grayslawson/ha-switchboard` as a Home Assistant
   App repository from **Settings → Apps → App store → ⋮ → Repositories**.
2. Install **HA Switchboard**, start it, and wait for the App to report that it
   is running.
3. Configure the App options below.
4. Install `custom_components/ha_switchboard/` through HACS as an Integration
   custom repository, or install it manually.
5. In **Settings → Devices & services → Add integration**, add **HA
   Switchboard**. For an App installed on the same Home Assistant system, the
   default gateway URL is normally:

   ```text
   http://ha-switchboard:8099
   ```

6. Enter the same gateway token in the Integration that you entered in the
   App, then select the resulting Switchboard conversation agent in an Assist
   pipeline.

The App's **Open Web UI** button uses Supervisor ingress. Ingress authenticates
the Home Assistant user; it is separate from the Core integration's direct
HTTP calls to the gateway.

## App options: what to enter

This is the safe starting configuration for the currently published `0.1.x`
implementation:

| Option | Recommended value | What it means |
| --- | --- | --- |
| `ingress_only` | `true` for ingress-only use; `false` for direct Core/adapter calls | When `true`, only Supervisor's ingress source is accepted. Set it to `false` only when the Core integration or another adapter must call the internal gateway URL directly; direct callers then need `gateway_token`. |
| `gateway_mode` | `adapter_only` | The normal mode. The Core integration or another adapter supplies sanitized profiles and owns Home Assistant execution. `supervisor_read_only` is reserved for a separately reviewed read-only adapter path. |
| `jev_endpoint` | Leave blank unless you have a Switchboard-compatible Jev service | The complete HTTP URL of a service implementing Switchboard's typed Jev contract. The current App does not accept an OpenRouter URL directly; see [OpenRouter](#openrouter-and-jev) below. |
| `jev_api_key` | Leave blank when `jev_endpoint` is blank | The API key for the configured Jev service. This is sent as a Bearer credential to that service and is not the gateway token. Do not put it in documentation, YAML committed to Git, logs, or screenshots. |
| `gateway_token` | A long random value | Bearer credential used by the Core integration to call the protected gateway endpoints. Use the exact same value in the HA Switchboard Integration configuration. |
| `profile_refresh_minutes` | `15` | Intended refresh interval for profile maintenance. In `0.1.x`, this does not create automatic Home Assistant discovery; the adapter still has to reconcile a complete profile. |
| `privacy_mode` | `local_only` | Prevents hosted routes from being selected by policy. Use `jev_hosted_allowed` only after configuring a working hosted Jev adapter. Use `hosted_allowed` only when hosted downstream routes are also intentionally enabled. |

For a local smoke test without a compatible Jev service, the options should
look like this. Replace the token placeholder with a value generated locally;
do not paste a real secret into a public issue or README:

```yaml
ingress_only: true
gateway_mode: adapter_only
jev_endpoint: ""
jev_api_key: ""
gateway_token: "<long-random-token>"
profile_refresh_minutes: 15
privacy_mode: local_only
```

For the normal Home Assistant OS App + Core integration arrangement, the Core
integration calls the App's internal hostname directly. Use this variant so
that direct calls are accepted and protected by the shared gateway token:

```yaml
ingress_only: false
gateway_mode: adapter_only
jev_endpoint: ""
jev_api_key: ""
gateway_token: "<the-same-long-random-token-used-in-the-integration>"
profile_refresh_minutes: 15
privacy_mode: local_only
```

Keep `ingress_only: true` when the App is intended to be reachable only from
Supervisor ingress. This is the more restrictive setting and follows Home
Assistant's ingress recommendation. Setting it to `false` does not make the
gateway public: health checks remain available, while direct profile and
conversation calls require the gateway token.

Generate a suitable gateway token on a trusted machine with:

```bash
openssl rand -hex 32
```

The gateway token is optional only when every caller is already confined to a
trusted Supervisor ingress path. It is required for direct calls when
`ingress_only` is `false`, and is recommended for the standalone Compose
deployment. It is not an OpenRouter API key and must not be reused as one.

## Gateway token and Supervisor ingress

The App is the gateway. The token protects the gateway; it does not indicate a
second gateway or another service that must be installed.

There are two independent paths:

| Caller | Path | Authentication boundary |
| --- | --- | --- |
| A person opening the App UI | Supervisor ingress → App | Home Assistant/Supervisor session; the App does not need a second user login for ingress. |
| Home Assistant Core integration or an adapter | Direct HTTP → App gateway | `Authorization: Bearer <gateway_token>` when a token is configured. |

`/healthz` and `/readyz` remain available for health checks. With
`ingress_only: true`, all other requests must come from Supervisor's ingress
source address `172.30.32.2`. With `ingress_only: false`, direct profile and
conversation requests must carry the matching gateway token, while requests
from Supervisor ingress remain accepted. The standalone Compose path
explicitly disables the Supervisor-only restriction and must have its own
network boundary and token.

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

The current Switchboard App does not translate between those two contracts:

- Switchboard posts `utterance`, candidates, bounded context, sanitized state,
  and typed questions directly to `jev_endpoint`.
- Switchboard expects a response containing a typed `decision` object.
- The App configuration has no OpenRouter model field.

Therefore, do **not** enter either
`https://openrouter.ai/api/alpha/decisions` or
`https://openrouter.ai/api/v1/chat/completions` in `jev_endpoint` for the
current release. A translation adapter must be supplied first. Until then,
leave both Jev fields blank; requests fail closed with a Jev-unavailable
response rather than executing an unclassified Home Assistant action.

When an OpenRouter adapter is available, its configuration will use the
OpenRouter API key in `jev_api_key`, the Decisions URL above, and
`privacy_mode: jev_hosted_allowed`. A gateway token is still separate and is
still used between Home Assistant Core and this App.

## Profile readiness

The App deliberately refuses writes until it has a complete current profile.
An adapter must:

1. observe relevant Home Assistant registry, state, Assist, reconnect, and
   restart changes;
2. call `POST /v1/profile/invalidate` for the affected sections;
3. read a fresh complete snapshot; and
4. call `POST /v1/profile/reconcile` with that replacement snapshot.

The endpoints are:

```text
GET  /healthz
GET  /readyz
GET  /v1/profile/status
POST /v1/profile/reconcile
POST /v1/profile/invalidate
POST /v1/assist/process
```

`/readyz` being degraded immediately after installation is expected until the
Core-side adapter has reconciled a profile. A blank Jev endpoint also leaves
the gateway fail-closed for conversation requests.

## Security model

The App follows Home Assistant's [App security guidance](https://developers.home-assistant.io/docs/apps/security/):

- it runs without host networking, privileged devices, or Home Assistant and
  Supervisor API access in the default adapter-only mode;
- it runs as an unprivileged numeric container user;
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

This means the App image is older than the startup-permission fix or the
Supervisor is still using a cached image. The App's custom AppArmor profile
must allow `/run.sh`, `/bin/sh`, the Alpine BusyBox shell, and the Python
entrypoint. Update the App repository, install the newer App version, and
restart it. If Supervisor still reports the old image, stop the App, refresh
the repository, update/reinstall the App, and start it again.

If the error persists on the repaired image, inspect the host's AppArmor audit
events:

```bash
journalctl _TRANSPORT=audit -g 'apparmor='
```

Do not solve this by disabling AppArmor or protection mode. Home Assistant
recommends a custom profile and least-privilege defaults for secure Apps.

### Gateway unavailable from the Core integration

Confirm that the Integration gateway URL is `http://ha-switchboard:8099` (or
the URL appropriate to the deployment), set the App's `ingress_only` option to
`false` for a direct internal caller, and ensure that the Integration's
gateway token exactly matches the App option. Health and readiness do not
prove that the protected conversation endpoint accepts the Integration's
credentials.

### Jev unavailable or invalid response

Confirm that `jev_endpoint` is a real Switchboard-compatible endpoint. An
OpenRouter Chat Completions or Decisions URL cannot be used directly by the
current App. Check the App log for the status transition, but never log or
paste the API key itself.

## License

HA Switchboard is distributed under the Apache License 2.0. Read the complete
terms in the repository [`LICENSE`](../LICENSE) file.
