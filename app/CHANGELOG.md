# Changelog

All notable App changes will be recorded here.

## 0.1.1 - Unreleased

- Fixed the custom AppArmor profile so the non-root shell entrypoint and Python
  runtime can start under Supervisor protection.
- Hardened the image build to preserve `/run.sh` executable permissions.
- Documented every App option, gateway-token boundary, OpenRouter limitation,
  security model, and startup troubleshooting path.

## 0.1.0 - Unreleased

- Initial development release of the HA Switchboard gateway App.
- Added Supervisor ingress, least-privilege defaults, and persistent `/data`
  storage.
- Added the Jev-backed typed decision boundary and optional downstream
  handoff contract.
