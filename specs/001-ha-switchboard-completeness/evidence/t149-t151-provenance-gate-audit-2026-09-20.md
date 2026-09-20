# T149/T151 Provenance Gate Audit — 2026-09-20

Status: **implementation hardened; publication remains blocked**. This audit
used only local source, local tests, and the already-recorded sanitized
read-only provenance observations. No credentials were supplied, printed, or
stored. No repository, registry, tag, release, or Home Assistant environment
was authenticated to or mutated.

## Concrete gate gap and correction

The prior `tools/verify-ghcr-image.py` path required registry username/token
environment variables before validation, had no credential-free offline input,
accepted an absent registry digest as `unknown`, and checked only for missing
expected architectures. It also had no input contract for comparing public
release metadata with the candidate and image facts.

The gate now:

- validates a sanitized `--provenance-file` JSON record without network access
  or credentials;
- permits the explicit `--image` path to use anonymous read-only registry
  access when credentials are unavailable, while still accepting scoped
  credentials in automation;
- requires an immutable `sha256:` index digest and immutable per-platform
  manifest/config identity;
- requires the exact Linux architecture set, including rejection of unexpected
  platforms, and checks every platform's source and revision labels; and
- requires offline records to include matching public repository, `v<image
  tag>`, target/image revision, image digest, architecture set, and published
  non-draft/non-prerelease metadata.

The offline input is a validation record only. It does not fetch, push, tag,
publish, or alter any external object.

## Existing publication blocker

The authoritative worktree is at
`/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`,
branch `codex/fix-apparmor-runtime`, source-bearing candidate
`d513f5ef89333e338ddb4a49306c8b97e6f3b2dc`.

The existing sanitized read-only evidence records that:

- the public mirror `master` and `v0.2.0` tag point to revisions different
  from this candidate (`086eec897a86b6f143ca63ac3663e1b8148b00e3` and
  `42dc7a0ff29ada170075f326f47fe439685ee24c`, respectively);
- the public GHCR `0.2.0` manifest is multi-architecture with `amd64` and
  `arm64`, but its platform revision labels identify
  `59eba81fe84ba31cfb772f5e79ccbdd829ad3b36`, not this candidate; and
- the public release/tag/image agreement and installed App/Core canary remain
  unproven.

Therefore T149 remains pending and T151 remains blocked. The new local gate
does not infer publication from a local branch, mutable tag, or stale public
artifact; a future authorized read-only provenance record must show exact
agreement before publication can proceed.

## Local verification

| Check | Result |
| --- | --- |
| `python3 -m pytest -q tests/test_ghcr_revision_gate.py` | 8 passed |
| `python3 -m py_compile tools/verify-ghcr-image.py tests/test_ghcr_revision_gate.py` | passed |
| `git diff --check` | passed |

Changed files owned by this worker are the verifier, its focused test, and
this evidence record. Existing changes in all other worktree paths were left
untouched.

## Follow-up acceptance audit — current worktree

The release-only follow-up found and corrected two workflow gaps without
touching App/Core source or the Home Assistant runtime:

- `build-app.yml` now requires the tag commit to equal the event/checkout
  revision before GHCR publication, in addition to protected-master ancestry.
- `build-app.yml` runs the bounded source-image E2E after the multi-architecture
  build and before pushing the versioned GHCR image.
- `mirror-public.yml` now runs the tag-gate E2E with
  `timeout --kill-after=10s 300s` and fails if the timeout utility is absent.

Focused local results after those changes: `19 passed` for
`tests/test_release_acceptance.py tests/test_release_workflows.py`, workflow
lint passed with `actionlint -config-file .github/actionlint.yaml
.forgejo/workflows/*.yml`, `bash -n tools/app-image-e2e.sh` passed, and the two
release tools compiled with `python3 -m py_compile`. No external publication,
HACS login, registry login, or Home Assistant restart was attempted.

T149 remains pending and T151 remains blocked: public mirror/tag/image
agreement, HACS, and installed App/Core canary evidence are still absent. The
existing unrelated dirty App/Core/test edits were preserved.

## Current-worktree acceptance reconciliation

The later bounded audit at `HEAD bd38f47486af5ffad16e03809179b384406a444d`
corrected the earlier public-export baseline: the exporter now excludes the
tracked private agent/spec paths and passes with 125 regular files exported.
The static HACS shape check passed, but no HACS action was invoked. The exact
pinned Hassfest reference was run against the read-only export and passed with
`Integrations: 1` and `Invalid integrations: 0`. This is local exported-tree
evidence only; the HACS token/public-repository gate and public release gates
remain open.

## Current branch provenance refresh — 2026-09-20

The authoritative current branch state is clean at
`799efc422b372ecc8117336a904e426126889e80` on
`codex/fix-apparmor-runtime`; its three coordinated version declarations are
all `0.2.0`. The current public comparison was collected anonymously and
read-only:

| Fact | Current observation | Gate meaning |
| --- | --- | --- |
| GitHub mirror `master` | `086eec897a86b6f143ca63ac3663e1b8148b00e3` | Does not equal current `HEAD`; mirror agreement pending |
| GitHub tag `v0.2.0` | `42dc7a0ff29ada170075f326f47fe439685ee24c` | Does not equal current `HEAD`; tag agreement pending |
| GitHub release `v0.2.0` | Non-draft/non-prerelease, published `2026-09-20T02:15:33Z`, zero assets | Existing public release metadata observed, but not a release of current `HEAD` |
| GHCR `0.2.0` | OCI index `sha256:8ed4ec883608a2d11bee20be8e811f80f3306dce123c11851475722e0f6b58b9`; exactly `amd64` and `arm64` | Public multi-platform manifest readable, but exact artifact match not proven |
| GHCR OCI revision labels | `59eba81fe84ba31cfb772f5e79ccbdd829ad3b36` on both platforms | Does not equal current `HEAD`; provenance gate fails closed |
| GHCR OCI source labels | `https://github.com/grayslawson/ha-switchboard` on both platforms | Source URL label agrees |

The command `env -u GHCR_USERNAME -u GHCR_TOKEN -u CR_PAT -u GITHUB_TOKEN
python3 tools/verify-ghcr-image.py --image
ghcr.io/grayslawson/ha-switchboard --tag 0.2.0 --source-url
https://github.com/grayslawson/ha-switchboard --revision
799efc422b372ecc8117336a904e426126889e80` exited `1` with
`ValueError: linux/amd64 image does not match source revision`. This is the
expected fail-closed result for the current branch, not a publication result.

Local public-tree gates were also refreshed: the exporter passed after
examining `203 tracked files` and emitted `125` regular files; the exported
release boundary passed; the pinned Hassfest image passed with
`Integrations: 1` and `Invalid integrations: 0`; static HACS metadata shape
passed; actionlint passed with no diagnostics; the focused release suite
passed `22`; and `git diff --check` passed. `hassfest` and `hacs` executables
are not installed. The HACS action was not invoked because its configured
public-repository token gate was unavailable.

T149 remains **pending** and T151 remains **blocked**. Unresolved gates are
current-`HEAD` public mirror/tag/release agreement, current-`HEAD` GHCR
revision and exact multi-architecture artifact agreement, HACS acceptance,
public App repository/Supervisor acceptance, AppArmor enforcement parity,
migration/rollback, provider acceptance, and installed App/Core canary proof.
No publication, HACS acceptance, exact multi-architecture artifact match, or
installed canary is claimed; no credential or external mutation was used.
