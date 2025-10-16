"""Health check and metrics endpoints."""

from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_event_bus, get_timeout_manager
from app.models import Workflow, ApprovalRequest, get_db
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(status="healthy", timestamp=datetime.now().timestamp())


@router.get("/metrics")
async def metrics(
    db_session: AsyncSession = Depends(get_db),
    event_bus = Depends(get_event_bus),
    timeout_manager = Depends(get_timeout_manager),
):
    """
    System metrics endpoint for observability.
    Returns workflow counts, approval stats, and event bus metrics.
    """
    # Get workflow counts by state
    workflow_counts = await db_session.execute(
        select(Workflow.state, func.count(Workflow.id)).group_by(Workflow.state)
    )
    workflows_by_state = {state: count for state, count in workflow_counts.fetchall()}

    # Get approval counts by status
    approval_counts = await db_session.execute(
        select(ApprovalRequest.status, func.count(ApprovalRequest.id)).group_by(ApprovalRequest.status)
    )
    approvals_by_status = {status: count for status, count in approval_counts.fetchall()}

    # Get total counts
    total_workflows = await db_session.execute(select(func.count(Workflow.id)))
    total_approvals = await db_session.execute(select(func.count(ApprovalRequest.id)))

    # Get event bus stats
    event_bus_stats = event_bus.get_stats()

    return {
        "timestamp": datetime.now().timestamp(),
        "workflows": {
            "total": total_workflows.scalar(),
            "by_state": workflows_by_state,
        },
        "approvals": {
            "total": total_approvals.scalar(),
            "by_status": approvals_by_status,
        },
        "event_bus": event_bus_stats,
        "timeout_manager": {
            "check_interval_seconds": timeout_manager.check_interval,
            "running": timeout_manager._running,
        },
    }