#!/bin/bash
# Azure Web App Startup Script for FastAPI
# This script starts the Uvicorn server

echo "Starting FastAPI application..."

# Note: Database tables are auto-created on startup by SQLAlchemy
# No migrations needed - using create_all() in startup

# Start Uvicorn server
# Azure expects the app to bind to 0.0.0.0 and use the PORT environment variable
echo "Starting Uvicorn server on port ${PORT:-8000}..."
python -m uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 1 \
    --log-level info
