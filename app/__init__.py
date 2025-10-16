"""Human-in-the-loop workflow orchestration application."""

# Core components
from app.core import (
    WorkflowEngine,
    ApprovalService,
    EventBus,
    TimeoutManager
)

# Agent Layer components
from app.agent_layer import (
    AgentProtocol,
    AgentRequest,
    AgentResponse,
    AgentOrchestrator,
    ConversationEventHandler
)

# Models and schemas
from app.models import (
    Database,
    get_db,
    Workflow,
    WorkflowEvent,
    ApprovalRequest
)

# Adapters
from app.adapters import (
    SlackAdapter,
)

# Configuration and security
from app.config import (
    settings,
    verify_callback_token,
    verify_slack_signature
)

__version__ = "1.0.0"

__all__ = [
    # Core
    'WorkflowEngine',
    'ApprovalService',
    'EventBus',
    'TimeoutManager',
    # Agent Layer
    'AgentProtocol',
    'AgentRequest',
    'AgentResponse',
    'AgentOrchestrator',
    'ConversationEventHandler',
    # Models
    'Database',
    'get_db',
    'Workflow',
    'WorkflowEvent',
    'ApprovalRequest',
    # Adapters
    'SlackAdapter',
    # Config
    'settings',
    'verify_callback_token',
    'verify_slack_signature'
]