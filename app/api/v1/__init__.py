"""API v1 module - consolidated router for all endpoints."""

from fastapi import APIRouter
from app.api.v1.routes import (
    workflows_router,
    approvals_router,
    admin_router,
    slack_router,
    health_router,
    ui_router,
    chat_router,
)

# Create main v1 router
router = APIRouter()

# Include all route modules
router.include_router(health_router)
router.include_router(workflows_router)
router.include_router(approvals_router)
router.include_router(admin_router)
router.include_router(slack_router)
router.include_router(ui_router)
router.include_router(chat_router)  # Agent integration layer

__all__ = ['router']