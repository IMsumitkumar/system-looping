"""Slack integration API endpoints."""

import json
import structlog
from fastapi import APIRouter, HTTPException, Request, Depends

from app.api.v1.dependencies import get_event_bus, get_slack_adapter
from app.models import get_db
from app.core import ApprovalService
from app.config import verify_callback_token, verify_slack_signature

router = APIRouter(prefix="/slack", tags=["slack"])
logger = structlog.get_logger()


@router.post("/interactive")
async def handle_slack_interaction(
    request: Request,
    db_session = Depends(get_db),
    event_bus = Depends(get_event_bus),
    slack_adapter = Depends(get_slack_adapter),
):
    """
    Handle Slack interactive component callbacks (button clicks and modal submissions).
    Slack sends form-encoded payload with signature verification.
    """
    # Get raw body and headers for signature verification
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    logger.info(
        "slack_interaction_received",
        timestamp=timestamp,
        has_signature=bool(signature),
        body_length=len(body),
    )

    # Verify Slack signature to prevent unauthorized requests
    if not verify_slack_signature(timestamp, body, signature):
        logger.warning("slack_signature_verification_failed")
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # Parse form data
    form_data = await request.form()
    payload_str = form_data.get("payload")

    if not payload_str:
        raise HTTPException(status_code=400, detail="No payload")

    payload = json.loads(payload_str)
    payload_type = payload.get("type")

    logger.info("slack_payload_type", type=payload_type)

    # Route based on payload type
    if payload_type == "block_actions":
        return await handle_button_click(payload, db_session, event_bus, slack_adapter)
    elif payload_type == "view_submission":
        return await handle_modal_submission(payload, db_session, event_bus, slack_adapter)
    else:
        logger.warning("unknown_payload_type", type=payload_type)
        raise HTTPException(status_code=400, detail=f"Unknown payload type: {payload_type}")


async def handle_button_click(payload: dict, db_session, event_bus, slack_adapter):
    """Handle button click - either open modal or process immediately."""
    action = payload["actions"][0]
    callback_token = action["value"]  # format: "approval_id:random:signature"
    action_id = action["action_id"]  # e.g., "approval_approve" or "approval_reject"

    logger.info("slack_button_clicked", action_id=action_id)

    # Verify callback token
    approval_id = verify_callback_token(callback_token)
    if not approval_id:
        logger.warning("callback_token_verification_failed")
        return {"text": "❌ Invalid or expired approval link"}

    # Get approval to check schema
    approval_service = ApprovalService(db_session, event_bus)
    approval = await approval_service.get_approval(approval_id)

    if not approval:
        return {"text": "❌ Approval not found"}

    # Parse schema
    from app.models.schemas import ApprovalUISchema
    schema = ApprovalUISchema(**approval.ui_schema_dict)

    # Determine decision
    decision = "approve" if "approve" in action_id else "reject"

    # Check if modal is needed (has text input fields)
    if slack_adapter.has_text_input_fields(schema):
        logger.info("opening_modal", decision=decision)

        # Get trigger_id from payload
        trigger_id = payload.get("trigger_id")
        if not trigger_id:
            logger.error("no_trigger_id_in_payload")
            return {"text": "❌ Error: Missing trigger_id"}

        # Open modal via Slack API
        modal_view = slack_adapter.render_modal_view(
            schema,
            {"approval_id": approval_id, "token": callback_token},
            decision
        )

        result = await slack_adapter.open_modal(trigger_id, modal_view)

        if not result.get("ok"):
            logger.error("modal_open_failed", error=result.get("error"))
            return {"text": f"❌ Error opening modal: {result.get('error')}"}

        # Return empty response - modal is already shown
        return {}

    # No text fields - process immediately with message state
    response_data = {}
    if "state" in payload and "values" in payload["state"]:
        response_data = extract_field_values(payload["state"]["values"])

    logger.info("processing_approval_without_modal", response_data=response_data)

    try:
        await approval_service.respond_to_approval(approval_id, decision, response_data)

        # Update Slack message with context preserved
        result_blocks = slack_adapter.render_approval_result(decision, response_data, schema)

        return {
            "response_action": "update",
            "message": {
                "text": f"✅ {'Approved' if decision == 'approve' else 'Rejected'}",
                "blocks": result_blocks,
            },
        }
    except ValueError as e:
        logger.error("approval_processing_error", error=str(e))

        # Send error message to conversation
        try:
            from app.models.orm import ConversationHistory
            from sqlalchemy import select

            approval = await approval_service.get_approval(approval_id)
            if approval and approval.workflow_id:
                stmt = select(ConversationHistory).where(
                    ConversationHistory.workflow_id == approval.workflow_id
                )
                result = await db_session.execute(stmt)
                conversation = result.scalar_one_or_none()

                if conversation:
                    error_message = (
                        f"⚠️ **Approval failed**\n\n"
                        f"Error: {str(e)}\n\n"
                        f"Please try again."
                    )
                    conversation.add_message("assistant", error_message)
                    await db_session.commit()
        except Exception as conv_error:
            logger.error("failed_to_send_error_to_conversation", error=str(conv_error), exc_info=True)

        return {"text": f"❌ Error: {str(e)}"}


async def handle_modal_submission(payload: dict, db_session, event_bus, slack_adapter):
    """Handle modal submission - process approval with modal values."""
    # Parse callback_id: "token:decision"
    # Token format: "approval_id:random:signature"
    callback_id = payload["view"]["callback_id"]
    parts = callback_id.rsplit(":", 1)  # Split from right to get decision

    if len(parts) != 2:
        logger.error("invalid_callback_id", callback_id=callback_id, parts_count=len(parts))
        return {"response_action": "errors", "errors": {"base": "Invalid callback ID"}}

    callback_token = parts[0]  # "approval_id:random:signature"
    decision = parts[1]  # "approve" or "reject"

    logger.info("modal_submitted", decision=decision, token_preview=callback_token[:50])

    # Verify callback token
    approval_id = verify_callback_token(callback_token)
    if not approval_id:
        logger.warning("modal_token_verification_failed")
        return {
            "response_action": "errors",
            "errors": {"base": "Invalid or expired approval link"}
        }

    # Extract field values from modal
    modal_values = payload["view"]["state"]["values"]
    response_data = extract_field_values(modal_values)

    logger.info("modal_data_extracted", response_data=response_data)

    # Process approval
    approval_service = ApprovalService(db_session, event_bus)

    try:
        await approval_service.respond_to_approval(approval_id, decision, response_data)

        logger.info("approval_processed_from_modal", approval_id=approval_id)

        # Modal auto-closes on success
        # Update the original message with context preserved
        approval = await approval_service.get_approval(approval_id)
        if approval and approval.slack_message_ts:
            # Parse schema to preserve context
            from app.models.schemas import ApprovalUISchema
            schema = ApprovalUISchema(**approval.ui_schema_dict)

            result_blocks = slack_adapter.render_approval_result(decision, response_data, schema)
            await slack_adapter.update_message(
                approval.slack_message_ts,
                f"✅ {'Approved' if decision == 'approve' else 'Rejected'}",
                result_blocks
            )

        return {"response_action": "clear"}  # Close modal

    except ValueError as e:
        logger.error("modal_approval_error", error=str(e))

        # Send error message to conversation (so user knows what happened)
        try:
            from app.models.orm import ConversationHistory
            from sqlalchemy import select

            # Get approval to find linked workflow
            approval = await approval_service.get_approval(approval_id)
            if approval and approval.workflow_id:
                # Find conversation linked to this workflow
                stmt = select(ConversationHistory).where(
                    ConversationHistory.workflow_id == approval.workflow_id
                )
                result = await db_session.execute(stmt)
                conversation = result.scalar_one_or_none()

                if conversation:
                    error_message = (
                        f"⚠️ **Approval validation failed**\n\n"
                        f"Error: {str(e)}\n\n"
                        f"Please try again and fill in all required fields."
                    )
                    conversation.add_message("assistant", error_message)
                    await db_session.commit()
                    logger.info("error_message_sent_to_conversation", conversation_id=conversation.conversation_id)
        except Exception as conv_error:
            logger.error("failed_to_send_error_to_conversation", error=str(conv_error), exc_info=True)

        # Show error in modal
        return {
            "response_action": "errors",
            "errors": {"base": str(e)}
        }


def extract_field_values(state_values: dict) -> dict:
    """Extract field values from Slack state (works for both messages and modals)."""
    response_data = {}

    for block_id, block_state in state_values.items():
        for field_action_id, value in block_state.items():
            if field_action_id.startswith("field_"):
                field_name = field_action_id.replace("field_", "")
                # Handle different input types
                if "selected_option" in value and value["selected_option"]:
                    response_data[field_name] = value["selected_option"].get("value")
                elif "selected_options" in value and value["selected_options"]:
                    response_data[field_name] = [opt.get("value") for opt in value["selected_options"]]
                elif "value" in value and value["value"]:
                    response_data[field_name] = value["value"]
                elif "selected_date" in value and value["selected_date"]:
                    response_data[field_name] = value["selected_date"]
                elif "selected_time" in value and value["selected_time"]:
                    response_data[field_name] = value["selected_time"]
                elif "selected_date_time" in value and value["selected_date_time"]:
                    response_data[field_name] = value["selected_date_time"]

    return response_data