"""Tests for the plate-step state machine. Run with: pytest -q"""
import pytest

from plate_step import Event, IllegalTransition, PlateStep, State


def test_happy_path_ends_completed():
    s = PlateStep("PLT-1", "read_absorbance", retry_safe=True)
    s.fire(Event.START)
    s.fire(Event.STEP_DONE)
    assert s.state is State.COMPLETED
    assert [e.event for e in s.log] == ["start", "step_done"]


def test_safe_step_retries_once_then_escalates():
    s = PlateStep("PLT-2", "read_absorbance", retry_safe=True, max_retries=1)
    s.fire(Event.START)
    assert s.handle_fault("timeout") is State.RUNNING          # first fault: auto-retry
    assert s.handle_fault("timeout again") is State.AWAITING_OPERATOR  # limit reached


def test_unsafe_step_never_auto_retries():
    s = PlateStep("PLT-3", "dispense_buffer", retry_safe=False)
    s.fire(Event.START)
    assert s.handle_fault("pressure error") is State.AWAITING_OPERATOR
    with pytest.raises(IllegalTransition):
        s.fire(Event.RETRY)  # retry must not even be possible from here


def test_illegal_move_is_rejected_and_not_logged():
    s = PlateStep("PLT-4", "seal_plate", retry_safe=True)
    with pytest.raises(IllegalTransition):
        s.fire(Event.STEP_DONE)  # cannot finish a step that never started
    assert s.state is State.QUEUED
    assert s.log == []


def test_every_transition_records_who_and_why():
    s = PlateStep("PLT-5", "dispense_buffer", retry_safe=False)
    s.fire(Event.START)
    s.handle_fault("pressure error")
    s.fire(Event.SAMPLE_COMPROMISED, actor="operator:cyang", note="partial volume")
    last = s.log[-1]
    assert last.actor == "operator:cyang"
    assert last.to_state == "quarantined"
    assert last.detail == {"note": "partial volume"}

def test_operator_can_abort_steps():
    s = PlateStep("PLT-5", "dispense_buffer", retry_safe=False)
    s.fire(Event.START)
    s.fire(Event.ABORT, actor="operator:cyang", note="operator aborts step")
    last = s.log[-1]
    assert last.actor == "operator:cyang"
    assert last.to_state == "aborted"
    assert last.detail == {"note": "operator aborts step"} 

def test_operator_can_not_abort_steps():
    s = PlateStep("PLT-5", "dispense_buffer", retry_safe=False)
    s.fire(Event.START)
    s.fire(Event.STEP_DONE, actor="operator:cyang", note="run completed")
    with pytest.raises(IllegalTransition):
        s.fire(Event.ABORT, actor="operator:cyang", note="orchestrator can not abort after completion")

def test_no_operator_name_can_not_abort():
    s = PlateStep("PLT-5", "dispense_buffer", retry_safe=False)
    s.fire(Event.START, actor="operator", note="run completed")    
    with pytest.raises(IllegalTransition):
        s.fire(Event.ABORT, actor="operator", note="run aborted by unknown operator")

def test_abort_needs_an_operator_name():
    s = PlateStep("PLT-8", "dispense_buffer", retry_safe=False)
    s.fire(Event.START)
    with pytest.raises(IllegalTransition):
        s.fire(Event.ABORT, actor="operator:")   # prefix, but no name
    assert s.state is State.RUNNING              # nothing changed