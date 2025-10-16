"""
Security utilities for callback token generation and verification.
Uses HMAC for cryptographically secure tokens.
"""

import secrets
import hmac
import hashlib
import time
from typing import Optional

from app.config.settings import settings

# Get secret key from settings
SECRET_KEY = settings.secret_key
SLACK_SIGNING_SECRET = settings.slack_signing_secret or ""


def generate_callback_token(approval_id: str) -> str:
    """
    Generate HMAC-signed callback token for approval requests.

    Format: {approval_id}:{random_part}:{signature}

    Args:
        approval_id: UUID of the approval request

    Returns:
        Secure callback token
    """
    # Generate cryptographically secure random part
    random_part = secrets.token_urlsafe(16)

    # Create HMAC signature
    message = f"{approval_id}:{random_part}".encode()
    signature = hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:16]

    # Combine into token
    token = f"{approval_id}:{random_part}:{signature}"

    return token


def verify_callback_token(token: str) -> Optional[str]:
    """
    Verify callback token and extract approval_id.

    Args:
        token: The callback token to verify

    Returns:
        approval_id if valid, None otherwise
    """
    try:
        import structlog
        logger = structlog.get_logger()

        # Log token verification attempt without exposing token value
        logger.info("callback_token_verification_start", token_length=len(token))

        # Parse token
        parts = token.split(":")
        logger.info("token_parts_split", parts_count=len(parts))

        if len(parts) != 3:
            logger.warning("callback_token_invalid_format", expected_parts=3, actual_parts=len(parts))
            return None

        approval_id, random_part, signature = parts

        # Recompute signature
        message = f"{approval_id}:{random_part}".encode()
        expected_signature = hmac.new(SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:16]

        # Log signature check without exposing actual signature values
        signature_match = hmac.compare_digest(signature, expected_signature)
        logger.info(
            "callback_token_signature_check",
            approval_id=approval_id,
            signature_match=signature_match,
        )

        # Constant-time comparison to prevent timing attacks
        if not signature_match:
            logger.warning("callback_token_signature_mismatch")
            return None

        logger.info("callback_token_valid", approval_id=approval_id)
        return approval_id

    except (ValueError, AttributeError) as e:
        import structlog
        logger = structlog.get_logger()
        logger.error("callback_token_verification_exception", error=str(e), exc_info=True)
        return None


def generate_idempotency_key() -> str:
    """Generate a random idempotency key"""
    return secrets.token_urlsafe(32)


def verify_slack_signature(timestamp: str, body: bytes, signature: str) -> bool:
    """
    Verify Slack request signature to prevent unauthorized requests.

    Args:
        timestamp: X-Slack-Request-Timestamp header value
        body: Raw request body (bytes)
        signature: X-Slack-Signature header value (format: v0=<hex>)

    Returns:
        True if signature is valid, False otherwise

    Security:
        - FAIL CLOSED: Rejects all requests if SLACK_SIGNING_SECRET not configured
        - Prevents replay attacks by checking timestamp is < 5 minutes old
        - Uses HMAC-SHA256 to verify request came from Slack
        - Constant-time comparison to prevent timing attacks

    Raises:
        RuntimeError: If SLACK_SIGNING_SECRET is not configured (production safety)
    """
    # SECURITY: Fail closed if signing secret not configured
    # This prevents accepting unsigned requests if misconfigured
    if not SLACK_SIGNING_SECRET:
        import structlog

        logger = structlog.get_logger()
        logger.error(
            "slack_signing_secret_not_configured",
            message="SLACK_SIGNING_SECRET environment variable not set. " "All Slack requests will be rejected.",
        )
        # Reject request - do not process unsigned requests
        return False

    try:
        import structlog
        logger = structlog.get_logger()

        # Check timestamp to prevent replay attacks (must be < 5 minutes old)
        current_time = int(time.time())
        request_time = int(timestamp)
        time_diff = abs(current_time - request_time)

        logger.info(
            "slack_signature_verification_attempt",
            current_time=current_time,
            request_time=request_time,
            time_diff_seconds=time_diff,
            timestamp_valid=time_diff <= 300,
        )

        if time_diff > 300:  # 5 minutes
            logger.warning("slack_signature_timestamp_too_old", time_diff_seconds=time_diff)
            return False

        # Compute expected signature
        # TODO: Check this on more use cases.
        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        expected_signature = (
            "v0=" + hmac.new(SLACK_SIGNING_SECRET.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
        )

        # Verify signature without exposing actual values in logs
        signature_match = hmac.compare_digest(signature, expected_signature)
        logger.info(
            "slack_signature_comparison",
            signature_match=signature_match,
            signature_length=len(signature),
        )

        # Constant-time comparison to prevent timing attacks
        return signature_match

    except (ValueError, AttributeError) as e:
        import structlog
        logger = structlog.get_logger()
        logger.error("slack_signature_verification_exception", error=str(e), exc_info=True)
        return False
