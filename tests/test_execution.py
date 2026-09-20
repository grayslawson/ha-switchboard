import asyncio

from custom_components.ha_switchboard.capabilities import CapabilityTarget, operation_spec
from custom_components.ha_switchboard.diagnostics import CoreDiagnosticLog
from custom_components.ha_switchboard.execution import ExecutionBoundary


def test_non_toggle_request_identity_is_idempotent():
    class Executor:
        def __init__(self):
            self.state = "off"
            self.writes = 0
            self.target = CapabilityTarget("cap", "ref", "light.lamp", "light", "turn_on", operation_spec("light", "turn_on"))

        async def resolve_capability(self, capability_id):
            return self.target if capability_id == "cap" else None

        async def read_state(self, target):
            return {"state": self.state, "attributes": {}}

        async def execute(self, target, parameters):
            self.writes += 1
            self.state = "on"
            return {"ok": True}

        def verify(self, target, parameters, before, after, result):
            return after["state"] == "on"

    async def run():
        executor = Executor()
        boundary = ExecutionBoundary(executor)
        kwargs = dict(capability_id="cap", parameters={}, expected_profile_revision="r", current_profile_revision="r", confirmed=False, request_id="request-1")
        first = await boundary.execute_proposal(**kwargs)
        second = await boundary.execute_proposal(**kwargs)
        assert first == second
        assert executor.writes == 1

    asyncio.run(run())


def test_toggle_request_identity_is_not_replayed():
    class Executor:
        def __init__(self):
            self.state = "off"
            self.writes = 0
            self.target = CapabilityTarget("cap", "ref", "light.lamp", "light", "toggle", operation_spec("light", "toggle"))

        async def resolve_capability(self, capability_id): return self.target
        async def read_state(self, target): return {"state": self.state, "attributes": {}}
        async def execute(self, target, parameters):
            self.writes += 1
            self.state = "on" if self.state == "off" else "off"
            return {"ok": True}
        def verify(self, target, parameters, before, after, result): return before["state"] != after["state"]

    async def run():
        executor = Executor()
        boundary = ExecutionBoundary(executor)
        kwargs = dict(capability_id="cap", parameters={}, expected_profile_revision="r", current_profile_revision="r", confirmed=False, request_id="request-1")
        await boundary.execute_proposal(**kwargs)
        await boundary.execute_proposal(**kwargs)
        assert executor.writes == 2

    asyncio.run(run())


def test_execution_outcome_diagnostics_are_correlated_and_bounded():
    class Executor:
        target = CapabilityTarget("cap", "ref", "light.lamp", "light", "turn_on", operation_spec("light", "turn_on"))

        async def resolve_capability(self, capability_id): return self.target
        async def read_state(self, target): return {"state": "off", "attributes": {}}
        async def execute(self, target, parameters): raise RuntimeError("private provider response")
        def verify(self, target, parameters, before, after, result): return False

    async def run():
        diagnostics = CoreDiagnosticLog()
        result = await ExecutionBoundary(Executor(), diagnostics).execute_proposal(
            capability_id="cap",
            parameters={},
            expected_profile_revision="r",
            current_profile_revision="r",
            confirmed=False,
            request_id="request-42",
        )
        assert result["response_key"] == "execution_failed"
        events = diagnostics.list()
        assert events[-1]["code"] == "execution_outcome"
        assert events[-1]["correlation_id"] == "request-42"
        assert "private provider response" not in repr(events)

    asyncio.run(run())


def test_execution_outcome_diagnostic_is_correlated_and_bounded():
    class Executor:
        target = CapabilityTarget("cap", "ref", "light.lamp", "light", "turn_on", operation_spec("light", "turn_on"))

        async def resolve_capability(self, capability_id):
            return self.target if capability_id == "cap" else None

        async def read_state(self, _target):
            return {"state": "on", "attributes": {}}

        async def execute(self, _target, _parameters):
            return {"ok": True}

        def verify(self, _target, _parameters, _before, _after, result):
            return result["ok"]

    async def run():
        diagnostics = CoreDiagnosticLog()
        result = await ExecutionBoundary(Executor(), diagnostics).execute_proposal(
            capability_id="cap",
            parameters={},
            expected_profile_revision="revision",
            current_profile_revision="revision",
            confirmed=False,
            request_id="request-42",
        )
        assert result["response_key"] == "execute_verified"
        events = diagnostics.list()
        outcome = events[-1]
        assert outcome["code"] == "execution_outcome"
        assert outcome["correlation_id"] == "request-42"
        assert outcome["fields"]["outcome"] == "execute_verified"
        assert outcome["fields"]["operation"] == "execute"
        assert "light.lamp" not in repr(outcome)

    asyncio.run(run())


def test_batch_outcome_diagnostic_reports_verified_progress():
    class Executor:
        def __init__(self):
            self.targets = {
                key: CapabilityTarget(key, key, f"light.{key}", "light", "turn_on", operation_spec("light", "turn_on"))
                for key in ("one", "two")
            }
            self.states = {key: "off" for key in self.targets}

        def profile_current(self, _revision):
            return True

        async def resolve_capability(self, capability_id):
            return self.targets.get(capability_id)

        async def read_state(self, target):
            return {"state": self.states[target.capability_id], "attributes": {}}

        async def execute(self, target, _parameters):
            self.states[target.capability_id] = "on"
            return {"ok": True}

        def verify(self, target, _parameters, _before, after, _result):
            return target.capability_id == "one" and after["state"] == "on"

    async def run():
        diagnostics = CoreDiagnosticLog()
        result = await ExecutionBoundary(Executor(), diagnostics).execute_batch_proposal(
            capability_ids=("one", "two"),
            expected_profile_revision="revision",
            current_profile_revision="revision",
            request_id="batch-42",
        )
        assert result["response_key"] == "batch_partial_failure"
        outcome = diagnostics.list()[-1]
        assert outcome["code"] == "execution_outcome"
        assert outcome["correlation_id"] == "batch-42"
        assert outcome["fields"]["operation"] == "batch"
        assert outcome["fields"]["verified_count"] == 1
        assert outcome["fields"]["total_count"] == 2

    asyncio.run(run())
