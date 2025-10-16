"""
OpenAI Adapter for Agent Integration Layer.

Reference implementation showing how to implement the AgentProtocol interface.
Uses OpenAI function calling to interact with WorkflowEngine and ApprovalService.
"""

from typing import List, Dict, Any, Optional
import os
import json
import structlog

from app.agent_layer.protocol import AgentProtocol, AgentRequest, AgentResponse, AgentCapability
from app.core.workflow_engine import WorkflowEngine
from app.core.approval_service import ApprovalService
from app.models.schemas import ApprovalUISchema, WorkflowStepConfig
from app.models.database import get_db_context

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None

logger = structlog.get_logger()


class OpenAIAdapter(AgentProtocol):
    """
    OpenAI implementation of AgentProtocol.

    Demonstrates how to integrate OpenAI with the workflow orchestration system.
    Other frameworks (LangGraph, CrewAI, custom) would follow similar patterns.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini", event_bus=None):
        """
        Initialize OpenAI adapter.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use (default: gpt-4o-mini)
            event_bus: EventBus for publishing workflow events (optional)
        """
        super().__init__(name="openai")

        if not OPENAI_AVAILABLE:
            raise ImportError(
                "OpenAI package not installed. Install with: pip install openai"
            )

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning(
                "openai_api_key_not_set",
                message="OPENAI_API_KEY not set - agent will not work"
            )

        self.model = model
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None
        self.event_bus = event_bus  # Store event_bus for WorkflowEngine calls

        logger.info("openai_adapter_initialized", model=model, has_event_bus=event_bus is not None)

    async def execute_task(self, request: AgentRequest) -> AgentResponse:
        """
        Execute task using OpenAI function calling.

        The agent will:
        1. Analyze user's message
        2. Determine what action to take (create workflow, check status, etc.)
        3. Call appropriate WorkflowEngine/ApprovalService methods
        4. Return conversational response
        """
        try:
            if not self.client:
                return AgentResponse(
                    message="I'm sorry, but I'm not configured properly. Please set OPENAI_API_KEY.",
                    status="error",
                    metadata={"error": "openai_not_configured"}
                )

            # Build messages for OpenAI
            messages = self._build_messages(request)

            # Define available functions
            tools = self._get_function_definitions()

            logger.info(
                "calling_openai",
                model=self.model,
                user_id=request.user_id,
                message_length=len(request.message)
            )

            # Call OpenAI with function calling
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )

            # Process response
            message = response.choices[0].message

            # Check if OpenAI wants to call a function
            if message.tool_calls:
                # Execute function calls
                agent_response = await self._execute_function_calls(
                    message.tool_calls,
                    request
                )
            else:
                # Just a conversational response
                agent_response = AgentResponse(
                    message=message.content or "I'm here to help with workflows and approvals!",
                    status="active",
                    metadata={}
                )

            logger.info(
                "openai_execution_complete",
                conversation_id=request.conversation_id,
                status=agent_response.status,
                has_workflow=agent_response.workflow_id is not None
            )

            return agent_response

        except Exception as e:
            logger.error(
                "openai_execution_failed",
                error=str(e),
                user_id=request.user_id,
                exc_info=True
            )
            return AgentResponse(
                message=f"I encountered an error: {str(e)}. Please try again.",
                status="error",
                metadata={"error": str(e)}
            )

    async def handle_approval_response(
        self,
        approval_id: str,
        decision: str,
        response_data: Dict[str, Any],
        conversation_id: Optional[str] = None
    ) -> AgentResponse:
        """
        Handle approval response from user.

        Args:
            approval_id: The approval request ID
            decision: "approve" or "reject"
            response_data: Form data from approval
            conversation_id: Optional conversation context

        Returns:
            AgentResponse acknowledging the decision
        """
        try:
            # Call ApprovalService to process the decision
            async with get_db_context() as db:
                approval_service = ApprovalService(db)
                await approval_service.respond_to_approval(
                    approval_id, decision, response_data
                )

            # Generate conversational response
            if decision == "approve":
                message = "✅ Approved! I've processed your approval and the workflow is continuing."
            else:
                message = "❌ Rejected. I've cancelled the workflow."

            logger.info(
                "approval_response_handled",
                approval_id=approval_id,
                decision=decision,
                conversation_id=conversation_id
            )

            return AgentResponse(
                message=message,
                approval_id=None if decision == "approve" else approval_id,
                status="active" if decision == "approve" else "completed",
                metadata={"decision": decision, "response_data": response_data}
            )

        except Exception as e:
            logger.error(
                "approval_response_failed",
                approval_id=approval_id,
                error=str(e),
                exc_info=True
            )
            return AgentResponse(
                message=f"Error processing approval: {str(e)}",
                status="error",
                metadata={"error": str(e)}
            )

    def get_capabilities(self) -> List[AgentCapability]:
        """Return list of capabilities"""
        # Add more capabilities here.
        return [
            AgentCapability.CREATE_WORKFLOW,
            AgentCapability.GET_WORKFLOW_STATUS,
            AgentCapability.APPROVE_WORKFLOW,
            AgentCapability.REJECT_WORKFLOW,
        ]

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _build_messages(self, request: AgentRequest) -> List[Dict[str, str]]:
        """Build message history for OpenAI"""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful workflow automation assistant. "
                    "You can create multi-step workflows with approvals, check workflow status, "
                    "and help users manage their workflows. "
                    "When users ask to create workflows, use the create_workflow function. "
                    "Be conversational and helpful.\n\n"
                    "IMPORTANT WORKFLOW PATTERNS:\n"
                    "1. When user says 'all tasks need approvals' or 'each task needs approval', "
                    "create the pattern: approval → task → approval → task → approval → task\n"
                    "2. Always put an approval step BEFORE each task when requested\n"
                    "3. For deployment workflows, the typical pattern is:\n"
                    "   - approval (review deployment plan)\n"
                    "   - task (execute deployment)\n"
                    "   - approval (verify deployment)\n"
                    "   - task (run tests)\n"
                    "Example: If user wants 3 tasks with approvals, create 6 steps total: "
                    "[approval, task1, approval, task2, approval, task3]"
                )
            }
        ]

        # Add conversation history (limit to last 10 messages for context window)
        for msg in request.conversation_history[-10:]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        # Add current message if not already in history
        if not request.conversation_history or request.conversation_history[-1]["content"] != request.message:
            messages.append({
                "role": "user",
                "content": request.message
            })

        return messages

    def _get_function_definitions(self) -> List[Dict]:
        """Define available functions for OpenAI function calling"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_workflow",
                    "description": "Create a new multi-step workflow with optional approval steps. IMPORTANT: When user wants 'all tasks with approvals', create approval steps BEFORE each task",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_type": {
                                "type": "string",
                                "description": "Type of workflow (e.g., 'deployment', 'purchase', 'contract')"
                            },
                            "description": {
                                "type": "string",
                                "description": "Human-readable description of what this workflow does"
                            },
                            "steps": {
                                "type": "array",
                                "description": "Workflow steps to execute in order. For 'all tasks need approval' pattern, alternate: approval, task, approval, task, etc.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["task", "approval"],
                                            "description": "Step type - approval steps should come BEFORE tasks when user wants approval for each task"
                                        },
                                        "handler": {
                                            "type": "string",
                                            "description": "Task handler name (for task steps) - e.g., 'cicd_creation', 'cicd_execution', etc."
                                        },
                                        "input": {
                                            "type": "object",
                                            "description": "Input data for the step including any UI schema for approvals"
                                        }
                                    },
                                    "required": ["type"]
                                }
                            }
                        },
                        "required": ["workflow_type", "description", "steps"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_workflow_status",
                    "description": "Get the current status of a workflow",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_id": {
                                "type": "string",
                                "description": "The workflow ID to check"
                            }
                        },
                        "required": ["workflow_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "retry_workflow",
                    "description": "Retry a failed or timed-out workflow from the point of failure",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_id": {
                                "type": "string",
                                "description": "The workflow ID to retry"
                            }
                        },
                        "required": ["workflow_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "rollback_approval",
                    "description": "Rollback a mistakenly rejected approval back to pending state",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "approval_id": {
                                "type": "string",
                                "description": "The approval ID to rollback"
                            }
                        },
                        "required": ["approval_id"]
                    }
                }
            }
        ]

    async def _execute_function_calls(
        self,
        tool_calls: List,
        request: AgentRequest
    ) -> AgentResponse:
        """Execute function calls from OpenAI"""
        results = []

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            logger.info(
                "executing_function",
                function=function_name,
                args=function_args
            )

            if function_name == "create_workflow":
                result = await self._create_workflow(function_args, request)
                results.append(result)
            elif function_name == "get_workflow_status":
                result = await self._get_workflow_status(function_args)
                results.append(result)
            elif function_name == "retry_workflow":
                result = await self._retry_workflow(function_args, request)
                results.append(result)
            elif function_name == "rollback_approval":
                result = await self._rollback_approval(function_args, request)
                results.append(result)

        # Return the last result (or combine if multiple)
        if results:
            return results[-1]

        return AgentResponse(
            message="I executed your request.",
            status="active",
            metadata={}
        )

    def _generate_approval_ui_schema(
        self,
        workflow_type: str,
        description: str,
        step_config: Dict[str, Any]
    ) -> ApprovalUISchema:
        """
        Generate context-aware approval UI schema based on workflow type.

        -> Either create custom based on the type or use the default.

        Creates smart, production-quality approval forms with fields appropriate
        to the workflow type (deployment, purchase, contract, etc.).

        Args:
            workflow_type: Type of workflow (e.g., 'deployment', 'purchase')
            description: Workflow description for context
            step_config: Step configuration (may contain custom fields)

        Returns:
            ApprovalUISchema object with context-aware fields
        """
        from app.models.schemas import FormField, ApprovalButton

        # Check if custom UI schema was provided in step config
        if "input" in step_config and "ui_schema" in step_config["input"]:
            return ApprovalUISchema(**step_config["input"]["ui_schema"])

        workflow_type_lower = workflow_type.lower()

        # Deployment workflow
        if "deploy" in workflow_type_lower:
            return ApprovalUISchema(
                title=f"🚀 {workflow_type.title()} Approval",
                description=f"Review deployment request: {description}",
                fields=[
                    FormField(
                        name="reviewer_name",
                        type="text",
                        label="Your Name",
                        required=True,
                        placeholder="Enter your full name"
                    ),
                    FormField(
                        name="environment",
                        type="select",
                        label="Target Environment (Optional)",
                        required=False,
                        options=[
                            {"label": "Production", "value": "production"},
                            {"label": "Staging", "value": "staging"},
                            {"label": "Development", "value": "development"}
                        ]
                    ),
                    FormField(
                        name="risk_assessment",
                        type="select",
                        label="Risk Level (Optional)",
                        required=False,
                        options=[
                            {"label": "Low - Routine change", "value": "low"},
                            {"label": "Medium - Moderate impact", "value": "medium"},
                            {"label": "High - Critical change", "value": "high"}
                        ],
                        help_text="Assess the risk level of this deployment"
                    ),
                    FormField(
                        name="comments",
                        type="textarea",
                        label="Review Comments",
                        placeholder="Add any notes or concerns about this deployment...",
                        required=False
                    )
                ],
                buttons=[
                    ApprovalButton(action="approve", label="✅ Approve Deployment", style="primary"),
                    ApprovalButton(action="reject", label="❌ Reject", style="danger")
                ]
            )

        # Purchase/procurement workflow
        elif "purchase" in workflow_type_lower or "procurement" in workflow_type_lower:
            return ApprovalUISchema(
                title=f"💰 {workflow_type.title()} Approval",
                description=f"Review purchase request: {description}",
                fields=[
                    FormField(
                        name="approver_name",
                        type="text",
                        label="Approver Name",
                        required=True,
                        placeholder="Enter your full name"
                    ),
                    FormField(
                        name="budget_amount",
                        type="number",
                        label="Budget Amount ($) (Optional)",
                        required=False,
                        validation={"min": 0},
                        placeholder="Enter amount in USD"
                    ),
                    FormField(
                        name="justification",
                        type="textarea",
                        label="Business Justification (Optional)",
                        required=False,
                        placeholder="Explain why this purchase is necessary...",
                        help_text="Provide clear business rationale for this expenditure"
                    ),
                    FormField(
                        name="urgency",
                        type="select",
                        label="Urgency Level (Optional)",
                        required=False,
                        options=[
                            {"label": "Low - Can wait", "value": "low"},
                            {"label": "Medium - Needed soon", "value": "medium"},
                            {"label": "High - Urgent", "value": "high"}
                        ]
                    )
                ],
                buttons=[
                    ApprovalButton(action="approve", label="✅ Approve Purchase", style="primary"),
                    ApprovalButton(action="reject", label="❌ Reject", style="danger")
                ]
            )

        # Contract/legal workflow
        elif "contract" in workflow_type_lower or "legal" in workflow_type_lower:
            return ApprovalUISchema(
                title=f"📄 {workflow_type.title()} Approval",
                description=f"Review contract: {description}",
                fields=[
                    FormField(
                        name="legal_reviewer",
                        type="text",
                        label="Legal Reviewer Name",
                        required=True,
                        placeholder="Enter your full name"
                    ),
                    FormField(
                        name="contract_value",
                        type="number",
                        label="Contract Value ($) (Optional)",
                        required=False,
                        validation={"min": 0},
                        placeholder="Total contract value in USD"
                    ),
                    FormField(
                        name="contract_duration",
                        type="select",
                        label="Contract Duration (Optional)",
                        required=False,
                        options=[
                            {"label": "1 year", "value": "1_year"},
                            {"label": "2 years", "value": "2_years"},
                            {"label": "3+ years", "value": "3_plus_years"}
                        ]
                    ),
                    FormField(
                        name="approval_notes",
                        type="textarea",
                        label="Legal Review Notes (Optional)",
                        required=False,
                        placeholder="Add legal review comments, concerns, or conditions...",
                        help_text="Document any legal considerations or required amendments"
                    )
                ],
                buttons=[
                    ApprovalButton(action="approve", label="✅ Approve Contract", style="primary"),
                    ApprovalButton(action="reject", label="❌ Reject", style="danger")
                ]
            )

        # Generic fallback for any other workflow type
        else:
            return ApprovalUISchema(
                title=f"✋ {workflow_type.title()} Approval",
                description=f"Review and approve: {description}",
                fields=[
                    FormField(
                        name="reviewer_name",
                        type="text",
                        label="Your Name",
                        required=True,
                        placeholder="Enter your full name"
                    ),
                    FormField(
                        name="comments",
                        type="textarea",
                        label="Comments",
                        placeholder="Add your review comments...",
                        required=False,
                        help_text="Provide any notes or feedback about this request"
                    )
                ],
                buttons=[
                    ApprovalButton(action="approve", label="✅ Approve", style="primary"),
                    ApprovalButton(action="reject", label="❌ Reject", style="danger")
                ]
            )

    async def _create_workflow(
        self,
        args: Dict[str, Any],
        request: AgentRequest
    ) -> AgentResponse:
        """Create workflow using WorkflowEngine"""
        try:
            workflow_type = args["workflow_type"]
            description = args["description"]
            steps_config = args.get("steps", [])

            # Convert steps to proper format and generate UI schemas for approvals
            steps = []
            has_approval = False
            for step_config in steps_config:
                step = {
                    "type": step_config["type"],
                    "handler": step_config.get("handler", "example_task"),
                    "input": step_config.get("input", {})
                }

                # Generate UI schema for approval steps
                if step["type"] == "approval":
                    has_approval = True
                    ui_schema = self._generate_approval_ui_schema(
                        workflow_type=workflow_type,
                        description=description,
                        step_config=step_config
                    )
                    step["input"]["ui_schema"] = ui_schema.model_dump()

                steps.append(step)

            # Create workflow via WorkflowEngine
            async with get_db_context() as db:
                engine = WorkflowEngine(db, self.event_bus)
                workflow = await engine.create_workflow(
                    workflow_type=workflow_type,
                    context={
                        "description": description,
                        "user_id": request.user_id,
                        "channel": request.channel
                    },
                    steps=steps
                )

                # Query for approval_id if approval steps exist
                approval_id = None
                if has_approval:
                    workflow_steps = await engine.get_workflow_steps(workflow.id)
                    approval_step = next(
                        (s for s in workflow_steps if s.step_type == "approval" and s.approval_id),
                        None
                    )
                    if approval_step:
                        approval_id = approval_step.approval_id

            # Build response message
            if has_approval:
                message = (
                    f"✅ I've created a {workflow_type} workflow with {len(steps)} steps. "
                    f"An approval will be sent to Slack when needed. "
                    f"Workflow ID: {workflow.id}"
                )
                if approval_id:
                    message += f"\nApproval ID: {approval_id}"
                status = "waiting_approval"
            else:
                message = (
                    f"✅ I've created a {workflow_type} workflow with {len(steps)} steps. "
                    f"It's now running. Workflow ID: {workflow.id}"
                )
                status = "active"

            logger.info(
                "workflow_created_by_agent",
                workflow_id=workflow.id,
                workflow_type=workflow_type,
                steps=len(steps),
                approval_id=approval_id
            )

            return AgentResponse(
                message=message,
                workflow_id=workflow.id,
                approval_id=approval_id,
                status=status,
                requires_approval=has_approval,
                metadata={
                    "workflow_type": workflow_type,
                    "steps_count": len(steps),
                    "description": description
                }
            )

        except Exception as e:
            logger.error(
                "workflow_creation_failed",
                error=str(e),
                exc_info=True
            )
            return AgentResponse(
                message=f"Failed to create workflow: {str(e)}",
                status="error",
                metadata={"error": str(e)}
            )

    async def _get_workflow_status(self, args: Dict[str, Any]) -> AgentResponse:
        """Get workflow status"""
        try:
            workflow_id = args["workflow_id"]

            async with get_db_context() as db:
                engine = WorkflowEngine(db)
                workflow = await engine.get_workflow(workflow_id)

            message = (
                f"Workflow {workflow_id}:\n"
                f"- Type: {workflow.workflow_type}\n"
                f"- State: {workflow.state}\n"
                f"- Created: {workflow.created_at}"
            )

            return AgentResponse(
                message=message,
                workflow_id=workflow_id,
                status="active",
                metadata={"workflow_state": workflow.state}
            )

        except Exception as e:
            return AgentResponse(
                message=f"Failed to get workflow status: {str(e)}",
                status="error",
                metadata={"error": str(e)}
            )

    async def _retry_workflow(self, args: Dict[str, Any], request: AgentRequest) -> AgentResponse:
        """Retry a failed or timed-out workflow"""
        try:
            workflow_id = args.get("workflow_id")

            # If workflow_id not provided, try to get it from conversation metadata
            if not workflow_id:
                workflow_id = request.metadata.get("workflow_id")

            if not workflow_id:
                return AgentResponse(
                    message="I need a workflow ID to retry. Which workflow would you like to retry?",
                    status="error",
                    metadata={"error": "workflow_id_required"}
                )

            async with get_db_context() as db:
                engine = WorkflowEngine(db, self.event_bus)
                workflow = await engine.retry_workflow(workflow_id)

            if workflow:
                message = (
                    f"🔄 **Retrying workflow!**\n\n"
                    f"Workflow ID: {workflow_id}\n"
                    f"Retry count: {workflow.retry_count}/{workflow.max_retries}\n\n"
                    f"I'll resume execution from the point of failure."
                )

                logger.info(
                    "workflow_retried_by_agent",
                    workflow_id=workflow_id,
                    retry_count=workflow.retry_count,
                    user_id=request.user_id
                )

                return AgentResponse(
                    message=message,
                    workflow_id=workflow_id,
                    status="active",
                    metadata={
                        "retry_count": workflow.retry_count,
                        "max_retries": workflow.max_retries
                    }
                )
            else:
                message = (
                    f"⚠️ **Cannot retry workflow**\n\n"
                    f"Workflow ID: {workflow_id}\n\n"
                    f"Maximum retry limit reached or workflow is not in a retryable state."
                )

                return AgentResponse(
                    message=message,
                    workflow_id=workflow_id,
                    status="error",
                    metadata={"error": "max_retries_exceeded"}
                )

        except Exception as e:
            logger.error(
                "workflow_retry_failed",
                error=str(e),
                workflow_id=args.get("workflow_id"),
                exc_info=True
            )
            return AgentResponse(
                message=f"Failed to retry workflow: {str(e)}",
                status="error",
                metadata={"error": str(e)}
            )

    async def _rollback_approval(self, args: Dict[str, Any], request: AgentRequest) -> AgentResponse:
        """Rollback a mistakenly rejected approval"""
        try:
            approval_id = args.get("approval_id")

            # If approval_id not provided, try to get it from conversation metadata
            if not approval_id:
                approval_id = request.metadata.get("approval_id")

            if not approval_id:
                return AgentResponse(
                    message="I need an approval ID to rollback. Which approval would you like to rollback?",
                    status="error",
                    metadata={"error": "approval_id_required"}
                )

            async with get_db_context() as db:
                from app.core.approval_service import ApprovalService

                approval_service = ApprovalService(db, self.event_bus)
                approval = await approval_service.rollback_approval(approval_id)

            message = (
                f"↩️ **Approval rolled back!**\n\n"
                f"Approval ID: {approval_id}\n\n"
                f"The approval has been reset to PENDING. You can now approve it again via Slack."
            )

            logger.info(
                "approval_rolled_back_by_agent",
                approval_id=approval_id,
                user_id=request.user_id
            )

            return AgentResponse(
                message=message,
                approval_id=approval_id,
                status="waiting_approval",
                metadata={"approval_status": "PENDING"}
            )

        except ValueError as e:
            # Validation errors (e.g., approval not in REJECTED state)
            return AgentResponse(
                message=f"Cannot rollback approval: {str(e)}",
                status="error",
                metadata={"error": str(e)}
            )
        except Exception as e:
            logger.error(
                "approval_rollback_failed",
                error=str(e),
                approval_id=args.get("approval_id"),
                exc_info=True
            )
            return AgentResponse(
                message=f"Failed to rollback approval: {str(e)}",
                status="error",
                metadata={"error": str(e)}
            )
