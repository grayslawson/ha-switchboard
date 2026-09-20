# Profile Reconciliation Contract

## Snapshot

A complete snapshot contains bounded sections for:

- exposed entity capabilities
- supported service operations
- area, floor, label, and group context
- routine/scene/script/media/climate metadata where supported
- Assist exposure and conversation-surface context
- current sanitized state/availability
- section fingerprints and source generation

Each capability has an opaque ID, a safe display label, domain/operation,
availability, parameter schema, risk class, and verification kind. The Core
adapter retains the mapping to raw entity IDs.

## Event triggers

The Core adapter must treat these as invalidation signals:

- Home Assistant startup and restart
- Core/App reconnect or gateway generation change
- entity, device, area, floor, label, and group registry changes
- Assist exposure or conversation-surface changes
- service capability changes
- relevant state/availability changes
- explicit operator scan

An event carries only a section code and event correlation identity. It does not
replace a complete snapshot.

## Lifecycle

1. Increment the local generation and mark affected sections stale.
2. Coalesce events while a reconcile is running.
3. Build a complete Core-local discovery snapshot.
4. Validate limits, exposure policy, operation matrix, and redaction.
5. POST one replacement to the gateway with the expected generation.
6. Activate the Core target map and App revision together.
7. Publish status and diagnostic event.

If any step fails, retain the last valid profile for read-only diagnostics,
block writes whose revision cannot be proven current, and expose the failure
code and recovery action.

## Invariants

- no partial snapshot may become active;
- a generation observed during a build invalidates the build result;
- raw IDs never cross the gateway boundary;
- capability IDs are stable only within a profile revision;
- an active profile has matching App and Core revisions;
- profile counts and warning lists are bounded.
