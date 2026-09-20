# Release Validation Contract

One release is a coordinated artifact set identified by a source revision and
semantic version.

## Required gates

1. Python compilation, focused tests, and full test suite.
2. App image smoke and bounded E2E checks for the supported architecture.
3. Home Assistant runtime fixture: discovery, config flow, startup scan,
   Assist read/control/parameter/confirmation/batch/fallback scenarios.
4. AppArmor, non-root, manifest, ingress, request-bound, and secret-redaction
   checks.
5. Release boundary/public export checks.
6. Workflow lint plus HACS and Hassfest validation.
7. Version consistency across App config, Docker build metadata, Python
   package, Core manifest, changelog, and release tag.
8. Multi-architecture image manifest and source-revision label verification.
9. Protected-master ancestry, public mirror/tag, and release metadata
   verification.
10. Live canary evidence for the installed App/Core pair, kept separate from
    source and CI evidence.
11. Update migration and rollback evidence for one compatible App/Core pair,
    including preserved config-entry/profile state and an identified backup or
    snapshot recovery point.
12. External dependency review for the Supervisor App repository, HACS,
    Hassfest/public mirror, GHCR, and each configured provider/fallback
    contract.

## Failure policy

- A failed mandatory gate blocks publication.
- A known external acceptance dependency is recorded as pending, not described
  as passed.
- A release rollback returns the App and Core integration to one known
  compatible artifact set.
- A cached Supervisor manifest, mutable `latest` tag, local fixture, or local
  image cannot satisfy public publication or live-canary evidence.
- Evidence records command, source/image revision, observed object/state, and
  timestamp without secrets, raw household identifiers, or provider content.
- T148, T149, and T151 remain pending until their external/runtime evidence is
  recorded; source metadata alone cannot close them.
