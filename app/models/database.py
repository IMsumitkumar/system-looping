"""
Database configuration and session management.
Currently uses SQLite for demo and local development.

SQLite Configuration:
- WAL (Write-Ahead Logging) mode for better concurrency
- IMMEDIATE transaction isolation to prevent race conditions
- Optimized pragmas for performance and reliability
- Foreign key constraints enforcement
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy import event, text
from contextlib import asynccontextmanager
import structlog

from app.config.settings import settings

logger = structlog.get_logger()

# SQLite connection arguments
connect_args = settings.get_connection_args()

# Create async engine for SQLite
engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,  # Controlled separately from debug mode
    future=True,
    connect_args=connect_args,
)
logger.info(
    "database_engine_created",
    type="sqlite",
    url=settings.database_url,
    echo_sql=settings.database_echo
)

# Enable foreign keys for each SQLite connection
# This must be set per-connection as it's not persistent
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable foreign keys and other pragmas for each connection"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def init_db():
    """
    Initialize SQLite database - create all tables and configure optimizations.

    SQLite optimizations:
    - WAL mode for better concurrency
    - Optimized cache and page sizes
    - Foreign key constraints enforcement
    """
    async with engine.begin() as conn:
        # SQLite-specific optimizations
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(text("PRAGMA cache_size=-10000"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.execute(text("PRAGMA page_size=4096"))

        logger.info(
            "database_initialized",
            type="sqlite",
            journal_mode="WAL",
            foreign_keys=True,
            cache_size="40MB",
        )

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """
    Dependency for getting database session in FastAPI routes.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """
    Context manager for getting database session outside of FastAPI routes.

    Usage:
        async with get_db_context() as session:
            result = await session.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class Database:
    """Database helper class for managing connections"""

    def __init__(self):
        self.engine = engine
        self.session_factory = AsyncSessionLocal

    async def init(self):
        """Initialize database schema"""
        await init_db()

    async def close(self):
        """Close all connections"""
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self):
        """Get a database session"""
        async with get_db_context() as session:
            yield session
