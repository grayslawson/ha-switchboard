from __future__ import annotations

from ha_switchboard.change_monitor import ChangeMonitor
from ha_switchboard.profile import ProfileCompiler
from ha_switchboard.protocol import LifecycleStatus, SectionId


def test_events_are_coalesced_and_status_is_redacted(sanitized_discovery: dict) -> None:
    monitor = ChangeMonitor()
    monitor.reconcile(sanitized_discovery)
    monitor.ingest({"event_type": "entity_registry_updated", "data": {"entity_id": "should-not-be-stored"}})
    monitor.ingest({"event_type": "exposure_updated"})
    status = monitor.status()
    assert SectionId.ENTITIES.value in status["pending_sections"]
    assert SectionId.EXPOSURE.value in status["pending_sections"]
    assert "should-not-be-stored" not in str(status)


def test_reconcile_activates_a_complete_new_profile(sanitized_discovery: dict) -> None:
    monitor = ChangeMonitor()
    first = monitor.reconcile(sanitized_discovery, revision="profile-one")
    monitor.ingest({"event_type": "entity_registry_updated"})
    second_snapshot = dict(sanitized_discovery)
    second_snapshot["organization"] = {"areas": ["New area"]}
    second = monitor.reconcile(second_snapshot, revision="profile-two")
    assert first.revision == "profile-one"
    assert second.revision == "profile-two"
    assert second.status is LifecycleStatus.ACTIVE
    assert not monitor.pending_sections


def test_newer_event_cannot_be_overwritten_by_an_older_candidate(sanitized_discovery: dict) -> None:
    class RacingCompiler(ProfileCompiler):
        monitor: ChangeMonitor | None = None

        def compile(self, snapshot, **kwargs):
            if self.monitor and self.monitor.active_profile:
                self.monitor.ingest({"event_type": "entity_registry_updated"})
                self.monitor = None
            return super().compile(snapshot, **kwargs)

    compiler = RacingCompiler()
    monitor = ChangeMonitor(compiler=compiler)
    monitor.reconcile(sanitized_discovery, revision="profile-one")
    compiler.monitor = monitor
    result = monitor.reconcile(sanitized_discovery, revision="profile-old")
    assert result.revision == "profile-one"
    assert "source_changed_during_reconcile" in monitor.pending_reasons
