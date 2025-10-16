"""
Streamlit Chat UI for Agent Integration Layer.

Simple, clean conversational interface to the workflow orchestration system.
"""
 
import streamlit as st
import requests
import uuid
import logging
import os
from datetime import datetime

# Setup logger
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DEFAULT_USER_ID = "IMSUMITKUMAR"  

# Page configuration
st.set_page_config(
    page_title="Workflow Assistant",
    page_icon="🤖",
    layout="centered"
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "workflow_id" not in st.session_state:
    st.session_state.workflow_id = None
if "approval_id" not in st.session_state:
    st.session_state.approval_id = None
if "status" not in st.session_state:
    st.session_state.status = "active"
if "last_message_count" not in st.session_state:
    st.session_state.last_message_count = 0
if "polling_enabled" not in st.session_state:
    st.session_state.polling_enabled = False
if "selected_example" not in st.session_state:
    st.session_state.selected_example = None


def send_message(user_message: str) -> dict:
    """
    Send message to the chat API and get response.

    Returns:
        Response dict with message, status, workflow_id, etc.
    """
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/chat/message",
            json={
                "user_id": DEFAULT_USER_ID,
                "message": user_message,
                "conversation_id": st.session_state.conversation_id,
                "channel": "streamlit"
            },
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            return {
                "message": f"Error: {response.status_code} - {response.text}",
                "conversation_id": st.session_state.conversation_id,
                "status": "error",
                "metadata": {}
            }

    except requests.exceptions.ConnectionError:
        return {
            "message": "Cannot connect to the API. Please make sure the server is running.",
            "conversation_id": st.session_state.conversation_id,
            "status": "error",
            "metadata": {}
        }
    except Exception as e:
        return {
            "message": f"Error: {str(e)}",
            "conversation_id": st.session_state.conversation_id,
            "status": "error",
            "metadata": {}
        }


def get_status_indicator(status: str) -> str:
    """Get emoji indicator for conversation status"""
    status_map = {
        "active": "🟢",
        "waiting_approval": "⏸️",
        "completed": "✅",
        "error": "⚠️"
    }
    return status_map.get(status, "🔵")


def check_for_new_messages() -> bool:
    """
    Check if there are new messages in the conversation.

    Returns:
        True if new messages were found, False otherwise
    """
    if not st.session_state.conversation_id:
        return False

    try:
        response = requests.get(
            f"{API_BASE_URL}/api/chat/conversations/{st.session_state.conversation_id}",
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            messages = data.get("messages", [])
            current_count = len(messages)

            # Check if there are new messages
            if current_count > st.session_state.last_message_count:
                # Calculate new message count before updating
                new_msg_count = current_count - st.session_state.last_message_count

                # Replace the entire message list to avoid duplicates
                # Only update if we have genuinely new messages
                new_messages = []
                for msg in messages:
                    new_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                        "metadata": msg.get("metadata", {}),
                        "timestamp": msg.get("timestamp")
                    })

                st.session_state.messages = new_messages
                st.session_state.last_message_count = current_count

                # Update status and IDs
                st.session_state.status = data.get("state", "active")
                if data.get("workflow_id"):
                    st.session_state.workflow_id = data["workflow_id"]
                if data.get("approval_id"):
                    st.session_state.approval_id = data["approval_id"]

                logger.info(f"Found {new_msg_count} new messages")
                return True

        return False

    except Exception as e:
        logger.error(f"Error checking for new messages: {e}")
        return False


# Title and header
st.title("🤖 Workflow Assistant")
st.markdown("I can help you create and manage workflows with approvals!")

# Sidebar with status information
with st.sidebar:
    st.header("Conversation Info")

    # Status indicator
    status_emoji = get_status_indicator(st.session_state.status)
    status_label = st.session_state.status.replace("_", " ").title()
    st.markdown(f"**Status:** {status_emoji} {status_label}")

    # Conversation ID
    if st.session_state.conversation_id:
        st.markdown(f"**Conversation:** `{st.session_state.conversation_id[:8]}...`")

    # Workflow ID
    if st.session_state.workflow_id:
        st.markdown(f"**Workflow:** `{st.session_state.workflow_id[:8]}...`")
        if st.button("View Workflow Details"):
            st.info(f"Workflow ID: {st.session_state.workflow_id}")

    # Approval ID
    if st.session_state.approval_id:
        st.markdown(f"**Approval:** `{st.session_state.approval_id[:8]}...`")
        st.warning("Waiting for approval via Slack")

    # Clear conversation button
    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.conversation_id = None
        st.session_state.workflow_id = None
        st.session_state.approval_id = None
        st.session_state.status = "active"
        st.rerun()

    # Example commands - Clickable
    with st.expander("💡 Try These Examples", expanded=False):
        examples = [
            "I want a staging deployment with two tasks: cicd creation, approval of cicd with sumit, Make sure all these tasks need approvals.",
            "Create a production deployment workflow with approval",
            "Create a 3-step workflow: build, test, deploy to staging",
            "Check my workflow status",
            "Deploy application to production environment"
        ]

        for idx, example in enumerate(examples):
            if st.button(example, key=f"example_{idx}", use_container_width=True):
                st.session_state.selected_example = example
                st.rerun()

# Display chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # Show metadata for assistant messages
        if msg["role"] == "assistant" and "metadata" in msg:
            metadata = msg.get("metadata", {})
            if metadata.get("workflow_id"):
                st.caption(f"Workflow: {metadata['workflow_id'][:12]}...")
            if metadata.get("approval_id"):
                st.caption(f"Approval: {metadata['approval_id'][:12]}...")

# Handle selected example
if st.session_state.selected_example:
    prompt = st.session_state.selected_example
    st.session_state.selected_example = None  # Clear after use
else:
    prompt = None

# Chat input
if not prompt:
    prompt = st.chat_input("Type your message here...")

if prompt:
    # Add user message to chat
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Display user message immediately
    with st.chat_message("user"):
        st.markdown(prompt)

    # Send to API and get response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response_data = send_message(prompt)

        # Extract response details
        assistant_message = response_data.get("message", "No response")
        st.session_state.conversation_id = response_data.get("conversation_id")
        st.session_state.status = response_data.get("status", "active")

        # Update workflow/approval IDs if present
        if response_data.get("workflow_id"):
            st.session_state.workflow_id = response_data["workflow_id"]
        if response_data.get("approval_id"):
            st.session_state.approval_id = response_data["approval_id"]

        # Display assistant message
        st.markdown(assistant_message)

        # Show status indicator
        if st.session_state.status == "waiting_approval":
            st.warning("⏸️ Waiting for approval. Check Slack!")
        elif st.session_state.status == "completed":
            st.success("✅ Completed!")
        elif st.session_state.status == "error":
            st.error("⚠️ Error occurred")

        # Show metadata
        metadata = response_data.get("metadata", {})
        if metadata:
            with st.expander("Response Details"):
                st.json(metadata)

    # Add assistant message to chat history
    st.session_state.messages.append({
        "role": "assistant",
        "content": assistant_message,
        "metadata": response_data.get("metadata", {})
    })

    # Update message count to prevent duplicate detection
    st.session_state.last_message_count = len(st.session_state.messages)

    # Rerun to update sidebar
    st.rerun()

# ========================================================================
# Autonomous Message Polling (Generic Layer Feature)
# ========================================================================

# Enable polling when there's an active conversation
if st.session_state.conversation_id and st.session_state.status in ["active", "waiting_approval"]:
    import time

    # Check for new messages every 3 seconds
    placeholder = st.empty()

    with placeholder.container():
        if check_for_new_messages():
            # New messages found - rerun to update UI
            st.rerun()

    # Auto-refresh every 3 seconds to check for updates
    time.sleep(3)
    st.rerun()
