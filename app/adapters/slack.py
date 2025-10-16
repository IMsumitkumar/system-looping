"""
Slack integration with Block Kit rendering.
Sends approval requests to Slack with circuit breaker protection.
"""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pybreaker import CircuitBreaker, CircuitBreakerError
import structlog

from app.models.schemas import ApprovalUISchema
from app.config.settings import settings

logger = structlog.get_logger()

# Circuit breaker for Slack API to prevent cascading failures
# pybreaker parameters:
# - fail_max: Number of failures before opening the circuit
# - reset_timeout: Seconds before attempting to close an open circuit
# - exclude: Exceptions to exclude from failure counting
slack_breaker = CircuitBreaker(
    fail_max=settings.circuit_breaker_fail_max,
    reset_timeout=settings.circuit_breaker_timeout_duration,
    name="slack_api"
)


class SlackAdapter:
    """
    Adapter for sending approval requests to Slack using Block Kit.
    Protected by circuit breaker to handle Slack API failures gracefully.
    """

    def __init__(self, bot_token: str = None, channel_id: str = None):
        self.bot_token = bot_token or settings.slack_bot_token
        self.channel_id = channel_id or settings.slack_channel_id

        if not self.bot_token:
            logger.warning("slack_not_configured", message="SLACK_BOT_TOKEN not set")

    def is_configured(self) -> bool:
        """Check if Slack is properly configured"""
        return bool(self.bot_token and self.channel_id)

    def render_blocks(self, schema: ApprovalUISchema, callback_data: dict) -> list:
        """
        Convert ApprovalUISchema to Slack Block Kit blocks.

        Args:
            schema: The approval UI schema
            callback_data: Data to include in button values (approval_id, token)

        Returns:
            List of Slack blocks
        """
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": schema.title}},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": schema.description},
            },
            {"type": "divider"},
        ]

        for field in schema.fields:
            if field.type == "select":
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{field.label}*" + (" (required)" if field.required else ""),
                        },
                        "accessory": {
                            "type": "static_select",
                            "action_id": f"field_{field.name}",
                            "placeholder": {"type": "plain_text", "text": field.placeholder or "Select an option"},
                            "options": [
                                {"text": {"type": "plain_text", "text": opt.get("label", opt.get("value", opt))},
                                 "value": opt.get("value", opt)}
                                for opt in (field.options or [])
                            ],
                        },
                    }
                )
            elif field.type == "multiselect":
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{field.label}*" + (" (required)" if field.required else ""),
                        },
                        "accessory": {
                            "type": "multi_static_select",
                            "action_id": f"field_{field.name}",
                            "placeholder": {"type": "plain_text", "text": field.placeholder or field.label},
                            "options": [
                                {"text": {"type": "plain_text", "text": opt.get("label", opt.get("value", opt))},
                                 "value": opt.get("value", opt)}
                                for opt in (field.options or [])
                            ],
                        },
                    }
                )
            elif field.type == "checkbox":
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{field.label}*" + (" (required)" if field.required else ""),
                        },
                        "accessory": {
                            "type": "checkboxes",
                            "action_id": f"field_{field.name}",
                            "options": [
                                {"text": {"type": "plain_text", "text": opt.get("label", opt.get("value", opt))},
                                 "value": opt.get("value", opt)}
                                for opt in (field.options or [])
                            ],
                        },
                    }
                )
            elif field.type == "radio":
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{field.label}*" + (" (required)" if field.required else ""),
                        },
                        "accessory": {
                            "type": "radio_buttons",
                            "action_id": f"field_{field.name}",
                            "options": [
                                {"text": {"type": "plain_text", "text": opt.get("label", opt.get("value", opt))},
                                 "value": opt.get("value", opt)}
                                for opt in (field.options or [])
                            ],
                        },
                    }
                )
            elif field.type == "date":
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{field.label}*" + (" (required)" if field.required else ""),
                        },
                        "accessory": {
                            "type": "datepicker",
                            "action_id": f"field_{field.name}",
                            "placeholder": {"type": "plain_text", "text": field.placeholder or "Select a date"}
                        },
                    }
                )
            elif field.type == "datetime":
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{field.label}*" + (" (required)" if field.required else ""),
                        },
                        "accessory": {
                            "type": "datetimepicker",
                            "action_id": f"field_{field.name}",
                        },
                    }
                )
            elif field.type == "hidden":
                pass

        blocks.append({"type": "divider"})

        button_elements = []
        for btn in schema.buttons:
            button_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn.label},
                    "style": btn.style if btn.style in ["primary", "danger"] else None,
                    "action_id": f"approval_{btn.action}",
                    # Use token directly - it already contains approval_id:random:signature
                    "value": callback_data['token'],
                }
            )

        if button_elements:
            blocks.append({"type": "actions", "elements": button_elements})

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Or respond via web: {settings.callback_base_url}/approval/{callback_data['approval_id']}",
                    }
                ],
            }
        )

        return blocks

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    @slack_breaker
    async def send_approval_request(
        self,
        schema: ApprovalUISchema,
        approval_id: str,
        callback_token: str,
    ) -> dict:
        """
        Send approval request to Slack with circuit breaker protection.

        Args:
            schema: The approval UI schema
            approval_id: The approval request ID
            callback_token: The secure callback token

        Returns:
            Slack API response with message timestamp

        Raises:
            CircuitBreakerError: If circuit breaker is open (too many failures)
        """
        if not self.is_configured():
            logger.warning("slack_send_skipped", reason="Slack not configured")
            return {"ok": False, "error": "slack_not_configured"}

        try:
            callback_data = {"approval_id": approval_id, "token": callback_token}

            blocks = self.render_blocks(schema, callback_data)

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json"},
                    json={"channel": self.channel_id, "blocks": blocks, "text": schema.title},
                )

                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    logger.error("slack_api_error", error=data.get("error"))
                    raise Exception(f"Slack API error: {data.get('error')}")

                logger.info(
                    "slack_message_sent",
                    approval_id=approval_id,
                    channel=self.channel_id,
                    ts=data.get("ts"),
                )

                return data
        except CircuitBreakerError:
            logger.error(
                "slack_circuit_breaker_open",
                approval_id=approval_id,
                message="Circuit breaker is open - too many Slack API failures"
            )
            return {"ok": False, "error": "circuit_breaker_open"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    @slack_breaker
    async def open_modal(self, trigger_id: str, view: dict) -> dict:
        """
        Open a Slack modal using views.open API.

        Args:
            trigger_id: The trigger_id from the interaction payload
            view: The modal view JSON

        Returns:
            Slack API response
        """
        if not self.is_configured():
            return {"ok": False, "error": "slack_not_configured"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://slack.com/api/views.open",
                    headers={
                        "Authorization": f"Bearer {self.bot_token}",
                        "Content-Type": "application/json"
                    },
                    json={"trigger_id": trigger_id, "view": view},
                )

                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    logger.error("slack_modal_open_error", error=data.get("error"))
                    raise Exception(f"Slack API error: {data.get('error')}")

                logger.info("slack_modal_opened", view_id=data.get("view", {}).get("id"))
                return data

        except CircuitBreakerError:
            logger.error("slack_circuit_breaker_open_modal")
            return {"ok": False, "error": "circuit_breaker_open"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    @slack_breaker
    async def update_message(
        self,
        message_ts: str,
        text: str,
        blocks: list = None,
    ) -> dict:
        """
        Update a Slack message with circuit breaker protection.

        Args:
            message_ts: Timestamp of message to update
            text: New message text
            blocks: New blocks (optional)

        Returns:
            Slack API response
        """
        if not self.is_configured():
            return {"ok": False, "error": "slack_not_configured"}

        try:
            payload = {"channel": self.channel_id, "ts": message_ts, "text": text}

            if blocks:
                payload["blocks"] = blocks

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://slack.com/api/chat.update",
                    headers={"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json"},
                    json=payload,
                )

                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    logger.error("slack_update_error", error=data.get("error"))
                    raise Exception(f"Slack API error: {data.get('error')}")

                logger.info("slack_message_updated", ts=message_ts)

                return data
        except CircuitBreakerError:
            logger.error(
                "slack_circuit_breaker_open_update",
                message_ts=message_ts,
                message="Circuit breaker is open - cannot update Slack message"
            )
            return {"ok": False, "error": "circuit_breaker_open"}

    def has_text_input_fields(self, schema: ApprovalUISchema) -> bool:
        """Check if schema has fields that require text input (need modal)."""
        text_input_types = ["text", "textarea", "email", "url", "tel", "number", "password"]
        return any(field.type in text_input_types for field in schema.fields)

    def render_modal_view(
        self,
        schema: ApprovalUISchema,
        callback_data: dict,
        decision: str
    ) -> dict:
        """
        Render Slack modal for text input fields.

        Args:
            schema: The approval UI schema
            callback_data: Data to include in callback_id (approval_id, token, decision)
            decision: 'approve' or 'reject'

        Returns:
            Slack modal view JSON
        """
        blocks = []
        text_input_types = ["text", "textarea", "email", "url", "tel", "number", "password"]

        for field in schema.fields:
            if field.type in text_input_types:
                if field.type == "textarea":
                    element = {
                        "type": "plain_text_input",
                        "action_id": f"field_{field.name}",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": field.placeholder or field.label}
                    }
                else:
                    element = {
                        "type": "plain_text_input",
                        "action_id": f"field_{field.name}",
                        "placeholder": {"type": "plain_text", "text": field.placeholder or field.label}
                    }

                blocks.append({
                    "type": "input",
                    "block_id": f"block_{field.name}",
                    "label": {"type": "plain_text", "text": field.label},
                    "element": element,
                    "optional": not field.required
                })

        # Encode callback data in callback_id (format: token:decision)
        # Token already contains approval_id, so don't duplicate it
        callback_id = f"{callback_data['token']}:{decision}"

        emoji = "✅" if decision == "approve" else "❌"
        title = f"{emoji} {decision.title()}"

        return {
            "type": "modal",
            "callback_id": callback_id,
            "title": {"type": "plain_text", "text": title[:24]},  # Max 24 chars
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": blocks
        }

    def render_approval_result(self, decision: str, response_data: dict, schema: ApprovalUISchema = None) -> list:
        """
        Render blocks for approval result (after decision).

        Args:
            decision: 'approve' or 'reject'
            response_data: The response data from user
            schema: Optional original schema to preserve context

        Returns:
            Slack blocks
        """
        emoji = "✅" if decision == "approve" else "❌"
        status_text = "Approved" if decision == "approve" else "Rejected"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {status_text}"},
            },
        ]

        # Preserve original context if schema provided
        if schema:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{schema.title}*\n{schema.description}"}
            })

        blocks.append({"type": "divider"})

        # Add response data
        if response_data:
            fields = []
            for key, value in response_data.items():
                # Format the value
                if isinstance(value, list):
                    value_str = ", ".join(str(v) for v in value)
                else:
                    value_str = str(value)

                # Make key more readable
                readable_key = key.replace("_", " ").title()
                fields.append({"type": "mrkdwn", "text": f"*{readable_key}:*\n{value_str}"})

            if fields:
                blocks.append({"type": "section", "fields": fields})

        return blocks
