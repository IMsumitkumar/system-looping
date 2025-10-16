"""
Approval service for managing human-in-the-loop approvals.
Handles creation, response, and timeout of approval requests.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from typing import List
import json
import structlog

from app.models.orm import ApprovalRequest, Workflow, WorkflowEvent
from app.models.schemas import ApprovalUISchema, ApprovalStatus, EventType, WorkflowState
from app.config.security import generate_callback_token

logger = structlog.get_logger()


class ApprovalService:
    """
    Manages approval request lifecycle.
    """

    def __init__(self, db: AsyncSession, event_bus=None):
        self.db = db
        self.event_bus = event_bus

    async def request_approval(
        self,
        workflow_id: str,
        ui_schema: ApprovalUISchema,
        timeout_seconds: int = 3600,
    ) -> ApprovalRequest:
        """
        Create an approval request for a workflow.

        Args:
            workflow_id: The workflow requiring approval
            ui_schema: The dynamic UI schema for the approval form
            timeout_seconds: How long before approval times out

        Returns:
            Created approval request
        """
        # Generate secure callback token
        approval_id = None
        callback_token = None

        # Create approval request
        approval = ApprovalRequest(
            workflow_id=workflow_id,
            status=ApprovalStatus.PENDING.value,
            ui_schema=json.dumps(ui_schema.model_dump()),
            expires_at=(datetime.now() + timedelta(seconds=timeout_seconds)).timestamp(),
            callback_token="temp",  # Will be updated with real token
        )

        self.db.add(approval)
        await self.db.flush()

        # Now generate token with the real approval ID
        callback_token = generate_callback_token(approval.id)
        approval.callback_token = callback_token

        await self.db.commit()
        await self.db.refresh(approval)

        logger.info(
            "approval_requested",
            approval_id=approval.id,
            workflow_id=workflow_id,
            expires_at=approval.expires_at,
            timeout_seconds=timeout_seconds,
        )

        # Record event in workflow event log (so it appears in event history)
        event = WorkflowEvent(
            workflow_id=workflow_id,
            event_type=EventType.APPROVAL_REQUESTED.value,
            event_data=json.dumps({
                "approval_id": approval.id,
                "workflow_id": workflow_id,
                "ui_schema": ui_schema.model_dump(),
                "expires_at": approval.expires_at,
                "callback_token": callback_token,
            }),
            occurred_at=datetime.now().timestamp(),
        )
        self.db.add(event)
        await self.db.flush()

        # Publish event to event bus
        if self.event_bus:
            await self.event_bus.publish(
                EventType.APPROVAL_REQUESTED,
                {
                    "approval_id": approval.id,
                    "workflow_id": workflow_id,
                    "ui_schema": ui_schema.model_dump(),
                    "expires_at": approval.expires_at,
                    "callback_token": callback_token,
                },
            )

        return approval

    async def get_approval(self, approval_id: str) -> ApprovalRequest:
        """Get approval request by ID"""
        result = await self.db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval_id))
        approval = result.scalar_one_or_none()

        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        return approval

    async def get_approval_by_token(self, callback_token: str) -> ApprovalRequest:
        """Get approval request by callback token"""
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.callback_token == callback_token)
        )
        approval = result.scalar_one_or_none()

        if not approval:
            raise ValueError("Invalid callback token")

        return approval

    async def respond_to_approval(
        self,
        approval_id: str,
        decision: str,
        response_data: dict,
    ) -> ApprovalRequest:
        """
        Process approval response (approve/reject).

        Uses SELECT FOR UPDATE row-level locking to prevent race conditions
        with concurrent approval responses or timeout manager.

        Args:
            approval_id: The approval request ID
            decision: 'approve' or 'reject'
            response_data: Form field values from the user

        Returns:
            Updated approval request

        Raises:
            ValueError: If approval not found, expired, or already processed
        """
        # Get approval with row-level lock to prevent concurrent modifications
        # with_for_update() will acquire the necessary locks
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
        approval = result.scalar_one_or_none()

        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        # CRITICAL: Check expiry FIRST before status
        # This prevents race with timeout manager
        if approval.is_expired():
            logger.warning(
                "approval_response_rejected_expired",
                approval_id=approval_id,
                workflow_id=approval.workflow_id,
                expires_at=approval.expires_at,
            )
            raise ValueError("Approval has expired")

        # Now check if still pending
        if approval.status != ApprovalStatus.PENDING.value:
            logger.warning(
                "approval_response_rejected_already_processed",
                approval_id=approval_id,
                workflow_id=approval.workflow_id,
                current_status=approval.status,
            )
            raise ValueError(f"Approval already {approval.status}")

        # VALIDATION: Check response against UI schema
        ui_schema_dict = approval.ui_schema_dict
        if ui_schema_dict and 'fields' in ui_schema_dict:
            # Validate required fields
            for field in ui_schema_dict['fields']:
                if field.get('required', False):
                    field_name = field['name']
                    if field_name not in response_data or not response_data[field_name]:
                        logger.warning(
                            "validation_required_field_missing",
                            approval_id=approval_id,
                            field_name=field_name
                        )
                        raise ValueError(
                            f"Required field '{field_name}' missing in response"
                        )

            # Validate field types (basic validation)
            for field in ui_schema_dict['fields']:
                field_name = field['name']
                if field_name in response_data:
                    value = response_data[field_name]
                    field_type = field['type']

                    if field_type == 'select' and field.get('options'):
                        # Extract valid values from options (options can be dicts with 'value' key or simple strings)
                        valid_values = []
                        for opt in field['options']:
                            if isinstance(opt, dict):
                                valid_values.append(opt.get('value', opt.get('label')))
                            else:
                                valid_values.append(opt)

                        if value not in valid_values:
                            logger.warning(
                                "validation_invalid_select_value",
                                approval_id=approval_id,
                                field_name=field_name,
                                value=value,
                                allowed_options=valid_values
                            )
                            raise ValueError(
                                f"Invalid value '{value}' for field '{field_name}'. "
                                f"Must be one of: {valid_values}"
                            )

            logger.info(
                "response_validation_passed",
                approval_id=approval_id,
                fields_validated=len(ui_schema_dict.get('fields', []))
            )

        # Update approval
        approval.status = ApprovalStatus.APPROVED.value if decision == "approve" else ApprovalStatus.REJECTED.value
        approval.response_data = json.dumps(response_data)
        approval.responded_at = datetime.now().timestamp()

        await self.db.commit()

        logger.info(
            "approval_received",
            approval_id=approval_id,
            workflow_id=approval.workflow_id,
            decision=decision,
            response_data=response_data,
            status=approval.status,
        )

        # Update Slack message if timestamp exists
        if approval.slack_message_ts:
            try:
                from app.adapters.slack import SlackAdapter

                slack = SlackAdapter()
                if slack.is_configured():
                    result_blocks = slack.render_approval_result(decision, response_data)
                    await slack.update_message(
                        message_ts=approval.slack_message_ts,
                        text=f"{'✅ Approved' if decision == 'approve' else '❌ Rejected'}",
                        blocks=result_blocks
                    )
                    logger.info(
                        "slack_message_updated",
                        approval_id=approval_id,
                        decision=decision,
                        message_ts=approval.slack_message_ts
                    )
            except Exception as e:
                # Don't fail approval if Slack update fails
                logger.error(
                    "slack_update_failed",
                    approval_id=approval_id,
                    error=str(e),
                    exc_info=True
                )

        # Publish event
        if self.event_bus:
            await self.event_bus.publish(
                EventType.APPROVAL_RECEIVED,
                {
                    "approval_id": approval_id,
                    "workflow_id": approval.workflow_id,
                    "decision": decision,
                    "response_data": response_data,
                },
            )

        # If this approval is part of a multi-step workflow, notify the engine
        from app.models.orm import WorkflowStep
        result = await self.db.execute(
            select(WorkflowStep).where(WorkflowStep.approval_id == approval_id)
        )
        step = result.scalar_one_or_none()

        if step:
            # This is a multi-step workflow - let engine handle continuation
            from app.core.workflow_engine import WorkflowEngine
            engine = WorkflowEngine(self.db, self.event_bus)
            await engine.handle_approval_response(approval_id, decision, response_data)
            return approval

        # For simple (non-multi-step) workflows, update workflow state on rejection
        if decision == "reject":
            workflow_result = await self.db.execute(
                select(Workflow).where(Workflow.id == approval.workflow_id)
            )
            workflow = workflow_result.scalar_one_or_none()

            if workflow:
                workflow.state = WorkflowState.REJECTED.value
                workflow.completed_at = datetime.now().timestamp()
                await self.db.commit()

                logger.info(
                    "workflow_rejected_simple",
                    workflow_id=workflow.id,
                    approval_id=approval_id,
                    reason="User rejected approval"
                )

        return approval

    async def mark_timeout(self, approval_id: str) -> ApprovalRequest:
        """
        Mark approval as timed out.

        Uses SELECT FOR UPDATE row-level locking to prevent race conditions
        with concurrent approval responses.

        Args:
            approval_id: The approval request ID

        Returns:
            Updated approval request (or unchanged if already processed)
        """
        # Get approval with row-level lock to prevent concurrent modifications
        # with_for_update() will acquire the necessary locks
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
        approval = result.scalar_one_or_none()

        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        # Only timeout if still pending
        if approval.status != ApprovalStatus.PENDING.value:
            logger.info(
                "timeout_skipped_already_processed",
                approval_id=approval_id,
                workflow_id=approval.workflow_id,
                current_status=approval.status,
            )
            return approval

        approval.status = ApprovalStatus.TIMEOUT.value
        approval.responded_at = datetime.now().timestamp()

        await self.db.commit()

        logger.warning(
            "approval_timeout",
            approval_id=approval_id,
            workflow_id=approval.workflow_id,
            expired_at=approval.expires_at,
        )

        # Publish event
        if self.event_bus:
            await self.event_bus.publish(
                EventType.APPROVAL_TIMEOUT,
                {
                    "approval_id": approval_id,
                    "workflow_id": approval.workflow_id,
                },
            )

        return approval

    async def get_pending_approvals(self) -> List[ApprovalRequest]:
        """Get all pending approval requests"""
        result = await self.db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING.value)
            .order_by(ApprovalRequest.requested_at)
        )
        return result.scalars().all()

    async def get_expired_approvals(self) -> List[ApprovalRequest]:
        """Get all expired but still pending approvals"""
        now = datetime.now().timestamp()
        result = await self.db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.PENDING.value)
            .where(ApprovalRequest.expires_at < now)
        )
        return result.scalars().all()

    async def update_slack_message_ts(self, approval_id: str, message_ts: str):
        """Update the Slack message timestamp for later updates"""
        approval = await self.get_approval(approval_id)
        approval.slack_message_ts = message_ts
        await self.db.commit()

    async def rollback_approval(self, approval_id: str) -> ApprovalRequest:
        """
        Rollback a rejected approval back to pending state.
        Allows users to correct mistaken rejections.

        Args:
            approval_id: The approval request ID

        Returns:
            Updated approval request

        Raises:
            ValueError: If approval not found or not in REJECTED state
        """
        # Get approval with row-level lock
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()
        )
        approval = result.scalar_one_or_none()

        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        # Only allow rollback for REJECTED approvals
        if approval.status != ApprovalStatus.REJECTED.value:
            raise ValueError(f"Can only rollback rejected approvals. Current status: {approval.status}")

        # Check if expired
        if approval.is_expired():
            raise ValueError("Cannot rollback expired approval")

        # Reset approval to pending state
        approval.status = ApprovalStatus.PENDING.value
        approval.response_data = None
        approval.responded_at = None

        await self.db.commit()

        logger.info(
            "approval_rolled_back",
            approval_id=approval_id,
            workflow_id=approval.workflow_id,
        )

        # Reset workflow state back to appropriate state
        workflow_result = await self.db.execute(
            select(Workflow).where(Workflow.id == approval.workflow_id)
        )
        workflow = workflow_result.scalar_one_or_none()

        if workflow:
            # Check if this is a multi-step workflow
            from app.models.orm import WorkflowStep
            step_result = await self.db.execute(
                select(WorkflowStep).where(WorkflowStep.approval_id == approval_id)
            )
            step = step_result.scalar_one_or_none()

            if step:
                # Multi-step workflow: set back to RUNNING and reset the step
                workflow.state = WorkflowState.RUNNING.value
                workflow.completed_at = None
                step.status = "running"
                step.task_output = None
                step.completed_at = None
            else:
                # Simple workflow: set back to WAITING_APPROVAL
                workflow.state = WorkflowState.WAITING_APPROVAL.value
                workflow.completed_at = None

            await self.db.commit()

            logger.info(
                "workflow_state_reset_after_rollback",
                workflow_id=workflow.id,
                new_state=workflow.state,
                approval_id=approval_id
            )

        # Publish event
        if self.event_bus:
            await self.event_bus.publish(
                EventType.APPROVAL_REQUESTED,
                {
                    "approval_id": approval_id,
                    "workflow_id": approval.workflow_id,
                    "action": "rollback",
                },
            )

        return approval
