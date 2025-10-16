"""
Database models using SQLAlchemy 2.0 async style.
"""

from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from typing import List, Dict
import uuid
import json

from app.models.database import Base


class Workflow(Base):
    """
    Main workflow entity tracking current state.
    """

    __tablename__ = "workflows"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_type = Column(String(100), nullable=False)
    state = Column(String(50), nullable=False)  # WorkflowState enum value
    context = Column(Text, nullable=False)  # JSON string
    created_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    updated_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    expires_at = Column(Float, nullable=True)
    version = Column(Integer, default=1)

    # Retry management fields
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    last_retry_at = Column(Float, nullable=True)

    # Rollback support fields
    rollback_count = Column(Integer, default=0, nullable=False)
    max_rollbacks = Column(Integer, default=3, nullable=False)
    last_rollback_at = Column(Float, nullable=True)
    previous_state = Column(String(50), nullable=True)  # Track state before rollback
    rollback_reason = Column(Text, nullable=True)

    # Relationships
    events = relationship("WorkflowEvent", back_populates="workflow", cascade="all, delete-orphan")
    approvals = relationship("ApprovalRequest", back_populates="workflow", cascade="all, delete-orphan")
    steps = relationship("WorkflowStep", back_populates="workflow", cascade="all, delete-orphan")

    # Indexes - optimized for common queries
    __table_args__ = (
        Index("idx_workflows_state", "state"),
        # Index for list_workflows ORDER BY created_at DESC
        Index("idx_workflows_created_desc", "created_at"),
        # Composite index for state + created_at filtering
        Index("idx_workflows_state_created", "state", "created_at"),
    )

    def to_dict(self, include_steps=False):
        """Convert to dictionary"""
        result = {
            "id": self.id,
            "workflow_type": self.workflow_type,
            "state": self.state,
            "context": json.loads(self.context) if isinstance(self.context, str) else self.context,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "version": self.version,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "last_retry_at": self.last_retry_at,
            "rollback_count": self.rollback_count,
            "max_rollbacks": self.max_rollbacks,
            "last_rollback_at": self.last_rollback_at,
            "previous_state": self.previous_state,
            "rollback_reason": self.rollback_reason,
        }

        # Check if steps are available (simpler approach - just try to access them)
        try:
            # Try to access steps - if they're loaded, this won't cause lazy loading issues
            # If they're not loaded in async context, this will be empty list (not None)
            steps_list = list(self.steps)  # Force evaluation
            result["is_multi_step"] = len(steps_list) > 0
            if include_steps:
                result["steps"] = [step.to_dict() for step in steps_list]
        except Exception as e:
            # If any error occurs (e.g., lazy loading in async), default to False
            result["is_multi_step"] = False

        return result

    @property
    def context_dict(self):
        """Get context as dictionary"""
        if isinstance(self.context, str):
            return json.loads(self.context)
        return self.context

    def update_context(self, context_dict: dict):
        """Update context from dictionary"""
        self.context = json.dumps(context_dict)
        self.updated_at = datetime.now().timestamp()
        self.version += 1


class WorkflowStep(Base):
    """
    Individual steps in a workflow - can be tasks or approvals.
    """
    __tablename__ = "workflow_steps"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = Column(String, ForeignKey("workflows.id"), nullable=False)
    step_order = Column(Integer, nullable=False)
    step_type = Column(String(50), nullable=False)  # "task" or "approval"
    status = Column(String(50), default="pending")  # pending, running, completed, failed

    # For task steps
    task_handler = Column(String(100), nullable=True)
    task_input = Column(Text, nullable=True)  # JSON
    task_output = Column(Text, nullable=True)  # JSON

    # For approval steps
    approval_id = Column(String, ForeignKey("approval_requests.id"), nullable=True)

    # Timestamps
    started_at = Column(Float, nullable=True)
    completed_at = Column(Float, nullable=True)

    # Relationships
    workflow = relationship("Workflow", back_populates="steps")
    approval = relationship("ApprovalRequest")

    # Indexes
    __table_args__ = (
        Index("idx_steps_workflow_order", "workflow_id", "step_order"),
        Index("idx_steps_status", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "step_order": self.step_order,
            "step_type": self.step_type,
            "status": self.status,
            "task_handler": self.task_handler,
            "task_input": json.loads(self.task_input) if self.task_input else None,
            "task_output": json.loads(self.task_output) if self.task_output else None,
            "approval_id": self.approval_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class WorkflowEvent(Base):
    """
    Append-only event log for workflow state transitions.
    Provides complete audit trail.
    """

    __tablename__ = "workflow_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(String, ForeignKey("workflows.id"), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(Text, nullable=False)  # JSON string
    occurred_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    sequence_number = Column(Integer, nullable=False, default=0)  # Event ordering per workflow

    # Relationship
    workflow = relationship("Workflow", back_populates="events")

    # Indexes - CRITICAL for performance
    __table_args__ = (
        # Composite index for get_workflow_events queries
        Index("idx_events_workflow_occurred", "workflow_id", "occurred_at"),
        # Index for event type filtering
        Index("idx_events_type", "event_type"),
        # Index for event ordering per workflow
        Index("idx_events_workflow_sequence", "workflow_id", "sequence_number"),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "event_type": self.event_type,
            "event_data": json.loads(self.event_data) if isinstance(self.event_data, str) else self.event_data,
            "occurred_at": self.occurred_at,
            "sequence_number": self.sequence_number,
        }

    @property
    def event_data_dict(self):
        """Get event data as dictionary"""
        if isinstance(self.event_data, str):
            return json.loads(self.event_data)
        return self.event_data


class ApprovalRequest(Base):
    """
    Approval requests with dynamic UI schema.
    Tracks approval lifecycle and responses.
    """

    __tablename__ = "approval_requests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = Column(String, ForeignKey("workflows.id"), nullable=False)
    status = Column(String(50), nullable=False)  # PENDING, APPROVED, REJECTED, TIMEOUT
    ui_schema = Column(Text, nullable=False)  # JSON string
    response_data = Column(Text, nullable=True)  # JSON string
    requested_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    responded_at = Column(Float, nullable=True)
    expires_at = Column(Float, nullable=False)
    callback_token = Column(String(255), unique=True, nullable=False)
    slack_message_ts = Column(String(255), nullable=True)  # For updating Slack messages

    # Relationship
    workflow = relationship("Workflow", back_populates="approvals")

    # Indexes
    __table_args__ = (
        Index("idx_approvals_pending", "status", "expires_at"),
        Index("idx_approvals_token", "callback_token"),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "ui_schema": json.loads(self.ui_schema) if isinstance(self.ui_schema, str) else self.ui_schema,
            "response_data": (
                json.loads(self.response_data)
                if self.response_data and isinstance(self.response_data, str)
                else self.response_data
            ),
            "requested_at": self.requested_at,
            "responded_at": self.responded_at,
            "expires_at": self.expires_at,
            "callback_token": self.callback_token,
            "slack_message_ts": self.slack_message_ts,
        }

    @property
    def ui_schema_dict(self):
        """Get UI schema as dictionary"""
        if isinstance(self.ui_schema, str):
            return json.loads(self.ui_schema)
        return self.ui_schema

    @property
    def response_data_dict(self):
        """Get response data as dictionary"""
        if self.response_data and isinstance(self.response_data, str):
            return json.loads(self.response_data)
        return self.response_data

    def is_expired(self) -> bool:
        """Check if approval has expired"""
        return datetime.now().timestamp() > self.expires_at

    def is_pending(self) -> bool:
        """Check if approval is still pending"""
        return self.status == "PENDING" and not self.is_expired()


class IdempotencyKey(Base):
    """
    Idempotency key tracking to prevent duplicate workflow creation.
    """

    __tablename__ = "idempotency_keys"

    key = Column(String(255), primary_key=True)
    workflow_id = Column(String, ForeignKey("workflows.id"), nullable=True)
    response_code = Column(Integer, nullable=False)
    response_body = Column(Text, nullable=False)  # JSON string
    created_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    expires_at = Column(Float, nullable=False)

    # Indexes
    __table_args__ = (
        Index("idx_idempotency_expires", "expires_at"),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "key": self.key,
            "workflow_id": self.workflow_id,
            "response_code": self.response_code,
            "response_body": json.loads(self.response_body) if isinstance(self.response_body, str) else self.response_body,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    def is_expired(self) -> bool:
        """Check if idempotency key has expired"""
        return datetime.now().timestamp() > self.expires_at


class DeadLetterQueue(Base):
    """
    Dead letter queue for failed events that exceeded max retries.
    """

    __tablename__ = "dead_letter_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_event_type = Column(String(100), nullable=False)
    event_data = Column(Text, nullable=False)  # JSON string
    error_message = Column(Text, nullable=False)
    retry_count = Column(Integer, nullable=False)
    created_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    workflow_id = Column(String, nullable=True)  # Optional workflow reference

    # Indexes
    __table_args__ = (
        Index("idx_dlq_created", "created_at"),
        Index("idx_dlq_event_type", "original_event_type"),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "original_event_type": self.original_event_type,
            "event_data": json.loads(self.event_data) if isinstance(self.event_data, str) else self.event_data,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "workflow_id": self.workflow_id,
        }


class ConversationHistory(Base):
    """
    Conversation history for agent interactions.
    Stores full message log and links to workflows/approvals.

    This enables:
    - Multi-turn conversations with context
    - State persistence across restarts
    - Long-running approval flows (hours/days)
    - Full audit trail of agent interactions
    """

    __tablename__ = "conversation_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(255), nullable=False, unique=True, index=True)
    user_id = Column(String(255), nullable=False)
    channel = Column(String(50), nullable=False)  # streamlit, slack, email, api
    messages = Column(Text, nullable=False, default="[]")  # JSON array of messages
    state = Column(String(50), nullable=False, default="active")  # active, waiting_approval, completed, error
    current_agent = Column(String(100), nullable=True)  # Which agent is handling this conversation
    workflow_id = Column(String, ForeignKey("workflows.id"), nullable=True)  # Linked workflow
    approval_id = Column(String, ForeignKey("approval_requests.id"), nullable=True)  # Linked approval
    context_metadata = Column("metadata", Text, nullable=True)  # JSON for agent-specific data (column name is "metadata")
    created_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    updated_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())
    last_message_at = Column(Float, nullable=False, default=lambda: datetime.now().timestamp())

    # Relationships
    workflow = relationship("Workflow")
    approval = relationship("ApprovalRequest")

    # Indexes - optimized for common queries
    __table_args__ = (
        Index("idx_conversations_user_updated", "user_id", "updated_at"),
        Index("idx_conversations_state", "state"),
        Index("idx_conversations_channel", "channel"),
        Index("idx_conversations_workflow", "workflow_id"),
        Index("idx_conversations_approval", "approval_id"),
    )

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "messages": json.loads(self.messages) if isinstance(self.messages, str) else self.messages,
            "state": self.state,
            "current_agent": self.current_agent,
            "workflow_id": self.workflow_id,
            "approval_id": self.approval_id,
            "metadata": json.loads(self.context_metadata) if self.context_metadata and isinstance(self.context_metadata, str) else self.context_metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_message_at": self.last_message_at,
        }

    @property
    def messages_list(self) -> List[Dict]:
        """
        Get messages as list.

        Handles both old (ISO string) and new (float) timestamp formats
        for backward compatibility during migration.
        """
        if isinstance(self.messages, str):
            messages = json.loads(self.messages)
        else:
            messages = self.messages

        # Normalize timestamps to float format
        for msg in messages:
            if isinstance(msg.get("timestamp"), str):
                # Convert ISO string to float
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(msg["timestamp"])
                    msg["timestamp"] = dt.timestamp()
                except (ValueError, AttributeError):
                    # If conversion fails, use current time
                    msg["timestamp"] = datetime.now().timestamp()

        return messages

    @property
    def metadata_dict(self) -> Dict:
        """Get metadata as dictionary"""
        if self.context_metadata and isinstance(self.context_metadata, str):
            return json.loads(self.context_metadata)
        return self.context_metadata or {}

    def add_message(self, role: str, content: str):
        """Add a message to the conversation"""
        messages = self.messages_list
        messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().timestamp()  # Store as float (Unix timestamp)
        })
        self.messages = json.dumps(messages)
        self.last_message_at = datetime.now().timestamp()
        self.updated_at = datetime.now().timestamp()

    def update_state(self, new_state: str):
        """Update conversation state"""
        self.state = new_state
        self.updated_at = datetime.now().timestamp()

    def link_workflow(self, workflow_id: str):
        """Link conversation to a workflow"""
        self.workflow_id = workflow_id
        self.updated_at = datetime.now().timestamp()

    def link_approval(self, approval_id: str):
        """Link conversation to an approval"""
        self.approval_id = approval_id
        self.state = "waiting_approval"
        self.updated_at = datetime.now().timestamp()
