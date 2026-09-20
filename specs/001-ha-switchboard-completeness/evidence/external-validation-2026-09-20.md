# T149 External Validation Worker Evidence — 2026-09-20

Status: **partial; Hassfest passed locally, HACS remains pending**. This
worker performed bounded read-only validation of the current checkout's
public export. It did not publish, push, tag, authenticate to, or mutate an
external repository, and it did not use or record credentials.

## Scope and baseline

- Worktree: `/home/deploy/.local/state/pd-nixos/worktrees/ha-switchboard-ci-hardening`.
- Branch: `codex/fix-apparmor-runtime`.
- `HEAD`: `fcff6e86e729f34d4d01201cafebe3bf86f9cddd`.
- The worktree was already dirty across workflows, source, tests, and
  specifications. Those changes were preserved. This worker owns only this
  evidence file.
- Required pd-nixos preflight was attempted with `just agent-preflight`; it
  returned `error: no justfile found` because this nested HA Switchboard
  worktree has no pd-nixos `Justfile`.

## Public export and local metadata checks

| Check | Result | Exact command and sanitized result |
| --- | --- | --- |
| Public export | passed | `python3 tools/ha-switchboard-export-public.py "$EXPORT_DIR"` — `public export: PASS (109 tracked files)`. The temporary export contained 90 regular files after the exporter exclusions. |
| Export boundary | passed | `python3 "$EXPORT_DIR/tools/check_release_boundary.py" --root "$EXPORT_DIR"` — `release boundary: PASS`; `.forgejo` and `.github` were absent from the export. |
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
