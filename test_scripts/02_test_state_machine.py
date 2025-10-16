#!/usr/bin/env python3
"""
Test: Workflow State Machine
Purpose: Verify all valid and invalid state transitions

Tests:
- All valid state transitions work correctly
- Invalid transitions are rejected
- Terminal states cannot transition
- State change events are recorded
- Version increments on each transition
"""

import asyncio
import sys

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    TestContext, create_test_workflow,
    assert_equal, assert_true, assert_raises_async
)

from app.core.workflow_engine import WorkflowEngine, InvalidStateTransitionError
from app.models.schemas import WorkflowState, STATE_TRANSITIONS


# ============================================================================
# Test: Valid Transition - CREATED to RUNNING
# ============================================================================

async def test_transition_created_to_running():
    """Test valid transition from CREATED to RUNNING"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            initial_version = workflow.version

            # Transition to RUNNING
            workflow = await engine.transition_to(
                workflow.id,
                WorkflowState.RUNNING,
                "Starting workflow execution"
            )

            assert_equal(workflow.state, WorkflowState.RUNNING.value)
            assert_equal(workflow.version, initial_version + 1)


# ============================================================================
# Test: Valid Transition - RUNNING to WAITING_APPROVAL
# ============================================================================

async def test_transition_running_to_waiting_approval():
    """Test valid transition from RUNNING to WAITING_APPROVAL"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)

            # CREATED -> RUNNING
            workflow = await engine.transition_to(workflow.id, WorkflowState.RUNNING)

            # RUNNING -> WAITING_APPROVAL
            workflow = await engine.transition_to(
                workflow.id,
                WorkflowState.WAITING_APPROVAL,
                "Requesting approval"
            )

            assert_equal(workflow.state, WorkflowState.WAITING_APPROVAL.value)


# ============================================================================
# Test: Valid Transition - WAITING_APPROVAL to APPROVED
# ============================================================================

async def test_transition_waiting_to_approved():
    """Test valid transition from WAITING_APPROVAL to APPROVED"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            await engine.transition_to(workflow.id, WorkflowState.WAITING_APPROVAL)

            # WAITING_APPROVAL -> APPROVED
            workflow = await engine.transition_to(
                workflow.id,
                WorkflowState.APPROVED,
                "Approval received"
            )

            assert_equal(workflow.state, WorkflowState.APPROVED.value)


# ============================================================================
# Test: Valid Transition - APPROVED to COMPLETED
# ============================================================================

async def test_transition_approved_to_completed():
    """Test valid transition from APPROVED to COMPLETED"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            await engine.transition_to(workflow.id, WorkflowState.WAITING_APPROVAL)
            await engine.transition_to(workflow.id, WorkflowState.APPROVED)

            # APPROVED -> COMPLETED
            workflow = await engine.transition_to(
                workflow.id,
                WorkflowState.COMPLETED,
                "Workflow completed"
            )

            assert_equal(workflow.state, WorkflowState.COMPLETED.value)


# ============================================================================
# Test: Valid Transition - RUNNING to COMPLETED (Direct)
# ============================================================================

async def test_transition_running_to_completed_direct():
    """Test valid transition from RUNNING directly to COMPLETED"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)

            # RUNNING -> COMPLETED (no approval needed)
            workflow = await engine.transition_to(
                workflow.id,
                WorkflowState.COMPLETED,
                "Completed without approval"
            )

            assert_equal(workflow.state, WorkflowState.COMPLETED.value)


# ============================================================================
# Test: Valid Transition - Failure Path
# ============================================================================

async def test_transition_failure_path():
    """Test failure path transitions"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Test 1: CREATED -> FAILED
            workflow1 = await create_test_workflow(engine)
            workflow1 = await engine.transition_to(
                workflow1.id,
                WorkflowState.FAILED,
                "Early failure"
            )
            assert_equal(workflow1.state, WorkflowState.FAILED.value)

            # Test 2: RUNNING -> FAILED
            workflow2 = await create_test_workflow(engine)
            await engine.transition_to(workflow2.id, WorkflowState.RUNNING)
            workflow2 = await engine.transition_to(
                workflow2.id,
                WorkflowState.FAILED,
                "Execution failure"
            )
            assert_equal(workflow2.state, WorkflowState.FAILED.value)

            # Test 3: WAITING_APPROVAL -> FAILED
            workflow3 = await create_test_workflow(engine)
            await engine.transition_to(workflow3.id, WorkflowState.RUNNING)
            await engine.transition_to(workflow3.id, WorkflowState.WAITING_APPROVAL)
            workflow3 = await engine.transition_to(
                workflow3.id,
                WorkflowState.FAILED,
                "Approval timeout"
            )
            assert_equal(workflow3.state, WorkflowState.FAILED.value)


# ============================================================================
# Test: Invalid Transition - CREATED to COMPLETED
# ============================================================================

async def test_invalid_transition_created_to_completed():
    """Test invalid transition from CREATED to COMPLETED"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)

            # Try invalid transition
            await assert_raises_async(
                InvalidStateTransitionError,
                engine.transition_to(workflow.id, WorkflowState.COMPLETED)
            )


# ============================================================================
# Test: Invalid Transition - From Terminal State
# ============================================================================

async def test_invalid_transition_from_completed():
    """Test that COMPLETED state cannot transition"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            await engine.transition_to(workflow.id, WorkflowState.COMPLETED)

            # Try to transition from COMPLETED
            await assert_raises_async(
                InvalidStateTransitionError,
                engine.transition_to(workflow.id, WorkflowState.RUNNING)
            )


# ============================================================================
# Test: Invalid Transition - From FAILED
# ============================================================================

async def test_invalid_transition_from_failed():
    """Test that FAILED state cannot transition (except TIMEOUT which can retry)"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.FAILED)

            # Try to transition from FAILED
            await assert_raises_async(
                InvalidStateTransitionError,
                engine.transition_to(workflow.id, WorkflowState.RUNNING)
            )


# ============================================================================
# Test: State Transition Events Recorded
# ============================================================================

async def test_state_transition_events_recorded():
    """Test that state transitions are recorded as events"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            workflow_id = workflow.id

            # Make several transitions
            await engine.transition_to(workflow_id, WorkflowState.RUNNING)
            await engine.transition_to(workflow_id, WorkflowState.WAITING_APPROVAL)
            await engine.transition_to(workflow_id, WorkflowState.APPROVED)
            await engine.transition_to(workflow_id, WorkflowState.COMPLETED)

            # Get events
            events = await engine.get_workflow_events(workflow_id)

            # Should have: WORKFLOW_STARTED + 4 WORKFLOW_STATE_CHANGED events
            assert_true(
                len(events) >= 5,
                f"Expected at least 5 events, got {len(events)}"
            )

            # Verify state change events
            state_change_events = [
                e for e in events if e.event_type == "workflow.state_changed"
            ]
            assert_equal(
                len(state_change_events),
                4,
                "Should have 4 state change events"
            )


# ============================================================================
# Test: Version Increments on Each Transition
# ============================================================================

async def test_version_increments():
    """Test that version increments on each state transition"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            initial_version = workflow.version

            # Make 4 transitions
            workflow = await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            assert_equal(workflow.version, initial_version + 1)

            workflow = await engine.transition_to(workflow.id, WorkflowState.WAITING_APPROVAL)
            assert_equal(workflow.version, initial_version + 2)

            workflow = await engine.transition_to(workflow.id, WorkflowState.APPROVED)
            assert_equal(workflow.version, initial_version + 3)

            workflow = await engine.transition_to(workflow.id, WorkflowState.COMPLETED)
            assert_equal(workflow.version, initial_version + 4)


# ============================================================================
# Test: State Machine Configuration
# ============================================================================

async def test_state_transitions_configuration():
    """Test that STATE_TRANSITIONS dict is correctly configured"""
    # Verify all states are defined
    all_states = list(WorkflowState)

    for state in all_states:
        assert_true(
            state in STATE_TRANSITIONS,
            f"State {state} missing from STATE_TRANSITIONS"
        )

    # Verify terminal states have no transitions
    assert_equal(
        STATE_TRANSITIONS[WorkflowState.COMPLETED],
        [],
        "COMPLETED should have no valid transitions"
    )

    assert_equal(
        STATE_TRANSITIONS[WorkflowState.FAILED],
        [],
        "FAILED should have no valid transitions"
    )

    # Verify CREATED can transition to RUNNING and FAILED
    assert_true(
        WorkflowState.RUNNING in STATE_TRANSITIONS[WorkflowState.CREATED],
        "CREATED should allow transition to RUNNING"
    )
    assert_true(
        WorkflowState.FAILED in STATE_TRANSITIONS[WorkflowState.CREATED],
        "CREATED should allow transition to FAILED"
    )

    print_info("State machine configuration verified ✓")


# ============================================================================
# Test: Can Transition Helper
# ============================================================================

async def test_can_transition_helper():
    """Test the can_transition helper method"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Test valid transition
            can_transition = engine.can_transition(
                WorkflowState.CREATED,
                WorkflowState.RUNNING
            )
            assert_true(can_transition, "Should allow CREATED -> RUNNING")

            # Test invalid transition
            cannot_transition = engine.can_transition(
                WorkflowState.CREATED,
                WorkflowState.COMPLETED
            )
            assert_equal(
                cannot_transition,
                False,
                "Should not allow CREATED -> COMPLETED"
            )


# ============================================================================
# Main Test Runner
# ============================================================================

async def main():
    """Run all state machine tests"""
    print_test_header("Workflow State Machine Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Valid: CREATED -> RUNNING", test_transition_created_to_running),
        ("Valid: RUNNING -> WAITING_APPROVAL", test_transition_running_to_waiting_approval),
        ("Valid: WAITING_APPROVAL -> APPROVED", test_transition_waiting_to_approved),
        ("Valid: APPROVED -> COMPLETED", test_transition_approved_to_completed),
        ("Valid: RUNNING -> COMPLETED (direct)", test_transition_running_to_completed_direct),
        ("Valid: Failure path transitions", test_transition_failure_path),
        ("Invalid: CREATED -> COMPLETED", test_invalid_transition_created_to_completed),
        ("Invalid: From COMPLETED state", test_invalid_transition_from_completed),
        ("Invalid: From FAILED state", test_invalid_transition_from_failed),
        ("State transition events recorded", test_state_transition_events_recorded),
        ("Version increments on transitions", test_version_increments),
        ("State machine configuration", test_state_transitions_configuration),
        ("can_transition helper method", test_can_transition_helper),
    ]

    for test_name, test_func in tests:
        try:
            await test_func()
            print_pass(test_name)
            tests_passed += 1
        except Exception as e:
            print_fail(test_name, str(e))
            import traceback
            traceback.print_exc()
            tests_failed += 1

    print_summary(tests_passed, tests_failed)
    return 0 if tests_failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
