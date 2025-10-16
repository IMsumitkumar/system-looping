"""
Agent Orchestrator for Generic Agent Integration Layer.

This is the "brain" that routes requests to appropriate agents and manages
conversation flow. It's the central component of the generic layer.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, Dict, List, Callable, Pattern
import re
import uuid
import structlog
from datetime import datetime

from app.agent_layer.protocol import AgentProtocol, AgentRequest, AgentResponse
from app.models.orm import ConversationHistory
from app.models.schemas import ChatMessageRequest, ChatMessageResponse

logger = structlog.get_logger()


class AgentRegistration:
    """Registration info for an agent"""

    def __init__(self, agent: AgentProtocol, patterns: List[str], priority: int = 0):
        self.agent = agent
        self.patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        self.priority = priority

    def matches(self, message: str) -> bool:
        """Check if message matches any of this agent's patterns"""
        return any(pattern.search(message) for pattern in self.patterns)


class AgentOrchestrator:
    """
    Orchestrates agent interactions and manages conversation state.

    This is the core of the Generic Agent Integration Layer.
    It routes requests to appropriate agents and persists conversation state.
    """

    def __init__(self, db: AsyncSession, event_bus=None):
        """
        Initialize orchestrator with database session.

        Args:
            db: Async database session
            event_bus: Optional event bus for publishing events
        """
        self.db = db
        self.event_bus = event_bus
        self._agents: List[AgentRegistration] = []
        self._default_agent: Optional[AgentProtocol] = None

        logger.info("agent_orchestrator_initialized")

    def register_agent(
        self,
        agent: AgentProtocol,
        patterns: Optional[List[str]] = None,
        set_as_default: bool = False
    ):
        """
        Register an agent with routing patterns.

        Args:
            agent: Agent implementation (OpenAI, LangGraph, etc.)
            patterns: Regex patterns to match for routing (e.g., ["deploy", "workflow"])
            set_as_default: If True, use this agent when no pattern matches

        Example:
            orchestrator.register_agent(
                openai_agent,
                patterns=["deploy", "workflow", "create.*approval"],
                set_as_default=True
            )
        """
        if patterns:
            registration = AgentRegistration(agent, patterns)
            self._agents.append(registration)
            logger.info(
                "agent_registered",
                agent_name=agent.name,
                patterns=patterns,
                total_agents=len(self._agents)
            )

        if set_as_default:
            self._default_agent = agent
            logger.info("default_agent_set", agent_name=agent.name)

    async def process_message(
        self,
        user_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        channel: str = "api"
    ) -> ChatMessageResponse:
        """
        Process a user message through the agent layer.

        This is the main entry point for all user interactions.

        Args:
            user_id: User identifier
            message: User's natural language message
            conversation_id: Optional existing conversation ID
            channel: Communication channel (streamlit, slack, email, api)

        Returns:
            ChatMessageResponse with agent's reply and conversation state

        Raises:
            Exception: If message processing fails
        """
        try:
            # Get or create conversation
            conversation = await self._get_or_create_conversation(
                user_id, conversation_id, channel
            )

            # Add user message to conversation
            conversation.add_message("user", message)
            await self.db.commit()

            logger.info(
                "processing_user_message",
                user_id=user_id,
                conversation_id=conversation.conversation_id,
                channel=channel,
                message_length=len(message)
            )

            # Route to appropriate agent
            agent = await self._route_to_agent(message, conversation)

            # Build agent request with conversation context
            agent_request = AgentRequest(
                user_id=user_id,
                message=message,
                conversation_id=conversation.conversation_id,
                channel=channel,
                conversation_history=conversation.messages_list,
                metadata={
                    "workflow_id": conversation.workflow_id,
                    "approval_id": conversation.approval_id,
                }
            )

            # Execute agent
            agent_response = await agent.execute_task(agent_request)

            # Update conversation with agent response
            await self._update_conversation_with_response(
                conversation, agent_response, agent.name
            )

            # Build response
            response = ChatMessageResponse(
                message=agent_response.message,
                conversation_id=conversation.conversation_id,
                workflow_id=agent_response.workflow_id or conversation.workflow_id,
                approval_id=agent_response.approval_id or conversation.approval_id,
                status=agent_response.status,
                metadata=agent_response.metadata
            )

            logger.info(
                "message_processed_successfully",
                conversation_id=conversation.conversation_id,
                agent=agent.name,
                status=agent_response.status
            )

            return response

        except Exception as e:
            logger.error(
                "message_processing_failed",
                user_id=user_id,
                conversation_id=conversation_id,
                error=str(e),
                exc_info=True
            )

            # Create error response
            error_message = "I encountered an error processing your request. Please try again."

            # If conversation exists, mark as error
            if conversation:
                conversation.add_message("assistant", error_message)
                conversation.update_state("error")
                await self.db.commit()

            return ChatMessageResponse(
                message=error_message,
                conversation_id=conversation.conversation_id if conversation else str(uuid.uuid4()),
                status="error",
                metadata={"error": str(e)}
            )

    async def handle_approval_response(
        self,
        approval_id: str,
        decision: str,
        response_data: Dict,
        conversation_id: Optional[str] = None
    ) -> ChatMessageResponse:
        """
        Handle approval response and update conversation.

        Args:
            approval_id: The approval request ID
            decision: "approve" or "reject"
            response_data: Form field values
            conversation_id: Optional conversation context

        Returns:
            ChatMessageResponse acknowledging the approval
        """
        try:
            # Find conversation linked to this approval
            if conversation_id:
                conversation = await self._get_conversation(conversation_id)
            else:
                conversation = await self._get_conversation_by_approval(approval_id)

            if not conversation:
                logger.warning(
                    "approval_response_no_conversation",
                    approval_id=approval_id,
                    decision=decision
                )
                return ChatMessageResponse(
                    message=f"{'✅ Approved' if decision == 'approve' else '❌ Rejected'}",
                    conversation_id=conversation_id or str(uuid.uuid4()),
                    status="completed",
                    metadata={}
                )

            # Get the agent that was handling this conversation
            agent = await self._get_agent_by_name(conversation.current_agent)
            if not agent:
                agent = self._default_agent

            # Let agent handle approval response
            agent_response = await agent.handle_approval_response(
                approval_id, decision, response_data, conversation.conversation_id
            )

            # Update conversation
            conversation.add_message("assistant", agent_response.message)
            conversation.update_state(agent_response.status)
            if decision == "approve":
                conversation.approval_id = None  # Clear approval link
            await self.db.commit()

            logger.info(
                "approval_response_processed",
                approval_id=approval_id,
                decision=decision,
                conversation_id=conversation.conversation_id
            )

            return ChatMessageResponse(
                message=agent_response.message,
                conversation_id=conversation.conversation_id,
                workflow_id=conversation.workflow_id,
                approval_id=None if decision == "approve" else approval_id,
                status=agent_response.status,
                metadata=agent_response.metadata
            )

        except Exception as e:
            logger.error(
                "approval_response_failed",
                approval_id=approval_id,
                error=str(e),
                exc_info=True
            )
            raise

    async def get_conversation(self, conversation_id: str) -> Optional[ConversationHistory]:
        """Get conversation by ID"""
        return await self._get_conversation(conversation_id)

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    async def _get_or_create_conversation(
        self,
        user_id: str,
        conversation_id: Optional[str],
        channel: str
    ) -> ConversationHistory:
        """Get existing conversation or create new one"""
        if conversation_id:
            conversation = await self._get_conversation(conversation_id)
            if conversation:
                return conversation

        # Create new conversation
        new_conv_id = conversation_id or f"conv-{uuid.uuid4()}"
        conversation = ConversationHistory(
            conversation_id=new_conv_id,
            user_id=user_id,
            channel=channel,
            state="active"
        )

        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)

        logger.info(
            "conversation_created",
            conversation_id=conversation.conversation_id,
            user_id=user_id,
            channel=channel
        )

        return conversation

    async def _get_conversation(self, conversation_id: str) -> Optional[ConversationHistory]:
        """Retrieve conversation by ID"""
        result = await self.db.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        return result.scalar_one_or_none()

    async def _get_conversation_by_approval(self, approval_id: str) -> Optional[ConversationHistory]:
        """Find conversation linked to an approval"""
        result = await self.db.execute(
            select(ConversationHistory).where(
                ConversationHistory.approval_id == approval_id
            )
        )
        return result.scalar_one_or_none()

    async def _route_to_agent(
        self,
        message: str,
        conversation: ConversationHistory
    ) -> AgentProtocol:
        """
        Route message to appropriate agent.

        Routing logic:
        1. If conversation has current_agent, continue with that agent
        2. Else if message matches any agent's patterns, use that agent
        3. Else use default agent
        4. If no default, raise error
        """
        # Continue with current agent if exists
        if conversation.current_agent:
            agent = await self._get_agent_by_name(conversation.current_agent)
            if agent:
                logger.debug(
                    "routing_to_current_agent",
                    agent=conversation.current_agent,
                    conversation_id=conversation.conversation_id
                )
                return agent

        # Match against agent patterns
        for registration in sorted(self._agents, key=lambda r: r.priority, reverse=True):
            if registration.matches(message):
                logger.info(
                    "routing_by_pattern_match",
                    agent=registration.agent.name,
                    message_preview=message[:50]
                )
                return registration.agent

        # Use default agent
        if self._default_agent:
            logger.debug("routing_to_default_agent", agent=self._default_agent.name)
            return self._default_agent

        # No agent available
        raise ValueError("No agent available to handle request. Register at least one agent.")

    async def _get_agent_by_name(self, name: Optional[str]) -> Optional[AgentProtocol]:
        """
        Get agent by name from registry.

        Used to retrieve the current agent handling a multi-turn conversation.
        """
        if not name:
            return None

        for registration in self._agents:
            if registration.agent.name == name:
                return registration.agent

        if self._default_agent and self._default_agent.name == name:
            return self._default_agent

        return None

    async def _update_conversation_with_response(
        self,
        conversation: ConversationHistory,
        agent_response: AgentResponse,
        agent_name: str
    ):
        """Update conversation with agent response"""
        # Add assistant message
        conversation.add_message("assistant", agent_response.message)

        # Update current agent
        conversation.current_agent = agent_name

        # Update state
        conversation.update_state(agent_response.status)

        # Link workflow if created
        if agent_response.workflow_id:
            conversation.link_workflow(agent_response.workflow_id)

        # Link approval if created
        if agent_response.approval_id:
            conversation.link_approval(agent_response.approval_id)

        await self.db.commit()

        logger.debug(
            "conversation_updated",
            conversation_id=conversation.conversation_id,
            agent=agent_name,
            workflow_id=agent_response.workflow_id,
            approval_id=agent_response.approval_id,
            status=agent_response.status
        )
