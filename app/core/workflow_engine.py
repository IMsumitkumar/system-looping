"""
Workflow engine with state machine management.
Handles workflow lifecycle and state transitions.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from datetime import datetime
from typing import Optional, List, Union
import json
import structlog

from app.models.orm import Workflow, WorkflowEvent
from app.models.schemas import WorkflowState, EventType, STATE_TRANSITIONS
from app.config.settings import settings

logger = structlog.get_logger()


# Task handler registry - register custom task handlers here
TASK_HANDLERS = {}
ROLLBACK_HANDLERS = {}

def register_task_handler(name: str, handler, rollback_handler=None):
    """Register a task handler"""
    TASK_HANDLERS[name] = handler
    if rollback_handler:
        ROLLBACK_HANDLERS[name] = rollback_handler

# Example handlers (for demo)
async def example_task_handler(input_data: dict) -> dict:
    """Example task handler"""
    logger.info("example_task_executed", input=input_data)
    return {"result": "success", "processed": input_data}

async def example_rollback_handler(output_data: dict):
    """Example rollback handler"""
    logger.info("example_task_rolled_back", output=output_data)

# Register example handler
register_task_handler("example_task", example_task_handler, example_rollback_handler)


class InvalidStateTransitionError(Exception):
    """Raised when attempting an invalid state transition"""

    pass


class ConcurrentModificationError(Exception):
    """Raised when workflow is modified concurrently"""

    pass


class WorkflowEngine:
    """
    Manages workflow state machine and transitions.
    Ensures valid state transitions and publishes events.
    """

    def __init__(self, db: AsyncSession, event_bus=None):
        self.db = db
        self.event_bus = event_bus

    async def create_workflow(
        self,
        workflow_type: str,
        context: dict,
        steps: Optional[List[dict]] = None,
        approval_timeout_seconds: int = 3600
    ) -> Workflow:
        """Create a new workflow"""
        workflow = Workflow(
            workflow_type=workflow_type,
            state=WorkflowState.CREATED.value,
            context=json.dumps(context),
        )

        self.db.add(workflow)
        await self.db.flush()

        # Create workflow steps if provided
        if steps:
            from app.models.orm import WorkflowStep
            for order, step_config in enumerate(steps):
                step = WorkflowStep(
                    workflow_id=workflow.id,
                    step_order=order,
                    step_type=step_config["type"],
                    task_handler=step_config.get("handler"),
                    task_input=json.dumps(step_config.get("input", {})) if step_config.get("input") else None
                )
                self.db.add(step)

        # Record creation event
        await self._record_event(
            workflow.id,
            EventType.WORKFLOW_STARTED,
            {
                "workflow_type": workflow_type,
                "initial_state": WorkflowState.CREATED.value,
                "context": context,
            },
        )

        logger.info(
            "workflow_created",
            workflow_id=workflow.id,
            workflow_type=workflow_type,
            state=workflow.state,
        )

        # CRITICAL: Commit BEFORE publishing event so handlers can read the workflow
        await self.db.commit()

        # Publish event to event bus AFTER commit
        if self.event_bus:
            await self.event_bus.publish(
                EventType.WORKFLOW_STARTED,
                {
                    "workflow_id": workflow.id,
                    "workflow_type": workflow_type,
                    "context": context,
                    "approval_timeout_seconds": approval_timeout_seconds,
                },
            )

        # If steps exist, transition to RUNNING and execute first step
        if steps:
            # CRITICAL: Transition workflow to RUNNING before executing steps
            # This prevents "Invalid transition from CREATED to COMPLETED" error
            await self.transition_to(workflow.id, WorkflowState.RUNNING, "Starting multi-step workflow")
            await self.execute_next_step(workflow.id)

        return workflow

    async def transition_to(self, workflow_id: str, new_state: WorkflowState, reason: str = None) -> Workflow:
        """
        Transition workflow to new state with validation and optimistic locking.

        Uses version-based concurrency control to prevent race conditions.
        Raises ConcurrentModificationError if workflow was modified concurrently.
        """
        # Get workflow with current version
        result = await self.db.execute(select(Workflow).where(Workflow.id == workflow_id))
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        current_state = WorkflowState(workflow.state)
        old_version = workflow.version

        # Validate transition
        if new_state not in STATE_TRANSITIONS.get(current_state, []):
            raise InvalidStateTransitionError(
                f"Invalid transition from {current_state.value} to {new_state.value}"
            )

        old_state = workflow.state
        new_updated_at = datetime.now().timestamp()

        # Perform optimistic locking update - only succeeds if version hasn't changed
        update_result = await self.db.execute(
            update(Workflow)
            .where(Workflow.id == workflow_id, Workflow.version == old_version)
            .values(
                state=new_state.value,
                updated_at=new_updated_at,
                version=old_version + 1,
            )
        )

        # Check if update succeeded
        if update_result.rowcount == 0:
            logger.warning(
                "concurrent_modification_detected",
                workflow_id=workflow_id,
                expected_version=old_version,
                attempted_transition=f"{current_state.value} -> {new_state.value}",
            )
            raise ConcurrentModificationError(
                f"Workflow {workflow_id} was modified concurrently. "
                f"Expected version {old_version}, but it has changed. Please retry."
            )

        # Refresh workflow object to get updated values
        await self.db.refresh(workflow)

        # Record state change event
        await self._record_event(
            workflow.id,
            EventType.WORKFLOW_STATE_CHANGED,
            {
                "from_state": old_state,
                "to_state": new_state.value,
                "reason": reason or "State transition",
                "version": workflow.version,
            },
        )

        logger.info(
            "workflow_state_changed",
            workflow_id=workflow.id,
            from_state=old_state,
            to_state=new_state.value,
            reason=reason,
            version=workflow.version,
        )

        # Publish event to event bus
        if self.event_bus:
            await self.event_bus.publish(
                EventType.WORKFLOW_STATE_CHANGED,
                {
                    "workflow_id": workflow.id,
                    "from_state": old_state,
                    "to_state": new_state.value,
                    "reason": reason,
                },
            )

        await self.db.commit()
        return workflow

    async def get_workflow(self, workflow_id: str) -> Workflow:
        """Get workflow by ID"""
        result = await self.db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        return workflow

    async def get_workflow_events(self, workflow_id: str) -> List[WorkflowEvent]:
        """Get all events for a workflow"""
        result = await self.db.execute(
            select(WorkflowEvent).where(WorkflowEvent.workflow_id == workflow_id).order_by(WorkflowEvent.occurred_at)
        )
        return result.scalars().all()

    async def list_workflows(self, state: WorkflowState = None, limit: int = 100) -> List[Workflow]:
        """List workflows, optionally filtered by state"""
        query = select(Workflow).options(selectinload(Workflow.steps)).order_by(Workflow.created_at.desc()).limit(limit)

        if state:
            query = query.where(Workflow.state == state.value)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def mark_completed(self, workflow_id: str, result_data: dict = None) -> Workflow:
        """Mark workflow as completed"""
        workflow = await self.transition_to(workflow_id, WorkflowState.COMPLETED, "Workflow completed successfully")

        # Update context with result
        if result_data:
            context = workflow.context_dict
            context["result"] = result_data
            workflow.update_context(context)

        # Record completion event
        await self._record_event(
            workflow.id,
            EventType.WORKFLOW_COMPLETED,
            {"workflow_id": workflow_id, "result": result_data or {}},
        )

        logger.info("workflow_completed", workflow_id=workflow_id, result=result_data)

        # Publish event
        if self.event_bus:
            await self.event_bus.publish(
                EventType.WORKFLOW_COMPLETED,
                {"workflow_id": workflow_id, "result": result_data or {}},
            )

        await self.db.commit()
        return workflow

    async def _cancel_pending_approvals(self, workflow_id: str, reason: str):
        """
        Cancel all pending approvals for a workflow.
        Ensures data consistency - no pending approvals for terminal workflows.
        """
        from app.models.orm import ApprovalRequest
        from app.models.schemas import ApprovalStatus

        result = await self.db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.workflow_id == workflow_id,
                ApprovalRequest.status == ApprovalStatus.PENDING.value
            )
        )
        approvals = result.scalars().all()

        if not approvals:
            return

        logger.info(
            "cancelling_pending_approvals",
            workflow_id=workflow_id,
            count=len(approvals),
            reason=reason
        )

        for approval in approvals:
            approval.status = ApprovalStatus.CANCELLED.value
            approval.responded_at = datetime.now().timestamp()

            await self._record_event(
                workflow_id,
                EventType.APPROVAL_CANCELLED,
                {"approval_id": approval.id, "reason": reason}
            )

        await self.db.commit()

        logger.info(
            "pending_approvals_cancelled",
            workflow_id=workflow_id,
            count=len(approvals)
        )

    async def _mark_running_steps_as_failed(self, workflow_id: str, reason: str):
        """
        Mark any running steps as failed when workflow fails.

        Maintains data consistency invariant: FAILED workflow should have no running steps.
        Running steps are typically approval steps that were interrupted by workflow failure.

        This fixes the issue where:
        - User cancels workflow while approval is pending
        - ApprovalRequest gets CANCELLED (correct)
        - But WorkflowStep stays "running" (bug!)
        - On retry, no failed steps found → nothing resets

        Args:
            workflow_id: The workflow ID
            reason: Why the workflow failed (for logging)
        """
        from app.models.orm import WorkflowStep

        result = await self.db.execute(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.status == "running"
            )
        )
        running_steps = result.scalars().all()

        if not running_steps:
            return

        logger.info(
            "marking_running_steps_as_failed",
            workflow_id=workflow_id,
            num_steps=len(running_steps),
            reason=reason
        )

        for step in running_steps:
            old_status = step.status
            step.status = "failed"
            step.task_output = json.dumps({
                "error": reason,
                "interrupted": True,
                "original_status": old_status
            })

            logger.info(
                "step_marked_failed_due_to_workflow_failure",
                workflow_id=workflow_id,
                step_id=step.id,
                step_order=step.step_order,
                step_type=step.step_type,
                old_status=old_status,
                reason="workflow_failed_while_step_running"
            )

        await self.db.commit()

        logger.info(
            "running_steps_marked_failed",
            workflow_id=workflow_id,
            num_steps=len(running_steps)
        )

    async def mark_failed(self, workflow_id: str, error: str, move_to_dlq: bool = False) -> Workflow:
        """
        Mark workflow as failed and cleanup pending approvals and running steps.

        Args:
            workflow_id: The workflow to mark as failed
            error: The error message
            move_to_dlq: If True, move the workflow to DLQ after marking as failed
        """
        # CRITICAL: Cancel pending approvals BEFORE state transition
        await self._cancel_pending_approvals(workflow_id, error)

        # CRITICAL: Mark running steps as failed (data consistency)
        # Ensures invariant: FAILED workflow has no running steps
        await self._mark_running_steps_as_failed(workflow_id, error)

        # transition_to already commits, so no need to commit again
        workflow = await self.transition_to(workflow_id, WorkflowState.FAILED, f"Workflow failed: {error}")

        # Record failure event (transition_to already recorded state change)
        await self._record_event(
            workflow.id,
            EventType.WORKFLOW_FAILED,
            {"workflow_id": workflow_id, "error": error},
        )

        logger.error("workflow_failed", workflow_id=workflow_id, error=error)

        # Publish event
        if self.event_bus:
            await self.event_bus.publish(
                EventType.WORKFLOW_FAILED,
                {"workflow_id": workflow_id, "error": error},
            )

        await self.db.commit()

        # Move to DLQ if requested
        if move_to_dlq:
            await self._move_workflow_to_dlq(workflow_id, error)

        return workflow

    async def _move_workflow_to_dlq(self, workflow_id: str, error_message: str):
        """
        Move a failed workflow to the Dead Letter Queue.

        Args:
            workflow_id: The workflow that failed
            error_message: Reason for DLQ
        """
        try:
            from app.models.orm import DeadLetterQueue
            from datetime import datetime

            # Get workflow details (refresh to ensure latest state)
            workflow = await self.get_workflow(workflow_id)

            # Create DLQ entry
            dlq_entry = DeadLetterQueue(
                original_event_type="workflow.failed_max_retries_exceeded",
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
            self.db.add(dlq_entry)
            await self.db.commit()

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

    async def _record_event(self, workflow_id: str, event_type: Union[EventType, str], event_data: dict):
        """
        Record an event in the workflow event log with sequence numbering.
        Ensures events are ordered per workflow for event replay and debugging.
        """
        # Handle both EventType enum and string (for testing)
        if isinstance(event_type, EventType):
            event_type_str = event_type.value
        else:
            event_type_str = event_type

        # Get next sequence number for this workflow
        result = await self.db.execute(
            select(func.max(WorkflowEvent.sequence_number))
            .where(WorkflowEvent.workflow_id == workflow_id)
        )
        max_seq = result.scalar() or 0
        next_seq = max_seq + 1

        event = WorkflowEvent(
            workflow_id=workflow_id,
            event_type=event_type_str,
            event_data=json.dumps(event_data),
            occurred_at=datetime.now().timestamp(),
            sequence_number=next_seq,
        )
        self.db.add(event)
        await self.db.flush()

    def can_transition(self, current_state: WorkflowState, new_state: WorkflowState) -> bool:
        """Check if transition is valid"""
        return new_state in STATE_TRANSITIONS.get(current_state, [])

    async def _find_first_failed_step(self, workflow_id: str) -> Optional[int]:
        """
        Find the step_order of the first failed or interrupted step in a workflow.

        Returns the step_order of the first failed step, or None if no failed steps exist.
        This is used to determine where to resume execution during retry.

        SAFETY NET: Also checks for "running" steps as a defensive measure.
        In normal operation, mark_failed() converts running → failed, but this
        provides resilience against edge cases or race conditions.
        """
        from app.models.orm import WorkflowStep

        result = await self.db.execute(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.status.in_(["failed", "running"])  # Safety: catch interrupted steps too
            )
            .order_by(WorkflowStep.step_order)
            .limit(1)
        )
        failed_step = result.scalar_one_or_none()

        if failed_step:
            logger.info(
                "first_failed_step_found",
                workflow_id=workflow_id,
                step_id=failed_step.id,
                step_order=failed_step.step_order,
                step_type=failed_step.step_type,
                step_status=failed_step.status
            )
            return failed_step.step_order

        logger.warning(
            "no_failed_steps_found",
            workflow_id=workflow_id,
            message="Expected to find failed steps but none exist"
        )
        return None

    async def _reset_steps_from_failure(self, workflow_id: str) -> int:
        """
        Reset all steps from the first failure point onwards to 'pending' state.

        This implements the "resume from failure" strategy:
        1. Find first failed step
        2. Reset that step + all subsequent steps to "pending"
        3. Clear execution metadata (timestamps, outputs, approval_ids)

        Returns the number of steps reset.

        TASK IDEMPOTENCY NOTE:
        Similar to AWS Step Functions, Temporal, and Airflow, task handlers should be
        designed to be idempotent or at least retry-safe:
        - Use workflow_id + step_id as idempotency key for external operations
        - Check if work was already done before re-executing
        - Use upsert operations instead of inserts
        - Avoid non-deterministic functions (datetime.now(), random())
        - Store intermediate state in step output for resume capability

        Example idempotent task handler:
            async def deploy_handler(input_data):
                deployment_id = f"{input_data['workflow_id']}_{input_data['step_id']}"
                if await check_deployment_exists(deployment_id):
                    return await get_deployment_status(deployment_id)
                return await create_deployment(deployment_id, input_data)
        """
        from app.models.orm import WorkflowStep

        # Find first failed step
        first_failed_order = await self._find_first_failed_step(workflow_id)

        if first_failed_order is None:
            logger.warning(
                "reset_steps_no_failed_steps",
                workflow_id=workflow_id,
                message="No failed steps found - nothing to reset"
            )
            return 0

        # Get all steps from failure point onwards
        result = await self.db.execute(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_order >= first_failed_order
            )
            .order_by(WorkflowStep.step_order)
        )
        steps_to_reset = result.scalars().all()

        if not steps_to_reset:
            logger.warning(
                "reset_steps_no_steps_to_reset",
                workflow_id=workflow_id,
                first_failed_order=first_failed_order
            )
            return 0

        logger.info(
            "reset_steps_initiated",
            workflow_id=workflow_id,
            first_failed_order=first_failed_order,
            steps_to_reset_count=len(steps_to_reset)
        )

        # Reset each step
        reset_count = 0
        for step in steps_to_reset:
            old_status = step.status

            # Reset to pending state
            step.status = "pending"
            step.started_at = None
            step.completed_at = None
            step.task_output = None

            # Clear approval_id for approval steps (orphaned approvals already cancelled)
            if step.step_type == "approval":
                step.approval_id = None

            logger.info(
                "step_reset_to_pending",
                workflow_id=workflow_id,
                step_id=step.id,
                step_order=step.step_order,
                step_type=step.step_type,
                old_status=old_status,
                new_status="pending"
            )

            reset_count += 1

        # Commit all resets in a single transaction
        await self.db.commit()

        logger.info(
            "reset_steps_completed",
            workflow_id=workflow_id,
            steps_reset_count=reset_count,
            first_failed_order=first_failed_order
        )

        return reset_count

    async def retry_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """
        Retry a timed-out or failed workflow.
        Implements exponential backoff and max retry limits.

        For multi-step workflows:
        - Finds first failed step
        - Resets that step + all subsequent steps to 'pending'
        - Resumes execution from the failed step

        For single-step workflows:
        - Uses event bus to trigger new approval request

        Returns:
            Updated workflow if retry was successful, None if max retries exceeded
        """
        # Get workflow with steps loaded
        result = await self.db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Check if workflow is in TIMEOUT or FAILED state
        if workflow.state not in [WorkflowState.TIMEOUT.value, WorkflowState.FAILED.value]:
            logger.warning(
                "retry_workflow_invalid_state",
                workflow_id=workflow_id,
                current_state=workflow.state,
                message="Can only retry workflows in TIMEOUT or FAILED state"
            )
            return None

        # Check if max retries exceeded
        if workflow.retry_count >= workflow.max_retries:
            logger.warning(
                "max_retries_exceeded",
                workflow_id=workflow_id,
                retry_count=workflow.retry_count,
                max_retries=workflow.max_retries,
                message="Moving workflow to Dead Letter Queue"
            )
            # Move to FAILED state permanently and send to DLQ
            await self.mark_failed(
                workflow_id,
                f"Max retries ({workflow.max_retries}) exceeded",
                move_to_dlq=True  # IMPORTANT: Move to DLQ after max retries
            )
            return None

        # Calculate exponential backoff delay
        backoff_seconds = settings.retry_initial_wait_seconds * (
            settings.retry_backoff_multiplier ** workflow.retry_count
        )
        backoff_seconds = min(backoff_seconds, settings.retry_max_wait_seconds)

        # Determine if this is a multi-step workflow
        is_multi_step = len(workflow.steps) > 0

        logger.info(
            "workflow_retry_initiated",
            workflow_id=workflow_id,
            retry_count=workflow.retry_count + 1,
            max_retries=workflow.max_retries,
            backoff_seconds=backoff_seconds,
            is_multi_step=is_multi_step
        )

        # Safety: Cancel any orphaned pending approvals from previous attempt
        await self._cancel_pending_approvals(
            workflow_id,
            f"Retrying workflow (attempt {workflow.retry_count + 1}/{workflow.max_retries})"
        )

        # Update retry count and timestamp
        workflow.retry_count += 1
        workflow.last_retry_at = datetime.now().timestamp()
        workflow.updated_at = datetime.now().timestamp()

        await self.db.commit()

        # Record retry event
        await self._record_event(
            workflow.id,
            EventType.APPROVAL_RETRY,
            {
                "retry_count": workflow.retry_count,
                "max_retries": workflow.max_retries,
                "backoff_seconds": backoff_seconds,
                "is_multi_step": is_multi_step,
            },
        )

        # Transition back to RUNNING
        await self.transition_to(
            workflow_id,
            WorkflowState.RUNNING,
            f"Retry attempt {workflow.retry_count}/{workflow.max_retries}"
        )

        # MULTI-STEP WORKFLOW: Reset failed steps and resume execution
        if is_multi_step:
            logger.info(
                "multi_step_retry_resetting_steps",
                workflow_id=workflow_id,
                retry_count=workflow.retry_count
            )

            # Reset steps from failure point
            reset_count = await self._reset_steps_from_failure(workflow_id)

            if reset_count > 0:
                # Resume execution from first pending step
                logger.info(
                    "multi_step_retry_resuming_execution",
                    workflow_id=workflow_id,
                    steps_reset=reset_count
                )
                await self.execute_next_step(workflow_id)
            else:
                # No steps to reset - this shouldn't happen but handle gracefully
                logger.error(
                    "multi_step_retry_no_steps_reset",
                    workflow_id=workflow_id,
                    message="Failed to reset any steps - marking workflow as failed"
                )
                await self.mark_failed(workflow_id, "Retry failed: no steps to reset")
                return None

        # SINGLE-STEP WORKFLOW: Publish retry event to trigger new approval
        else:
            logger.info(
                "single_step_retry_publishing_event",
                workflow_id=workflow_id,
                retry_count=workflow.retry_count
            )

            if self.event_bus:
                await self.event_bus.publish(
                    EventType.APPROVAL_RETRY,
                    {
                        "workflow_id": workflow_id,
                        "retry_count": workflow.retry_count,
                        "max_retries": workflow.max_retries,
                        "backoff_seconds": backoff_seconds,
                    },
                )

        logger.info(
            "workflow_retry_completed",
            workflow_id=workflow_id,
            retry_count=workflow.retry_count,
            new_state=WorkflowState.RUNNING.value,
            is_multi_step=is_multi_step
        )

        return workflow

    def calculate_exponential_backoff(self, retry_count: int) -> float:
        """
        Calculate exponential backoff delay with jitter.

        Args:
            retry_count: Current retry attempt (0-indexed)

        Returns:
            Delay in seconds
        """
        backoff = settings.retry_initial_wait_seconds * (
            settings.retry_backoff_multiplier ** retry_count
        )
        return min(backoff, settings.retry_max_wait_seconds)

    async def rollback_workflow(
        self,
        workflow_id: str,
        target_state: WorkflowState,
        reason: str,
        rollback_by: str = "system"
    ) -> Optional[Workflow]:
        """
        Rollback a workflow to a previous state with full audit trail.

        Args:
            workflow_id: The workflow to rollback
            target_state: The state to rollback to
            reason: Reason for rollback (for audit)
            rollback_by: Who initiated the rollback

        Returns:
            Updated workflow or None if rollback not allowed
        """
        import time

        logger.info(
            "rollback_workflow_initiated",
            workflow_id=workflow_id,
            target_state=target_state.value,
            reason=reason,
            rollback_by=rollback_by
        )

        # Get current workflow
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            logger.error("workflow_not_found_for_rollback", workflow_id=workflow_id)
            return None

        current_state = WorkflowState(workflow.state)

        # Check if rollback is allowed from current state
        if target_state not in STATE_TRANSITIONS.get(current_state, []):
            logger.error(
                "rollback_not_allowed",
                workflow_id=workflow_id,
                current_state=current_state.value,
                target_state=target_state.value
            )
            raise InvalidStateTransitionError(
                f"Cannot rollback from {current_state.value} to {target_state.value}"
            )

        # Check rollback limits
        if workflow.rollback_count >= workflow.max_rollbacks:
            logger.error(
                "rollback_limit_exceeded",
                workflow_id=workflow_id,
                rollback_count=workflow.rollback_count,
                max_rollbacks=workflow.max_rollbacks
            )
            raise ValueError(f"Maximum rollback limit ({workflow.max_rollbacks}) exceeded")

        # Perform rollback
        workflow.previous_state = workflow.state
        workflow.state = target_state.value
        workflow.rollback_count += 1
        workflow.last_rollback_at = time.time()
        workflow.rollback_reason = reason
        workflow.updated_at = time.time()
        workflow.version += 1

        # Record rollback event
        await self._record_event(
            workflow_id,
            EventType.WORKFLOW_ROLLED_BACK,
            {
                "from_state": current_state.value,
                "to_state": target_state.value,
                "reason": reason,
                "rollback_by": rollback_by,
                "rollback_count": workflow.rollback_count,
                "timestamp": time.time()
            }
        )

        await self.db.commit()
        await self.db.refresh(workflow)

        # Publish rollback event
        if self.event_bus:
            await self.event_bus.publish(
                EventType.WORKFLOW_ROLLED_BACK,
                {
                    "workflow_id": workflow_id,
                    "from_state": current_state.value,
                    "to_state": target_state.value,
                    "reason": reason,
                    "rollback_by": rollback_by,
                    "rollback_count": workflow.rollback_count
                }
            )

        logger.info(
            "rollback_workflow_completed",
            workflow_id=workflow_id,
            from_state=current_state.value,
            to_state=target_state.value,
            rollback_count=workflow.rollback_count
        )

        return workflow

    async def can_rollback(self, workflow_id: str, target_state: WorkflowState) -> bool:
        """
        Check if a workflow can be rolled back to a target state.

        Args:
            workflow_id: The workflow to check
            target_state: The desired rollback state

        Returns:
            True if rollback is allowed, False otherwise
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return False

        current_state = WorkflowState(workflow.state)

        # Check state transition allows it
        if target_state not in STATE_TRANSITIONS.get(current_state, []):
            return False

        # Check rollback limit
        if workflow.rollback_count >= workflow.max_rollbacks:
            return False

        return True

    async def get_rollback_history(self, workflow_id: str) -> List[dict]:
        """
        Get the rollback history for a workflow.

        Args:
            workflow_id: The workflow ID

        Returns:
            List of rollback events
        """
        stmt = select(WorkflowEvent).where(
            WorkflowEvent.workflow_id == workflow_id,
            WorkflowEvent.event_type == EventType.WORKFLOW_ROLLED_BACK.value
        ).order_by(WorkflowEvent.occurred_at.desc())

        result = await self.db.execute(stmt)
        events = result.scalars().all()

        return [
            {
                "event_id": event.id,
                "from_state": event.event_data_dict.get("from_state"),
                "to_state": event.event_data_dict.get("to_state"),
                "reason": event.event_data_dict.get("reason"),
                "rollback_by": event.event_data_dict.get("rollback_by"),
                "timestamp": event.occurred_at
            }
            for event in events
        ]

    async def execute_next_step(self, workflow_id: str):
        """Execute the next pending step in the workflow"""
        from app.models.orm import WorkflowStep

        try:
            # Get next pending step
            result = await self.db.execute(
                select(WorkflowStep)
                .where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.status == "pending"
                )
                .order_by(WorkflowStep.step_order)
                .limit(1)
            )
            step = result.scalar_one_or_none()

            if not step:
                # No more steps - complete workflow
                logger.info("workflow_all_steps_completed", workflow_id=workflow_id)
                await self.mark_completed(workflow_id, {"message": "All steps completed"})
                return

            # Mark step as running
            step.status = "running"
            step.started_at = datetime.now().timestamp()
            await self.db.commit()

            logger.info(
                "step_started",
                workflow_id=workflow_id,
                step_id=step.id,
                step_type=step.step_type,
                step_order=step.step_order
            )

            # Execute based on type
            if step.step_type == "task":
                await self._execute_task_step(step)
            elif step.step_type == "approval":
                await self._execute_approval_step(step)
            else:
                logger.error("unknown_step_type", step_type=step.step_type)
                await self.mark_failed(workflow_id, f"Unknown step type: {step.step_type}")

        except ConcurrentModificationError as e:
            # Handle concurrency errors gracefully
            logger.error(
                "execute_next_step_concurrency_error",
                workflow_id=workflow_id,
                error=str(e),
                message="Concurrent modification detected - marking workflow as failed"
            )
            await self.mark_failed(workflow_id, f"Concurrency error: {str(e)}")

        except Exception as e:
            # Handle any other unexpected errors
            logger.error(
                "execute_next_step_error",
                workflow_id=workflow_id,
                error=str(e),
                exc_info=True
            )
            await self.mark_failed(workflow_id, f"Unexpected error: {str(e)}")

    async def _execute_task_step(self, step):
        """Execute a task step"""
        from app.models.orm import WorkflowStep

        try:
            # Get handler
            handler = TASK_HANDLERS.get(step.task_handler)

            if not handler:
                logger.warning(
                    "task_handler_not_found",
                    handler=step.task_handler,
                    step_id=step.id
                )
                # Mark as completed anyway (handler not required for MVP)
                result = {"status": "skipped", "reason": "handler_not_found"}
            else:
                # Execute handler
                input_data = json.loads(step.task_input) if step.task_input else {}
                result = await handler(input_data)

            # Mark completed
            step.task_output = json.dumps(result)
            step.status = "completed"
            step.completed_at = datetime.now().timestamp()
            await self.db.commit()

            logger.info(
                "task_step_completed",
                workflow_id=step.workflow_id,
                step_id=step.id,
                handler=step.task_handler
            )

            # Publish STEP_COMPLETED event for conversational updates
            if self.event_bus:
                await self.event_bus.publish(
                    EventType.STEP_COMPLETED,
                    {
                        "workflow_id": step.workflow_id,
                        "step_id": step.id,
                        "step_order": step.step_order,
                        "step_type": step.step_type,
                        "handler": step.task_handler,
                        "result": result
                    }
                )

            # Continue to next step
            await self.execute_next_step(step.workflow_id)

        except Exception as e:
            logger.error(
                "task_step_failed",
                workflow_id=step.workflow_id,
                step_id=step.id,
                error=str(e)
            )
            step.status = "failed"
            step.task_output = json.dumps({"error": str(e)})
            await self.db.commit()

            await self.mark_failed(step.workflow_id, f"Task step failed: {str(e)}")

    async def _execute_approval_step(self, step):
        """Execute an approval step by creating an approval request"""
        from app.models.orm import WorkflowStep
        from app.core.approval_service import ApprovalService

        try:
            # CRITICAL: Use SELECT FOR UPDATE to acquire row-level lock
            # This prevents race conditions where two threads try to create approvals simultaneously
            result = await self.db.execute(
                select(WorkflowStep)
                .where(WorkflowStep.id == step.id)
                .with_for_update()
            )
            locked_step = result.scalar_one_or_none()

            if not locked_step:
                logger.error("step_not_found_for_lock", step_id=step.id)
                return

            # IDEMPOTENCY GUARD: Check if approval already exists for this step
            # Now that we have the lock, this check is safe
            if locked_step.approval_id:
                logger.warning(
                    "approval_already_exists_skipping",
                    step_id=locked_step.id,
                    approval_id=locked_step.approval_id,
                    workflow_id=locked_step.workflow_id
                )
                await self.db.commit()  # Release lock
                return  # Don't create duplicate!

            # Get approval service
            approval_service = ApprovalService(self.db, self.event_bus)

            # Parse approval config from step input
            approval_config = json.loads(locked_step.task_input) if locked_step.task_input else {}

            # Create approval request
            workflow = await self.get_workflow(locked_step.workflow_id)
            ui_schema = approval_config.get("ui_schema", {
                "title": "Approval Required",
                "description": "Please approve this workflow step",
                "fields": [],
                "buttons": [
                    {"action": "approve", "label": "Approve", "style": "primary"},
                    {"action": "reject", "label": "Reject", "style": "danger"}
                ]
            })

            timeout_seconds = approval_config.get("timeout_seconds", 3600)

            # Import ApprovalUISchema for validation
            from app.models.schemas import ApprovalUISchema
            ui_schema_obj = ApprovalUISchema(**ui_schema)

            approval = await approval_service.request_approval(
                workflow_id=locked_step.workflow_id,
                ui_schema=ui_schema_obj,
                timeout_seconds=timeout_seconds
            )

            # Link approval to step (critical - prevents duplicates)
            locked_step.approval_id = approval.id
            await self.db.commit()  # Commit releases the lock

            logger.info(
                "approval_step_created",
                workflow_id=locked_step.workflow_id,
                step_id=locked_step.id,
                approval_id=approval.id
            )

            # The approval response will be handled by handle_approval_response

        except Exception as e:
            logger.error(
                "approval_step_failed",
                workflow_id=step.workflow_id,
                step_id=step.id,
                error=str(e)
            )
            step.status = "failed"
            await self.db.commit()
            await self.mark_failed(step.workflow_id, f"Approval step failed: {str(e)}")

    async def handle_approval_response(self, approval_id: str, decision: str, response_data: dict = None):
        """Handle approval response and continue or rollback workflow"""
        from app.models.orm import WorkflowStep

        # Get the step associated with this approval
        result = await self.db.execute(
            select(WorkflowStep).where(WorkflowStep.approval_id == approval_id)
        )
        step = result.scalar_one_or_none()

        if not step:
            logger.warning("approval_step_not_found", approval_id=approval_id)
            return

        if decision == "approve":
            # Mark step as completed
            step.status = "completed"
            step.completed_at = datetime.now().timestamp()
            step.task_output = json.dumps(response_data or {"decision": "approved"})
            await self.db.commit()

            logger.info(
                "approval_step_approved",
                workflow_id=step.workflow_id,
                step_id=step.id,
                approval_id=approval_id
            )

            # Continue to next step
            await self.execute_next_step(step.workflow_id)

        else:  # rejected
            # Mark step as failed
            step.status = "failed"
            step.completed_at = datetime.now().timestamp()
            step.task_output = json.dumps(response_data or {"decision": "rejected"})
            await self.db.commit()

            logger.info(
                "approval_step_rejected",
                workflow_id=step.workflow_id,
                step_id=step.id,
                approval_id=approval_id
            )

            # Rollback completed steps
            await self._rollback_steps(step.workflow_id, step.step_order)

    async def _rollback_steps(self, workflow_id: str, failed_step_order: int):
        """Rollback all completed task steps before the failed approval"""
        from app.models.orm import WorkflowStep

        logger.info(
            "rollback_initiated",
            workflow_id=workflow_id,
            failed_step_order=failed_step_order
        )

        # Get all completed task steps before the failed one
        result = await self.db.execute(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_order < failed_step_order,
                WorkflowStep.status == "completed",
                WorkflowStep.step_type == "task"
            )
            .order_by(WorkflowStep.step_order.desc())  # Reverse order
        )
        steps = result.scalars().all()

        # Execute rollback handlers
        for step in steps:
            rollback_handler = ROLLBACK_HANDLERS.get(step.task_handler)
            if rollback_handler:
                try:
                    output_data = json.loads(step.task_output) if step.task_output else {}
                    await rollback_handler(output_data)
                    logger.info(
                        "step_rolled_back",
                        step_id=step.id,
                        handler=step.task_handler
                    )
                except Exception as e:
                    logger.error(
                        "rollback_failed",
                        step_id=step.id,
                        handler=step.task_handler,
                        error=str(e)
                    )

        # Mark workflow as rejected (user decision, not system failure)
        await self.transition_to(workflow_id, WorkflowState.REJECTED, "Approval rejected - workflow rolled back")

    async def get_workflow_steps(self, workflow_id: str) -> List:
        """Get all steps for a workflow"""
        from app.models.orm import WorkflowStep

        result = await self.db.execute(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.step_order)
        )
        return result.scalars().all()
