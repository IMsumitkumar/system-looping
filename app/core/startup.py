"""Application startup and shutdown lifecycle management."""

from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI

from app.models import Database
from app.core import EventBus, TimeoutManager
from app.core.events import register_event_handlers
from app.adapters import SlackAdapter

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI lifespan management for startup/shutdown.
    Manages background tasks for event processing and timeout checking.
    """
    logger.info("application_starting")

    # Initialize database
    db = Database()
    await db.init()
    logger.info("database_initialized")

    # IMPORTANT: Initialize event bus with db for DLQ support
    event_bus = EventBus(max_queue_size=1000, db=db)

    # Start event bus
    await event_bus.start()
    logger.info("event_bus_started")

    # Initialize timeout manager
    timeout_manager = TimeoutManager(db, event_bus, check_interval=10)

    # Start timeout manager
    await timeout_manager.start()
    logger.info("timeout_manager_started")

    # Initialize Slack adapter
    slack_adapter = SlackAdapter()

    # Register event handlers with all dependencies
    register_event_handlers(event_bus, db, slack_adapter)
    logger.info("event_handlers_registered")

    # Store in app state for access in routes
    app.state.db = db
    app.state.event_bus = event_bus
    app.state.timeout_manager = timeout_manager
    app.state.slack_adapter = slack_adapter

    logger.info("application_ready")

    yield

    # Shutdown
    logger.info("application_shutting_down")

    await timeout_manager.stop()
    await event_bus.stop()
    await db.close()

    logger.info("application_stopped")