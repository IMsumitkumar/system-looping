#!/usr/bin/env python3
"""
Test: Workflow Engine
Purpose: Test workflow CRUD operations

Tests:
- Create workflow
- Get workflow by ID
- List workflows
- Mark completed
- Mark failed
- Get workflow events
"""

import asyncio
import sys

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    TestContext, create_test_workflow,
    assert_equal, assert_true, assert_not_equal, assert_raises_async
)

from app.core.workflow_engine import WorkflowEngine
from app.models.schemas import WorkflowState


async def test_create_workflow():
    """Test creating a workflow"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(
                engine,
                workflow_type="deployment",
                context={"env": "production", "version": "1.2.3"}
            )

            assert_equal(workflow.workflow_type, "deployment")
            assert_equal(workflow.state, WorkflowState.CREATED.value)
            assert_true(workflow.id is not None)
            assert_equal(workflow.version, 1)


async def test_get_workflow():
    """Test getting a workflow by ID"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create workflow
            workflow = await create_test_workflow(engine)
            workflow_id = workflow.id

            # Get workflow
            retrieved = await engine.get_workflow(workflow_id)
            assert_equal(retrieved.id, workflow_id)
            assert_equal(retrieved.workflow_type, workflow.workflow_type)


async def test_get_nonexistent_workflow():
    """Test getting a non-existent workflow"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            await assert_raises_async(
                ValueError,
                engine.get_workflow("non-existent-id")
            )


async def test_list_workflows():
    """Test listing workflows"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create multiple workflows
            for i in range(5):
                await create_test_workflow(engine, workflow_type=f"type-{i}")

            # List all workflows
            workflows = await engine.list_workflows(limit=100)
            assert_equal(len(workflows), 5)


async def test_list_workflows_filtered_by_state():
    """Test listing workflows filtered by state"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create workflows in different states
            w1 = await create_test_workflow(engine)  # CREATED
            w2 = await create_test_workflow(engine)
            await engine.transition_to(w2.id, WorkflowState.RUNNING)  # RUNNING
            w3 = await create_test_workflow(engine)
            await engine.transition_to(w3.id, WorkflowState.RUNNING)  # RUNNING

            # List only RUNNING workflows
            running = await engine.list_workflows(state=WorkflowState.RUNNING)
            assert_equal(len(running), 2)

            # List only CREATED workflows
            created = await engine.list_workflows(state=WorkflowState.CREATED)
            assert_equal(len(created), 1)


async def test_mark_completed():
    """Test marking workflow as completed"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)

            # Mark completed with result data
            result_data = {"status": "success", "duration": 123}
            workflow = await engine.mark_completed(workflow.id, result_data)

            assert_equal(workflow.state, WorkflowState.COMPLETED.value)

            # Verify result is in context
            context = workflow.context_dict
            assert_equal(context["result"]["status"], "success")


async def test_mark_failed():
    """Test marking workflow as failed"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)

            # Mark failed
            workflow = await engine.mark_failed(workflow.id, "Database connection failed")

            assert_equal(workflow.state, WorkflowState.FAILED.value)


async def test_get_workflow_events():
    """Test getting workflow events"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            await engine.transition_to(workflow.id, WorkflowState.RUNNING)
            await engine.transition_to(workflow.id, WorkflowState.COMPLETED)

            # Get events
            events = await engine.get_workflow_events(workflow.id)

            # Should have: WORKFLOW_STARTED + 2 STATE_CHANGED + 1 COMPLETED
            assert_true(len(events) >= 3, f"Expected at least 3 events, got {len(events)}")

            # Verify first event is WORKFLOW_STARTED
            assert_equal(events[0].event_type, "workflow.started")


async def test_workflow_context():
    """Test workflow context operations"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create with context
            context = {"key1": "value1", "key2": 123}
            workflow = await create_test_workflow(engine, context=context)

            # Get context
            retrieved_context = workflow.context_dict
            assert_equal(retrieved_context["key1"], "value1")
            assert_equal(retrieved_context["key2"], 123)


async def test_workflow_timestamps():
    """Test workflow timestamps"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)

            assert_true(workflow.created_at is not None)
            assert_true(workflow.updated_at is not None)

            initial_updated_at = workflow.updated_at

            # Make a transition
            await asyncio.sleep(0.1)
            workflow = await engine.transition_to(workflow.id, WorkflowState.RUNNING)

            # Updated timestamp should change
            assert_not_equal(
                workflow.updated_at,
                initial_updated_at,
                "updated_at should change on transition"
            )


async def main():
    """Run all workflow engine tests"""
    print_test_header("Workflow Engine Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Create workflow", test_create_workflow),
        ("Get workflow by ID", test_get_workflow),
        ("Get non-existent workflow", test_get_nonexistent_workflow),
        ("List workflows", test_list_workflows),
        ("List workflows filtered by state", test_list_workflows_filtered_by_state),
        ("Mark workflow completed", test_mark_completed),
        ("Mark workflow failed", test_mark_failed),
        ("Get workflow events", test_get_workflow_events),
        ("Workflow context operations", test_workflow_context),
        ("Workflow timestamps", test_workflow_timestamps),
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
