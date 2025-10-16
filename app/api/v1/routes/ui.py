"""Web UI endpoints for approvals and home page."""

import structlog
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.v1.dependencies import get_event_bus
from app.models import get_db
from app.core import ApprovalService
from app.config.settings import settings

router = APIRouter(tags=["ui"])
logger = structlog.get_logger()

# Templates for web UI
templates = Jinja2Templates(directory="static")


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Landing page with API documentation links"""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "api_base_url": settings.frontend_api_base_url,
            "chat_agent_url": settings.frontend_chat_agent_url,
        }
    )


@router.get("/approval/{approval_id}", response_class=HTMLResponse)
async def approval_page(
    approval_id: str,
    request: Request,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """Render HTML form for approval"""
    approval_service = ApprovalService(db_session, event_bus)

    try:
        approval = await approval_service.get_approval(approval_id)

        return templates.TemplateResponse(
            "approval_form.html",
            {
                "request": request,
                "approval": approval.to_dict(),
                "ui_schema": approval.ui_schema_dict,
                "callback_token": approval.callback_token,
            },
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Approval not found")