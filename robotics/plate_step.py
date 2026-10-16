"""Run-control state machine for one plate step in a lab work cell.

Module 1 practice for the Alexion orchestration interview.

Design rules this file demonstrates:
  1. States, events and allowed transitions are explicit (one table).
  2. Any move not in the table is rejected (IllegalTransition).
  3. Guards check conditions before a transition (safe-to-retry, retry limit).
  4. Every transition is recorded as an auditable event (who, what, when, why).
  5. Decision logic is separate from device I/O, so it can be tested without hardware.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re


class State(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAULTED = "faulted"
    AWAITING_OPERATOR = "awaiting_operator"
    QUARANTINED = "quarantined"
    ABORTED = "aborted"  


class Event(str, Enum):
    START = "start"                          # device free and barcode verified
    STEP_DONE = "step_done"                  # device reports success, result stored
    FAULT = "fault"                          # device error or timeout
    RETRY = "retry"                          # automatic retry (only if safe)
    ESCALATE = "escalate"                    # not safe to retry: a person decides
    OPERATOR_CLEARED = "operator_cleared"    # operator fixed the cause, resume
    SAMPLE_COMPROMISED = "sample_compromised"  # operator judges the sample unusable
    ABORT = "abort"                          # operator aborts the step


# The whole behaviour in one table: (current state, event) -> next state.
# Anything not listed here is an illegal move.
TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.QUEUED, Event.START): State.RUNNING,
    (State.RUNNING, Event.STEP_DONE): State.COMPLETED,
    (State.RUNNING, Event.FAULT): State.FAULTED,
    (State.FAULTED, Event.RETRY): State.RUNNING,
    (State.FAULTED, Event.ESCALATE): State.AWAITING_OPERATOR,
    (State.AWAITING_OPERATOR, Event.OPERATOR_CLEARED): State.RUNNING,
    (State.AWAITING_OPERATOR, Event.SAMPLE_COMPROMISED): State.QUARANTINED,
    (State.RUNNING, Event.ABORT): State.ABORTED,
    (State.AWAITING_OPERATOR, Event.ABORT): State.ABORTED,
    (State.FAULTED, Event.ABORT): State.ABORTED,
    (State.QUEUED, Event.ABORT): State.ABORTED,
}

TERMINAL = {State.COMPLETED, State.QUARANTINED, State.ABORTED}


class IllegalTransition(Exception):
    """Raised when an event is not allowed in the current state."""


@dataclass
class AuditEvent:
    timestamp: str
    sample_id: str
    step: str
    from_state: str
    event: str
    to_state: str
    actor: str
    detail: dict


@dataclass
class PlateStep:
    sample_id: str
    step: str             # e.g. "read_absorbance", "dispense_buffer"
    retry_safe: bool      # is the step idempotent (safe to repeat)?
    max_retries: int = 1
    state: State = State.QUEUED
    retries_used: int = 0
    log: list[AuditEvent] = field(default_factory=list)

    def fire(self, event: Event, actor: str = "orchestrator", **detail) -> State:
        """Apply one event. Rejects illegal moves; records every legal one."""
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise IllegalTransition(
                f"'{event.value}' is not allowed in state '{self.state.value}'"
            )
        if event is Event.ABORT:
            name = actor.removeprefix("operator:")
            if not actor.startswith("operator:") or not name.strip():
                raise IllegalTransition("abort needs a named operator, e.g. 'operator:cyang'")
        # Guard: an automatic retry needs a safe step and retries left.
        if event is Event.RETRY:
            if not self.retry_safe:
                raise IllegalTransition("retry blocked: step is not safe to repeat")
            if self.retries_used >= self.max_retries:
                raise IllegalTransition("retry blocked: retry limit reached")
            self.retries_used += 1

        new_state = TRANSITIONS[key]
        self.log.append(
            AuditEvent(
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                sample_id=self.sample_id,
                step=self.step,
                from_state=self.state.value,
                event=event.value,
                to_state=new_state.value,
                actor=actor,
                detail=detail,
            )
        )
        self.state = new_state
        return new_state

    def handle_fault(self, reason: str) -> State:
        """Exception policy: retry automatically only if safe and within the limit;
        otherwise escalate to a person. Never retry an unsafe step silently."""
        self.fire(Event.FAULT, reason=reason)
        if self.retry_safe and self.retries_used < self.max_retries:
            return self.fire(Event.RETRY, reason=f"auto-retry after: {reason}")
        return self.fire(Event.ESCALATE, reason=reason)


def print_log(step: PlateStep) -> None:
    for e in step.log:
        print("  " + json.dumps(asdict(e)))


if __name__ == "__main__":
    print("Scenario 1: plate reader times out (safe to retry), retry succeeds")
    read = PlateStep(sample_id="PLT-0001", step="read_absorbance", retry_safe=True)
    read.fire(Event.START, barcode="PLT-0001")
    read.handle_fault("plate reader timeout")
    read.fire(Event.STEP_DONE, result_ref="results/PLT-0001.csv")
    print_log(read)
    print(f"  final state: {read.state.value}\n")

    print("Scenario 2: liquid handler error mid-dispense (NOT safe to retry)")
    dispense = PlateStep(sample_id="PLT-0002", step="dispense_buffer", retry_safe=False)
    dispense.fire(Event.START, barcode="PLT-0002")
    dispense.handle_fault("pressure error mid-dispense")
    dispense.fire(Event.SAMPLE_COMPROMISED, actor="operator:cyang",
                  note="partial volume, cannot recover")
    print_log(dispense)
    print(f"  final state: {dispense.state.value}\n")

    print("Scenario 3: an illegal move is rejected")
    queued = PlateStep(sample_id="PLT-0003", step="seal_plate", retry_safe=True)
    try:
        queued.fire(Event.STEP_DONE)
    except IllegalTransition as err:
        print(f"  rejected: {err}")
