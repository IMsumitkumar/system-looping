"""
Event bus implementation using AsyncIO queues.
Provides pub/sub pattern for asynchronous event processing.
"""

import asyncio
from typing import Callable, Awaitable, Optional, Dict, List
from collections import defaultdict
import structlog
import json
from datetime import datetime

from app.models.schemas import EventType
from app.config.settings import settings

logger = structlog.get_logger()


class EventBus:
    """
    Lightweight event bus using asyncio queues.
    Supports multiple subscribers per event type with DLQ for failed events.
    """

    def __init__(self, max_queue_size: int = 1000, db = None):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._handlers: Dict[EventType, List[Callable[[dict], Awaitable[None]]]] = defaultdict(list)
        self._running = False
        self._processor_task: asyncio.Task = None
        self._db = db  # Database reference for DLQ
        self._retry_counts: Dict[str, int] = {}  # Track retry counts per event

    def subscribe(self, event_type: EventType, handler: Callable[[dict], Awaitable[None]]):
        """
        Subscribe a handler to an event type.

        Args:
            event_type: The event type to listen for
            handler: Async function that receives event data
        """
        self._handlers[event_type].append(handler)
        logger.info(
            "event_handler_subscribed",
            event_type=event_type.value,
            handler=handler.__name__,
            total_handlers=len(self._handlers[event_type]),
        )

    async def publish(self, event_type: EventType, data: dict):
        """
        Publish an event to the bus.

        Args:
            event_type: The type of event
            data: Event payload
        """
        try:
            await self._queue.put({"type": event_type, "data": data})
            logger.debug("event_published", event_type=event_type.value, queue_size=self._queue.qsize())
        except asyncio.QueueFull:
            logger.error("event_queue_full", event_type=event_type.value, data=data)
            raise

    async def start(self):
        """Start the event processor"""
        if self._running:
            logger.warning("event_bus_already_running")
            return

        self._running = True
        self._processor_task = asyncio.create_task(self._process_events())
        logger.info("event_bus_started")

    async def stop(self):
        """Stop the event processor"""
        if not self._running:
            return

        self._running = False

        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        logger.info("event_bus_stopped", pending_events=self._queue.qsize())

    async def _process_events(self):
        """
        Background task that processes events from the queue.
        Runs handlers for each event type.
        """
        logger.info("event_processor_started")

        while self._running:
            try:
                # Wait for event with timeout to allow clean shutdown
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)

                event_type = event["type"]
                event_data = event["data"]

                handlers = self._handlers.get(event_type, [])

                if not handlers:
                    logger.warning("no_handlers_for_event", event_type=event_type.value)
                    continue

                logger.debug(
                    "processing_event",
                    event_type=event_type.value,
                    handlers=len(handlers),
                    data=event_data,
                )

                # Generate event ID for tracking retries
                event_id = f"{event_type.value}:{id(event_data)}"

                # Run all handlers concurrently
                handler_tasks = [
                    self._run_handler(handler, event_data, event_type, event_id)
                    for handler in handlers
                ]

                await asyncio.gather(*handler_tasks, return_exceptions=True)

            except asyncio.TimeoutError:
                # No events in queue, continue loop
                continue
            except asyncio.CancelledError:
                logger.info("event_processor_cancelled")
                break
            except Exception as e:
                logger.error("event_processor_error", error=str(e), exc_info=True)

        logger.info("event_processor_stopped")

    async def _run_handler(self, handler: Callable, data: dict, event_type: EventType, event_id: str):
        """
        Run a single handler with error handling and DLQ support.
        """
        try:
            await handler(data)
            # CRITICAL: Clean up successful events to prevent memory leak
            self._retry_counts.pop(event_id, None)
        except Exception as e:
            # Track retry count for this event
            retry_count = self._retry_counts.get(event_id, 0) + 1
            self._retry_counts[event_id] = retry_count

            logger.error(
                "event_handler_error",
                handler=handler.__name__,
                event_type=event_type.value,
                error=str(e),
                retry_count=retry_count,
                exc_info=True,
            )

            # Move to DLQ after max retries
            if retry_count >= settings.event_bus_max_retries:
                await self._move_to_dlq(event_type, data, str(e), retry_count)
                # Clean up retry counter
                self._retry_counts.pop(event_id, None)
            else:
                logger.info(
                    "event_will_retry",
                    event_type=event_type.value,
                    retry_count=retry_count,
                    max_retries=settings.event_bus_max_retries
                )

    async def _move_to_dlq(self, event_type: EventType, event_data: dict, error_message: str, retry_count: int):
        """
        Move failed event to Dead Letter Queue.
        """
        if not self._db:
            logger.warning(
                "dlq_disabled",
                event_type=event_type.value,
                message="Database not configured for DLQ"
            )
            return

        try:
            from app.models import DeadLetterQueue

            async with self._db.session() as session:
                dlq_entry = DeadLetterQueue(
                    original_event_type=event_type.value,
                    event_data=json.dumps(event_data),
                    error_message=error_message,
                    retry_count=retry_count,
                    created_at=datetime.now().timestamp(),
                    workflow_id=event_data.get("workflow_id"),  # Optional workflow reference
                )
                session.add(dlq_entry)
                await session.commit()

                logger.warning(
                    "event_moved_to_dlq",
                    event_type=event_type.value,
                    dlq_id=dlq_entry.id,
                    error=error_message,
                    retry_count=retry_count
                )
        except Exception as dlq_error:
            logger.error(
                "dlq_write_failed",
                event_type=event_type.value,
                error=str(dlq_error),
                exc_info=True
            )

    def get_stats(self) -> dict:
        """Get event bus statistics"""
        return {
            "running": self._running,
            "queue_size": self._queue.qsize(),
            "max_queue_size": self._queue.maxsize,
            "event_types": list(self._handlers.keys()),
            "total_handlers": sum(len(handlers) for handlers in self._handlers.values()),
        }
