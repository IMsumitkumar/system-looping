#!/usr/bin/env python3
"""
Test: Approval Flow
Purpose: End-to-end approval testing

Tests:
- Complete approval flow (request -> approve -> complete)
- Rejection flow
- Timeout flow
- Approval expiry handling
- Token-based approval access
"""

import asyncio
import sys

from fixtures import (
    print_test_header, print_pass, print_fail, print_summary, print_info,
    TestContext, create_test_workflow, create_test_approval,
    assert_equal, assert_true, assert_raises_async
)

from app.core.workflow_engine import WorkflowEngine
from app.core.approval_service import ApprovalService
from app.models.schemas import WorkflowState, ApprovalStatus


async def test_complete_approval_flow():
    """Test complete approval flow from creation to approval"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create workflow
            workflow = await create_test_workflow(engine)

            # Request approval
            approval = await create_test_approval(service, workflow.id)
            assert_equal(approval.status, ApprovalStatus.PENDING.value)

            # Approve
            approval = await service.respond_to_approval(
                approval.id,
                "approve",
                {"approver_name": "Test User", "risk_level": "low"}
            )

            assert_equal(approval.status, ApprovalStatus.APPROVED.value)
            assert_true(approval.responded_at is not None)


async def test_rejection_flow():
    """Test approval rejection flow"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id)

            # Reject
            approval = await service.respond_to_approval(
                approval.id,
                "reject",
                {"approver_name": "Test User", "risk_level": "low", "comments": "Not ready"}
            )

            assert_equal(approval.status, ApprovalStatus.REJECTED.value)


async def test_timeout_flow():
    """Test approval timeout flow"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id, timeout_seconds=1)

            # Wait for timeout
            await asyncio.sleep(1.5)

            # Mark timeout
            approval = await service.mark_timeout(approval.id)
            assert_equal(approval.status, ApprovalStatus.TIMEOUT.value)


async def test_approval_by_token():
    """Test approval access using callback token"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            workflow = await create_test_workflow(engine)
            approval = await create_test_approval(service, workflow.id)

            # Get approval by token
            retrieved = await service.get_approval_by_token(approval.callback_token)
            assert_equal(retrieved.id, approval.id)


async def test_get_pending_approvals():
    """Test getting all pending approvals"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            engine = WorkflowEngine(session, ctx.event_bus)
            service = ApprovalService(session, ctx.event_bus)

            # Create multiple workflows and approvals
            for i in range(5):
                workflow = await create_test_workflow(engine)
                await create_test_approval(service, workflow.id)

            # Get pending approvals
            pending = await service.get_pending_approvals()
            assert_equal(len(pending), 5)


async def test_approval_not_found():
    """Test approval not found error"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            service = ApprovalService(session, ctx.event_bus)

            await assert_raises_async(
                ValueError,
                service.get_approval("non-existent-id")
            )


async def test_invalid_callback_token():
    """Test invalid callback token"""
    async with TestContext() as ctx:
        async with ctx.get_session() as session:
            service = ApprovalService(session, ctx.event_bus)

            await assert_raises_async(
                ValueError,
                service.get_approval_by_token("invalid-token")
            )


async def main():
    """Run all approval flow tests"""
    print_test_header("Approval Flow Tests")

    tests_passed = 0
    tests_failed = 0

    tests = [
        ("Complete approval flow", test_complete_approval_flow),
        ("Rejection flow", test_rejection_flow),
        ("Timeout flow", test_timeout_flow),
        ("Approval by callback token", test_approval_by_token),
        ("Get pending approvals", test_get_pending_approvals),
        ("Approval not found error", test_approval_not_found),
        ("Invalid callback token error", test_invalid_callback_token),
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
