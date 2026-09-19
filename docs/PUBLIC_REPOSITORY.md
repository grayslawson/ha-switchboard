# Repository and mirror policy

The private development source is maintained in Forgejo. GitHub is the public
release mirror at `https://github.com/grayslawson/ha-switchboard`.

The Forgejo `master` branch is the source of the public mirror. The Forgejo
Action in `.forgejo/workflows/mirror-public.yml` exports only the allowlisted
release tree, runs the release-boundary checker, and then updates GitHub's
`master`. It does not push the private repository history or unknown files.

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

The App image is built by the private Forgejo workflow on the dedicated
`ha-switchboard` runner and pushed directly to GHCR. GitHub does not rebuild
the image or run release automation.

## GHCR package association

The package at `ghcr.io/grayslawson/ha-switchboard` is public and is verified
after every private build for its version tags, `latest` (on `master`), Linux
`amd64`/`arm64` manifests, and OCI source label. A package pushed with the
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
