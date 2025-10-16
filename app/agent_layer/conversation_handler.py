"""
Conversation Event Handler for Autonomous Conversation Updates.

Part of the Generic Agent Integration Layer.
Listens to workflow events and automatically updates conversations
so users see real-time progress without having to ask.

This is framework-agnostic - works with ANY agent implementation.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any, Optional
import structlog

from app.models.orm import ConversationHistory
from app.models.schemas import EventType

logger = structlog.get_logger()


class ConversationEventHandler:
    """
    Listens to workflow events and automatically updates conversations.

    This provides autonomous conversational updates so users don't have to
    manually ask "what's the status?" - they see updates in real-time.

    Key events handled:
    - APPROVAL_REQUESTED: "⏸️ Approval needed! Check Slack."
    - APPROVAL_RECEIVED: "✅ Approved! Executing next task..." or "❌ Rejected."
    - WORKFLOW_COMPLETED: "🎉 Workflow completed successfully!"
    - WORKFLOW_FAILED: "⚠️ Workflow failed: {error}"
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize handler with database session.

        Args:
            db: Async database session
        """
        self.db = db
        logger.info("conversation_event_handler_initialized")

    async def on_approval_requested(self, event_data: Dict[str, Any]):
        """
        Handle APPROVAL_REQUESTED event.

        Automatically adds message to conversation:
        "⏸️ Approval needed! Check Slack to approve."

        Args:
            event_data: Event payload with workflow_id, approval_id, ui_schema
        """
        try:
            workflow_id = event_data.get("workflow_id")
            approval_id = event_data.get("approval_id")
            ui_schema = event_data.get("ui_schema", {})

            if not workflow_id:
                logger.warning("approval_requested_no_workflow_id", event_data=event_data)
                return

            # Find conversation linked to this workflow
            conversation = await self._find_conversation_by_workflow(workflow_id)

            if not conversation:
                logger.debug(
                    "approval_requested_no_conversation",
                    workflow_id=workflow_id,
                    message="No conversation linked to this workflow - skipping update"
                )
                return

            # Extract title from UI schema for better context
            title = ui_schema.get("title", "Approval Required")

            # Add autonomous message
            message = f"⏸️ **{title}**\n\nPlease check Slack to approve this request."

            if approval_id:
                message += f"\n\n_Approval ID: `{approval_id[:12]}...`_"

            conversation.add_message("assistant", message)
            conversation.update_state("waiting_approval")
            await self.db.commit()

            logger.info(
                "conversation_updated_approval_requested",
                conversation_id=conversation.conversation_id,
                workflow_id=workflow_id,
                approval_id=approval_id
            )

        except Exception as e:
            logger.error(
                "approval_requested_handler_failed",
                error=str(e),
                event_data=event_data,
                exc_info=True
            )

    async def on_approval_received(self, event_data: Dict[str, Any]):
        """
        Handle APPROVAL_RECEIVED event.

        Automatically adds message based on decision:
        - Approved: "✅ Approval approved! Executing next task..."
        - Rejected: "❌ Approval rejected. Workflow cancelled."

        Args:
            event_data: Event payload with workflow_id, approval_id, decision
        """
        try:
            workflow_id = event_data.get("workflow_id")
            decision = event_data.get("decision")
            approval_id = event_data.get("approval_id")
            response_data = event_data.get("response_data", {})

            if not workflow_id:
                logger.warning("approval_received_no_workflow_id", event_data=event_data)
                return

            # Find conversation
            conversation = await self._find_conversation_by_workflow(workflow_id)

            if not conversation:
                logger.debug(
                    "approval_received_no_conversation",
                    workflow_id=workflow_id,
                    message="No conversation linked - skipping update"
                )
                return

            # Generate message based on decision
            if decision == "approve":
                message = "✅ **Approval approved!**\n\nExecuting next task..."

                # Add reviewer info if available
                reviewer = response_data.get("reviewer_name") or response_data.get("approver_name")
                if reviewer:
                    message += f"\n\n_Approved by: {reviewer}_"

                conversation.update_state("active")

            else:  # rejected
                message = "❌ **Approval rejected.**\n\nWorkflow has been cancelled."

                # Add rejection reason if available
                comments = response_data.get("comments")
                if comments:
                    message += f"\n\n_Reason: {comments}_"

                conversation.update_state("completed")

            conversation.add_message("assistant", message)
            await self.db.commit()

            logger.info(
                "conversation_updated_approval_received",
                conversation_id=conversation.conversation_id,
                workflow_id=workflow_id,
                decision=decision
            )

        except Exception as e:
            logger.error(
                "approval_received_handler_failed",
                error=str(e),
                event_data=event_data,
                exc_info=True
            )

    async def on_workflow_completed(self, event_data: Dict[str, Any]):
        """
        Handle WORKFLOW_COMPLETED event.

        Automatically adds message:
        "🎉 Workflow completed successfully!"

        Args:
            event_data: Event payload with workflow_id, result
        """
        try:
            workflow_id = event_data.get("workflow_id")
            result = event_data.get("result", {})

            if not workflow_id:
                logger.warning("workflow_completed_no_workflow_id", event_data=event_data)
                return

            # Find conversation
            conversation = await self._find_conversation_by_workflow(workflow_id)

            if not conversation:
                logger.debug(
                    "workflow_completed_no_conversation",
                    workflow_id=workflow_id,
                    message="No conversation linked - skipping update"
                )
                return

            # Generate completion message
            message = "🎉 **Workflow completed successfully!**\n\nAll tasks have been executed."

            # Add result details if available
            if result and isinstance(result, dict) and result.get("message"):
                message += f"\n\n_{result['message']}_"

            conversation.add_message("assistant", message)
            conversation.update_state("completed")
            await self.db.commit()

            logger.info(
                "conversation_updated_workflow_completed",
                conversation_id=conversation.conversation_id,
                workflow_id=workflow_id
            )

        except Exception as e:
            logger.error(
                "workflow_completed_handler_failed",
                error=str(e),
                event_data=event_data,
                exc_info=True
            )

    async def on_workflow_failed(self, event_data: Dict[str, Any]):
        """
        Handle WORKFLOW_FAILED event.

        Automatically adds message:
        "⚠️ Workflow failed: {error}"

        Args:
            event_data: Event payload with workflow_id, error
        """
        try:
            workflow_id = event_data.get("workflow_id")
            error = event_data.get("error", "Unknown error")

            if not workflow_id:
                logger.warning("workflow_failed_no_workflow_id", event_data=event_data)
                return

            # Find conversation
            conversation = await self._find_conversation_by_workflow(workflow_id)

            if not conversation:
                logger.debug(
                    "workflow_failed_no_conversation",
                    workflow_id=workflow_id,
                    message="No conversation linked - skipping update"
                )
                return

            # Generate error message
            message = f"⚠️ **Workflow failed**\n\n{error}\n\nYou can ask me to retry the workflow."

            conversation.add_message("assistant", message)
            conversation.update_state("error")
            await self.db.commit()

            logger.info(
                "conversation_updated_workflow_failed",
                conversation_id=conversation.conversation_id,
                workflow_id=workflow_id,
                error=error
            )

        except Exception as e:
            logger.error(
                "workflow_failed_handler_failed",
                error=str(e),
                event_data=event_data,
                exc_info=True
            )

    async def on_step_completed(self, event_data: Dict[str, Any]):
        """
        Handle custom STEP_COMPLETED event (for task steps).

        Automatically adds message:
        "✅ Task completed: {task_name}"

        Args:
            event_data: Event payload with workflow_id, step_order, step_type, handler
        """
        try:
            workflow_id = event_data.get("workflow_id")
            step_order = event_data.get("step_order")
            step_type = event_data.get("step_type")
            handler = event_data.get("handler", "Task")

            if not workflow_id:
                logger.warning("step_completed_no_workflow_id", event_data=event_data)
                return

            # Only update for task steps (not approval steps)
            if step_type != "task":
                return

            # Find conversation
            conversation = await self._find_conversation_by_workflow(workflow_id)

            if not conversation:
                logger.debug(
                    "step_completed_no_conversation",
                    workflow_id=workflow_id,
                    message="No conversation linked - skipping update"
                )
                return

            # Generate message
            task_name = handler.replace("_", " ").title()
            message = f"✅ **Task {step_order + 1} completed:** {task_name}"

            conversation.add_message("assistant", message)
            await self.db.commit()

            logger.info(
                "conversation_updated_step_completed",
                conversation_id=conversation.conversation_id,
                workflow_id=workflow_id,
                step_order=step_order
            )

        except Exception as e:
            logger.error(
                "step_completed_handler_failed",
                error=str(e),
                event_data=event_data,
                exc_info=True
            )

    # ========================================================================
    # Helper Methods
    # ========================================================================

    async def _find_conversation_by_workflow(
        self,
        workflow_id: str
    ) -> Optional[ConversationHistory]:
        """
        Find conversation linked to a workflow.

        Args:
            workflow_id: The workflow ID

        Returns:
            ConversationHistory or None if not found
        """
        result = await self.db.execute(
            select(ConversationHistory).where(
                ConversationHistory.workflow_id == workflow_id
            )
        )
        return result.scalar_one_or_none()
