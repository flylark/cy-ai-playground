"""
test_run_events.py - tests for publishing state transitions on the message bus

All tests use InMemoryBus, so they need no network and run fine in CI.
"""
import pytest

from bus import InMemoryBus
from plate_step import Event, IllegalTransition, PlateStep, State
from run_events import AuditRecorder, OperatorAlerter, PublishingStep, topic_for


def wired_bus():
    """A bus with both subscribers attached, the way a lab would run it."""
    bus = InMemoryBus()
    alerter, recorder = OperatorAlerter(), AuditRecorder()
    bus.subscribe(OperatorAlerter.TOPIC, alerter)
    bus.subscribe(AuditRecorder.TOPIC, recorder)
    return bus, alerter, recorder


def test_every_transition_is_published_once_and_in_order():
    bus, _, recorder = wired_bus()
    run = PublishingStep(PlateStep("PLT-10", "dispense_buffer", retry_safe=False), bus)
    run.fire(Event.START)
    run.handle_fault("pressure error")  # two transitions: fault, then escalate
    run.fire(Event.SAMPLE_COMPROMISED, actor="operator:cyang")

    history = recorder.history("PLT-10")
    assert [e.sequence for e in history] == [1, 2, 3, 4]
    assert [e.to_state for e in history] == [
        State.RUNNING, State.FAULTED, State.AWAITING_OPERATOR, State.QUARANTINED,
    ]


def test_illegal_move_publishes_nothing():
    bus, _, recorder = wired_bus()
    run = PublishingStep(PlateStep("PLT-11", "seal_plate", retry_safe=True), bus)
    with pytest.raises(IllegalTransition):
        run.fire(Event.STEP_DONE)  # cannot finish a step that never started
    assert recorder.records == {}


def test_alerter_only_hears_plates_waiting_for_an_operator():
    bus, alerter, _ = wired_bus()

    ok = PublishingStep(PlateStep("PLT-12", "read_absorbance", retry_safe=True), bus)
    ok.fire(Event.START)
    ok.fire(Event.STEP_DONE)
    assert alerter.alerts == []  # a normal run raises no alert

    bad = PublishingStep(PlateStep("PLT-13", "dispense_buffer", retry_safe=False), bus)
    bad.fire(Event.START)
    bad.handle_fault("pressure error")
    assert len(alerter.alerts) == 1
    assert "PLT-13" in alerter.alerts[0]
    assert "pressure error" in alerter.alerts[0]


def test_duplicate_delivery_is_ignored():
    bus, _, recorder = wired_bus()
    run = PublishingStep(PlateStep("PLT-14", "read_absorbance", retry_safe=True), bus)
    run.fire(Event.START)

    first = recorder.history("PLT-14")[0]
    bus.publish(topic_for(first), first.model_dump_json())  # same event arrives again

    assert len(recorder.records) == 1
    assert recorder.duplicates == 1


def test_bad_event_is_rejected_not_crashed():
    bus, _, recorder = wired_bus()
    bus.publish("lab/events/plate/PLT-15/running", "this is not JSON")
    bus.publish("lab/events/plate/PLT-15/running", '{"event_id": "abc", "sequence": 0}')

    assert recorder.records == {}
    assert len(recorder.rejected) == 2


def test_sample_id_that_would_break_a_topic_is_rejected_before_any_move():
    bus, _, recorder = wired_bus()
    step = PlateStep("PLT/16", "seal_plate", retry_safe=True)
    with pytest.raises(ValueError):  # "/" would split the topic into extra levels
        PublishingStep(step, bus)
    assert step.state is State.QUEUED  # rejected at the edge: nothing happened
    assert recorder.records == {}


class FlakyBus(InMemoryBus):
    """A bus whose first publish fails, like a broker that briefly drops out."""

    def __init__(self):
        super().__init__()
        self.fail_next = True

    def publish(self, topic, payload):
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("broker unavailable")
        super().publish(topic, payload)


def test_failed_publish_stays_pending_and_is_resent_with_the_same_id():
    bus = FlakyBus()
    recorder = AuditRecorder()
    bus.subscribe(AuditRecorder.TOPIC, recorder)
    run = PublishingStep(PlateStep("PLT-17", "seal_plate", retry_safe=True), bus)

    with pytest.raises(ConnectionError):  # the caller is told: fail loud, not silent
        run.fire(Event.START)
    assert run.state is State.RUNNING     # the transition itself did happen
    assert run.pending == 1               # ...and is waiting to be published
    assert recorder.records == {}

    run.flush()                           # broker is back: resend
    assert run.pending == 0
    assert [e.event_id for e in recorder.history("PLT-17")] == [f"{run.run_id}-1"]

def test_broken_subscriber_does_not_stop_the_run():
    bus = InMemoryBus()
    recorder = AuditRecorder()

    def broken_dashboard(topic, payload):
        raise RuntimeError("dashboard crashed")

    bus.subscribe("lab/events/#", broken_dashboard)
    bus.subscribe(AuditRecorder.TOPIC, recorder)
    run = PublishingStep(PlateStep("PLT-18", "seal_plate", retry_safe=True), bus)

    run.fire(Event.START)               # must not raise
    run.fire(Event.STEP_DONE)

    assert run.state is State.COMPLETED
    assert len(recorder.records) == 2   # other subscribers still got every event
    assert len(bus.errors) == 2         # failures are recorded, not hidden