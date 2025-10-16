"""Event handlers for workflow orchestration."""

import structlog
from app.core import WorkflowEngine, ApprovalService, EventBus
from app.models import Database
from app.models.schemas import (
    EventType,
    WorkflowState,
    ApprovalUISchema,
)
from app.adapters import SlackAdapter

logger = structlog.get_logger()


def register_event_handlers(event_bus: EventBus, db: Database, slack_adapter: SlackAdapter):
    """
    Register handlers for workflow events.

    Args:
        event_bus: The event bus instance
        db: Database instance for session management
        slack_adapter: Slack adapter for notifications
    """

    async def handle_workflow_started(data: dict):
        """
        When a workflow starts, handle legacy single-step workflows.
        For multi-step workflows, the workflow engine handles execution via execute_next_step().
        """
        logger.info("handling_workflow_started", data=data)

        async with db.session() as session:
            engine = WorkflowEngine(session, event_bus)
            approval_service = ApprovalService(session, event_bus)

            workflow_id = data["workflow_id"]
            context = data["context"]
            approval_timeout = data.get("approval_timeout_seconds", 3600)

            # Check if this is a multi-step workflow
            workflow = await engine.get_workflow(workflow_id)
            steps = await engine.get_workflow_steps(workflow_id)

            if steps and len(steps) > 0:
                # Multi-step workflow - execution is handled by execute_next_step()
                # which was already called in create_workflow()
                logger.info("multi_step_workflow_detected", workflow_id=workflow_id, num_steps=len(steps))
                return

            # Legacy single-step workflow handling
            # Transition to RUNNING
            await engine.transition_to(workflow_id, WorkflowState.RUNNING, "Workflow started")

            # Check if approval is required
            if "_approval_schema" in context:
                # Transition to WAITING_APPROVAL
                await engine.transition_to(workflow_id, WorkflowState.WAITING_APPROVAL, "Requesting approval")

                # Create the actual approval request
                ui_schema = ApprovalUISchema(**context["_approval_schema"])
                timeout = context.get("_approval_timeout", approval_timeout)
                await approval_service.request_approval(workflow_id, ui_schema, timeout)

                logger.info(
                    "approval_request_created",
                    workflow_id=workflow_id,
                    timeout_seconds=timeout,
                )
            else:
                # No approval needed, complete immediately
                logger.info("no_approval_needed", workflow_id=workflow_id)
                await engine.mark_completed(workflow_id, {"auto_approved": True})

    async def handle_approval_requested(data: dict):
        """When approval is requested, send to Slack"""
        logger.info("handling_approval_requested", data=data)

        approval_id = data["approval_id"]
        ui_schema_dict = data["ui_schema"]
        callback_token = data["callback_token"]

        # Convert dict back to Pydantic model
        ui_schema = ApprovalUISchema(**ui_schema_dict)

        # Send to Slack
        try:
            result = await slack_adapter.send_approval_request(ui_schema, approval_id, callback_token)

            if result.get("ok") and result.get("ts"):
                # Store Slack message timestamp for later updates
                async with db.session() as session:
                    approval_service = ApprovalService(session, event_bus)
                    await approval_service.update_slack_message_ts(approval_id, result["ts"])

                logger.info("slack_message_sent", approval_id=approval_id, ts=result["ts"])
        except Exception as e:
            logger.error("slack_send_failed", approval_id=approval_id, error=str(e))

    async def handle_approval_received(data: dict):
        """
        When approval is received, update workflow state.

        ARCHITECTURAL TRADE-OFF:
        This handler has conditional logic based on whether approval_service already
        processed the approval synchronously. This creates tight coupling between
        the approval service and event handler.

        For multi-step workflows:
        - approval_service.respond_to_approval() directly calls engine.handle_approval_response()
        - This handler checks workflow type and skips processing to avoid duplicates

        Better design would be:
        1. Split into two events: APPROVAL_RESPONSE_RECORDED + WORKFLOW_APPROVAL_COMPLETED
        2. Use explicit flag in event data: "workflow_transition_needed: bool"
        3. Make event handlers pure (no conditional logic based on caller)

        Current approach chosen for MVP velocity - works correctly but reduces
        event handler purity. Worth refactoring in production for better maintainability.

        This prevents duplicate execute_next_step() calls which cause:
        - Duplicate approval requests
        - Concurrency errors (version conflicts)
        - Race conditions
        """
        logger.info("handling_approval_received", data=data)

        workflow_id = data["workflow_id"]
        decision = data["decision"]
        response_data = data.get("response_data", {})
        approval_id = data.get("approval_id")

        async with db.session() as session:
            engine = WorkflowEngine(session, event_bus)

            # Check if this is a multi-step workflow
            steps = await engine.get_workflow_steps(workflow_id)

            if steps and len(steps) > 0:
                # Multi-step workflow - approval response ALREADY handled by approval_service
                # which calls engine.handle_approval_response() at line 303 of approval_service.py
                # DO NOT call handle_approval_response() again here - it causes duplicates!
                logger.info(
                    "multi_step_approval_already_handled",
                    workflow_id=workflow_id,
                    approval_id=approval_id,
                    decision=decision,
                    num_steps=len(steps),
                    message="Approval already processed by approval_service - skipping event handler"
                )
                return  # EXIT EARLY - critical to prevent duplicate processing!

            # Legacy single-step workflow handling
            if decision == "approve":
                await engine.transition_to(workflow_id, WorkflowState.APPROVED, "Approval received")
                await engine.mark_completed(workflow_id, {"approval": response_data})
            else:
                rejection_reason = response_data.get("rejection_reason", "No reason provided")
                reviewer_name = response_data.get("reviewer_name", "Unknown")
                message = f"Rejected by {reviewer_name}: {rejection_reason}"
                await engine.transition_to(workflow_id, WorkflowState.REJECTED, message)

    async def handle_approval_timeout(data: dict):
        """When approval times out, transition to TIMEOUT terminal state"""
        logger.info("handling_approval_timeout", data=data)

        workflow_id = data["workflow_id"]
        approval_id = data.get("approval_id", "unknown")

        async with db.session() as session:
            engine = WorkflowEngine(session, event_bus)
            # TIMEOUT is a terminal state - human didn't respond in time
            message = f"Approval request {approval_id} timed out - no human response received"
            await engine.transition_to(workflow_id, WorkflowState.TIMEOUT, message)

    async def handle_approval_retry(data: dict):
        """Handle retry event after timeout"""
        logger.info("handling_approval_retry", data=data)

        workflow_id = data["workflow_id"]
        retry_count = data.get("retry_count", 1)

        async with db.session() as session:
            engine = WorkflowEngine(session, event_bus)
            approval_service = ApprovalService(session, event_bus)

            # Re-request approval
            workflow = await engine.get_workflow(workflow_id)
            context = workflow.context_dict

            if "_approval_schema" in context:
                # Transition to WAITING_APPROVAL
                await engine.transition_to(
                    workflow_id,
                    WorkflowState.WAITING_APPROVAL,
                    f"Retry {retry_count} - requesting approval again"
                )

                # Create new approval request
                ui_schema = ApprovalUISchema(**context["_approval_schema"])
                timeout = context.get("_approval_timeout", 3600)
                await approval_service.request_approval(workflow_id, ui_schema, timeout)

                logger.info(
                    "approval_retry_request_sent",
                    workflow_id=workflow_id,
                    retry_count=retry_count
                )

    # Subscribe handlers to events
    event_bus.subscribe(EventType.WORKFLOW_STARTED, handle_workflow_started)
    event_bus.subscribe(EventType.APPROVAL_REQUESTED, handle_approval_requested)
    event_bus.subscribe(EventType.APPROVAL_RECEIVED, handle_approval_received)
    event_bus.subscribe(EventType.APPROVAL_TIMEOUT, handle_approval_timeout)
    event_bus.subscribe(EventType.APPROVAL_RETRY, handle_approval_retry)



    # ========================================================================
    # Conversation Event Handlers (Agent Layer Feature)
    # ========================================================================
    from app.agent_layer import ConversationEventHandler

    # Create conversation handler instance (will be created per event)
    async def create_conversation_handler_and_handle(event_type: str, event_data: dict):
        """
        Factory function that creates a ConversationEventHandler with DB session
        and calls the appropriate method based on event type.
        """
        async with db.session() as session:
            handler = ConversationEventHandler(session)

            if event_type == EventType.APPROVAL_REQUESTED.value:
                await handler.on_approval_requested(event_data)
            elif event_type == EventType.APPROVAL_RECEIVED.value:
                await handler.on_approval_received(event_data)
            elif event_type == EventType.WORKFLOW_COMPLETED.value:
                await handler.on_workflow_completed(event_data)
            elif event_type == EventType.WORKFLOW_FAILED.value:
                await handler.on_workflow_failed(event_data)
            elif event_type == EventType.STEP_COMPLETED.value:
                await handler.on_step_completed(event_data)

    # Register conversation event handlers
    async def handle_approval_requested_conv(data):
        await create_conversation_handler_and_handle(
            EventType.APPROVAL_REQUESTED.value, data
        )

    async def handle_approval_received_conv(data):
        await create_conversation_handler_and_handle(
            EventType.APPROVAL_RECEIVED.value, data
        )

    async def handle_workflow_completed_conv(data):
        await create_conversation_handler_and_handle(
            EventType.WORKFLOW_COMPLETED.value, data
        )

    async def handle_workflow_failed_conv(data):
        await create_conversation_handler_and_handle(
            EventType.WORKFLOW_FAILED.value, data
        )

    async def handle_step_completed_conv(data):
        await create_conversation_handler_and_handle(
            EventType.STEP_COMPLETED.value, data
        )

    event_bus.subscribe(EventType.APPROVAL_REQUESTED, handle_approval_requested_conv)
    event_bus.subscribe(EventType.APPROVAL_RECEIVED, handle_approval_received_conv)
    event_bus.subscribe(EventType.WORKFLOW_COMPLETED, handle_workflow_completed_conv)
    event_bus.subscribe(EventType.WORKFLOW_FAILED, handle_workflow_failed_conv)
    event_bus.subscribe(EventType.STEP_COMPLETED, handle_step_completed_conv)

    logger.info(
        "conversation_event_handlers_registered",
        handlers=[
            "APPROVAL_REQUESTED",
            "APPROVAL_RECEIVED",
            "WORKFLOW_COMPLETED",
            "WORKFLOW_FAILED",
            "STEP_COMPLETED",
        ],
    )