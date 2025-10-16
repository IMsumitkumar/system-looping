"""
Main FastAPI application - Human-in-the-Loop Orchestrator.
"""

import os
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import router as api_v1_router
from app.core.startup import lifespan

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="Human-in-the-Loop Orchestrator",
    description="Event-driven workflow orchestration with human approvals",
    version="1.0.0",
    lifespan=lifespan,
)

# ============================================================================
# Middleware Configuration
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Mount API Routes
# ============================================================================

# Include all v1 API routes
app.include_router(api_v1_router)

# ============================================================================
# Mount Static Files
# ============================================================================

# Mount dashboard static assets (CSS, JS)
app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")

# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    reload = os.getenv("RELOAD", "false").lower() == "true"

    logger.info(
        "starting_server",
        host=host,
        port=port,
        reload=reload
    )

    uvicorn.run(
        "main:app" if reload else app,
        host=host,
        port=port,
        reload=reload
    )