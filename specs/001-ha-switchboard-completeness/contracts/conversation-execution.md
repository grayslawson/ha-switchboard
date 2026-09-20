# Conversation and Execution Contract

## Core flow

1. Receive an Assist utterance with conversation and user identity.
2. Resolve a pending clarification/confirmation context, if present.
3. Read current Core-local state and active profile revision.
4. Offer clear supported routine intents to Home Assistant's native
   Conversation/Assist handler using a filter that excludes Switchboard itself.
   If native handling returns a result, preserve that result and do not call Jev
   or fallback.
5. Ask the gateway for a bounded typed result only when native handling does
   not claim the request.
6. Validate every returned capability and parameter locally.
7. Create a pending context for clarification/confirmation, or execute only an
   allowed proposal.
8. Verify the resulting state and emit a specific user response.
9. Persist only redacted diagnostic information.

## Native Assist fast path

- Home Assistant owns native entity, area, domain, and built-in intent
  resolution for clear routine requests.
- The Core conversation entity invokes the public native intent helper before
  constructing a provider request. The native intent filter excludes
  Switchboard's own conversation entity to prevent recursion.
- A native result is returned as the Home Assistant conversation result and is
  recorded as a bounded `native_fast_path` diagnostic event. It does not call
  Jev, a hosted fallback, or the gateway execution proposal path.
- A native miss continues through local read-only handling and then the bounded
  Jev/confirmation/fallback route. Jev remains advisory and Core still owns
  every write gate.

## Single action

A write requires all of:

- active profile and matching revision
- exposed/allowlisted capability
- supported operation
- valid normalized parameters
- current availability
- confirmation when risk policy requires it
- request identity not already consumed
- successful Home Assistant service call
- post-action verification

Any missing gate returns a reason-specific response and no write.

## Batch action

- Resolve targets by safe display context, area, label, group, or plural intent.
- Enforce the maximum of 32 targets.
- Preflight all members before the first write.
- Reject or ask for confirmation if any member is unsafe.
- Execute only compatible, allowlisted operations.
- Verify each member independently.
- Return succeeded, failed, skipped, and unavailable counts with safe display
  names and a clear partial-completion statement.
- Store a request identity for non-toggle idempotency; do not replay toggles
  silently.

## Conversation context

Clarification and confirmation contexts are Core-local, user/conversation
bound, short-lived, and one-time. A bare affirmative without a matching pending
context is not authorization. A negative answer cancels the context. Expired,
consumed, or cross-user context produces a new safe prompt.

## Response language

The response must distinguish completed, partially completed, awaiting input,
cancelled, unavailable, unsupported, stale, and blocked outcomes. It must never
use the prohibited generic sentence “I could not safely complete that
request.”
