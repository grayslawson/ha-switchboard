# HA Switchboard

HA Switchboard is a Jev-backed Home Assistant control layer. When a request is
sent to its Conversation entity, it keeps the bounded decision path close to
Home Assistant and can hand open-ended
requests to a user-configured traditional LLM when policy allows it.

This checkout declares the coordinated source version `0.2.1`. The source
release candidate is published as `v0.2.1`, but the App remains experimental
and is not a complete production release until the remaining live-pair,
rollback, and AppArmor gates in `docs/RELEASE.md` pass. Verify the matching
source tag, multi-architecture image, and GitHub Release before installing it
from the public package.

Install this App from the HA-Switchboard App repository, then install the
companion `custom_components/ha_switchboard` integration separately in Home
Assistant Core. The App is not a replacement for Home Assistant Assist,
Wyoming/ESPHome satellites, dashboards, or existing conversation agents.

For the complete option-by-option setup guide, gateway-token explanation,
OpenRouter/Jev compatibility note, security model, and troubleshooting, read
[`DOCS.md`](DOCS.md).

Local E2E, image, and host-test results cover this checkout and its disposable
harness. The published v0.2.1 artifact also has independent GHCR provenance
and HACS validation; the installed public App/Core migration and rollback
gates remain open. For the detailed acceptance matrix and current open-gate
evidence, see the repository's [release checklist](../docs/RELEASE.md).

In 0.2.1 the App provides the gateway, redacted profile store, readiness and
scan UI, and provider routing. It does not discover Home Assistant entities,
create the Conversation entity, or execute services. The separately installed
Core integration owns those responsibilities and also keeps short-lived,
user-bound, one-time clarification/parameter/confirmation context locally;
that context is not stored in the App or sent to providers. The store's unit
lifecycle is covered in this checkout, while full live follow-up acceptance is
still pending.

Home Assistant's native Assist/Conversation path remains the fast path for
clear built-in intents. Switchboard does not replace Home Assistant intent
matching or require Jev for every simple command. The Core Conversation entity
is an optional bounded routing layer for ambiguous, compound, or higher-risk
requests; an eligible fallback handles open-ended requests with bounded prose
or one proposal. Mobile and dashboard Assist, voice satellites, native
Conversation, and `conversation.process` remain Home Assistant channels around
the App/Core boundary.

The project is licensed under Apache 2.0. See the repository `LICENSE` file
for the complete terms.

For updates, keep the App and Core integration on one compatible versioned
artifact set. Preserve the existing Supervisor/Core volume and config entry,
refresh or reinstall the App to avoid a cached manifest, and verify profile
reconciliation before testing Assist. If the update fails, restore the
verified snapshot and exact previous App/Core pair; do not reset the fixture or
roll back only the App.
