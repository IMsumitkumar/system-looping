"""
Test fixtures and helper utilities for standalone test scripts.
Provides common setup, teardown, and test data creation functions.
"""

import sys
import os
import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from sqlalchemy import text

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import Database, AsyncSessionLocal
from app.core.workflow_engine import WorkflowEngine
from app.core.approval_service import ApprovalService
from app.core.event_bus import EventBus
from app.core.timeout_manager import TimeoutManager
from app.models.schemas import ApprovalUISchema, ApprovalButton, FormField, WorkflowState
from app.models.orm import Base


# ============================================================================
# Color codes for terminal output
# ============================================================================

GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'


# ============================================================================
# Test output helpers
# ============================================================================

def print_test_header(test_name):
    """Print formatted test header"""
    print(f"\n{'='*70}")
    print(f"{CYAN}Running: {test_name}{RESET}")
    print(f"{'='*70}\n")


def print_pass(test_name):
    """Print test pass message"""
    print(f"{GREEN}✓ PASS{RESET}: {test_name}")


def print_fail(test_name, error):
    """Print test failure message with error details"""
    print(f"{RED}✗ FAIL{RESET}: {test_name}")
    print(f"{RED}  Error: {error}{RESET}")


def print_info(message):
    """Print informational message"""
    print(f"{BLUE}ℹ {message}{RESET}")


def print_summary(tests_passed, tests_failed):
    """Print test summary"""
    print(f"\n{'='*70}")
    total = tests_passed + tests_failed
    if tests_failed == 0:
        print(f"{GREEN}✓ ALL TESTS PASSED{RESET}: {tests_passed}/{total}")
    else:
        print(f"{RED}✗ SOME TESTS FAILED{RESET}: {tests_passed} passed, {tests_failed} failed")
    print(f"{'='*70}\n")


# ============================================================================
# Database setup/teardown
# ============================================================================

async def create_test_database(db_path="./test_workflows.db"):
    """
    Create a fresh test database.
    Deletes existing database and creates new schema.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import event
    from app.models.orm import Base

    # Remove existing database
    if os.path.exists(db_path):
        os.remove(db_path)

    if os.path.exists(f"{db_path}-shm"):
        os.remove(f"{db_path}-shm")

    if os.path.exists(f"{db_path}-wal"):
        os.remove(f"{db_path}-wal")

    # Create a new engine for this specific test database
    db_url = f"sqlite+aiosqlite:///{db_path}"
    test_engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args={"timeout": 10.0, "check_same_thread": False}
    )

    # Enable foreign keys for SQLite
    @event.listens_for(test_engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create session factory for this engine
    test_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    # Initialize database schema
    async with test_engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(text("PRAGMA cache_size=-10000"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.execute(text("PRAGMA page_size=4096"))
        await conn.run_sync(Base.metadata.create_all)

    # Create a custom Database object with the test engine
    db = Database()
    db.engine = test_engine
    db.session_factory = test_session_factory

    return db


async def cleanup_database(db: Database):
    """Clean up test database"""
    try:
        await db.close()
    except Exception:
        pass


# ============================================================================
# Test data factories
# ============================================================================

async def create_test_workflow(engine: WorkflowEngine, workflow_type="test", context=None):
    """
    Create a test workflow.

    Args:
        engine: WorkflowEngine instance
        workflow_type: Type of workflow
        context: Workflow context data

    Returns:
        Created workflow
    """
    if context is None:
        context = {"test": "data", "timestamp": datetime.now().isoformat()}

    return await engine.create_workflow(workflow_type, context)


async def create_test_approval(service: ApprovalService, workflow_id: str, timeout_seconds=3600):
    """
    Create a test approval request.

    Args:
        service: ApprovalService instance
        workflow_id: ID of workflow requiring approval
        timeout_seconds: Approval timeout

    Returns:
        Created approval request
    """
    schema = ApprovalUISchema(
        title="Test Approval",
        description="Test approval request for automated testing",
        fields=[
            FormField(
                name="approver_name",
                type="text",
                label="Your Name",
                required=True
            ),
            FormField(
                name="risk_level",
                type="select",
                label="Risk Assessment",
                options=[
                    {"label": "Low", "value": "low"},
                    {"label": "Medium", "value": "medium"},
                    {"label": "High", "value": "high"}
                ],
                required=True
            ),
            FormField(
                name="comments",
                type="textarea",
                label="Additional Comments",
                required=False
            )
        ],
        buttons=[
            ApprovalButton(action="approve", label="Approve", style="primary"),
            ApprovalButton(action="reject", label="Reject", style="danger")
        ]
    )

    return await service.request_approval(workflow_id, schema, timeout_seconds)


async def create_expired_approval(service: ApprovalService, workflow_id: str):
    """
    Create an approval that is already expired.

    Args:
        service: ApprovalService instance
        workflow_id: ID of workflow requiring approval

    Returns:
        Created approval request (already expired)
    """
    # Create approval with 1 second timeout
    approval = await create_test_approval(service, workflow_id, timeout_seconds=1)

    # Wait for it to expire
    await asyncio.sleep(1.5)

    return approval


# ============================================================================
# Event bus helpers
# ============================================================================

class EventCollector:
    """Helper class to collect events for testing"""

    def __init__(self):
        self.events = []

    async def handler(self, data: dict):
        """Event handler that collects events"""
        self.events.append(data)

    def get_events(self):
        """Get collected events"""
        return self.events

    def clear(self):
        """Clear collected events"""
        self.events = []

    def count(self):
        """Get count of collected events"""
        return len(self.events)

    def find_event(self, **kwargs):
        """Find event matching criteria"""
        for event in self.events:
            match = True
            for key, value in kwargs.items():
                if event.get(key) != value:
                    match = False
                    break
            if match:
                return event
        return None


# ============================================================================
# Test context managers
# ============================================================================

class TestContext:
    """Context manager for setting up test environment"""

    _context_counter = 0

    def __init__(self, db_path=None, clean_on_entry=True):
        # Generate unique database path for each context
        if db_path is None:
            TestContext._context_counter += 1
            import time
            db_path = f"./test_workflows_{TestContext._context_counter}_{int(time.time()*1000)}.db"
        self.db_path = db_path
        self.db = None
        self.event_bus = None
        self.clean_on_entry = clean_on_entry

    async def __aenter__(self):
        """Setup test environment"""
        self.db = await create_test_database(self.db_path)
        self.event_bus = EventBus()
        await self.event_bus.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup test environment"""
        if self.event_bus:
            await self.event_bus.stop()

        if self.db:
            await cleanup_database(self.db)

        # Clean up database files
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

        for ext in ["-shm", "-wal"]:
            if os.path.exists(f"{self.db_path}{ext}"):
                try:
                    os.remove(f"{self.db_path}{ext}")
                except Exception:
                    pass

    @asynccontextmanager
    async def get_session(self):
        """Get a new database session as an async context manager"""
        # Use the test database's session factory, not the global one
        session = self.db.session_factory()
        try:
            yield session
        finally:
            await session.close()

    async def clear_all_data(self):
        """Clear all data from the database (useful between tests)"""
        from app.models.orm import Workflow, ApprovalRequest, WorkflowEvent
        async with self.get_session() as session:
            # Delete in order to respect foreign keys
            await session.execute(text("DELETE FROM approval_requests"))
            await session.execute(text("DELETE FROM workflow_events"))
            await session.execute(text("DELETE FROM workflows"))
            await session.commit()


# ============================================================================
# Assertion helpers
# ============================================================================

def assert_equal(actual, expected, message=""):
    """Assert two values are equal"""
    if actual != expected:
        raise AssertionError(
            f"{message}\nExpected: {expected}\nActual: {actual}"
        )


def assert_not_equal(actual, expected, message=""):
    """Assert two values are not equal"""
    if actual == expected:
        raise AssertionError(
            f"{message}\nExpected values to be different, but both are: {actual}"
        )


def assert_true(condition, message=""):
    """Assert condition is true"""
    if not condition:
        raise AssertionError(f"{message}\nExpected: True\nActual: False")


def assert_false(condition, message=""):
    """Assert condition is false"""
    if condition:
        raise AssertionError(f"{message}\nExpected: False\nActual: True")


def assert_in(item, container, message=""):
    """Assert item is in container"""
    if item not in container:
        raise AssertionError(
            f"{message}\nExpected {item} to be in {container}"
        )


def assert_not_in(item, container, message=""):
    """Assert item is not in container"""
    if item in container:
        raise AssertionError(
            f"{message}\nExpected {item} to not be in {container}"
        )


def assert_raises(exception_type, func, *args, **kwargs):
    """Assert function raises specific exception"""
    try:
        func(*args, **kwargs)
        raise AssertionError(
            f"Expected {exception_type.__name__} to be raised, but no exception was raised"
        )
    except exception_type:
        pass  # Expected
    except Exception as e:
        raise AssertionError(
            f"Expected {exception_type.__name__} to be raised, but got {type(e).__name__}: {e}"
        )


async def assert_raises_async(exception_type, coro):
    """Assert async function raises specific exception"""
    try:
        await coro
        raise AssertionError(
            f"Expected {exception_type.__name__} to be raised, but no exception was raised"
        )
    except exception_type:
        pass  # Expected
    except Exception as e:
        raise AssertionError(
            f"Expected {exception_type.__name__} to be raised, but got {type(e).__name__}: {e}"
        )


# ============================================================================
# Performance testing helpers
# ============================================================================

class PerformanceTimer:
    """Context manager for timing operations"""

    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.duration_ms = None

    def __enter__(self):
        """Start timer"""
        self.start_time = datetime.now()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timer"""
        self.end_time = datetime.now()
        duration = self.end_time - self.start_time
        self.duration_ms = duration.total_seconds() * 1000

    def get_duration_ms(self):
        """Get duration in milliseconds"""
        return self.duration_ms


# ============================================================================
# Mock helpers
# ============================================================================

class MockSlackAPI:
    """Mock Slack API for testing"""

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.messages_sent = []

    async def post_message(self, channel, blocks):
        """Mock posting message to Slack"""
        if self.should_fail:
            raise Exception("Slack API error")

        message = {
            "channel": channel,
            "blocks": blocks,
            "ts": f"{datetime.now().timestamp()}"
        }
        self.messages_sent.append(message)
        return {"ok": True, "ts": message["ts"]}

    async def update_message(self, channel, ts, blocks):
        """Mock updating Slack message"""
        if self.should_fail:
            raise Exception("Slack API error")

        return {"ok": True, "ts": ts}

    def get_messages(self):
        """Get all messages sent"""
        return self.messages_sent

    def clear(self):
        """Clear message history"""
        self.messages_sent = []
