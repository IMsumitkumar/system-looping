"""Workflow management API endpoints."""

from typing import List
from datetime import datetime, timedelta
import json
import structlog
from fastapi import APIRouter, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import get_event_bus
from app.models import get_db
from app.core import WorkflowEngine, ApprovalService, InvalidStateTransitionError
from app.models import IdempotencyKey
from app.models.schemas import (
    WorkflowCreate,
    WorkflowResponse,
    WorkflowEventsResponse,
    WorkflowEventResponse,
    WorkflowState,
    ApprovalUISchema,
    WorkflowStepResponse,
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
logger = structlog.get_logger()


@router.post("", response_model=WorkflowResponse)
async def create_workflow(
    workflow_req: WorkflowCreate,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Create a new workflow with optional approval requirement.

    If approval_schema is provided, the workflow will automatically
    request approval after creation.

    Supports idempotency via Idempotency-Key header to prevent duplicate workflows.
    """
    # Check for idempotency key
    if idempotency_key:
        # Check if key already exists
        result = await db_session.execute(
            select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
        )
        existing = result.scalar_one_or_none()

        if existing and not existing.is_expired():
            logger.info(
                "idempotency_key_found",
                idempotency_key=idempotency_key,
                workflow_id=existing.workflow_id
            )
            return JSONResponse(
                status_code=existing.response_code,
                content=existing.response_body if isinstance(existing.response_body, dict) else json.loads(existing.response_body)
            )

    engine = WorkflowEngine(db_session, event_bus)
    approval_service = ApprovalService(db_session, event_bus)

    # Prepare context with approval schema embedded (if provided)
    context = workflow_req.context.copy()
    if workflow_req.approval_schema:
        context["_approval_schema"] = workflow_req.approval_schema.model_dump()
        context["_approval_timeout"] = workflow_req.approval_timeout_seconds

    # Create workflow (commits internally, then publishes workflow.started event)
    workflow = await engine.create_workflow(
        workflow_req.workflow_type,
        context,
        steps=[step.model_dump() for step in workflow_req.steps] if workflow_req.steps else None,
        approval_timeout_seconds=workflow_req.approval_timeout_seconds,
    )

    logger.info("workflow_created_via_api", workflow_id=workflow.id)

    # Store idempotency key if provided
    if idempotency_key:
        response_body = workflow.to_dict()
        idem_record = IdempotencyKey(
            key=idempotency_key,
            workflow_id=workflow.id,
            response_code=200,
            response_body=json.dumps(response_body),
            created_at=datetime.now().timestamp(),
            expires_at=(datetime.now() + timedelta(hours=24)).timestamp()
        )
        db_session.add(idem_record)
        await db_session.commit()

        logger.info(
            "idempotency_key_stored",
            idempotency_key=idempotency_key,
            workflow_id=workflow.id,
            expires_at=idem_record.expires_at
        )

    return WorkflowResponse(**workflow.to_dict())


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """Get workflow by ID"""
    engine = WorkflowEngine(db_session, event_bus)

    try:
        workflow = await engine.get_workflow(workflow_id)
        return WorkflowResponse(**workflow.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{workflow_id}/events", response_model=WorkflowEventsResponse)
async def get_workflow_events(
    workflow_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """Get all events for a workflow (audit trail)"""
    engine = WorkflowEngine(db_session, event_bus)

    try:
        events = await engine.get_workflow_events(workflow_id)
        return WorkflowEventsResponse(
            workflow_id=workflow_id,
            events=[WorkflowEventResponse(**event.to_dict()) for event in events],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    state: WorkflowState = None,
    limit: int = 100,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """List workflows, optionally filtered by state"""
    engine = WorkflowEngine(db_session, event_bus)
    workflows = await engine.list_workflows(state, limit)
    return [WorkflowResponse(**wf.to_dict()) for wf in workflows]


@router.post("/{workflow_id}/cancel", response_model=WorkflowResponse)
async def cancel_workflow(
    workflow_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Cancel a running workflow.
    Transitions workflow to FAILED state with cancellation reason.
    """
    engine = WorkflowEngine(db_session, event_bus)

    try:
        workflow = await engine.mark_failed(workflow_id, "Cancelled by user")
        logger.info("workflow_cancelled", workflow_id=workflow_id)
        return WorkflowResponse(**workflow.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{workflow_id}/retry", response_model=WorkflowResponse)
async def retry_workflow(
    workflow_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Retry a failed or timed-out workflow.

    Only workflows in FAILED or TIMEOUT state can be retried.
    REJECTED workflows cannot be retried (user decision).
    Implements exponential backoff and respects max retry limits.
    """
    engine = WorkflowEngine(db_session, event_bus)

    try:
        workflow = await engine.retry_workflow(workflow_id)

        if not workflow:
            # Get current state for better error message
            current_workflow = await engine.get_workflow(workflow_id)
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry workflow in {current_workflow.state} state. "
                       f"Only FAILED or TIMEOUT workflows can be retried. "
                       f"REJECTED workflows represent user decisions and cannot be retried."
            )

        logger.info("workflow_retried_via_api", workflow_id=workflow_id, retry_count=workflow.retry_count)
        return WorkflowResponse(**workflow.to_dict())

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{workflow_id}/rollback")
async def rollback_workflow(
    workflow_id: str,
    target_state: WorkflowState,
    reason: str = "Manual rollback",
    rollback_by: str = "user",
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Rollback a workflow to a previous state.

    This allows recovering from incorrect approvals or stuck workflows.
    """
    logger.info("api_rollback_workflow", workflow_id=workflow_id, target_state=target_state.value)

    try:
        engine = WorkflowEngine(db_session, event_bus)
        workflow = await engine.rollback_workflow(
            workflow_id=workflow_id,
            target_state=target_state,
            reason=reason,
            rollback_by=rollback_by
        )

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return {
            "success": True,
            "workflow_id": workflow.id,
            "previous_state": workflow.previous_state,
            "current_state": workflow.state,
            "rollback_count": workflow.rollback_count,
            "max_rollbacks": workflow.max_rollbacks,
            "reason": reason
        }

    except InvalidStateTransitionError as e:
        logger.error("rollback_invalid_transition", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.error("rollback_limit_exceeded", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("rollback_error", workflow_id=workflow_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}")


@router.get("/{workflow_id}/can-rollback/{target_state}")
async def check_can_rollback(
    workflow_id: str,
    target_state: WorkflowState,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Check if a workflow can be rolled back to a specific state.
    """
    engine = WorkflowEngine(db_session, event_bus)
    can_rollback = await engine.can_rollback(workflow_id, target_state)

    return {
        "can_rollback": can_rollback,
        "workflow_id": workflow_id,
        "target_state": target_state.value
    }


@router.get("/{workflow_id}/rollback-history")
async def get_rollback_history(
    workflow_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Get the rollback history for a workflow.
    """
    engine = WorkflowEngine(db_session, event_bus)
    history = await engine.get_rollback_history(workflow_id)

    return {
        "workflow_id": workflow_id,
        "rollback_count": len(history),
        "history": history
    }


@router.get("/{workflow_id}/steps", response_model=List[WorkflowStepResponse])
async def get_workflow_steps(
    workflow_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """Get all steps for a workflow"""
    engine = WorkflowEngine(db_session, event_bus)
    steps = await engine.get_workflow_steps(workflow_id)
    return [WorkflowStepResponse(**step.to_dict()) for step in steps]