"""
Generic Agent Integration Layer.

This layer provides a framework-agnostic interface for integrating
ANY agent framework with the workflow orchestration system.

Key Components:
- AgentProtocol: Abstract interface that all agents must implement
- AgentOrchestrator: Routes messages to appropriate agents
- ConversationHandler: Autonomous conversation updates from workflow events
- Adapters: Framework-specific implementations (OpenAI, LangGraph, etc.)
"""

from app.agent_layer.protocol import (
    AgentProtocol,
    AgentRequest,
    AgentResponse,
    AgentCapability
)
from app.agent_layer.orchestrator import AgentOrchestrator
from app.agent_layer.conversation_handler import ConversationEventHandler

__all__ = [
    'AgentProtocol',
    'AgentRequest',
    'AgentResponse',
    'AgentCapability',
    'AgentOrchestrator',
    'ConversationEventHandler',
]
