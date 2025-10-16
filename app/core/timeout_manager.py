"""
Timeout manager for checking and handling expired approvals.
Runs as a background task checking for timeouts periodically.
"""

import asyncio
import structlog

from app.models.database import Database
from app.core.approval_service import ApprovalService

logger = structlog.get_logger()


class TimeoutManager:
    """
    Background service that checks for expired approvals.
    """

    def __init__(self, db: Database, event_bus=None, check_interval: int = 10):
        self.db = db
        self.event_bus = event_bus
        self.check_interval = check_interval
        self._running = False
        self._task: asyncio.Task = None

    async def start(self):
        """Start the timeout checker"""
        if self._running:
            logger.warning("timeout_manager_already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._check_timeouts_loop())
        logger.info("timeout_manager_started", check_interval=self.check_interval)

    async def stop(self):
        """Stop the timeout checker"""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("timeout_manager_stopped")

    async def _check_timeouts_loop(self):
        """Background loop that checks for timeouts"""
        logger.info("timeout_checker_started")

        while self._running:
            try:
                # Check immediately on first iteration, then sleep
                await self._check_and_process_timeouts()
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.info("timeout_checker_cancelled")
                break
            except Exception as e:
                logger.error("timeout_checker_error", error=str(e), exc_info=True)
                # Continue running even if one check fails
                await asyncio.sleep(self.check_interval)

        logger.info("timeout_checker_stopped")

    async def _check_and_process_timeouts(self):
        """
        Check for expired approvals and process them.

        Flow:
        1. Mark approval as TIMEOUT
        2. Transition workflow to TIMEOUT state (CRITICAL - required for retry_workflow)
        3. Attempt retry
        4. If max retries exceeded, move to DLQ
        """
        async with self.db.session() as session:
            approval_service = ApprovalService(session, self.event_bus)

            # Get all expired approvals
            expired_approvals = await approval_service.get_expired_approvals()

            if not expired_approvals:
                return

            logger.info("expired_approvals_found", count=len(expired_approvals))

            # Process each expired approval
            for approval in expired_approvals:
                try:
                    # Mark approval as timed out
                    await approval_service.mark_timeout(approval.id)

                    # CRITICAL: Transition workflow to TIMEOUT state BEFORE retry
                    # retry_workflow() requires workflow to be in TIMEOUT or FAILED state
                    from app.core.workflow_engine import WorkflowEngine
                    from app.models.schemas import WorkflowState

                    workflow_engine = WorkflowEngine(session, self.event_bus)

                    # Get workflow to check current state
                    workflow = await workflow_engine.get_workflow(approval.workflow_id)

                    # Only transition if not already in terminal state
                    if workflow.state not in [
                        WorkflowState.TIMEOUT.value,
                        WorkflowState.FAILED.value,
                        WorkflowState.COMPLETED.value,
                        WorkflowState.REJECTED.value
                    ]:
                        await workflow_engine.transition_to(
                            approval.workflow_id,
                            WorkflowState.TIMEOUT,
                            f"Approval {approval.id} timed out - no response received"
                        )
                        logger.info(
                            "workflow_transitioned_to_timeout",
                            workflow_id=approval.workflow_id,
                            approval_id=approval.id
                        )

                    # Attempt retry
                    retry_result = await workflow_engine.retry_workflow(approval.workflow_id)

                    if retry_result:
                        logger.info(
                            "workflow_retry_after_timeout",
                            workflow_id=approval.workflow_id,
                            approval_id=approval.id,
                            retry_count=retry_result.retry_count,
                            max_retries=retry_result.max_retries
                        )
                    else:
                        # Max retries exceeded - move to DLQ
                        logger.warning(
                            "workflow_failed_max_retries",
                            workflow_id=approval.workflow_id,
                            approval_id=approval.id,
                            message="Moving workflow to Dead Letter Queue"
                        )

                        # Move to DLQ
                        await self._move_workflow_to_dlq(
                            session,
                            approval.workflow_id,
                            f"Max retries ({workflow.max_retries}) exceeded after timeouts"
                        )

                except Exception as e:
                    logger.error(
                        "timeout_processing_error",
                        approval_id=approval.id,
                        error=str(e),
                        exc_info=True,
                    )

    async def _move_workflow_to_dlq(self, session, workflow_id: str, error_message: str):
        """
        Move a failed workflow to the Dead Letter Queue.

        Args:
            session: Database session
            workflow_id: The workflow that failed
            error_message: Reason for DLQ
        """
        try:
            from app.models import DeadLetterQueue, Workflow
            from sqlalchemy import select
            import json
            from datetime import datetime

            # Get workflow details
            result = await session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                logger.error("workflow_not_found_for_dlq", workflow_id=workflow_id)
                return

            # Create DLQ entry
            dlq_entry = DeadLetterQueue(
                original_event_type="workflow.timeout_max_retries_exceeded",
                event_data=json.dumps({
                    "workflow_id": workflow_id,
                    "workflow_type": workflow.workflow_type,
                    "state": workflow.state,
                    "retry_count": workflow.retry_count,
                    "max_retries": workflow.max_retries,
                    "context": workflow.context_dict,
                }),
                error_message=error_message,
                retry_count=workflow.retry_count,
                created_at=datetime.now().timestamp(),
                workflow_id=workflow_id,
            )
            session.add(dlq_entry)
            await session.commit()

            logger.warning(
                "workflow_moved_to_dlq",
                workflow_id=workflow_id,
                dlq_id=dlq_entry.id,
                retry_count=workflow.retry_count,
                error=error_message
            )

        except Exception as e:
            logger.error(
                "dlq_write_failed_for_workflow",
                workflow_id=workflow_id,
                error=str(e),
                exc_info=True
            )
