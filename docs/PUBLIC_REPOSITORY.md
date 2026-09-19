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
public `release.yml` workflow turns those tags into full GitHub Releases, which
is required for HACS to present versioned integration updates.

The App image is built by the private Forgejo workflow on the dedicated
`ha-switchboard` runner and pushed directly to GHCR. GitHub does not rebuild
the image; its public workflow only validates the sanitized mirror and creates
the GitHub Release for a mirrored version tag.

The public export intentionally excludes `.forgejo/`, private specifications,
operator notes, homelab configuration, and any future unallowlisted path. A
new public file must be added to
`tools/ha-switchboard-export-public.py` explicitly before it can be
published.
