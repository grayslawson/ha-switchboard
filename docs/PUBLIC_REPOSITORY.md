# Repository and mirror policy

The private development source is maintained in Forgejo. GitHub is intended to
be the public release mirror at `https://github.com/grayslawson/ha-switchboard`.

The Forgejo `master` branch is the source selected for the public mirror when
the mirror action succeeds. The Forgejo Action in
`.forgejo/workflows/mirror-public.yml` exports only the allowlisted release
tree, runs the release-boundary checker, and then updates GitHub's `master`.
It does not push the private repository history or unknown files.

Configure these repository Action secrets in Forgejo; do not use a token in
source, workflow text, fixtures, or logs:

- `GH_PACKAGE_TOKEN` authenticates the private App build to GHCR.
- `GH_MIRROR_TOKEN` is a narrowly scoped GitHub token with contents write
  access only to `grayslawson/ha-switchboard`.

If `GH_MIRROR_TOKEN` is absent, the mirror job is skipped and the public
repository is not updated.

Version tags matching `v*` are exported to the public repository as well. The
Forgejo mirror workflow creates or updates the corresponding full GitHub
Release through the GitHub API, which is required for HACS to present
versioned integration updates. The public repository intentionally has no
automatic GitHub Actions jobs; Forgejo owns validation, builds, mirroring, and
release publication.

The App image is intended to be built by the private Forgejo workflow on the
dedicated `ha-switchboard` runner and pushed directly to GHCR. GitHub does not
rebuild the image or run release automation. A source mirror, tag, or local
manifest is not evidence that the corresponding image or GitHub Release exists;
verify each artifact separately before announcing a release.

The private source declares version `0.2.0`. Do not describe a source version
as public without verifying its matching tag, multi-architecture image, and
GitHub Release.

## GHCR package association

The package reference `ghcr.io/grayslawson/ha-switchboard` is an external
release artifact only when a matching publication is verified. A release claim
requires checking its version tags, `latest` (when applicable), Linux
`amd64`/`arm64` manifest, and OCI source label against the source revision;
source files and a local build do not establish that proof. A package pushed with the
Forgejo-owned `GH_PACKAGE_TOKEN` is not automatically linked to the GitHub
repository, even when the image label names that repository. Until the owner
connects it in the package page (`Profile → Packages → ha-switchboard →
Connect repository → grayslawson/ha-switchboard`), GitHub's repository sidebar
can show `No packages published` while the image is already pullable.

This is a GitHub package metadata operation, not a reason to delete the image.
Keep the existing tags and digests intact, perform the one-time UI
association, and then verify that `GET
/user/packages/container/ha-switchboard` reports the repository and that the
repository package sidebar displays the image.

The public export intentionally excludes `.forgejo/`, private specifications,
operator notes, homelab configuration, and any future unallowlisted path. A
new public file must be added to
`tools/ha-switchboard-export-public.py` explicitly before it can be
published.

HACS status is separate from mirror status. The local HACS files may be
present before HACS GitHub device authentication is complete; that does not
prove that the exported repository can be installed or updated through HACS.

## Current source status

This checkout records source metadata for `0.2.0` in the App, gateway package,
Core manifest, Docker build metadata, and changelog. It does not record a
successful public mirror, protected-master ancestry, GitHub tag or Release,
GHCR digest, HACS/Hassfest result, or live App/Core canary. Keep those states
separate when preparing a release.

The HACS metadata is intentionally limited to the custom-integration boundary:
`hacs.json` enables README rendering and release-archive installation, and
`repository.yaml` supplies the repository name, URL, and maintainer. These
files do not install the Supervisor App and do not constitute HACS catalog
acceptance.

## Public support boundary

The exported documentation must describe the current implementation, not the
future completeness target. The App and Core integration remain separate:
Core owns Home Assistant credentials, raw entity references, exposure,
follow-up authorization, service execution, and verification; the App stores
sanitized profile data and routes bounded provider requests. The Core-local
conversation context is short-lived, user-bound, and one-time consumed; it is
not an App or provider persistence feature.

Home Assistant's native Assist/Conversation intent matching remains the fast
path for clear simple commands. Switchboard does not replace built-in intent
handlers or require Jev for every request. The Core Conversation entity is an
additional bounded layer for ambiguous, compound, or higher-risk routing. It
is reachable through Assist pipelines used by the mobile app and dashboards,
voice satellites/Wyoming or ESPHome pipelines, the native Conversation
surface, and `conversation.process`. Open-ended requests may use an eligible
fallback, which returns bounded prose or one proposal rather than executing
Home Assistant services.

The provider contracts remain distinct. Direct TypeSafe System One uses the
`/v1/systemone` contract with runtime `JEV_PROVIDER`, `JEV_BASE_URL` or
`JEV_ENDPOINT`, `JEV_API_KEY`, and `JEV_MODEL`; OpenRouter Decisions uses the
exact alpha Decisions URL with the App's `jev_model` and `jev_api_key`; and a
non-OpenRouter Jev URL must return Switchboard's typed `decision` envelope.
Native OpenRouter Decisions is a parameter-free route/capability chooser. It
does not extract brightness, volume, temperature, or HVAC values. The
`openrouter` or `openai_compatible` fallback is a generic OpenAI-compatible
chat-completions adapter
configured with `fallback_endpoint`, `fallback_model`, and
`fallback_api_key`; `typed_http` is a separate Switchboard handoff contract.
Fallback is disabled by default; `local_only` blocks hosted routes,
`jev_hosted_allowed` permits hosted Jev only, and `hosted_allowed` is required
for hosted fallback. None of these routes can execute Home Assistant services
directly.

Exposed script and scene routines may appear as sanitized profile rows, but
their `activate` operation is currently rejected by the Core execution
boundary. They are therefore not advertised as executable Switchboard
controls. Local fixture and E2E output is sanitized disposable-harness
evidence only; it is not proof of public publication, HACS acceptance, or a
live production installation.
