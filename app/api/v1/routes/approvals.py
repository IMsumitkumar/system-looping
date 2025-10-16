"""Approval management API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException, Depends

from app.api.v1.dependencies import get_event_bus
from app.models import get_db
from app.core import ApprovalService
from app.config import verify_callback_token
from app.models.schemas import (
    ApprovalRequestResponse,
    ApprovalResponseSubmit,
    ApprovalUISchema,
)

router = APIRouter(tags=["approvals"])
logger = structlog.get_logger()


@router.post("/api/workflows/{workflow_id}/request-approval", response_model=ApprovalRequestResponse)
async def request_approval_for_workflow(
    workflow_id: str,
    approval_schema: ApprovalUISchema,
    timeout_seconds: int = 3600,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """Manually request approval for a workflow"""
    approval_service = ApprovalService(db_session, event_bus)

    approval = await approval_service.request_approval(workflow_id, approval_schema, timeout_seconds)

    # Get approval dict and remove ui_schema to avoid duplicate argument
    approval_dict = approval.to_dict()
    approval_dict.pop('ui_schema', None)

    return ApprovalRequestResponse(
        **approval_dict,
        is_expired=approval.is_expired(),
        ui_schema=approval_schema,
    )


@router.get("/api/approvals/{approval_id}", response_model=ApprovalRequestResponse)
async def get_approval(
    approval_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """Get approval request details"""
    approval_service = ApprovalService(db_session, event_bus)

    try:
        approval = await approval_service.get_approval(approval_id)

        # Get approval dict and remove ui_schema to avoid duplicate argument
        approval_dict = approval.to_dict()
        approval_dict.pop('ui_schema', None)

        return ApprovalRequestResponse(
            **approval_dict,
            is_expired=approval.is_expired(),
            ui_schema=ApprovalUISchema(**approval.ui_schema_dict),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/approvals")
async def get_pending_approvals(
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """Get all pending approval requests"""
    approval_service = ApprovalService(db_session, event_bus)

    approvals = await approval_service.get_pending_approvals()

    # Convert to response format
    approval_list = []
    for approval in approvals:
        approval_dict = approval.to_dict()
        approval_dict.pop('ui_schema', None)

        approval_list.append(ApprovalRequestResponse(
            **approval_dict,
            is_expired=approval.is_expired(),
            ui_schema=ApprovalUISchema(**approval.ui_schema_dict),
        ))

    return approval_list


@router.post("/api/callbacks/{callback_token}")
async def approval_callback(
    callback_token: str,
    response: ApprovalResponseSubmit,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Callback endpoint for approval responses.
    Token-based authentication for security.
    """
    # Verify token and extract approval ID
    approval_id = verify_callback_token(callback_token)
    if not approval_id:
        raise HTTPException(status_code=403, detail="Invalid callback token")

    approval_service = ApprovalService(db_session, event_bus)

    try:
        approval = await approval_service.respond_to_approval(
            approval_id,
            response.decision,
            response.response_data,
        )

        return {"success": True, "approval_id": approval_id, "status": approval.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/approvals/{approval_id}/rollback")
async def rollback_approval(
    approval_id: str,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Rollback a rejected approval to pending state.
    Allows users to correct mistaken rejections.
    """
    approval_service = ApprovalService(db_session, event_bus)

    try:
        approval = await approval_service.rollback_approval(approval_id)
        return {"success": True, "approval_id": approval_id, "status": approval.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))