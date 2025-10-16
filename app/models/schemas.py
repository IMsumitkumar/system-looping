"""
Pydantic schemas for API requests and responses.
Includes enums for state management and approval UI schemas.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal, Any, List, Dict
from enum import Enum
from datetime import datetime


# ============================================================================
# Enums
# ============================================================================


class WorkflowState(str, Enum):
    """Workflow state machine states"""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ApprovalStatus(str, Enum):
    """Approval request statuses"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"  # Workflow was cancelled/failed


class EventType(str, Enum):
    """Event types for the event bus"""

    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_STATE_CHANGED = "workflow.state_changed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RECEIVED = "approval.received"
    APPROVAL_TIMEOUT = "approval.timeout"
    APPROVAL_RETRY = "approval.retry"
    APPROVAL_CANCELLED = "approval.cancelled"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_ROLLED_BACK = "workflow.rolled_back"
    STEP_COMPLETED = "step.completed"


# ============================================================================
# State Machine Configuration
# ============================================================================

# Valid state transitions
STATE_TRANSITIONS = {
    WorkflowState.CREATED: [WorkflowState.RUNNING, WorkflowState.FAILED],
    WorkflowState.RUNNING: [
        WorkflowState.WAITING_APPROVAL,
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
        WorkflowState.REJECTED,
        WorkflowState.TIMEOUT,  # Allow timeouts from RUNNING (multi-step workflows)
    ],
    WorkflowState.WAITING_APPROVAL: [
        WorkflowState.APPROVED,
        WorkflowState.REJECTED,
        WorkflowState.TIMEOUT,
        WorkflowState.FAILED,
    ],
    WorkflowState.APPROVED: [WorkflowState.COMPLETED, WorkflowState.FAILED],
    WorkflowState.REJECTED: [WorkflowState.RUNNING],  # Allow rollback to RUNNING for approval retry
    WorkflowState.TIMEOUT: [WorkflowState.RUNNING, WorkflowState.FAILED],  # Can retry or fail permanently
    WorkflowState.COMPLETED: [],  # Terminal state - use rollback_workflow for rollbacks
    WorkflowState.FAILED: [WorkflowState.RUNNING],  # Can retry - system error, not user decision
}


# ============================================================================
# Approval UI Schema
# ============================================================================


class FormField(BaseModel):
    """Dynamic form field definition"""

    name: str = Field(..., description="Field identifier")
    type: Literal[
        "text",           # Single-line text input
        "textarea",       # Multi-line text
        "select",         # Dropdown select
        "multiselect",    # Multiple selection dropdown
        "checkbox",       # Single checkbox
        "radio",          # Radio button group
        "number",         # Number input with validation
        "email",          # Email input with validation
        "url",            # URL input with validation
        "tel",            # Telephone number
        "date",           # Date picker
        "datetime",       # Date and time picker
        "time",           # Time picker
        "file",           # File upload
        "color",          # Color picker
        "range",          # Slider/range
        "password",       # Password input
        "hidden"          # Hidden field
    ] = Field(..., description="Field type")
    label: str = Field(..., description="Field label shown to user")
    required: bool = Field(default=False, description="Whether field is required")
    placeholder: Optional[str] = Field(default=None, description="Placeholder text")
    options: Optional[List[Dict[str, str]]] = Field(default=None, description="Options for select, multiselect, radio, checkbox fields")
    validation: Optional[Dict[str, Any]] = Field(default=None, description="Validation rules (min, max, pattern, accept, etc.)")
    default_value: Optional[Any] = Field(default=None, description="Default field value")
    help_text: Optional[str] = Field(default=None, description="Helper text for the field")
    conditional: Optional[Dict[str, Any]] = Field(default=None, description="Conditional display rules")


class ApprovalButton(BaseModel):
    """Approval action button"""

    action: Literal["approve", "reject"] = Field(..., description="Button action")
    label: str = Field(..., description="Button text")
    style: Literal["primary", "danger"] = Field(default="primary", description="Button style")


class ApprovalUISchema(BaseModel):
    """Schema for generating dynamic approval UIs"""

    title: str = Field(..., description="Approval request title")
    description: str = Field(..., description="Approval request description")
    fields: List[FormField] = Field(default_factory=list, description="Form fields")
    buttons: List[ApprovalButton] = Field(default_factory=list, description="Action buttons")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "🚀 Production Deployment Approval",
                "description": "Review deployment to production environment",
                "fields": [
                    {"name": "reviewer_name", "type": "text", "label": "Your Name", "required": True},
                    {
                        "name": "risk_level",
                        "type": "select",
                        "label": "Risk Assessment",
                        "options": ["Low", "Medium", "High"],
                        "required": True,
                    },
                    {"name": "comments", "type": "textarea", "label": "Additional Comments"},
                ],
                "buttons": [
                    {"action": "approve", "label": "✅ Approve", "style": "primary"},
                    {"action": "reject", "label": "❌ Reject", "style": "danger"},
                ],
            }
        }


# ============================================================================
# Workflow Schemas
# ============================================================================


class WorkflowStepConfig(BaseModel):
    """Configuration for a workflow step"""
    type: Literal["task", "approval"] = Field(..., description="Step type")
    handler: Optional[str] = Field(None, description="Task handler name (for task steps)")
    input: Optional[Dict[str, Any]] = Field(None, description="Step input data")


class WorkflowCreate(BaseModel):
    """Request to create a new workflow"""

    workflow_type: str = Field(..., description="Type of workflow", examples=["deployment", "purchase", "contract"])
    context: Dict[str, Any] = Field(..., description="Workflow context data")
    steps: Optional[List[WorkflowStepConfig]] = Field(None, description="Workflow steps (if multi-step)")
    approval_schema: Optional[ApprovalUISchema] = Field(
        default=None, description="Approval UI schema (for single-step)"
    )
    approval_timeout_seconds: int = Field(default=3600, description="Approval timeout in seconds")


class WorkflowResponse(BaseModel):
    """Workflow representation"""

    id: str
    workflow_type: str
    state: WorkflowState
    context: Dict[str, Any]
    created_at: float
    updated_at: float
    expires_at: Optional[float] = None
    version: int
    retry_count: int = 0
    max_retries: int = 3
    last_retry_at: Optional[float] = None
    is_multi_step: bool = False


class WorkflowEventResponse(BaseModel):
    """Workflow event representation"""

    id: int
    workflow_id: str
    event_type: EventType
    event_data: Dict[str, Any]
    occurred_at: float
    sequence_number: int = 0


class WorkflowStepResponse(BaseModel):
    """Workflow step representation"""
    id: str
    workflow_id: str
    step_order: int
    step_type: str
    status: str
    task_handler: Optional[str] = None
    task_input: Optional[Dict[str, Any]] = None
    task_output: Optional[Dict[str, Any]] = None
    approval_id: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


# ============================================================================
# Approval Schemas
# ============================================================================


class ApprovalRequestResponse(BaseModel):
    """Approval request representation"""

    id: str
    workflow_id: str
    status: ApprovalStatus
    ui_schema: ApprovalUISchema
    response_data: Optional[Dict[str, Any]] = None
    requested_at: float
    responded_at: Optional[float] = None
    expires_at: float
    is_expired: bool = False
    callback_token: str


class ApprovalResponseSubmit(BaseModel):
    """Approval response submission"""

    decision: Literal["approve", "reject"] = Field(..., description="Approval decision")
    response_data: Dict[str, Any] = Field(default_factory=dict, description="Form field values")


# ============================================================================
# List/Filter Schemas
# ============================================================================


class WorkflowListResponse(BaseModel):
    """List of workflows with pagination"""

    workflows: List[WorkflowResponse]
    total: int


class WorkflowEventsResponse(BaseModel):
    """Workflow event history"""

    workflow_id: str
    events: List[WorkflowEventResponse]


# ============================================================================
# Slack Schemas
# ============================================================================


class SlackInteractionPayload(BaseModel):
    """Slack interactive component payload (simplified)"""

    type: str
    user: Dict
    actions: List[Dict]
    response_url: str
    state: Optional[Dict] = None


# ============================================================================
# Error Schemas
# ============================================================================


class ErrorResponse(BaseModel):
    """Standard error response"""

    error: str
    detail: Optional[str] = None


# ============================================================================
# Health Check
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response"""

    status: Literal["healthy", "unhealthy"]
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())
    version: str = "1.0.0"


# ============================================================================
# Conversation History Schemas (Agent Integration Layer)
# ============================================================================


class ConversationMessage(BaseModel):
    """Single message in a conversation"""

    role: Literal["user", "assistant", "system"] = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    timestamp: float = Field(..., description="Message timestamp")


class ConversationHistoryCreate(BaseModel):
    """Request to create a new conversation"""

    user_id: str = Field(..., description="User ID")
    channel: Literal["streamlit", "slack", "email", "api"] = Field(..., description="Communication channel")
    initial_message: Optional[str] = Field(None, description="Initial user message")


class ConversationHistoryResponse(BaseModel):
    """Conversation history representation"""

    id: str
    conversation_id: str
    user_id: str
    channel: str
    messages: List[ConversationMessage]
    state: Literal["active", "waiting_approval", "completed", "error"]
    current_agent: Optional[str] = None
    workflow_id: Optional[str] = None
    approval_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: float
    updated_at: float
    last_message_at: float


class ChatMessageRequest(BaseModel):
    """Request to send a chat message to the agent"""

    user_id: str = Field(..., description="User ID")
    message: str = Field(..., description="User message")
    conversation_id: Optional[str] = Field(None, description="Existing conversation ID (if continuing)")
    channel: Literal["streamlit", "slack", "email", "api"] = Field(default="api", description="Communication channel")


class ChatMessageResponse(BaseModel):
    """Response from the agent with conversation state"""

    message: str = Field(..., description="Agent's response message")
    conversation_id: str = Field(..., description="Conversation ID for context")
    workflow_id: Optional[str] = Field(None, description="Associated workflow ID")
    approval_id: Optional[str] = Field(None, description="Associated approval ID")
    status: Literal["active", "waiting_approval", "completed", "error"] = Field(
        ...,
        description="Conversation status"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional response metadata")
