"""API v1 route modules."""

from app.api.v1.routes.workflows import router as workflows_router
from app.api.v1.routes.approvals import router as approvals_router
from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.slack import router as slack_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.ui import router as ui_router
from app.api.v1.routes.chat import router as chat_router

__all__ = [
    'workflows_router',
    'approvals_router',
    'admin_router',
    'slack_router',
    'health_router',
    'ui_router',
    'chat_router',
]