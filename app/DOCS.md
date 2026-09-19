# HA Switchboard App

This App runs the portable gateway. Install the companion integration
separately in Home Assistant Core, then configure its gateway URL and the same
optional gateway token.

The App stores profile snapshots and redacted operational state in `/data`.
It does not read the Home Assistant configuration directory, install custom
components, or execute Home Assistant services. In the default adapter-only
mode it also does not request the Supervisor or Home Assistant API proxy.

Configure Jev and downstream provider credentials through Supervisor options or
the runtime secret mechanism appropriate to the deployment. Never put keys in
the App repository, image, Compose file, fixtures, or logs.

## License

HA Switchboard is distributed under the Apache License 2.0. Read the complete
terms in the repository [`LICENSE`](../LICENSE) file.
