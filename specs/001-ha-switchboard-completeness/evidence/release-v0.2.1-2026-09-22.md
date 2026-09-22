# v0.2.1 release readback

Date: 2026-09-22 UTC (2026-09-21 EDT)

Status: the protected-master, public mirror, GitHub Release, HACS, GHCR
multi-architecture, and exact published-image runtime gates passed. The
installed public App/Core migration and rollback pair, AppArmor enforcement
parity, and the two optional live follow-up cases remain open.

## Source and workflow identity

- Forgejo protected `master`: `e514d04f6b29b70ee604afbb8c6993209ad2f31d`.
- Forgejo tag `v0.2.1`: the same commit; protected-master ancestry check passed.
- Post-merge workflow runs for that commit all passed: build/publish `5590`,
  CI `5591`, mirror `5592`, and Hassfest `5593`.
- Tag workflow runs all passed: App image build/publish `5594` and mirror/
  Release `5596`.
- The public GitHub mirror refs were read back after publication. The mirror
  uses sanitized mirror commits; the workflow commit marker ties them back to
  the Forgejo source revision above.

## Public package and HACS

- GitHub Release `v0.2.1` is published, non-draft, and non-prerelease.
- Its uploaded HACS asset is `ha_switchboard.zip` (43,471 bytes).
- The pinned HACS action passed all four checks against `v0.2.1`: brands,
  information, integration manifest, and HACS metadata.
- `tools/verify-ghcr-image.py` passed for
  `ghcr.io/grayslawson/ha-switchboard:0.2.1` with exactly `amd64` and
  `arm64`; the verified OCI index digest was
  `sha256:3fbfe446f87216c9e6768bf6f8eb4f82e0243374e83b91b9b249d04dfbfd8fcf`.
  Both platform source/revision labels matched the published source contract.

## Exact published-image runtime readback

An isolated Podman canary pulled the immutable `0.2.1` image without touching
the Home Assistant Supervisor volume. It observed the image's root entrypoint
transition to runtime UID `65532`, `/healthz` HTTP 200, unauthenticated API
HTTP 401, and token-authenticated profile-status API HTTP 200. This proves the
published image boundary and token contract; it is not an installed
Supervisor App/Core pair.

## Preserved local Home Assistant state

The read-only local fixture startup check remained ready after publication:
the existing `hassio` config entry and Conversation agent were present, 28
fixture entities and 28 active capabilities were reconciled, and there were no
pending profile sections or invalidations. The existing Supervisor volume was
verified unchanged. No reset, volume removal, or destructive rebuild was used.

## Remaining gates

- T059: the second-user and natural-TTL live follow-up cases remain opt-in and
  unrun.
- T148/T149/T151: the exact published image was runtime-checked in isolation,
  but a disposable or explicitly approved Home Assistant installation running
  the public App/Core pair has not yet completed the full migration, rollback,
  read-only Assist, and low-risk control matrix. AppArmor enforcement is also
  unavailable in the current WSL/Podman environment.

