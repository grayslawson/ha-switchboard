# Changelog

All notable App changes will be recorded here.

Release availability is determined by the matching source tag, App image,
and public GitHub release, not by this changelog alone.

## 0.2.0

- Adds the Core conversation agent, automatic and manual capability scans,
  read-only answers, bounded multi-device controls, and diagnostic sensors.
- Adds a native OpenRouter Decisions adapter and configurable fallback routes.
  Hosted fallback requires explicit `hosted_allowed` privacy mode.
- Adds a redacted App Web UI, clearer App options, and local development
  fixtures. The App and Core integration remain separate installations.
- Fixes App discovery, non-root option loading, and AppArmor startup behavior.
- Hardens redaction, provider transport, Core execution checks, and release
  gates. Provider and Home Assistant credentials are never included in model
  request context.
- Keeps the project experimental: confirmation continuation, broad parameter
  extraction, and automatic setup of every Home Assistant surface are not yet
  complete.

## 0.1.3 - 2026-09-19 (unpublished source, included in 0.2.0)

- Added plain-language Supervisor option labels and inline help for connection,
  provider, privacy, scan, and token settings.
- Exposed the configurable fallback options in the local App manifest.

## 0.1.2 - 2026-09-19 (unpublished source, included in 0.2.0)

- Added bounded multi-device on/off requests for exposed lights, switches,
  and fans, with per-member preflight and partial-failure reporting.
- Added optional OpenRouter chat and typed HTTP fallback routes. Hosted
  fallback requires explicit `hosted_allowed` privacy mode.
- Added local read-only state answers and diagnostic sensors for profile
  readiness, capability count, and pending invalidations.
- Added a native OpenRouter Decisions adapter for parameter-free controls.
  Read-only answers and parameter extraction are not yet supported by it.
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

## 0.1.1 - 2026-09-19 (unpublished source, included in 0.2.0)

- Fixed the custom AppArmor profile so the non-root shell entrypoint and Python
  runtime can start under Supervisor protection.
- Hardened the image build to preserve `/run.sh` executable permissions.
- Documented every App option, gateway-token boundary, OpenRouter limitation,
  security model, and startup troubleshooting path.

## 0.1.0 - Public release

- Initial development release of the HA Switchboard gateway App.
- Added Supervisor ingress, least-privilege defaults, and persistent `/data`
  storage.
- Added the Jev-backed typed decision boundary and optional downstream
  handoff contract.
