"""Admin and Dead Letter Queue management endpoints."""

import json
from datetime import datetime
import structlog
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy import select

from app.api.v1.dependencies import get_event_bus
from app.models import DeadLetterQueue, get_db
from app.models.schemas import EventType

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = structlog.get_logger()


@router.get("/dlq")
async def get_dead_letter_queue(
    limit: int = 100,
    db_session = Depends(get_db),
):
    """
    Inspect dead letter queue entries.
    Returns failed events that exceeded max retries.
    """
    result = await db_session.execute(
        select(DeadLetterQueue)
        .order_by(DeadLetterQueue.created_at.desc())
        .limit(limit)
    )
    dlq_entries = result.scalars().all()

    return {
        "total": len(dlq_entries),
        "entries": [entry.to_dict() for entry in dlq_entries]
    }


@router.post("/test-dlq")
async def test_dead_letter_queue(event_bus = Depends(get_event_bus)):
    """
    Test endpoint to trigger DLQ by publishing an event that will fail.
    Creates a test event with a failing handler to demonstrate DLQ functionality.
    """

    # Register a handler that always fails
    async def failing_handler(data: dict):
        """Handler that always raises an exception"""
        raise ValueError(f"Test DLQ failure: {data.get('message', 'no message')}")

    # Subscribe failing handler to test event
    # Use an existing event type that we'll intercept
    test_event_type = EventType.WORKFLOW_STARTED

    # Temporarily subscribe failing handler
    event_bus.subscribe(test_event_type, failing_handler)

    # Publish event that will fail
    test_data = {
        "workflow_id": "test_dlq_trigger",
        "message": "This is a test event to trigger DLQ",
        "timestamp": datetime.now().timestamp(),
        "test": True
    }

    await event_bus.publish(test_event_type, test_data)

    logger.info(
        "dlq_test_triggered",
        message="Published test event that will fail 3 times and move to DLQ"
    )

    return {
        "success": True,
        "message": "Test event published. It will fail 3 times and move to DLQ. Wait 5-10 seconds then check /api/admin/dlq",
        "event_type": test_event_type.value,
        "instructions": [
            "1. Wait 5-10 seconds for retries to complete",
            "2. Go to home.html and click 'Dead Letter Queue' tab",
            "3. Click '🔄 Refresh DLQ' button",
            "4. You should see the failed event with retry_count=3"
        ]
    }


@router.post("/dlq/{entry_id}/retry")
async def retry_dlq_entry(
    entry_id: int,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Retry a single DLQ entry by republishing the event.

    Use this after fixing bugs that caused the event to fail.
    The event will be republished to the event bus and handlers will try again.
    """
    # Get DLQ entry
    result = await db_session.execute(
        select(DeadLetterQueue).where(DeadLetterQueue.id == entry_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    try:
        # Parse event data
        event_data = json.loads(entry.event_data)
        event_type = EventType(entry.original_event_type)

        # Republish event to event bus
        await event_bus.publish(event_type, event_data)

        logger.info(
            "dlq_entry_republished",
            dlq_id=entry_id,
            event_type=entry.original_event_type,
            workflow_id=entry.workflow_id
        )

        # Optionally delete entry after successful republish
        # For now, keep it for audit trail
        # await db_session.delete(entry)
        # await db_session.commit()

        return {
            "success": True,
            "message": "Event republished successfully. Check logs to verify handler succeeded.",
            "entry_id": entry_id,
            "event_type": entry.original_event_type,
            "note": "DLQ entry kept for audit trail. Delete manually if retry succeeded."
        }

    except Exception as e:
        logger.error(
            "dlq_retry_failed",
            dlq_id=entry_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to retry event: {str(e)}")


@router.post("/dlq/retry-all")
async def retry_all_dlq_entries(
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Retry ALL DLQ entries by republishing events.

    Use this after deploying a bug fix that should resolve all failures.
    WARNING: This will republish ALL failed events. Use with caution.
    """
    # Get all DLQ entries
    result = await db_session.execute(
        select(DeadLetterQueue).order_by(DeadLetterQueue.created_at.asc())
    )
    entries = result.scalars().all()

    if not entries:
        return {
            "success": True,
            "message": "No DLQ entries to retry",
            "retried_count": 0
        }

    retried_count = 0
    failed_count = 0
    errors = []

    for entry in entries:
        try:
            # Parse event data
            event_data = json.loads(entry.event_data)
            event_type = EventType(entry.original_event_type)

            # Republish event
            await event_bus.publish(event_type, event_data)
            retried_count += 1

            logger.info(
                "dlq_entry_republished_bulk",
                dlq_id=entry.id,
                event_type=entry.original_event_type
            )

        except Exception as e:
            failed_count += 1
            errors.append({
                "entry_id": entry.id,
                "error": str(e)
            })
            logger.error(
                "dlq_bulk_retry_failed",
                dlq_id=entry.id,
                error=str(e)
            )

    return {
        "success": True,
        "message": f"Retried {retried_count} events. {failed_count} failed.",
        "retried_count": retried_count,
        "failed_count": failed_count,
        "errors": errors if errors else None,
        "note": "DLQ entries kept for audit trail. Use /clear to delete all."
    }


@router.delete("/dlq/clear")
async def clear_all_dlq_entries(db_session = Depends(get_db)):
    """
    Delete ALL DLQ entries.

    Use this to clean up after resolving all issues.
    WARNING: This permanently deletes all DLQ entries. Cannot be undone.
    """
    # Count entries before deletion
    count_result = await db_session.execute(
        select(DeadLetterQueue)
    )
    entries = count_result.scalars().all()
    count = len(entries)

    # Delete all entries
    for entry in entries:
        await db_session.delete(entry)

    await db_session.commit()

    logger.warning(
        "dlq_cleared",
        deleted_count=count,
        message="All DLQ entries deleted"
    )

    return {
        "success": True,
        "message": f"Deleted {count} DLQ entries",
        "deleted_count": count
    }


@router.post("/dlq/bulk-retry")
async def bulk_retry_dlq_entries(
    request: Request,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
):
    """
    Retry multiple selected DLQ entries.

    Body: { "entry_ids": [1, 2, 3] }
    """
    body = await request.json()
    entry_ids = body.get("entry_ids", [])

    if not entry_ids:
        raise HTTPException(status_code=400, detail="No entry IDs provided")

    retried_count = 0
    failed_count = 0
    errors = []

    for entry_id in entry_ids:
        try:
            # Get entry
            result = await db_session.execute(
                select(DeadLetterQueue).where(DeadLetterQueue.id == entry_id)
            )
            entry = result.scalar_one_or_none()

            if not entry:
                failed_count += 1
                errors.append({
                    "entry_id": entry_id,
                    "error": "Entry not found"
                })
                continue

            # Parse and republish
            event_data = json.loads(entry.event_data)
            event_type = EventType(entry.original_event_type)
            await event_bus.publish(event_type, event_data)

            retried_count += 1

        except Exception as e:
            failed_count += 1
            errors.append({
                "entry_id": entry_id,
                "error": str(e)
            })

    return {
        "success": True,
        "message": f"Retried {retried_count} events. {failed_count} failed.",
        "retried_count": retried_count,
        "failed_count": failed_count,
        "errors": errors if errors else None
    }


@router.delete("/dlq/bulk-delete")
async def bulk_delete_dlq_entries(
    request: Request,
    db_session = Depends(get_db),
):
    """
    Delete multiple selected DLQ entries.

    Body: { "entry_ids": [1, 2, 3] }
    """
    body = await request.json()
    entry_ids = body.get("entry_ids", [])

    if not entry_ids:
        raise HTTPException(status_code=400, detail="No entry IDs provided")

    deleted_count = 0
    not_found_count = 0

    for entry_id in entry_ids:
        result = await db_session.execute(
            select(DeadLetterQueue).where(DeadLetterQueue.id == entry_id)
        )
        entry = result.scalar_one_or_none()

        if entry:
            await db_session.delete(entry)
            deleted_count += 1
        else:
            not_found_count += 1

    await db_session.commit()

    return {
        "success": True,
        "message": f"Deleted {deleted_count} entries. {not_found_count} not found.",
        "deleted_count": deleted_count,
        "not_found_count": not_found_count
    }


@router.delete("/dlq/{entry_id}")
async def delete_dlq_entry(
    entry_id: int,
    db_session = Depends(get_db),
):
    """
    Delete a single DLQ entry.

    Use this to clean up resolved entries or entries that are no longer relevant.
    """
    # Get DLQ entry
    result = await db_session.execute(
        select(DeadLetterQueue).where(DeadLetterQueue.id == entry_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    # Delete entry
    await db_session.delete(entry)
    await db_session.commit()

    logger.info(
        "dlq_entry_deleted",
        dlq_id=entry_id,
        event_type=entry.original_event_type,
        workflow_id=entry.workflow_id
    )

    return {
        "success": True,
        "message": "DLQ entry deleted successfully",
        "entry_id": entry_id
    }