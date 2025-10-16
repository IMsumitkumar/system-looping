#!/bin/bash
# Azure Web App Startup Script for Streamlit Chat
# This script starts the Streamlit chat application

echo "Starting Streamlit Chat application..."

# Set API base URL from environment variable (set in Azure App Settings)
export API_BASE_URL=${API_BASE_URL:-"https://lyzr-human-in-loop-workflow-b3agasdpfab8d7hd.centralindia-01.azurewebsites.net"}

echo "API Base URL: $API_BASE_URL"

# Start Streamlit
# Azure expects the app to bind to 0.0.0.0 and use the PORT environment variable
streamlit run streamlit_chat.py \
    --server.port ${PORT:-8501} \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false
