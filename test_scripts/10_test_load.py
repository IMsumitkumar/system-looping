#!/usr/bin/env python3
"""
Test: Load and Performance
Purpose: Test system under load

Tests:
- Create many workflows concurrently
- Process many approvals concurrently
- Event queue handling under load
- Database performance under load
"""

import asyncio
import sys
import time

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    TestContext, create_test_workflow, create_test_approval, PerformanceTimer,
    assert_true, assert_equal
)

from app.core.workflow_engine import WorkflowEngine
from app.core.approval_service import ApprovalService
from app.models.schemas import WorkflowState


async def test_create_100_workflows_concurrently():
    """Test creating 100 workflows concurrently"""
    async with TestContext() as ctx:
        print_info("Creating 100 workflows concurrently...")

        async def create_workflow_task(i):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)
                return await create_test_workflow(
                    engine,
                    workflow_type=f"load-test-{i % 10}",
                    context={"index": i, "batch": "load-test"}
                )

        with PerformanceTimer() as timer:
            workflows = await asyncio.gather(*[
                create_workflow_task(i) for i in range(100)
            ])

        duration_ms = timer.get_duration_ms()
        print_info(f"Created 100 workflows in {duration_ms:.2f}ms ({duration_ms/100:.2f}ms per workflow)")

        assert_equal(len(workflows), 100, "Should create 100 workflows")

        # Performance target: < 5 seconds for 100 workflows
        assert_true(
            duration_ms < 5000,
            f"Should create 100 workflows in < 5s, took {duration_ms:.2f}ms"
        )


async def test_process_50_approvals_concurrently():
    """Test processing 50 approval responses concurrently"""
    async with TestContext() as ctx:
        # First, create 50 workflows and approvals
        print_info("Setting up 50 approvals...")
        approval_ids = []

        for i in range(50):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)
                service = ApprovalService(session, ctx.event_bus)

                workflow = await create_test_workflow(engine)
                approval = await create_test_approval(service, workflow.id)
                approval_ids.append(approval.id)
                await session.commit()

        print_info(f"Processing {len(approval_ids)} approvals concurrently...")

        async def approve_task(approval_id, i):
            async with ctx.get_session() as session:
                service = ApprovalService(session, ctx.event_bus)
                return await service.respond_to_approval(
                    approval_id,
                    "approve",
                    {"approver_name": f"User-{i}", "risk_level": "low"}
                )

        with PerformanceTimer() as timer:
            results = await asyncio.gather(*[
                approve_task(aid, i) for i, aid in enumerate(approval_ids)
            ], return_exceptions=True)

        duration_ms = timer.get_duration_ms()

        # Count successes
        successes = [r for r in results if not isinstance(r, Exception)]
        print_info(f"Processed {len(successes)}/50 approvals in {duration_ms:.2f}ms")

        assert_equal(len(successes), 50, "All approvals should succeed")

        # Performance target: < 3 seconds for 50 approvals
        assert_true(
            duration_ms < 3000,
            f"Should process 50 approvals in < 3s, took {duration_ms:.2f}ms"
        )


async def test_event_queue_under_load():
    """Test event queue handling under load"""
    async with TestContext() as ctx:
        event_count = 0

        async def counting_handler(data: dict):
            nonlocal event_count
            event_count += 1

        # Subscribe to workflow events
        from app.models.schemas import EventType
        ctx.event_bus.subscribe(EventType.WORKFLOW_STARTED, counting_handler)
        ctx.event_bus.subscribe(EventType.WORKFLOW_STATE_CHANGED, counting_handler)

        print_info("Creating 50 workflows to generate events...")

        # Create 50 workflows, each generating multiple events
        async def create_and_transition(i):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)
                workflow = await create_test_workflow(engine)
                await engine.transition_to(workflow.id, WorkflowState.RUNNING)
                await engine.transition_to(workflow.id, WorkflowState.COMPLETED)
                return workflow.id

        workflow_ids = await asyncio.gather(*[
            create_and_transition(i) for i in range(50)
        ])

        # Wait for event processing
        print_info("Waiting for event processing...")
        await asyncio.sleep(2)

        # Should have received many events (50 * 3 = 150 minimum)
        print_info(f"Received {event_count} events")
        assert_true(
            event_count >= 100,
            f"Should receive at least 100 events, got {event_count}"
        )


async def test_database_write_performance():
    """Test database write performance under load"""
    async with TestContext() as ctx:
        print_info("Testing database write performance...")

        async def write_workflow(i):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)
                workflow = await create_test_workflow(
                    engine,
                    workflow_type="write-test",
                    context={"iteration": i, "timestamp": time.time()}
                )
                # Make some transitions
                await engine.transition_to(workflow.id, WorkflowState.RUNNING)
                return workflow.id

        # Write 100 workflows sequentially (to test write speed)
        with PerformanceTimer() as timer:
            for i in range(100):
                await write_workflow(i)

        duration_ms = timer.get_duration_ms()
        avg_write_ms = duration_ms / 100

        print_info(f"Sequential writes: {duration_ms:.2f}ms total, {avg_write_ms:.2f}ms per workflow")

        # Performance target: average write < 50ms
        assert_true(
            avg_write_ms < 50,
            f"Average write should be < 50ms, got {avg_write_ms:.2f}ms"
        )


async def test_database_read_performance():
    """Test database read performance"""
    async with TestContext() as ctx:
        # Create 100 workflows first
        print_info("Setting up 100 workflows for read test...")
        workflow_ids = []

        for i in range(100):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)
                workflow = await create_test_workflow(engine)
                workflow_ids.append(workflow.id)

        print_info("Testing read performance...")

        # Read all workflows
        async def read_workflow(workflow_id):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session)
                return await engine.get_workflow(workflow_id)

        with PerformanceTimer() as timer:
            workflows = await asyncio.gather(*[
                read_workflow(wid) for wid in workflow_ids
            ])

        duration_ms = timer.get_duration_ms()
        avg_read_ms = duration_ms / 100

        print_info(f"Concurrent reads: {duration_ms:.2f}ms total, {avg_read_ms:.2f}ms per workflow")

        assert_equal(len(workflows), 100, "Should read all workflows")

        # Performance target: average read < 10ms
        assert_true(
            avg_read_ms < 10,
            f"Average read should be < 10ms, got {avg_read_ms:.2f}ms"
        )


async def test_mixed_read_write_load():
    """Test mixed read/write workload"""
    async with TestContext() as ctx:
        print_info("Testing mixed read/write workload...")

        # Create some initial workflows
        workflow_ids = []
        for i in range(20):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)
                workflow = await create_test_workflow(engine)
                workflow_ids.append(workflow.id)

        async def write_task(i):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session, ctx.event_bus)
                workflow = await create_test_workflow(engine, workflow_type=f"mixed-{i}")
                return workflow.id

        async def read_task(workflow_id):
            async with ctx.get_session() as session:
                engine = WorkflowEngine(session)
                return await engine.get_workflow(workflow_id)

        # Mix of 30 writes and 50 reads
        tasks = []
        tasks.extend([write_task(i) for i in range(30)])
        tasks.extend([read_task(workflow_ids[i % len(workflow_ids)]) for i in range(50)])

        with PerformanceTimer() as timer:
            results = await asyncio.gather(*tasks, return_exceptions=True)

        duration_ms = timer.get_duration_ms()

        # Count successes
        successes = [r for r in results if not isinstance(r, Exception)]
        print_info(f"Mixed workload: {len(successes)}/80 operations in {duration_ms:.2f}ms")

        # Should complete successfully
        assert_true(
            len(successes) >= 75,
            f"Should complete at least 75/80 operations, got {len(successes)}"
        )


async def main():
    """Run all load tests"""
    print_test_header("Load and Performance Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Create 100 workflows concurrently", test_create_100_workflows_concurrently),
        ("Process 50 approvals concurrently", test_process_50_approvals_concurrently),
        ("Event queue under load", test_event_queue_under_load),
        ("Database write performance", test_database_write_performance),
        ("Database read performance", test_database_read_performance),
        ("Mixed read/write load", test_mixed_read_write_load),
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
