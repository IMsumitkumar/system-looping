# Human-in-the-Loop Workflow Orchestration System

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)

> **A event-driven workflow orchestration system with human approval loops.**

This system solves a critical challenge in modern agent systems: **how do you pause workflow execution, request human feedback through dynamic UIs across multiple channels (Slack, Web, Chat), and automatically resume—while remaining event-driven, state-aware, and resilient to failures?**

Built for environments where critical actions (deployments, purchases, contracts) require human approvals that may arrive hours or days later, through different channels.

---

## Problem Statement

Modern agent systems often require **human approvals or feedback** before executing critical actions—a purchase, a deployment, a message, a contract.

These approval loops are often **asynchronous**, **multi-channel**, and **stateful**—yet most systems handle them as blocking calls or static forms.

This system provides an orchestration layer where **agents can pause**, request **human feedback** via dynamic **approval UIs**, and **resume automatically** once a response is received—even when approvals happen hours later or through different channels.

The orchestration remains **event-driven**, **state-aware**, and **resilient to failures or delays**.

---

**My Development Approach:**

- **Claude Web**: Used for brainstorming architectural decisions, evaluating design trade-offs, and planning the overall system architecture.
- **Claude Code**: Used as a coding assistant for implementation, refactoring, and debugging

---

## Architecture Diagram

> Click on the diagram below to view the full interactive architecture on Excalidraw

<a href="https://link.excalidraw.com/l/7fmTiDrE4i9/32FXRHi4XIz" target="_blank">
  <img src="./image.png" alt="System Architecture Diagram" width="800">
</a>

**[Please click me - View Full Architecture Diagram](https://link.excalidraw.com/l/7fmTiDrE4i9/32FXRHi4XIz)**

---

## Key Features

### 1. State Machine

- **Version-based optimistic locking** prevents concurrent modification conflicts
- **State transition validation** enforces valid workflow paths
- **Event sourcing** provides complete audit trail
- **Resume-from-failure** for multi-step workflows


### 2. Event Bus

- **Async pub/sub** decouples components
- **Automatic retry** with exponential backoff
- **Dead Letter Queue** captures permanently failed events
- **Multiple subscribers** per event type

### 3. Approval System


- **Dynamic UI schema** renders across web, Slack, and chat
- **HMAC-signed tokens** prevent approval spoofing
- **Row-level locking** prevents duplicate processing
- **Expiry check happens before status check** (prevents race conditions)

### 4. Timeout Manager

- **Background task** checks expired approvals every 10 seconds
- **Automatic retry** with configurable backoff
- **Transitions workflow to TIMEOUT state** before retry
- **Max retries → Dead Letter Queue** flow


### 5. Concurrency Safety

- **Optimistic locking** for workflow updates
- **Pessimistic locking (SELECT FOR UPDATE)** for critical sections
- **Idempotency keys** prevent duplicate workflow creation

### 6. Multi-Step Orchestration

- **Sequential task and approval** step execution
- **Step-level status tracking** (pending, running, completed, failed)
- **Failed step detection and reset** for retry
- **Rollback support** when approvals are rejected


### 7. Integration Layer

- **Adapter pattern** isolates external service logic
- **Circuit breaker** prevents cascading failures
- **Conversation handlers** provide autonomous status updates
- **Graceful degradation** when external services fail

### 8. Dead Letter Queue

- **Captures events** after max retries exhausted
- **Stores full event context** for debugging
- **Admin UI** for inspection and manual retry
- **Bulk retry operations** after bug fixes

### 9. Agent Integration

- **Framework-agnostic protocol** for any LLM
- **Persistent conversation history** in database
- **Context-aware multi-turn** dialogue
- **Autonomous conversation updates** via event handlers


### 10. Configuration & Observability

- **Pydantic settings** with startup validation
- **All timeouts and retry limits** configurable
- **Composite database indexes** for query performance
- **Structured logging** for every state transition

---

## Core Components

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| **Event Bus** | Pub/sub messaging | AsyncIO queues, DLQ, retry logic |
| **Workflow Engine** | State machine | Optimistic locking, event sourcing, rollback |
| **Approval Service** | Human-in-loop | Dynamic schemas, secure tokens, multi-channel |
| **Timeout Manager** | Background watcher | Expiry checking, auto-retry, DLQ integration |
| **Slack Adapter** | External integration | Block Kit rendering |
| **Agent Orchestrator** | AI integration | Generic protocol, conversation context |
| **Conversation Handler** | Real-time updates | Event-driven chat updates |

---

## Technology Stack

### Backend

- **Framework**: FastAPI
- **ORM**: SQLAlchemy 2.0
- **Database**: SQLite (dev) / PostgreSQL (prod)(pending) with async
- **Validation**: Pydantic
- **Logging**: Structlog
- **HTTP Client**: HTTPX
- **Resilience**: Tenacity(retries), PyBreaker

### Frontend

This is fully vibe coded.
- **Web UI**: Vanilla JavaScript + CSS 
- **Chat Interface**: Streamlit

### Integrations

- **Slack**: slack-sdk- Block Kit approvals
- **AI Agent**: OpenAI API 

---

## Installation & Setup

### Prerequisites

- **Python 3.11+** 
- **OpenAI API Key** (for AI)
- **Slack App** (optional, for approvals), we have Web based UI for approvals as well

### 1. Clone the Repository

```bash
git clone 
cd 
```

### 2. Create Virtual Environment

```bash
python -m venv venv

source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

**Required settings:**

```bash
# Generate a secure secret key
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# Add your OpenAI API key (required for chat interface)
OPENAI_API_KEY=sk-your-openai-key-here

# Optional: Add Slack credentials for approval notifications
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_CHANNEL_ID=C1234567890
```

For complete configuration options, see `.env.example` or `./docs/CONFIGURATION.md`

Auto DB setup and creates tables at startup.py

### 6. Slack App Setup (Optional)

If you want to use Slack approvals:

1. **Create Slack App**: https://api.slack.com/apps → "Create New App" → "From scratch"
2. **Add Bot Token Scopes** (OAuth & Permissions):
   - `chat:write` - Send messages
   - `chat:write.public` - Send to channels without joining
3. **Install to Workspace** → Copy "Bot User OAuth Token" → Set as `SLACK_BOT_TOKEN`
4. **Get Signing Secret**: Basic Information → Copy "Signing Secret" → Set as `SLACK_SIGNING_SECRET`
5. **Get Channel ID**: Right-click channel → View channel details → Copy ID → Set as `SLACK_CHANNEL_ID`
6. **Enable Interactivity**: Interactivity & Shortcuts → Request URL: `https://your-domain.com/api/slack/actions`

---

## Running the Application

### Backend API

```bash
uvicorn main:app --reload --port 8000
```

### Streamlit Chat (Optional)

```bash
streamlit run streamlit_chat.py
```

### Access Points

- **Web Dashboard**: http://localhost:8000/
- **Chat Interface**: http://localhost:8501
- **Health Check**: http://localhost:8000/api/health

### Verify Installation

```bash
# Check API health
curl http://localhost:8000/api/health
```

---

## Dynamic UI Schemas

Approval forms are defined as JSON schemas that render consistently across web, Slack, and chat interfaces.

📋 **Schema Definition**: See [`app/models/schemas.py`](./app/models/schemas.py) - `ApprovalUISchema` class


This schema automatically renders as:
- **Web**: HTML form with validation
- **Slack**: Block Kit message with interactive components
- **Chat**: Formatted text with options

---

*"This project taught me that building reliable systems is about handling failure, not just success."*

**Sumit Kumar** ([@IMsumitkumar](https://github.com/IMsumitkumar))
