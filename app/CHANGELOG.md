# Changelog

All notable App changes will be recorded here.

Release availability is determined by the matching source tag, App image,
and public GitHub release, not by this changelog alone.

## 0.2.1 — source release candidate (not published)

- Coordinates the App, Core integration, Python package, and image metadata for
  the next release candidate after the provider-boundary, release-provenance,
  and preserve-first local-runtime hardening pass.
- Adds bounded OpenAI-compatible fallback compatibility for providers that
  reject the optional JSON-schema response hint, while keeping strict
  Switchboard response validation and opaque capability selection.
- Allows an eligible fallback to offer one revalidated proposal when Jev
  refuses or is unavailable, prioritizes explicit named targets within the
  bounded provider context, and discards bounded provider-side explanations.
- Stores only shallow opaque metadata for Core-local clarification and
  confirmation continuations, avoiding nested profile-state failures while
  preserving the same-conversation confirmation, cancellation, and one-shot
  replay checks.
- Makes GHCR provenance verification compatible with registries that omit the
  optional blob digest header by hashing the exact response bytes, while still
  rejecting any supplied digest header that disagrees with the descriptor.
- Fixes the local development rebuild path when Supervisor sees a changed
  App version, and records the event-driven preserve-first App/Core restart
  watcher and disposable v0.2.1 Assist canary evidence.
- Records that the local HA 2026.9 validation environment survives the
  approved App/Core restart sequence without losing its fixtures, config entry,
  gateway token presence, or active profile. Public image, mirror, HACS, and
  installed-canary evidence remains an external release gate.

## 0.2.0 — source release candidate (not published)

- Adds the Core Conversation agent, automatic and manual capability scans,
  local read-only answers, bounded multi-device controls, and diagnostic
  sensors. Home Assistant's native intent matching and Assist/Conversation
  channels remain the simple-command fast path; Switchboard is an additional
  bounded routing layer.
- Adds a native OpenRouter Decisions adapter and configurable fallback routes.
  Hosted fallback requires explicit `hosted_allowed` privacy mode.
- Adds a redacted App Web UI, clearer App options, and local development
  fixtures. The App and Core integration remain separate installations.
- Fixes App discovery, non-root option loading, and AppArmor startup behavior.
- Hardens redaction, provider transport, Core execution checks, and release
  gates. Provider and Home Assistant credentials are never included in model
  request context.
- Keeps the project experimental: Core-local clarification/parameter/
  confirmation continuation is bounded and unit-tested but lacks complete live
  Assist/E2E acceptance, native OpenRouter Decisions does not extract action
  parameters, script/scene activation is held out of Core execution, and
  automatic setup of every Home Assistant surface is not provided.
- Uses one coordinated version across the App, image, Python package, Core
  manifest, and this changelog. This entry is source metadata only; it does
  not claim a public tag, GHCR digest, GitHub Release, HACS acceptance, or
  live App/Core canary.

The coordinated source authorities are `app/config.yaml` and `app/Dockerfile`
for the App/image, `app/ha_switchboard/__init__.py` and `pyproject.toml` for
the gateway package, and `custom_components/ha_switchboard/manifest.json` for
Core. At the time of the historical 0.2.0 entry, these authorities all read
`0.2.0`; the current candidate is recorded at the top of this changelog.

## 0.1.3 - 2026-09-19

- Added plain-language Supervisor option labels and inline help for connection,
  provider, privacy, scan, and token settings.
- Exposed the configurable fallback options in the local App manifest.

## 0.1.2 - 2026-09-19

- Added bounded multi-device on/off requests for exposed lights, switches,
  and fans, with per-member preflight and partial-failure reporting.
- Added optional OpenRouter chat and typed HTTP fallback routes. Hosted
  fallback requires explicit `hosted_allowed` privacy mode.
- Added local read-only state answers and diagnostic sensors for profile
  readiness, capability count, and pending invalidations.
- Added a native OpenRouter Decisions adapter for parameter-free controls.
  Read-only answers are served from Core's local snapshot; the native adapter
  does not extract action parameters and asks for clarification instead.
- Added a redacted App Web UI with profile status and a manual scan request.
  Core scans on startup and detects App restarts or manual requests without
  waiting for the periodic refresh interval.
- Added bounded App log events for startup, profile reconciliation, scans,
  decision outcomes, and provider HTTP failures; no credentials or raw
  utterances are logged.
- Allowed the Alpine dynamic loader, system libraries, libpython, and Python
  extension modules to be read and memory-mapped under the custom AppArmor
  profile. This fixes startup failures that appeared as missing
  `libpython3.12.so.1.0` and `Py_BytesMain` relocation errors.
- Added a packaging regression check and documented the AppArmor diagnosis.

## 0.1.1 - 2026-09-19

- Fixed the custom AppArmor profile so the non-root shell entrypoint and Python
  runtime can start under Supervisor protection.
- Hardened the image build to preserve `/run.sh` executable permissions.
- Documented every App option, gateway-token boundary, OpenRouter limitation,
  security model, and startup troubleshooting path.

## 0.1.0 - Initial development release (availability external)

- Initial development release of the HA Switchboard gateway App.
- Added Supervisor ingress, least-privilege defaults, and persistent `/data`
  storage.
- Added the Jev-backed typed decision boundary and optional downstream
  handoff contract.
