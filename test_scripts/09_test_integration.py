#!/usr/bin/env python3
"""
Test: Full System Integration
Purpose: End-to-end system integration tests

Tests:
- Complete approval workflow via all components
- Event propagation through system
- Database transactions
- Component coordination
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
from app.models.schemas import WorkflowState, ApprovalStatus, EventType


async def test_complete_workflow_with_approval():
    """
    Test complete workflow: create -> request approval -> approve -> complete

    This is the full end-to-end happy path.
    """
    async with TestContext() as ctx:
        event_collector = EventCollector()

        # Subscribe to all events
        for event_type in EventType:
            ctx.event_bus.subscribe(event_type, event_collector.handler)

        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # 1. Create workflow
            workflow = await create_test_workflow(engine, workflow_type="deployment")
            print_info(f"Created workflow: {workflow.id}")

            # 2. Transition to RUNNING
            workflow = await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            print_info("Transitioned to RUNNING")

            # 3. Request approval
            workflow = await engine.transition_to(workflow.id, WorkflowState.WAITING_APPROVAL)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=3600)
            print_info(f"Created approval: {approval.id}")

            # 4. Approve
            approval = await service.respond_to_approval(
                approval.id,
                "approve",
                {"approver_name": "Integration Test", "risk_level": "low"}
            )
            print_info("Approval received")

            # 5. Transition to APPROVED
            workflow = await engine.transition_to(workflow.id, WorkflowState.APPROVED)

            # 6. Complete workflow
            workflow = await engine.mark_completed(
                workflow.id,
                {"status": "deployed", "env": "production"}
            )
            print_info("Workflow completed")

            await session.commit()

        # Wait for events to propagate
        await asyncio.sleep(0.2)

        # Verify final state
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session)
            final_workflow = await engine.get_workflow(workflow.id)

            assert_equal(final_workflow.state, WorkflowState.COMPLETED.value)

            # Verify events were published
            events = event_collector.get_events()
            assert_true(len(events) >= 5, f"Expected at least 5 events, got {len(events)}")

            # Verify specific events
            workflow_started = event_collector.find_event(workflow_id=workflow.id)
            assert_true(workflow_started is not None, "Should have workflow started event")

            print_info(f"Total events received: {len(events)}")


async def test_workflow_rejection_path():
    """
    Test rejection path: create -> request approval -> reject -> failed
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create and request approval
            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            await engine.transition_to(workflow.id, WorkflowState.WAITING_APPROVAL)
            approval = await create_test_approval(service, workflow.id)

            # Reject
            approval = await service.respond_to_approval(
                approval.id,
                "reject",
                {"approver_name": "Reviewer", "risk_level": "low", "comments": "Not ready"}
            )

            # Transition to REJECTED then FAILED
            await engine.transition_to(workflow.id, WorkflowState.REJECTED)
            workflow = await engine.mark_failed(workflow.id, "Approval rejected")

            assert_equal(workflow.state, WorkflowState.FAILED.value)
            assert_equal(approval.status, ApprovalStatus.REJECTED.value)


async def test_workflow_timeout_path():
    """
    Test timeout path: create -> request approval -> timeout -> failed
    """
    async with TestContext() as ctx:
        timeout_mgr = TimeoutManager(ctx.db, ctx.event_bus, check_interval=1)

        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create approval with short timeout
            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            await engine.transition_to(workflow.id, WorkflowState.WAITING_APPROVAL)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=1)

            workflow_id = workflow.id
            approval_id = approval.id
            await session.commit()

        # Start timeout manager
        await timeout_mgr.start()

        try:
            # Wait for timeout
            print_info("Waiting for timeout...")
            await asyncio.sleep(3)

            # Verify approval timed out
            async with ctx.get_session() as session:
                service = ApprovalService(session, ctx.event_bus)
                approval = await service.get_approval(approval_id)
                assert_equal(approval.status, ApprovalStatus.TIMEOUT.value)

                # Transition workflow to TIMEOUT then FAILED
                engine = WorkflowEngine(session, ctx.event_bus)
                await engine.transition_to(workflow_id, WorkflowState.TIMEOUT)
                workflow = await engine.mark_failed(workflow_id, "Approval timeout")
                assert_equal(workflow.state, WorkflowState.FAILED.value)

        finally:
            await timeout_mgr.stop()


async def test_event_propagation():
    """
    Test that events propagate through all subscribers
    """
    async with TestContext() as ctx:
        collector1 = EventCollector()
        collector2 = EventCollector()

        # Subscribe both collectors
        ctx.event_bus.subscribe(EventType.WORKFLOW_STARTED, collector1.handler)
        ctx.event_bus.subscribe(EventType.WORKFLOW_STARTED, collector2.handler)
        ctx.event_bus.subscribe(EventType.WORKFLOW_COMPLETED, collector1.handler)
        ctx.event_bus.subscribe(EventType.WORKFLOW_COMPLETED, collector2.handler)

        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create and complete workflow
            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            await engine.mark_completed(workflow.id)

        # Wait for propagation
        await asyncio.sleep(0.2)

        # Both collectors should receive events
        assert_true(collector1.count() >= 2, "Collector 1 should receive events")
        assert_true(collector2.count() >= 2, "Collector 2 should receive events")


async def test_database_transaction_rollback():
    """
    Test that database transactions roll back on error
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create workflow
            workflow = await create_test_workflow(engine)
            workflow_id = workflow.id

            # Verify workflow exists
            retrieved = await engine.get_workflow(workflow_id)
            assert_equal(retrieved.id, workflow_id)

        # Start new transaction that will fail
        try:
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)

                # Create another workflow
                workflow2 = await create_test_workflow(engine)
                workflow2_id = workflow2.id

                # Force an error before commit
                raise Exception("Simulated error")

        except Exception:
            pass  # Expected

        # Verify first workflow still exists
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session)
            workflow1 = await engine.get_workflow(workflow_id)
            assert_equal(workflow1.id, workflow_id)

        # Verify second workflow was rolled back (doesn't exist)
        try:
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session)
                await engine.get_workflow(workflow2_id)
            # If we get here, rollback failed
            raise AssertionError("Transaction should have been rolled back")
        except ValueError:
            # Expected - workflow doesn't exist
            pass


async def test_concurrent_workflows():
    """
    Test creating and processing multiple workflows concurrently
    """
    async with TestContext() as ctx:
        async def create_and_complete_workflow(workflow_num):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)

                workflow = await create_test_workflow(
                    engine,
                    workflow_type=f"concurrent-{workflow_num}"
                )
                await engine.transition_to(workflow.id, WorkflowState.RUNNING)
                await engine.mark_completed(workflow.id, {"num": workflow_num})

                return workflow.id

        # Create 10 workflows concurrently
        workflow_ids = await asyncio.gather(*[
            create_and_complete_workflow(i) for i in range(10)
        ])

        # Verify all were created
        assert_equal(len(workflow_ids), 10)

        # Verify all are completed
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session)

            for workflow_id in workflow_ids:
                workflow = await engine.get_workflow(workflow_id)
                assert_equal(workflow.state, WorkflowState.COMPLETED.value)


async def main():
    """Run all integration tests"""
    print_test_header("Full System Integration Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Complete workflow with approval", test_complete_workflow_with_approval),
        ("Workflow rejection path", test_workflow_rejection_path),
        ("Workflow timeout path", test_workflow_timeout_path),
        ("Event propagation", test_event_propagation),
        ("Database transaction rollback", test_database_transaction_rollback),
        ("Concurrent workflows", test_concurrent_workflows),
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
