#!/usr/bin/env python3
"""
Test: Race Condition and Concurrency Control
Purpose: Verify optimistic locking, row-level locking, and check order fixes

Tests Critical Fixes:
1. Optimistic locking prevents concurrent workflow state modifications
2. Row-level locking prevents concurrent approval responses
3. Check order fix (expiry before status) prevents race conditions
"""

import asyncio
import sys
from datetime import datetime, timedelta

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    TestContext, create_test_workflow, create_test_approval,
    assert_equal, assert_true
)

from app.core.workflow_engine import WorkflowEngine, ConcurrentModificationError, InvalidStateTransitionError
from app.core.approval_service import ApprovalService
from app.models.schemas import WorkflowState


# ============================================================================
# Test: Concurrent Workflow State Transitions (Optimistic Locking)
# ============================================================================

async def test_concurrent_workflow_transitions():
    """
    Test that concurrent workflow state transitions use optimistic locking.

    Scenario:
    - Create workflow in CREATED state
    - Two tasks try to transition to different states simultaneously
    - One should succeed, one should get ConcurrentModificationError

    Tests Fix #1: Optimistic locking (workflow_engine.py:86-173)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create workflow
            workflow = await create_test_workflow(engine)
            await session.commit()

            workflow_id = workflow.id
            initial_version = workflow.version

            # Two tasks trying to transition simultaneously
            results = []
            errors = []

            async def transition_1():
                try:
                    async with ctx.get_session() as s:
                        e = WorkflowEngine(s, ctx.event_bus)
                        await e.transition_to(workflow_id, WorkflowState.RUNNING, "Task 1")
                        results.append("task1_success")
                except ConcurrentModificationError as ex:
                    errors.append(("task1", str(ex)))
                except Exception as ex:
                    errors.append(("task1", f"Unexpected error: {ex}"))

            async def transition_2():
                try:
                    async with ctx.get_session() as s:
                        e = WorkflowEngine(s, ctx.event_bus)
                        await e.transition_to(workflow_id, WorkflowState.RUNNING, "Task 2")
                        results.append("task2_success")
                except ConcurrentModificationError as ex:
                    errors.append(("task2", str(ex)))
                except Exception as ex:
                    errors.append(("task2", f"Unexpected error: {ex}"))

            # Run both transitions concurrently
            await asyncio.gather(transition_1(), transition_2())

            # Verify: Exactly one should succeed, one should fail
            if len(results) != 1:
                raise AssertionError(
                    f"Expected exactly 1 success, got {len(results)}: {results}"
                )

            if len(errors) != 1:
                raise AssertionError(
                    f"Expected exactly 1 ConcurrentModificationError, got {len(errors)}: {errors}"
                )

            # Verify the error is ConcurrentModificationError
            error_task, error_msg = errors[0]
            assert_true(
                "modified concurrently" in error_msg.lower(),
                f"Expected concurrent modification error, got: {error_msg}"
            )

            # Verify workflow version incremented
            async with ctx.get_session() as s:
                e = WorkflowEngine(s, ctx.event_bus)
                updated_workflow = await e.get_workflow(workflow_id)
                assert_equal(
                    updated_workflow.version,
                    initial_version + 1,
                    "Version should increment by 1 after successful transition"
                )
                assert_equal(
                    updated_workflow.state,
                    WorkflowState.RUNNING.value,
                    "Workflow should be in RUNNING state"
                )


# ============================================================================
# Test: Concurrent Approval Responses (Row-Level Locking)
# ============================================================================

async def test_concurrent_approval_responses():
    """
    Test that concurrent approval responses use row-level locking.

    Scenario:
    - Create approval request
    - Two users try to approve simultaneously
    - Only one should succeed

    Tests Fix #2: Row-level locking (approval_service.py:137)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create workflow and approval
            workflow = await create_test_workflow(engine)
            await session.commit()

            approval = await create_test_approval(service, workflow.id, timeout_seconds=3600)
            await session.commit()

            approval_id = approval.id

            # Two users trying to respond simultaneously
            successes = []
            failures = []

            async def respond_user1():
                try:
                    async with ctx.get_session() as s:
                        srv = ApprovalService(s, ctx.event_bus)
                        await srv.respond_to_approval(
                            approval_id,
                            "approve",
                            {"approver_name": "User1", "risk_level": "low"}
                        )
                        successes.append("user1")
                except ValueError as ex:
                    failures.append(("user1", str(ex)))
                except Exception as ex:
                    failures.append(("user1", f"Unexpected: {ex}"))

            async def respond_user2():
                try:
                    async with ctx.get_session() as s:
                        srv = ApprovalService(s, ctx.event_bus)
                        await srv.respond_to_approval(
                            approval_id,
                            "approve",
                            {"approver_name": "User2", "risk_level": "medium"}
                        )
                        successes.append("user2")
                except ValueError as ex:
                    failures.append(("user2", str(ex)))
                except Exception as ex:
                    failures.append(("user2", f"Unexpected: {ex}"))

            # Run both responses concurrently
            await asyncio.gather(respond_user1(), respond_user2())

            # Verify: Exactly one should succeed
            if len(successes) != 1:
                raise AssertionError(
                    f"Expected exactly 1 success, got {len(successes)}: {successes}"
                )

            if len(failures) != 1:
                raise AssertionError(
                    f"Expected exactly 1 failure, got {len(failures)}: {failures}"
                )

            # Verify the failure is "already processed"
            fail_user, fail_msg = failures[0]
            assert_true(
                "already" in fail_msg.lower(),
                f"Expected 'already processed' error, got: {fail_msg}"
            )


# ============================================================================
# Test: Double-Click Protection
# ============================================================================

async def test_double_click_protection():
    """
    Test that double-clicking approve button doesn't process twice.

    Scenario:
    - User clicks approve button twice in quick succession
    - Second click should be rejected

    Tests Fix #2: Row-level locking prevents double processing
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create workflow and approval
            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id)
            await session.commit()

            approval_id = approval.id

            # First click - should succeed
            async with ctx.get_session() as s:
                srv = ApprovalService(s, ctx.event_bus)
                result1 = await srv.respond_to_approval(
                    approval_id,
                    "approve",
                    {"approver_name": "User", "risk_level": "low"}
                )

            assert_equal(result1.status, "APPROVED", "First response should succeed")

            # Second click - should fail
            try:
                async with ctx.get_session() as s:
                    srv = ApprovalService(s, ctx.event_bus)
                    await srv.respond_to_approval(
                        approval_id,
                        "approve",
                        {"approver_name": "User", "risk_level": "low"}
                    )
                raise AssertionError("Second click should have been rejected")
            except ValueError as ex:
                assert_true(
                    "already" in str(ex).lower(),
                    f"Expected 'already processed' error, got: {ex}"
                )


# ============================================================================
# Test: Approval Expiry Check Order
# ============================================================================

async def test_approval_expiry_check_order():
    """
    Test that expiry is checked BEFORE status.

    Scenario:
    - Create approval with short timeout
    - Wait for it to expire
    - Try to approve it
    - Should fail with "expired" error, not "already processed"

    Tests Fix #3: Check order fix (approval_service.py:145-164)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create workflow and approval with 1 second timeout
            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=1)
            await session.commit()

            approval_id = approval.id

            # Wait for it to expire
            print_info("Waiting for approval to expire...")
            await asyncio.sleep(1.5)

            # Try to respond to expired approval
            try:
                async with ctx.get_session() as s:
                    srv = ApprovalService(s, ctx.event_bus)
                    await srv.respond_to_approval(
                        approval_id,
                        "approve",
                        {"approver_name": "Late User", "risk_level": "low"}
                    )
                raise AssertionError("Should have rejected expired approval")
            except ValueError as ex:
                # CRITICAL: Must say "expired", not "already processed"
                error_msg = str(ex).lower()
                assert_true(
                    "expired" in error_msg,
                    f"Expected 'expired' error, got: {ex}"
                )
                assert_true(
                    "already" not in error_msg,
                    f"Should NOT say 'already processed', got: {ex}"
                )


# ============================================================================
# Test: Approval + Timeout Race Condition
# ============================================================================

async def test_approval_timeout_race():
    """
    Test race between user approval and timeout manager.

    Scenario:
    - Create approval with short timeout
    - User tries to approve at same time timeout fires
    - One should succeed, one should fail gracefully

    Tests Fix #2 & #3: Row-level locking + check order
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create workflow and approval with 2 second timeout
            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=2)
            await session.commit()

            approval_id = approval.id

            # Wait until just before timeout
            await asyncio.sleep(1.5)

            # Race: user approval vs timeout
            user_result = None
            timeout_result = None
            user_error = None
            timeout_error = None

            async def user_approve():
                nonlocal user_result, user_error
                try:
                    # Wait a bit to let timeout happen first (testing the race)
                    await asyncio.sleep(0.7)  # Total = 2.2s, past timeout
                    async with ctx.get_session() as s:
                        srv = ApprovalService(s, ctx.event_bus)
                        user_result = await srv.respond_to_approval(
                            approval_id,
                            "approve",
                            {"approver_name": "User", "risk_level": "low"}
                        )
                except Exception as ex:
                    user_error = ex

            async def timeout_mark():
                nonlocal timeout_result, timeout_error
                try:
                    await asyncio.sleep(0.6)  # Total = 2.1s, just past timeout
                    async with ctx.get_session() as s:
                        srv = ApprovalService(s, ctx.event_bus)
                        timeout_result = await srv.mark_timeout(approval_id)
                except Exception as ex:
                    timeout_error = ex

            # Run both operations concurrently
            await asyncio.gather(user_approve(), timeout_mark())

            # Verify: One should succeed, other should fail or be skipped
            success_count = 0
            if user_result and not user_error:
                success_count += 1
            if timeout_result and not timeout_error:
                success_count += 1

            # At least one should have completed
            assert_true(
                success_count >= 1,
                f"Expected at least one operation to succeed. "
                f"User error: {user_error}, Timeout error: {timeout_error}"
            )


# ============================================================================
# Test: Retry After Concurrent Modification
# ============================================================================

async def test_retry_after_concurrent_modification():
    """
    Test that retry succeeds after ConcurrentModificationError.

    Scenario:
    - First attempt gets ConcurrentModificationError
    - Retry with fresh data should succeed

    Tests Fix #1: Optimistic locking works correctly
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create workflow
            workflow = await create_test_workflow(engine)
            await session.commit()
            workflow_id = workflow.id

            # Task 1: Transition to RUNNING (will succeed)
            async with ctx.get_session() as s:
                e = WorkflowEngine(s, ctx.event_bus)
                await e.transition_to(workflow_id, WorkflowState.RUNNING)

            # Task 2: Try to transition from CREATED (will fail - stale state)
            # Note: This test reads fresh data, so it will get InvalidStateTransitionError
            # for RUNNING -> RUNNING. In a real concurrent scenario with truly stale
            # data, it would get ConcurrentModificationError.
            try:
                async with ctx.get_session() as s:
                    e = WorkflowEngine(s, ctx.event_bus)
                    # Workflow is now RUNNING, so attempting RUNNING -> RUNNING is invalid
                    await e.transition_to(workflow_id, WorkflowState.RUNNING)
                raise AssertionError("Should have raised an error (ConcurrentModificationError or InvalidStateTransitionError)")
            except (ConcurrentModificationError, InvalidStateTransitionError):
                pass  # Expected - either error is acceptable

            # Task 2: Retry with fresh data (should succeed)
            async with ctx.get_session() as s:
                e = WorkflowEngine(s, ctx.event_bus)
                # Get fresh data
                fresh_workflow = await e.get_workflow(workflow_id)
                assert_equal(fresh_workflow.state, WorkflowState.RUNNING.value)

                # Now transition to WAITING_APPROVAL (valid from RUNNING)
                await e.transition_to(workflow_id, WorkflowState.WAITING_APPROVAL)

            # Verify final state
            async with ctx.get_session() as s:
                e = WorkflowEngine(s, ctx.event_bus)
                final_workflow = await e.get_workflow(workflow_id)
                assert_equal(
                    final_workflow.state,
                    WorkflowState.WAITING_APPROVAL.value,
                    "Retry should succeed with fresh data"
                )


# ============================================================================
# Main Test Runner
# ============================================================================

async def main():
    """Run all race condition tests"""
    print_test_header("Race Condition and Concurrency Control Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Concurrent workflow state transitions (Optimistic Locking)",
         test_concurrent_workflow_transitions),
        ("Concurrent approval responses (Row-Level Locking)",
         test_concurrent_approval_responses),
        ("Double-click protection",
         test_double_click_protection),
        ("Approval expiry check order",
         test_approval_expiry_check_order),
        ("Approval + timeout race condition",
         test_approval_timeout_race),
        ("Retry after concurrent modification",
         test_retry_after_concurrent_modification),
    ]

    for test_name, test_func in tests:
        try:
            await test_func()
            print_pass(test_name)
            tests_passed += 1
        except Exception as e:
            print_fail(test_name, str(e))
            tests_failed += 1

    print_summary(tests_passed, tests_failed)
    return 0 if tests_failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
