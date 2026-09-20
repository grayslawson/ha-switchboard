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
