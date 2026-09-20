# T149 External Validation Worker Evidence — 2026-09-20

Status: **partial; public export and static HACS shape passed, while Hassfest
and HACS acceptance remain pending**. This
worker performed bounded read-only validation of the current checkout's
public export. It did not publish, push, tag, authenticate to, or mutate an
external repository, and it did not use or record credentials.

## Scope and baseline

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Branch: `codex/fix-apparmor-runtime`.
- `HEAD`: `bd38f47486af5ffad16e03809179b384406a444d`.
- The worktree was already dirty across workflows, source, tests, and
  specifications. Those changes were preserved. This worker owns only this
  evidence file.
- Required pd-nixos preflight was attempted with `just agent-preflight`; it
  returned `error: no justfile found` because this nested HA Switchboard
  worktree has no pd-nixos `Justfile`.

## Public export and local metadata checks

| Check | Result | Exact command and sanitized result |
| --- | --- | --- |
| Public export | passed | `python3 tools/ha-switchboard-export-public.py "$EXPORT_DIR"` — `public export: PASS (202 tracked files)`. The temporary export contained 125 regular files after the explicit private-path exclusions. |
| Export boundary | passed | `python3 tools/check_release_boundary.py --root "$EXPORT_DIR"` — `release boundary: PASS`; `.agents`, `.forgejo`, `.github`, `.specify`, `specs`, and `AGENTS.md` were absent from the export. |
| Local HACS-shaped metadata | passed | A read-only Python check parsed `hacs.json`, `repository.yaml`, and `custom_components/ha_switchboard/manifest.json`, verified one integration and the required manifest keys — `metadata/structure: PASS`. This is static metadata evidence only, not HACS validation. |
| Working-tree whitespace | passed | `git diff --check` — exit `0`. |

The exporter uses `git ls-files`; therefore untracked worktree files were not
included in this public-export check. That is the behavior of the checked-in
exporter and is recorded here so this result is not mistaken for a full dirty
working-tree release.

## Hassfest

| Gate | Result | Exact command and result |
| --- | --- | --- |
| Hassfest executable | pending / unavailable | `command -v hassfest` — exit `1`; no local `hassfest` executable is installed. |
| Hassfest on exported tree | passed | `timeout 180s podman run --rm --workdir /github/workspace --volume "$EXPORT_DIR:/github/workspace:ro" ghcr.io/home-assistant/hassfest@sha256:66b55a8ce14cdcf0c200dd4dab1f3228ac8d3f6e0404ec710a0d8a79b296eba4` — exit `0`; `Integrations: 1`; `Invalid integrations: 0`. |

The run used the exact pinned image in `.forgejo/workflows/validation.yml` and
`.forgejo/workflows/mirror-public.yml`. The export was mounted read-only. No
Home Assistant, GitHub, HACS, provider, registry, or repository credentials
were passed.

The official Home Assistant developer material documents Hassfest as a GitHub
Action; this repository additionally pins and runs the Hassfest container for
the exported tree. The successful container result is local exported-tree
evidence, not proof of a public mirror or release.

## HACS

| Gate | Result | Exact evidence and reason |
| --- | --- | --- |
| HACS executable | pending / unavailable | `command -v hacs` — exit `1`; no local `hacs` executable is installed. `uvx --version` was available as `uv 0.12.13`, but no official HACS `uvx` command is documented. |
| HACS validation | pending | The checked-in command path in `.forgejo/workflows/hacs.yml` and `.forgejo/workflows/mirror-public.yml` executes `test -n "$GH_MIRROR_TOKEN"`, exports it as `INPUT_GITHUB_TOKEN`, and runs the pinned `ghcr.io/hacs/action@sha256:dc92fdad2f6ffbe74bffb7269d781ea8e064f52d9bb486cdf3925d74e7ab6ebf` against `REPOSITORY=grayslawson/ha-switchboard`, `CATEGORY=integration`, and a public branch/tag ref. `GH_MIRROR_TOKEN` and `INPUT_GITHUB_TOKEN` were both absent from this worker process; no token was supplied and the HACS action was not invoked. |
| HACS local/uvx alternative | pending / not established | The official HACS action documentation describes the GitHub Action and its repository/release/branch validation modes, but does not document a supported `hacs` executable, `uvx` command, or credential-free local container mode. A third-party package/example is not treated as equivalent to the HACS action. |

The local metadata/structure check above does not establish HACS acceptance.
The official HACS requirements also include repository-level facts such as the
public repository/default branch and optional release behavior; those facts
were intentionally not queried because this worker was instructed not to
contact or mutate external repositories.

## Conclusion and remaining gate

Hassfest can be run locally without publishing or credentials using the pinned
container command above, and it passed for the current tracked public export.
HACS has no established credential-free local/`uvx` path in the documented
tooling reviewed here. The configured external HACS gate remains pending until
an authorized run can inspect the published public repository with its
required credential and record the action result. Neither the local HACS
metadata check nor the Hassfest pass is HACS acceptance.

References:

- [HACS GitHub Action documentation](https://www.hacs.xyz/docs/publish/action/)
- [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
- [Home Assistant Hassfest guidance](https://developers.home-assistant.io/blog/2020/04/16/hassfest/)

No workflow, source, task, existing evidence file, external repository, or
Home Assistant environment was changed by this worker.

## Current-worktree reconciliation

The current audit supersedes the older baseline above at `HEAD
bd38f47486af5ffad16e03809179b384406a444d`:

- The exporter now passes with `public export: PASS (202 tracked files)` and
  125 regular files in the temporary export. The exported-tree boundary also
  passes, with `.agents`, `.forgejo`, `.github`, `.specify`, `specs`, and
  `AGENTS.md` absent.
- Static HACS metadata/structure validation passes for exactly one integration,
  the required manifest keys, `hacs.json`, the repository URL, and the brand
  icon. This is not HACS acceptance; the official HACS action was not invoked
  because its token/public-repository gate remains intentionally open.
- The exact pinned Hassfest invocation was run against the read-only export:
  `timeout --kill-after=10s 180s podman run --rm --workdir
  /github/workspace --volume "$EXPORT_DIR:/github/workspace:ro"
  ghcr.io/home-assistant/hassfest@sha256:66b55a8ce14cdcf0c200dd4dab1f3228ac8d3f6e0404ec710d8a79b296eba4` —
  exit `0`; `Integrations: 1`; `Invalid integrations: 0`.

The current local result therefore does not claim Hassfest or HACS acceptance.

## Current branch refresh — 2026-09-20

Fresh bounded checks were run against current `HEAD`
`799efc422b372ecc8117336a904e426126889e80` on
`codex/fix-apparmor-runtime`; the worktree was clean before this evidence
update. The public exporter examined `203 tracked files` and produced `125`
regular files in a temporary export. The exact commands and sanitized results
were:

| Check | Result |
| --- | --- |
| `python3 tools/ha-switchboard-export-public.py "$TMP/public"` | `public export: PASS (203 tracked files)` |
| `python3 tools/check_release_boundary.py --root "$TMP/public"` | `release boundary: PASS` |
| Read-only HACS metadata shape check for `hacs.json`, `repository.yaml`, and `custom_components/ha_switchboard/manifest.json` | `metadata/structure: PASS`; one `ha_switchboard` integration, version `0.2.0`, required manifest keys, and public repository URL present |
| `command -v hassfest`; `command -v hacs` | both unavailable locally |
| `timeout --kill-after=10s 180s podman run --rm --workdir /github/workspace --volume "$TMP/public:/github/workspace:ro" ghcr.io/home-assistant/hassfest@sha256:66b55a8ce14cdcf0c200dd4dab1f3228ac8d3f6e0404ec710a0d8a79b296eba4` | exit `0`; `Integrations: 1`; `Invalid integrations: 0` |
| `actionlint -config-file .github/actionlint.yaml .forgejo/workflows/*.yml` | exit `0`, no diagnostics |
| `python3 -m pytest -q tests/test_release_boundary.py tests/test_release_acceptance.py tests/test_release_workflows.py` | exit `0`; `22 passed` |
| `git diff --check` | exit `0` |

The HACS result remains static shape evidence only. The checked-in HACS path
requires `GH_MIRROR_TOKEN` and invokes the pinned HACS action against the
public GitHub repository; no HACS token was present or supplied, and that
action was not invoked. Hassfest passed only for the read-only local export;
it does not prove public mirror state, HACS acceptance, or an installed
canary. No external repository, registry, or Home Assistant environment was
mutated.
