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
branch `codex/fix-apparmor-runtime`, candidate `HEAD`
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
