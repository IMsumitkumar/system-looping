"""
Chat API endpoints for Agent Integration Layer.

Provides conversational interface to the workflow orchestration system.
"""

from typing import Optional
import structlog
from fastapi import APIRouter, HTTPException, Depends

from app.api.v1.dependencies import get_event_bus, get_orchestrator
from app.models import get_db
from app.agent_layer import AgentOrchestrator
from app.models.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ConversationHistoryResponse,
    ConversationMessage,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = structlog.get_logger()


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    request: ChatMessageRequest,
    db_session=Depends(get_db),
    event_bus=Depends(get_event_bus),
):
    """
    Send a message to the agent and get a response.

    This is the main entry point for conversational interactions.
    The agent will:
    - Parse the user's natural language message
    - Determine what action to take (create workflow, check status, etc.)
    - Call the appropriate WorkflowEngine/ApprovalService methods
    - Return a conversational response

    The conversation state is persisted in the database, so users can
    resume conversations across sessions.

    Example:
        POST /api/chat/message
        {
            "user_id": "user123",
            "message": "Deploy to production with approval",
            "channel": "streamlit"
        }
    """
    try:
        # Get orchestrator
        orchestrator = get_orchestrator(db_session, event_bus)

        # Process message through orchestrator
        response = await orchestrator.process_message(
            user_id=request.user_id,
            message=request.message,
            conversation_id=request.conversation_id,
            channel=request.channel
        )

        logger.info(
            "chat_message_processed",
            user_id=request.user_id,
            conversation_id=response.conversation_id,
            status=response.status
        )

        return response

    except Exception as e:
        logger.error(
            "chat_message_failed",
            user_id=request.user_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process message: {str(e)}"
        )


@router.get("/conversations/{conversation_id}", response_model=ConversationHistoryResponse)
async def get_conversation(
    conversation_id: str,
    db_session=Depends(get_db),
    event_bus=Depends(get_event_bus),
):
    """
    Get conversation history by ID.

    Returns the full conversation including:
    - All messages (user and assistant)
    - Current state
    - Linked workflow and approval IDs
    - Metadata

    Useful for:
    - Resuming conversations
    - Viewing conversation history
    - Debugging agent interactions
    """
    try:
        orchestrator = get_orchestrator(db_session, event_bus)
        conversation = await orchestrator.get_conversation(conversation_id)

        if not conversation:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation {conversation_id} not found"
            )

        # Convert to response format
        messages = [
            ConversationMessage(
                role=msg["role"],
                content=msg["content"],
                timestamp=msg["timestamp"]
            )
            for msg in conversation.messages_list
        ]

        return ConversationHistoryResponse(
            id=conversation.id,
            conversation_id=conversation.conversation_id,
            user_id=conversation.user_id,
            channel=conversation.channel,
            messages=messages,
            state=conversation.state,
            current_agent=conversation.current_agent,
            workflow_id=conversation.workflow_id,
            approval_id=conversation.approval_id,
            metadata=conversation.metadata_dict,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            last_message_at=conversation.last_message_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_conversation_failed",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get conversation: {str(e)}"
        )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db_session=Depends(get_db),
):
    """
    Delete a conversation.

    This is a soft delete - the conversation is removed from the database
    but associated workflows and approvals are not affected.

    Use cases:
    - User wants to clear chat history
    - Testing and cleanup
    """
    try:
        from sqlalchemy import select, delete
        from app.models.orm import ConversationHistory

        # Check if conversation exists
        result = await db_session.execute(
            select(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation {conversation_id} not found"
            )

        # Delete conversation
        await db_session.execute(
            delete(ConversationHistory).where(
                ConversationHistory.conversation_id == conversation_id
            )
        )
        await db_session.commit()

        logger.info(
            "conversation_deleted",
            conversation_id=conversation_id,
            user_id=conversation.user_id
        )

        return {
            "success": True,
            "conversation_id": conversation_id,
            "message": "Conversation deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "delete_conversation_failed",
            conversation_id=conversation_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete conversation: {str(e)}"
        )
