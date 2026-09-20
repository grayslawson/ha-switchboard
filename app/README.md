# HA Switchboard

HA Switchboard is a Jev-backed Home Assistant control layer. It keeps the
fast, bounded decision path close to Home Assistant and can hand open-ended
requests to a user-configured traditional LLM when policy allows it.

This checkout declares version `0.2.0`. A source version alone is not proof
of publication; check for the matching source tag, image, and GitHub release
before installing it from the public package.

Install this App from the HA-Switchboard App repository, then install the
companion `custom_components/ha_switchboard` integration separately in Home
Assistant Core. The App is not a replacement for Home Assistant Assist,
Wyoming/ESPHome satellites, dashboards, or existing conversation agents.

For the complete option-by-option setup guide, gateway-token explanation,
OpenRouter/Jev compatibility note, security model, and troubleshooting, read
[`DOCS.md`](DOCS.md).

Local E2E, image, and host-test results cover this checkout and its disposable
harness. They do not prove a public release or a working HACS install/update
path.

The project is licensed under Apache 2.0. See the repository `LICENSE` file
for the complete terms.
