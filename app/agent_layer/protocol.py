"""
Agent Protocol Interface for Generic Agent Integration Layer.

This module defines the contract that ANY agent framework must implement
to integrate with the workflow orchestration system.

Each framework creates an adapter that implements the AgentProtocol interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from enum import Enum


class AgentCapability(str, Enum):
    """Capabilities that an agent can provide"""

    CREATE_WORKFLOW = "create_workflow"
    GET_WORKFLOW_STATUS = "get_workflow_status"
    APPROVE_WORKFLOW = "approve_workflow"
    REJECT_WORKFLOW = "reject_workflow"
    RETRY_WORKFLOW = "retry_workflow"
    CANCEL_WORKFLOW = "cancel_workflow"


class AgentRequest(BaseModel):
    """
    Standardized request format for agent execution.

    This format is framework-agnostic.
    """

    user_id: str = Field(..., description="User making the request")
    message: str = Field(..., description="Natural language message from user")
    conversation_id: Optional[str] = Field(None, description="Conversation thread ID for context")
    channel: str = Field(default="api", description="Channel: streamlit, slack, email, api")
    conversation_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Previous messages in conversation for context (role, content, timestamp)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (workflow_id, approval_id, etc.)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user123",
                "message": "Deploy to production with approval",
                "conversation_id": "conv-abc123",
                "channel": "streamlit",
                "conversation_history": [
                    {"role": "user", "content": "Hello", "timestamp": 1760462305.149938},
                    {"role": "assistant", "content": "Hi! How can I help?", "timestamp": 1760462305.153327}
                ],
                "metadata": {"timezone": "UTC"}
            }
        }


class AgentResponse(BaseModel):
    """
    Standardized response format from agent execution.

    This format is framework-agnostic.
    """

    message: str = Field(..., description="Agent's response message to user")
    workflow_id: Optional[str] = Field(None, description="Created/updated workflow ID")
    approval_id: Optional[str] = Field(None, description="Created/pending approval ID")
    status: str = Field(
        default="active",
        description="Conversation status: active, waiting_approval, completed, error"
    )
    requires_approval: bool = Field(
        default=False,
        description="Whether this action requires approval"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional response data (step_info, error_details, etc.)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message": "I've created a deployment workflow with approval. Please review in Slack.",
                "workflow_id": "wf-123",
                "approval_id": "apr-456",
                "status": "waiting_approval",
                "requires_approval": True,
                "metadata": {"steps": 3, "estimated_duration": "5 minutes"}
            }
        }


class AgentProtocol(ABC):
    """
    Abstract base class defining the contract for agent implementations.

    Any agent framework must implement this interface to integrate
    with the workflow orchestration system.

    This is the "generic" part of the Generic Agent Integration Layer.
    """

    def __init__(self, name: str):
        """
        Initialize agent with a unique name.

        Args:
            name: Unique identifier for this agent (e.g., "openai", "langgraph")
        """
        self.name = name

    @abstractmethod
    async def execute_task(self, request: AgentRequest) -> AgentResponse:
        """
        Execute a task based on user's natural language request.

        This is the main entry point for agent execution. The agent should:
        1. Parse the user's message
        2. Determine what action to take (create workflow, check status, etc.)
        3. Call the appropriate WorkflowEngine/ApprovalService methods
        4. Return a standardized response

        Args:
            request: Standardized agent request with user message and context

        Returns:
            AgentResponse: Standardized response with message and state

        Raises:
            Exception: If agent execution fails

        Example:
            request = AgentRequest(
                user_id="user123",
                message="Deploy to production with approval",
                channel="streamlit"
            )
            response = await agent.execute_task(request)
            # response.message = "Deployment workflow created! Approval sent to Slack."
            # response.workflow_id = "wf-123"
            # response.status = "waiting_approval"
        """
        pass

    @abstractmethod
    async def handle_approval_response(
        self,
        approval_id: str,
        decision: str,
        response_data: Dict[str, Any],
        conversation_id: Optional[str] = None
    ) -> AgentResponse:
        """
        Handle approval response (approve/reject) and continue conversation.

        This method is called when a user responds to an approval request.
        The agent should:
        1. Process the approval decision
        2. Update workflow state via ApprovalService
        3. Generate a conversational response for the user

        Args:
            approval_id: The approval request ID
            decision: "approve" or "reject"
            response_data: Form field values from approval
            conversation_id: Optional conversation context

        Returns:
            AgentResponse: Response acknowledging the approval decision

        Raises:
            Exception: If approval processing fails

        Example:
            response = await agent.handle_approval_response(
                approval_id="apr-456",
                decision="approve",
                response_data={"reviewer": "Alice", "comments": "LGTM"},
                conversation_id="conv-abc"
            )
            # response.message = "✅ Approved! Deploying to production now..."
            # response.status = "active"
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> List[AgentCapability]:
        """
        Return list of capabilities this agent supports.

        This allows the orchestrator to route requests to appropriate agents
        based on their capabilities.

        Returns:
            List of AgentCapability enums

        Example:
            capabilities = agent.get_capabilities()
            # [AgentCapability.CREATE_WORKFLOW, AgentCapability.APPROVE_WORKFLOW]
        """
        pass

    def __repr__(self) -> str:
        """String representation of agent"""
        return f"<{self.__class__.__name__}(name='{self.name}')>"
