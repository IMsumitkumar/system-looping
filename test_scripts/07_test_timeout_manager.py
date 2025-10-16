#!/usr/bin/env python3
"""
Test: Timeout Manager
Purpose: Test timeout detection and handling

Tests:
- Expired approvals are detected
- Timeout events are published
- Already-processed approvals are skipped
- Timeout manager lifecycle
"""

import asyncio
import sys

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    TestContext, create_test_workflow, create_test_approval, EventCollector,
    assert_equal, assert_true
)

from app.core.workflow_engine import WorkflowEngine
from app.core.approval_service import ApprovalService
from app.core.timeout_manager import TimeoutManager
from app.models.schemas import EventType, ApprovalStatus


async def test_expired_approvals_detected():
    """Test that timeout manager detects expired approvals"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create approval with 1 second timeout
            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=1)
            await session.commit()

            # Wait for expiry
            print_info("Waiting for approval to expire...")
            await asyncio.sleep(1.5)

            # Get expired approvals
            expired = await service.get_expired_approvals()
            assert_equal(len(expired), 1, "Should find one expired approval")
            assert_equal(expired[0].id, approval.id)


async def test_timeout_manager_processes_expired():
    """Test that timeout manager processes expired approvals"""
    async with TestContext() as ctx:
        timeout_mgr = TimeoutManager(ctx.db, ctx.event_bus, check_interval=1)

        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create approval with 1 second timeout
            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=1)
            approval_id = approval.id
            await session.commit()

        # Start timeout manager
        await timeout_mgr.start()

        try:
            # Wait for timeout to be processed
            print_info("Waiting for timeout manager to process...")
            await asyncio.sleep(3)

            # Check approval status
            async with ctx.get_session() as session:
                service = ApprovalService(session, ctx.event_bus)
                approval = await service.get_approval(approval_id)

                assert_equal(
                    approval.status,
                    ApprovalStatus.TIMEOUT.value,
                    "Approval should be marked as TIMEOUT"
                )

        finally:
            await timeout_mgr.stop()


async def test_already_processed_approvals_skipped():
    """Test that already-processed approvals are skipped"""
    async with TestContext() as ctx:
        timeout_mgr = TimeoutManager(ctx.db, ctx.event_bus, check_interval=1)

        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create approval
            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=10)

            # Approve it immediately
            approval = await service.respond_to_approval(
                approval.id,
                "approve",
                {"approver_name": "User", "risk_level": "low"}
            )
            approval_id = approval.id
            await session.commit()

        # Start timeout manager
        await timeout_mgr.start()

        try:
            # Wait for timeout check
            await asyncio.sleep(2)

            # Verify status hasn't changed
            async with ctx.get_session() as session:
                service = ApprovalService(session, ctx.event_bus)
                approval = await service.get_approval(approval_id)

                assert_equal(
                    approval.status,
                    ApprovalStatus.APPROVED.value,
                    "Status should remain APPROVED, not changed to TIMEOUT"
                )

        finally:
            await timeout_mgr.stop()


async def test_timeout_events_published():
    """Test that timeout events are published to event bus"""
    async with TestContext() as ctx:
        timeout_mgr = TimeoutManager(ctx.db, ctx.event_bus, check_interval=1)
        event_collector = EventCollector()

        # Subscribe to timeout events
        ctx.event_bus.subscribe(EventType.APPROVAL_TIMEOUT, event_collector.handler)

        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create approval with 1 second timeout
            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=1)
            approval_id = approval.id
            await session.commit()

        # Start timeout manager
        await timeout_mgr.start()

        try:
            # Wait for processing
            await asyncio.sleep(3)

            # Verify event was published
            events = event_collector.get_events()
            assert_true(len(events) > 0, "Should publish timeout event")

            timeout_event = event_collector.find_event(approval_id=approval_id)
            assert_true(
                timeout_event is not None,
                "Should find timeout event for our approval"
            )

        finally:
            await timeout_mgr.stop()


async def test_timeout_manager_lifecycle():
    """Test timeout manager start/stop lifecycle"""
    async with TestContext() as ctx:
        timeout_mgr = TimeoutManager(ctx.db, ctx.event_bus, check_interval=5)

        # Start
        await timeout_mgr.start()
        assert_true(timeout_mgr._running, "Should be running after start")

        # Stop
        await timeout_mgr.stop()
        assert_equal(timeout_mgr._running, False, "Should not be running after stop")


async def test_multiple_expired_approvals():
    """Test processing multiple expired approvals"""
    async with TestContext() as ctx:
        timeout_mgr = TimeoutManager(ctx.db, ctx.event_bus, check_interval=1)

        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create 5 approvals with 1 second timeout
            approval_ids = []
            for i in range(5):
                workflow = await create_test_workflow(engine)
                approval = await create_test_approval(service, workflow.id, timeout_seconds=1)
                approval_ids.append(approval.id)

            await session.commit()

        # Start timeout manager
        await timeout_mgr.start()

        try:
            # Wait for processing
            print_info("Waiting for timeout manager to process 5 approvals...")
            await asyncio.sleep(3)

            # Verify all are timed out
            async with ctx.get_session() as session:
                service = ApprovalService(session, ctx.event_bus)

                for approval_id in approval_ids:
                    approval = await service.get_approval(approval_id)
                    assert_equal(
                        approval.status,
                        ApprovalStatus.TIMEOUT.value,
                        f"Approval {approval_id} should be TIMEOUT"
                    )

        finally:
            await timeout_mgr.stop()


async def main():
    """Run all timeout manager tests"""
    print_test_header("Timeout Manager Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Expired approvals detected", test_expired_approvals_detected),
        ("Timeout manager processes expired approvals", test_timeout_manager_processes_expired),
        ("Already-processed approvals skipped", test_already_processed_approvals_skipped),
        ("Timeout events published", test_timeout_events_published),
        ("Timeout manager lifecycle", test_timeout_manager_lifecycle),
        ("Multiple expired approvals", test_multiple_expired_approvals),
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
