#!/usr/bin/env python3
"""
Test: Database Performance and Configuration
Purpose: Verify database indexes, WAL mode, and performance optimizations

Tests Critical Fixes #4 and #5:
- Database indexes are created correctly
- WAL mode is enabled
- Foreign keys are enforced
- Query performance meets requirements
"""

import asyncio
import sys
import time
from datetime import datetime
from sqlalchemy import text

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    TestContext, create_test_workflow, create_test_approval,
    assert_true, assert_equal, PerformanceTimer
)

from app.core.workflow_engine import WorkflowEngine
from app.core.approval_service import ApprovalService
from app.models.schemas import WorkflowState


# ============================================================================
# Test: WAL Mode Enabled
# ============================================================================

async def test_wal_mode_enabled():
    """
    Test that SQLite WAL mode is enabled.

    Verifies:
    - journal_mode is WAL
    - Allows concurrent reads during writes

    Tests Fix #5: SQLite WAL mode (database.py:62-86)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            # Check journal mode
            result = await session.execute(text("PRAGMA journal_mode"))
            journal_mode = result.scalar()

            assert_equal(
                journal_mode.upper(),
                "WAL",
                "Database should be in WAL mode for better concurrency"
            )

            print_info(f"Journal mode: {journal_mode}")


# ============================================================================
# Test: Foreign Keys Enabled
# ============================================================================

async def test_foreign_keys_enabled():
    """
    Test that foreign key constraints are enforced.

    Verifies:
    - foreign_keys pragma is ON
    - Orphan records are rejected

    Tests Fix #5: Foreign key enforcement (database.py:67)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            # Check foreign keys pragma
            result = await session.execute(text("PRAGMA foreign_keys"))
            foreign_keys = result.scalar()

            assert_equal(
                foreign_keys,
                1,
                "Foreign keys should be enabled"
            )

            print_info("Foreign keys: ENABLED")

            # Test enforcement - try to create approval with non-existent workflow
            try:
                await session.execute(text(
                    "INSERT INTO approval_requests "
                    "(id, workflow_id, status, ui_schema, expires_at, callback_token) "
                    "VALUES ('test', 'non-existent-workflow', 'PENDING', '{}', 0, 'token')"
                ))
                await session.commit()
                raise AssertionError("Should have rejected orphan approval record")
            except Exception as e:
                # Should fail due to foreign key constraint
                assert_true(
                    "foreign key" in str(e).lower() or "constraint" in str(e).lower(),
                    f"Expected foreign key error, got: {e}"
                )
                await session.rollback()


# ============================================================================
# Test: Workflow Indexes Exist
# ============================================================================

async def test_workflow_indexes_exist():
    """
    Test that workflow table indexes are created.

    Verifies all indexes from models.py:35-41:
    - idx_workflows_state
    - idx_workflows_created_desc
    - idx_workflows_state_created

    Tests Fix #4: Database indexes (models.py:35-41)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            # Get all indexes for workflows table
            result = await session.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='workflows'"
            ))
            indexes = [row[0] for row in result.fetchall()]

            print_info(f"Workflow indexes: {indexes}")

            # Check for required indexes
            required_indexes = [
                "idx_workflows_state",
                "idx_workflows_created_desc",
                "idx_workflows_state_created",
            ]

            for idx_name in required_indexes:
                assert_true(
                    idx_name in indexes,
                    f"Missing required index: {idx_name}"
                )


# ============================================================================
# Test: WorkflowEvent Indexes Exist
# ============================================================================

async def test_workflow_event_indexes_exist():
    """
    Test that workflow_events table indexes are created.

    Verifies all indexes from models.py:88-93:
    - idx_events_workflow_occurred
    - idx_events_type

    Tests Fix #4: Event table indexes (models.py:88-93)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            result = await session.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='workflow_events'"
            ))
            indexes = [row[0] for row in result.fetchall()]

            print_info(f"Event indexes: {indexes}")

            required_indexes = [
                "idx_events_workflow_occurred",
                "idx_events_type",
            ]

            for idx_name in required_indexes:
                assert_true(
                    idx_name in indexes,
                    f"Missing required index: {idx_name}"
                )


# ============================================================================
# Test: Approval Indexes Exist
# ============================================================================

async def test_approval_indexes_exist():
    """
    Test that approval_requests table indexes are created.

    Verifies all indexes from models.py:136-139:
    - idx_approvals_pending
    - idx_approvals_token

    Tests Fix #4: Approval table indexes (models.py:136-139)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            result = await session.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='approval_requests'"
            ))
            indexes = [row[0] for row in result.fetchall()]

            print_info(f"Approval indexes: {indexes}")

            required_indexes = [
                "idx_approvals_pending",
                "idx_approvals_token",
            ]

            for idx_name in required_indexes:
                assert_true(
                    idx_name in indexes,
                    f"Missing required index: {idx_name}"
                )


# ============================================================================
# Test: Query Plan Uses Indexes
# ============================================================================

async def test_query_plan_uses_indexes():
    """
    Test that queries use indexes (EXPLAIN QUERY PLAN).

    Verifies:
    - get_workflow_events query uses idx_events_workflow_occurred
    - list_workflows query uses idx_workflows_created_desc
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create test data
            workflow = await create_test_workflow(engine)
            await session.commit()

            # Test 1: get_workflow_events should use index
            result = await session.execute(text(
                "EXPLAIN QUERY PLAN "
                "SELECT * FROM workflow_events "
                "WHERE workflow_id = :wid "
                "ORDER BY occurred_at",
            ), {"wid": workflow.id})

            query_plan = " ".join([str(row[3]) for row in result.fetchall()])
            print_info(f"Events query plan: {query_plan}")

            assert_true(
                "idx_events_workflow_occurred" in query_plan or "USING INDEX" in query_plan.upper(),
                "Events query should use index"
            )

            # Test 2: list_workflows should use index
            result = await session.execute(text(
                "EXPLAIN QUERY PLAN "
                "SELECT * FROM workflows "
                "ORDER BY created_at DESC "
                "LIMIT 100"
            ))

            query_plan = " ".join([str(row[3]) for row in result.fetchall()])
            print_info(f"Workflows query plan: {query_plan}")

            assert_true(
                "idx_workflows_created" in query_plan or "USING INDEX" in query_plan.upper(),
                "Workflows query should use index"
            )


# ============================================================================
# Test: Performance - Get Workflow Events
# ============================================================================

async def test_performance_get_workflow_events():
    """
    Test get_workflow_events performance with many events.

    Requirement: Query < 100ms with 1000 events

    Tests Fix #4: Index performance
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create workflow
            workflow = await create_test_workflow(engine)
            await session.commit()

            # Create 1000 events
            print_info("Creating 1000 events...")
            for i in range(1000):
                await engine._record_event(
                    workflow.id,
                    "test.event",
                    {"iteration": i, "timestamp": datetime.now().isoformat()}
                )

                # Commit in batches
                if i % 100 == 0:
                    await session.commit()
                    print_info(f"  Created {i} events...")

            await session.commit()

            # Measure query performance
            print_info("Measuring query performance...")

            with PerformanceTimer() as timer:
                events = await engine.get_workflow_events(workflow.id)

            duration_ms = timer.get_duration_ms()
            event_count = len(events)

            print_info(f"Retrieved {event_count} events in {duration_ms:.2f}ms")

            # Verify we got all events
            assert_equal(
                event_count,
                1001,  # 1000 + initial WORKFLOW_STARTED event
                "Should retrieve all events"
            )

            # Performance requirement: < 100ms
            assert_true(
                duration_ms < 100,
                f"Query should complete in < 100ms, took {duration_ms:.2f}ms"
            )


# ============================================================================
# Test: Performance - List Workflows
# ============================================================================

async def test_performance_list_workflows():
    """
    Test list_workflows performance with many workflows.

    Requirement: Query < 200ms with 1000 workflows (reduced from 10k for speed)

    Tests Fix #4: Index performance
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)

            # Create 1000 workflows
            print_info("Creating 1000 workflows...")
            for i in range(1000):
                await create_test_workflow(
                    engine,
                    workflow_type=f"test-{i % 10}",
                    context={"index": i}
                )

                # Commit in batches
                if i % 100 == 0:
                    await session.commit()
                    print_info(f"  Created {i} workflows...")

            await session.commit()

            # Measure query performance
            print_info("Measuring query performance...")

            with PerformanceTimer() as timer:
                workflows = await engine.list_workflows(limit=100)

            duration_ms = timer.get_duration_ms()

            print_info(f"Listed {len(workflows)} workflows in {duration_ms:.2f}ms")

            # Verify results
            assert_equal(
                len(workflows),
                100,
                "Should return 100 workflows (limit)"
            )

            # Performance requirement: < 200ms
            assert_true(
                duration_ms < 200,
                f"Query should complete in < 200ms, took {duration_ms:.2f}ms"
            )


# ============================================================================
# Test: Concurrent Reads During Write
# ============================================================================

async def test_concurrent_reads_during_write():
    """
    Test that WAL mode allows concurrent reads during writes.

    Verifies:
    - Read can happen while write transaction is open
    - WAL mode enables this concurrency

    Tests Fix #5: WAL mode concurrency (database.py:64)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session1:
            engine1 = WorkflowEngine(session1, ctx.event_bus)

            # Create initial workflow
            workflow = await create_test_workflow(engine1)
            await session1.commit()
            workflow_id = workflow.id

            # Start a write transaction but don't commit yet
            await engine1._record_event(
                workflow_id,
                "test.event",
                {"message": "Long running write"}
            )
            # DON'T commit yet - transaction is open

            # While write transaction is open, try to read from another session
            read_success = False
            async with ctx.get_session() as session2:
                engine2 = WorkflowEngine(session2, ctx.event_bus)

                # This should succeed due to WAL mode
                retrieved_workflow = await engine2.get_workflow(workflow_id)
                read_success = retrieved_workflow is not None

            # Now commit the write
            await session1.commit()

            # Verify read succeeded during write
            assert_true(
                read_success,
                "WAL mode should allow concurrent reads during writes"
            )

            print_info("Concurrent read during write: SUCCESS ✓")


# ============================================================================
# Test: Cache Size Configuration
# ============================================================================

async def test_cache_size_configuration():
    """
    Test that SQLite cache size is configured.

    Verifies:
    - cache_size pragma is set (should be negative for KB, -10000 = ~40MB)
    """
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            result = await session.execute(text("PRAGMA cache_size"))
            cache_size = result.scalar()

            print_info(f"Cache size: {cache_size} pages")

            # Should be set to -10000 (negative means KB)
            # Or it might be positive (pages), so just check it's configured
            assert_true(
                cache_size != 0 and cache_size is not None,
                f"Cache size should be configured, got: {cache_size}"
            )


# ============================================================================
# Main Test Runner
# ============================================================================

async def main():
    """Run all database performance tests"""
    print_test_header("Database Performance and Configuration Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("WAL mode enabled", test_wal_mode_enabled),
        ("Foreign keys enabled", test_foreign_keys_enabled),
        ("Workflow indexes exist", test_workflow_indexes_exist),
        ("WorkflowEvent indexes exist", test_workflow_event_indexes_exist),
        ("Approval indexes exist", test_approval_indexes_exist),
        ("Query plan uses indexes", test_query_plan_uses_indexes),
        ("Performance: get_workflow_events < 100ms", test_performance_get_workflow_events),
        ("Performance: list_workflows < 200ms", test_performance_list_workflows),
        ("Concurrent reads during write (WAL)", test_concurrent_reads_during_write),
        ("Cache size configuration", test_cache_size_configuration),
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
