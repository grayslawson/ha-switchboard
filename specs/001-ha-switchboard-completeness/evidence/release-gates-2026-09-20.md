# T149 Release-Gate Evidence — 2026-09-20

Status: **partial; external publication and installed-canary gates remain
pending or blocked**. The safe local source, runtime-read-only, image,
packaging, public-export, release-boundary, and workflow-lint checks passed.
No repository was published or mutated, and the preserved Home Assistant /
Supervisor environment was not reset, restarted, removed, or recreated.

## Scope and baseline

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Branch: `codex/fix-apparmor-runtime`.
- Source revision at the start of this evidence pass:
  `fcff6e86e729f34d4d01201cafebe3bf86f9cddd`.
- Coordinated source version: `0.2.0`.
- The worktree already contained unrelated concurrent changes. They were
  preserved; this worker owns only this evidence file.
- `just agent-preflight` was attempted and returned `error: no justfile
  found`. This nested HA Switchboard worktree has its own `AGENTS.md` and no
  pd-nixos `Justfile`, so the pd-nixos preflight entrypoint is unavailable
  here; this is not a release-gate pass or failure.

## Local source, runtime, image, and packaging gates

| Gate | Result | Exact command and sanitized result |
| --- | --- | --- |
| Python compilation | passed | `python3 -m compileall -q app/ha_switchboard custom_components/ha_switchboard tools` — exit `0`. |
| Full source tests | passed with expected skips | `python3 -m pytest -q tests` — exit `0`; `393 passed, 3 skipped`. The skips were the Home Assistant 2026.9 ConversationEntity runtime dependency, the unavailable Home Assistant config-flow dependency, and the explicitly opt-in live native-miss probe. |
| Release boundary | passed | `python3 tools/check_release_boundary.py` — exit `0`; `release boundary: PASS`. |
| Quality audit | passed | `python3 tools/check_release_boundary.py --quality` — exit `0`; `quality audit: PASS`. |
| Packaging and standalone runtime | passed | `python3 -m pytest -q tests/test_packaging.py tests/test_standalone_runtime.py` — exit `0`; `10 passed`. |
| Release workflow tests | passed | `python3 -m pytest -q tests/test_release_workflows.py tests/test_release_acceptance.py` — exit `0`; `18 passed`. |
| Local App image smoke | passed | `timeout 300s bash tools/app-image-smoke.sh` — exit `0`; local amd64 image health/readiness transitions, unauthenticated boundary, persistence, stale-profile recovery, and non-root serving checks passed. This is local-image evidence only. |
| Bounded local App image E2E | passed | `timeout 300s bash tools/app-image-e2e.sh` — exit `0`; local source image, non-root runtime, ingress and token API contract passed. AppArmor enforcement was not requested. |
| Read-only local startup | passed | `python3 tools/local-fixtures/local_api.py startup` — exit `0`; existing local Supervisor/Core target, options, config entry, conversation agent, 28 fixture entities, active profile, revision, and zero pending sections were observed. |
| Read-only local profile | passed | `docker exec -i busy_cohen docker exec -i homeassistant python3 - profile < tools/local-fixtures/local_api.py` — exit `0`; profile `active`, 28 capabilities, revision present, zero pending/invalidated sections. |
| Read-only config-entry verification | passed | `docker exec -i busy_cohen docker exec -i homeassistant python3 - verify < tools/local-fixtures/local_api.py` — exit `0`; the existing `ha_switchboard` entry was present with Hass.io source, version `1`, and token presence, without exposing connection data. |
| Read-only restart inspection | passed | `python3 tools/local-fixtures/local_api.py restart-cycle` — exit `0`; `restart_requested: false`, `restart_performed: false`, and local lifecycle invariants remained present. |

The runtime commands above are preserved-fixture evidence, not a public
release or installed live-canary claim. No provider request, token rotation,
Core/App restart, or destructive fixture operation was performed.

## Public export and workflow-lint gates

| Gate | Result | Exact command and sanitized result |
| --- | --- | --- |
| Public export | passed | `python3 tools/ha-switchboard-export-public.py "$EXPORT_DIR"` with an empty temporary destination — exit `0`; `public export: PASS (109 tracked files)`. |
| Exported-tree boundary | passed | `python3 tools/check_release_boundary.py --root "$EXPORT_DIR"` — exit `0`; `release boundary: PASS`. |
| Private workflow lint | passed | `actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml` — exit `0`, no diagnostics. |

The export was temporary and was not pushed or copied to a public repository.

## External and installed-release gates

These are not inferred from local tests, metadata, or a local image.

| Gate | Result | Authoritative reason |
| --- | --- | --- |
| Hassfest | pending | No local `hassfest` executable is installed (`command -v hassfest` unavailable). The repository workflow invokes the pinned Hassfest GitHub Action against the exported public tree; that public Action run was not performed in this worker. |
| HACS | pending | No local `hacs` executable is installed (`command -v hacs` unavailable). HACS validation is defined by the public-tree GitHub Action workflow and was not run against a published mirror. |
| GHCR immutable image | blocked/pending | The earlier read-only probe recorded `registry username and token environment variables are required`; that observation predates the current verifier hardening. The verifier now supports credential-free offline records and anonymous read-only registry access when available, but no current published-artifact proof was attempted here. No registry credentials were supplied or printed. |
| Public mirror and tag | pending | Read-only `git ls-remote --heads --tags github refs/heads/master refs/tags/v0.2.0` exited `0` and found both refs, but neither remote ref matched the local source revision. No ref was pushed or changed. The read-only GitHub release query returned `v0.2.0`, non-draft/non-prerelease, with zero assets; matching source/tag/mirror provenance remains unproven. |
| Protected-master ancestry | pending | This evidence pass ran on `codex/fix-apparmor-runtime`, not protected `master`; no tag or publication operation was attempted. The release workflow requires protected-master ancestry before publication. |
| AppArmor enforcement parity | pending | The bounded image E2E explicitly reported `AppArmor enforcement: not requested`; source/image checks passed, but installed enforcement was not proven. |
| Multi-architecture artifact | pending | The local image checks exercised amd64 only. The arm64 manifest and exact GHCR digest/source-revision labels could not be verified because the GHCR credential gate above was unavailable. |
| Supervisor/App repository acceptance | pending | No public App repository metadata refresh, amd64/aarch64 pull, update, or hot-backup/restore acceptance was performed. The local image is not a public Supervisor artifact. |
| Migration and rollback | pending | No candidate public App/Core pair, verified external snapshot, previous immutable artifact, update, or rollback cycle was exercised. The user explicitly prohibited HA environment restart/recreation actions for this worker. |
| Live App/Core canary | blocked/pending | The contract requires an installed candidate App/Core pair at the exact released artifact, complete profile reconciliation, a read-only Assist check, and one low-risk control with post-action verification. The user explicitly prohibited reset/restart/remove/recreate of the HA environment, and no matching published App/Core artifact was available for a canary. The preserved fixture checks above are not canary evidence. |
| Provider/fallback acceptance | pending | No provider credentials or provider bodies were used. Deterministic source/fixture failure tests passed, but live Jev/TypeSafe/OpenRouter/fallback availability and wire-contract acceptance remain external gates. |

## Safety and changed files

- No workflow, task, documentation, App/Core source, or existing evidence file
  was edited.
- No token, password, private key, raw entity ID, conversation ID, provider
  body, or registry credential was written to this record.
- No external repository was published, pushed, tagged, or otherwise mutated.
- No Home Assistant/Supervisor volume or environment reset, restart, removal,
  or recreation was performed.
- Worker-owned changed file: `specs/001-ha-switchboard-completeness/evidence/release-gates-2026-09-20.md` only.

## Reconciliation note — current acceptance tooling

The historical GHCR credential error above is superseded as an implementation
constraint by `t149-t151-provenance-gate-audit-2026-09-20.md`: the offline
provenance path is sanitized and network-free, while the registry path remains
read-only and fails closed on missing or mismatched digest, source, revision, or
architecture facts. It does not establish current public publication.

The current release workflow also binds a tag event to both the checked-out
revision and protected-master ancestry before image publication, and invokes
the pre-publication App image E2E through a 300-second timeout with a
10-second kill grace period. These are local source/workflow gates only; T149
and T151 remain pending for matching public mirror/tag/GHCR/HACS and installed
App/Core canary evidence.

## Follow-up public acceptance audit — current worktree

At `HEAD bd38f47486af5ffad16e03809179b384406a444d`, the bounded package/public
checks produced these sanitized results:

- `python3 tools/ha-switchboard-export-public.py "$EXPORT_DIR"` passed with
  202 tracked source files examined and 125 regular files exported.
- `python3 tools/check_release_boundary.py --root "$EXPORT_DIR"` passed. The
  exporter now explicitly excludes private `.agents/`, `.specify/`, `specs/`,
  and `AGENTS.md` paths that had caused the prior fail-closed export rejection.
- `python3 -m pytest -q tests/test_release_boundary.py
  tests/test_release_acceptance.py tests/test_release_workflows.py` passed:
  `22 passed`.
- `actionlint -config-file .github/actionlint.yaml
  .forgejo/workflows/*.yml` passed with no diagnostics.
- Static HACS metadata/structure validation passed: exactly one integration,
  required HACS manifest keys, `hacs.json`, repository URL, and brand icon.
  This is not HACS acceptance.
- The exact pinned Hassfest invocation passed against the read-only export:
  `timeout --kill-after=10s 180s podman run --rm --workdir /github/workspace
  --volume "$EXPORT_DIR:/github/workspace:ro"
  ghcr.io/home-assistant/hassfest@sha256:66b55a8ce14cdcf0c200dd4dab1f3228ac8d3f6e0404ec710d8a79b296eba4` —
  exit `0`; `Integrations: 1`; `Invalid integrations: 0`.

The HACS token/public-repository gate,
public mirror/tag/GHCR provenance, and installed App/Core canary remain open.
