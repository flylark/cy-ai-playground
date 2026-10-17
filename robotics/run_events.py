"""
run_events.py - connects the run-control state machine to the message bus

Before: plate_step.py records every transition, but nobody else hears about it.
After:  every transition is PUBLISHED as an event, and other services SUBSCRIBE.

    PlateStep --fire()--> audit log --publish--> bus +--> OperatorAlerter
                                                     +--> AuditRecorder
                                                     +--> (any new service later)

Ideas this file demonstrates:
  1. Decoupling: the state machine does not know who is listening.
     Adding a dashboard later means adding a subscriber, not changing run control.
  2. Events are facts in the past tense ("state changed"), not commands ("do X").
  3. The log is written first, then published from the log, so the record is
     the source of truth and the bus only carries copies (a small "outbox").
     If a publish fails, the entry stays pending and is resent later with the
     SAME event ID, so a resend can never create a second record.
  4. Topics carry routing information, so subscribers filter with wildcards:
       lab/events/plate/<sample_id>/<to_state>
  5. At-least-once delivery (MQTT QoS 1) can deliver the same event twice,
     so subscribers must be idempotent: each event has an ID, duplicates are ignored.
  6. Every event matches a versioned data contract, like schema.py.
"""
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bus import InMemoryBus, MessageBus
from plate_step import AuditEvent, Event, PlateStep, State

EVENT_SCHEMA_VERSION = "1.0"
EVENT_TOPIC_ROOT = "lab/events/plate"
SAMPLE_ID_PATTERN = r"^[A-Za-z0-9_-]+$"  # no "/", "+" or "#": safe inside a topic


class StateChanged(BaseModel):
    """THE EVENT CONTRACT: one message per state transition."""
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str = EVENT_SCHEMA_VERSION
    event_id: str = Field(min_length=1)                  # unique: used to drop duplicates
    sequence: int = Field(ge=1)                          # 1, 2, 3... per plate step
    sample_id: str = Field(pattern=SAMPLE_ID_PATTERN)
    step: str = Field(min_length=1)
    from_state: State
    event: Event
    to_state: State
    actor: str = Field(min_length=1)
    timestamp: datetime
    detail: dict[str, str] = {}

    @classmethod
    def from_audit(cls, audit: AuditEvent, sequence: int, event_id: str) -> "StateChanged":
        return cls(
            event_id=event_id,
            sequence=sequence,
            sample_id=audit.sample_id,
            step=audit.step,
            from_state=State(audit.from_state),
            event=Event(audit.event),
            to_state=State(audit.to_state),
            actor=audit.actor,
            timestamp=datetime.fromisoformat(audit.timestamp),
            detail={key: str(value) for key, value in audit.detail.items()},
        )


def topic_for(event: StateChanged) -> str:
    return f"{EVENT_TOPIC_ROOT}/{event.sample_id}/{event.to_state.value}"


class PublishingStep:
    """Wraps a PlateStep so every legal transition is published on the bus.

    plate_step.py stays unchanged and still knows nothing about the bus.
    If a move is illegal, PlateStep raises and nothing is published.
    """

    def __init__(self, step: PlateStep, bus: MessageBus):
        # Check input at the edge, BEFORE any transition can happen.
        if not re.fullmatch(SAMPLE_ID_PATTERN, step.sample_id):
            raise ValueError(f"sample_id {step.sample_id!r} cannot be used in a topic")
        self.step = step
        self.bus = bus
        self.run_id = uuid.uuid4().hex[:12]  # one ID per run; event IDs build on it
        self._published = 0  # how many audit-log entries are already on the bus

    @property
    def state(self) -> State:
        return self.step.state

    @property
    def pending(self) -> int:
        """Transitions recorded in the log but not yet on the bus."""
        return len(self.step.log) - self._published

    def fire(self, event: Event, actor: str = "orchestrator", **detail) -> State:
        new_state = self.step.fire(event, actor, **detail)
        self._publish_new_entries()
        return new_state

    def handle_fault(self, reason: str) -> State:
        new_state = self.step.handle_fault(reason)  # may record two transitions
        self._publish_new_entries()
        return new_state

    def flush(self) -> None:
        """Resend anything still pending, e.g. after the broker comes back."""
        self._publish_new_entries()

    def _publish_new_entries(self) -> None:
        # The log was written first; publish whatever is not on the bus yet.
        for audit in self.step.log[self._published:]:
            sequence = self._published + 1
            message = StateChanged.from_audit(
                audit, sequence=sequence, event_id=f"{self.run_id}-{sequence}"
            )
            self.bus.publish(topic_for(message), message.model_dump_json())
            self._published = sequence  # counted only AFTER a successful publish


class OperatorAlerter:
    """Subscriber: tells a person when a plate is waiting for them.
    In a real lab this would page or email the operator on duty."""

    TOPIC = f"{EVENT_TOPIC_ROOT}/+/{State.AWAITING_OPERATOR.value}"

    def __init__(self):
        self.alerts: list[str] = []

    def __call__(self, topic: str, payload: str) -> None:
        event = StateChanged.model_validate_json(payload)
        reason = event.detail.get("reason", "no reason given")
        self.alerts.append(
            f"Plate {event.sample_id} needs an operator at step '{event.step}': {reason}"
        )


class AuditRecorder:
    """Subscriber: keeps the full history of every plate.
    Validates each event against the contract and ignores duplicates."""

    TOPIC = f"{EVENT_TOPIC_ROOT}/#"

    def __init__(self):
        self.records: dict[str, StateChanged] = {}  # event_id -> event
        self.duplicates = 0
        self.rejected: list[tuple[str, str, str]] = []  # (topic, payload, reason)

    def __call__(self, topic: str, payload: str) -> None:
        try:
            event = StateChanged.model_validate_json(payload)
        except ValidationError as error:
            self.rejected.append((topic, payload, str(error)))
            return
        if event.event_id in self.records:
            self.duplicates += 1  # delivered twice: already recorded, so ignore it
            return
        self.records[event.event_id] = event

    def history(self, sample_id: str) -> list[StateChanged]:
        events = [e for e in self.records.values() if e.sample_id == sample_id]
        return sorted(events, key=lambda e: e.sequence)


if __name__ == "__main__":
    bus = InMemoryBus()  # MqttBus follows the same contract, so this code does not change
    alerter, recorder = OperatorAlerter(), AuditRecorder()
    bus.subscribe(OperatorAlerter.TOPIC, alerter)
    bus.subscribe(AuditRecorder.TOPIC, recorder)

    print("Run: liquid handler error mid-dispense (not safe to retry)")
    run = PublishingStep(PlateStep("PLT-0002", "dispense_buffer", retry_safe=False), bus)
    run.fire(Event.START, barcode="PLT-0002")
    run.handle_fault("pressure error mid-dispense")
    run.fire(Event.SAMPLE_COMPROMISED, actor="operator:cyang", note="partial volume")

    print("\nAlerts sent to the operator:")
    for alert in alerter.alerts:
        print(f"  {alert}")

    print("\nAudit history for PLT-0002, built only from bus messages:")
    for e in recorder.history("PLT-0002"):
        print(f"  {e.sequence}. {e.event.value:<19} {e.from_state.value} -> "
              f"{e.to_state.value}  ({e.actor})")

    print("\nSimulating a duplicate delivery (possible with QoS 1):")
    last = recorder.history("PLT-0002")[-1]
    bus.publish(topic_for(last), last.model_dump_json())
    print(f"  records still {len(recorder.records)}, duplicates ignored: {recorder.duplicates}")
