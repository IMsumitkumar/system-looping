"""
Centralized configuration management using Pydantic Settings.
Validates environment variables on startup and provides typed config access.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings with validation.
    Loads from environment variables with fallback to .env file.
    """

    # Database Configuration
    database_url_sqlite: str = Field(
        default="sqlite+aiosqlite:///./workflows.db",
        description="SQLite database URL for local development"
    )
    database_echo: bool = Field(
        default=False,
        description="Log all SQL queries"
    )

    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_pool_recycle: int = 3600  # Recycle connections after 1 hour

    # Application Configuration
    # MUST be set via environment variables - no insecure defaults
    secret_key: str = Field(
        ...,
        description="Cryptographic secret key - MUST be set in .env"
    )
    callback_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for callbacks"
    )

    # Frontend Configuration (for JavaScript)
    frontend_api_base_url: str = Field(
        default="http://localhost:8000",
        description="API base URL for frontend JavaScript"
    )
    frontend_chat_agent_url: str = Field(
        default="http://localhost:8501",
        description="Chat agent URL for frontend (Streamlit app)"
    )

    # Slack Integration (Optional)
    slack_bot_token: Optional[str] = None
    slack_channel_id: Optional[str] = None
    slack_signing_secret: Optional[str] = None

    # Timeout Configuration
    default_approval_timeout_seconds: int = 3600  # 1 hour
    max_workflow_duration_seconds: int = 86400  # 24 hours
    timeout_check_interval_seconds: int = 10

    # Retry Configuration
    max_retry_attempts: int = 3
    retry_backoff_multiplier: float = 2.0
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 60.0

    # Circuit Breaker Configuration
    circuit_breaker_fail_max: int = 5
    circuit_breaker_timeout_duration: int = 60
    circuit_breaker_success_threshold: int = 3

    # Event Bus Configuration
    event_bus_max_queue_size: int = 1000
    event_bus_max_retries: int = 3

    # Idempotency Configuration
    idempotency_key_expiry_hours: int = 24

    # Environment
    environment: str = "development"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        """
        Returns the SQLite database URL.
        """
        return self.database_url_sqlite

    def is_production(self) -> bool:
        """Check if running in production"""
        return self.environment.lower() == "production"

    def validate_critical_config(self):
        """
        Validate critical configuration on startup.
        Raises ValueError if critical config is missing.
        """
        errors = []

        # Check database URL is set
        if not self.database_url:
            errors.append("DATABASE_URL must be set")

        # Check secret key is set (Pydantic will enforce this, but double-check)
        if not self.secret_key:
            errors.append("SECRET_KEY must be set in environment variables")

        # Warn about Slack if not configured (non-critical)
        if not self.slack_bot_token:
            import structlog
            logger = structlog.get_logger()
            logger.warning(
                "slack_not_configured",
                message="SLACK_BOT_TOKEN not set - Slack notifications disabled"
            )

        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

    def get_connection_args(self) -> dict:
        """Get SQLite-specific connection arguments"""
        return {
            "timeout": 10.0,
            "check_same_thread": False,
        }


# Global settings instance
settings = Settings()
