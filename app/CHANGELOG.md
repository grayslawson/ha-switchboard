# Changelog

All notable App changes will be recorded here.

## 0.1.2 - 2026-09-19

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

## 0.1.0 - Unreleased

- Initial development release of the HA Switchboard gateway App.
- Added Supervisor ingress, least-privilege defaults, and persistent `/data`
  storage.
- Added the Jev-backed typed decision boundary and optional downstream
  handoff contract.
