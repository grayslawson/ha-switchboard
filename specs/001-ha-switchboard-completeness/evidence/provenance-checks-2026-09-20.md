# T149 Provenance Worker Evidence — 2026-09-20

Status: **partial; provenance gates remain pending**. This worker performed
read-only checks of the current checkout, public GitHub mirror/tag/release
metadata, and the public GHCR manifest/config labels. No credentials were
used, requested, printed, or written. No repository or registry was pushed,
tagged, published, logged into, or mutated.

## Scope and baseline

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Branch: `codex/fix-apparmor-runtime`.
- Local source candidate at collection: `d513f5ef89333e338ddb4a49306c8b97e6f3b2dc`.
- A later local-only evidence reconciliation commit contains no source/image changes.
- Coordinated local version declarations: App `0.2.0`, Python package `0.2.0`,
  and Core manifest `0.2.0`.
- The worktree was already dirty across workflows, source, tests, and specs;
  the initial status contained 113 entries. Existing changes were preserved.
  This worker owns only this evidence file.
- `just agent-preflight` was attempted and returned `error: no justfile
  found`; this nested HA Switchboard worktree has no pd-nixos `Justfile`.

## Local ancestry versus public artifacts

| Check | Result | Exact command and sanitized result |
| --- | --- | --- |
| Local branch and revision | observed | The source-bearing candidate was `d513f5ef89333e338ddb4a49306c8b97e6f3b2dc`; the current branch may contain a later evidence-only descendant. |
| Local protected-tip ancestry | passed locally | `git merge-base --is-ancestor HEAD 59eba81fe84ba31cfb772f5e79ccbdd829ad3b36` — exit `0`. This is only local object ancestry, not public-mirror proof. |
| Local version metadata | passed | `rg -n '^(version:|  version:)|"version"|version\\s*=' app/config.yaml pyproject.toml custom_components/ha_switchboard/manifest.json app/CHANGELOG.md` — App, Python, and Core declarations each reported `0.2.0`. |

The local branch is therefore distinguishable from the published artifacts:
local `HEAD` is not asserted to be the public release revision merely because
it is an ancestor of a locally known Forgejo protected tip.

## Public mirror refs and release metadata

| Gate | Result | Exact command and sanitized result |
| --- | --- | --- |
| Public mirror refs | pending | `git ls-remote --heads --tags github refs/heads/master refs/tags/v0.2.0` — exit `0`; `refs/heads/master=086eec897a86b6f143ca63ac3663e1b8148b00e3`; `refs/tags/v0.2.0=42dc7a0ff29ada170075f326f47fe439685ee24c`. Neither equals local `HEAD`. |
| Public tag metadata | pending | `curl --fail-with-body --silent --show-error --location --max-time 20 -H 'Accept: application/vnd.github+json' https://api.github.com/repos/grayslawson/ha-switchboard/git/ref/tags/v0.2.0` — exit `0`; public ref `refs/tags/v0.2.0`, object type `commit`, object SHA `42dc7a0ff29ada170075f326f47fe439685ee24c`. |
| GitHub Release metadata | pending | `curl --fail-with-body --silent --show-error --location --max-time 20 -H 'Accept: application/vnd.github+json' https://api.github.com/repos/grayslawson/ha-switchboard/releases/tags/v0.2.0` — exit `0`; tag `v0.2.0`, target `master`, non-draft, non-prerelease, published `2026-09-20T02:15:33Z`, assets `0`. |
| Public repository metadata | observed | `curl --fail-with-body --silent --show-error --location --max-time 20 -H 'Accept: application/vnd.github+json' https://api.github.com/repos/grayslawson/ha-switchboard` — exit `0`; public repository `grayslawson/ha-switchboard`, default branch `master`, not archived. |

The release/tag and public mirror are not treated as matching local source
provenance. No public ref was changed.

## GHCR manifest and source-label availability

The following read-only Python probe used the GHCR Bearer challenge to obtain
an anonymous pull token. It did not use a username, password, package token,
or registry login; the token value was never printed or retained in the
repository.

| Gate | Result | Exact command and sanitized result |
| --- | --- | --- |
| GHCR tag `0.2.0` manifest | pending for this source | `python3 - <<'PY' ... urllib.request ... https://ghcr.io/v2/grayslawson/ha-switchboard/manifests/0.2.0 ... PY` — initial status `401`, Bearer challenge; anonymous token obtained; manifest media type `application/vnd.oci.image.index.v1+json`; digest `sha256:8ed4ec883608a2d11bee20be8e811f80f3306dce123c11851475722e0f6b58b9`. |
| GHCR architectures | available but mismatched | The manifest contained `linux/amd64` digest `sha256:6b5a1730eeb1d2efc557e0c72d7c71df7f0e757bf9484281816082f97f191f20` and `linux/arm64` digest `sha256:f34cd2edab7b85c832d10b9b27878790008c1af0d1412c022bf1c5dc4446c020`. |
| GHCR source labels | available and consistent across platforms | Both platform configs reported `org.opencontainers.image.source=https://github.com/grayslawson/ha-switchboard`. |
| GHCR revision labels | pending/mismatch | Both platform configs reported `org.opencontainers.image.revision=59eba81fe84ba31cfb772f5e79ccbdd829ad3b36`, which is not local `HEAD=d513f5ef89333e338ddb4a49306c8b97e6f3b2dc`. |

The GHCR artifact is publicly readable and multi-architecture, but its
revision label identifies the local protected-tip object rather than this
worker's local branch `HEAD`. The image therefore cannot close the exact
source/image provenance gate for this worker. A local image or mutable tag
would not repair that mismatch.

## Gate disposition and safety

- **T149:** remains pending. Local version declarations and public GHCR
  manifest availability were observed, but public mirror/tag/release and
  GHCR revision provenance do not match this local `HEAD`; installed-canary,
  HACS, Hassfest, and other external/runtime gates are not inferred here.
- **T151:** remains pending. No protected-master/public-mirror/tag/image
  agreement was established for local `HEAD`, and no publication operation
  was authorized or attempted.
- No workflows, source files, tasks, existing evidence files, repositories,
  registries, Home Assistant environments, or credentials were changed.
- Worker-owned changed file: `specs/001-ha-switchboard-completeness/evidence/provenance-checks-2026-09-20.md` only.

## Current branch refresh — 2026-09-20

The earlier collection above is superseded for current-branch comparison by a
fresh read-only pass at `HEAD=799efc422b372ecc8117336a904e426126889e80` on
`codex/fix-apparmor-runtime`. `git status --short --branch` showed no
uncommitted paths; the branch is nine commits ahead of its local Forgejo
tracking ref, whose observed tip is `fcff6e86e729f34d4d01201cafebe3bf86f9cddd`.
The current `HEAD` commit changes only `.forgejo/workflows/mirror-public.yml`,
`specs/001-ha-switchboard-completeness/tasks.md`,
`tests/test_app_image_e2e.py`, `tests/test_release_acceptance.py`, and
`tests/test_release_workflows.py` relative to its parent.

The three coordinated source declarations still agree on `0.2.0`:
`app/config.yaml`, `pyproject.toml`, and
`custom_components/ha_switchboard/manifest.json`. This is local source
evidence only.

| Current read-only gate | Result | Sanitized observation |
| --- | --- | --- |
| Public GitHub mirror refs | pending/mismatch | `git ls-remote --heads --tags github refs/heads/master refs/tags/v0.2.0` exited `0`; `master=086eec897a86b6f143ca63ac3663e1b8148b00e3`, `v0.2.0=42dc7a0ff29ada170075f326f47fe439685ee24c`. Neither equals current `HEAD`. |
| Public GitHub tag/release metadata | observed, not matching | Anonymous GitHub API reads reported tag object `42dc7a0ff29ada170075f326f47fe439685ee24c`; release `v0.2.0` is non-draft/non-prerelease, published `2026-09-20T02:15:33Z`, with zero assets. This does not publish or identify current `HEAD`. |
| GHCR `0.2.0` manifest | available, provenance mismatch | Anonymous Bearer-token pull metadata reported OCI index digest `sha256:8ed4ec883608a2d11bee20be8e811f80f3306dce123c11851475722e0f6b58b9` with exactly `linux/amd64` and `linux/arm64`; both platform source labels are `https://github.com/grayslawson/ha-switchboard`, while both revision labels are `59eba81fe84ba31cfb772f5e79ccbdd829ad3b36`, not current `HEAD`. |
| Current local GHCR verifier | failed closed as expected | With `GHCR_USERNAME`, `GHCR_TOKEN`, `CR_PAT`, and `GITHUB_TOKEN` unset, `python3 tools/verify-ghcr-image.py --image ghcr.io/grayslawson/ha-switchboard --tag 0.2.0 --source-url https://github.com/grayslawson/ha-switchboard --revision 799efc422b372ecc8117336a904e426126889e80` exited `1`: `linux/amd64 image does not match source revision`. |

The GHCR index is publicly readable and advertises both expected Linux
architectures, but exact multi-architecture artifact matching is **not**
proven because both immutable platform revision labels identify an older
revision. No registry credential, login, tag, push, or publication was used.

The current external gates therefore remain open: current-`HEAD` public
mirror/tag/release agreement, current-`HEAD` GHCR label agreement, HACS
acceptance, and an installed App/Core canary. No publication, HACS
acceptance, or installed canary is inferred.
