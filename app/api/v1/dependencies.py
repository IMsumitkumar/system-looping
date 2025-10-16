"""Shared dependencies for API routes."""

from typing import Optional
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import get_db, Database
from app.core import EventBus, TimeoutManager
from app.adapters import SlackAdapter

# For Python 3.8 compatibility - not using Annotated
def get_event_bus(request: Request) -> EventBus:
    """Get event bus from app state."""
    return request.app.state.event_bus


def get_timeout_manager(request: Request) -> TimeoutManager:
    """Get timeout manager from app state."""
    return request.app.state.timeout_manager


def get_slack_adapter(request: Request) -> SlackAdapter:
    """Get Slack adapter from app state."""
    return request.app.state.slack_adapter


def get_database(request: Request) -> Database:
    """Get database instance from app state."""
    return request.app.state.db


def get_orchestrator(db_session: AsyncSession, event_bus: EventBus):
    """
    Get agent orchestrator with registered agents.

    This creates a new orchestrator instance per request with the current
    database session and event_bus, and registers available agent adapters.
    """
    from app.agent_layer import AgentOrchestrator
    from app.agent_layer.adapters import OpenAIAdapter
    import os

    orchestrator = AgentOrchestrator(db_session, event_bus)

    # Register agent adapters (OpenAI, LangGraph, etc.)
    try:
        openai_agent = OpenAIAdapter(event_bus=event_bus)
        orchestrator.register_agent(
            openai_agent,
            patterns=[
                r"deploy",
                r"workflow",
                r"create.*workflow",
                r"approval",
                r"production",
                r"run.*test",
            ],
            set_as_default=True  # Use as default for all unmatched messages
        )
    except ImportError:
        # OpenAI not installed - gracefully handle
        pass
    except Exception as e:
        # Log but don't fail if agent registration fails
        import structlog
        logger = structlog.get_logger()
        logger.warning("agent_registration_failed", error=str(e))

    return orchestrator


# Type aliases for dependency injection - using standard Depends syntax
DbSession = AsyncSession
EventBusDep = EventBus
TimeoutManagerDep = TimeoutManager
SlackAdapterDep = SlackAdapter
DatabaseDep = Database