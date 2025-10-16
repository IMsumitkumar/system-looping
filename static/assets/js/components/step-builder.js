/**
 * Step Builder Component
 * Handles multi-step workflow creation with visual step pipeline
 */

const StepBuilder = {
    steps: [],
    currentStepIndex: null,

    init() {
        this.steps = [];
        this.currentStepIndex = null;
        this.render();
    },

    addTaskStep() {
        const step = {
            type: 'task',
            handler: '',
            input: {}
        };
        this.steps.push(step);
        this.render();
        this.scrollToBottom();
    },

    addApprovalStep() {
        const step = {
            type: 'approval',
            input: {
                ui_schema: {
                    title: '',
                    description: '',
                    fields: [],
                    buttons: [
                        { action: 'approve', label: 'Approve', style: 'primary' },
                        { action: 'reject', label: 'Reject', style: 'danger' }
                    ]
                },
                timeout_seconds: 3600
            }
        };
        this.steps.push(step);
        this.render();
        this.scrollToBottom();
    },

    removeStep(index) {
        this.steps.splice(index, 1);
        this.render();
    },

    updateStep(index, field, value) {
        if (this.steps[index].type === 'task') {
            if (field === 'handler') {
                this.steps[index].handler = value;
            } else if (field === 'input') {
                try {
                    this.steps[index].input = JSON.parse(value);
                } catch (e) {
                    // Invalid JSON, keep as is
                }
            }
        } else if (this.steps[index].type === 'approval') {
            if (field === 'title') {
                this.steps[index].input.ui_schema.title = value;
            } else if (field === 'description') {
                this.steps[index].input.ui_schema.description = value;
            } else if (field === 'timeout') {
                this.steps[index].input.timeout_seconds = parseInt(value);
            }
        }
    },

    getSteps() {
        return this.steps;
    },

    scrollToBottom() {
        const container = document.getElementById('stepBuilderContainer');
        if (container) {
            setTimeout(() => {
                container.scrollTop = container.scrollHeight;
            }, 100);
        }
    },

    render() {
        const container = document.getElementById('stepBuilderContainer');
        if (!container) return;

        if (this.steps.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="padding: 32px;">
                    <div class="empty-state__icon">${Icons.cubeTransparent(48)}</div>
                    <h3 class="empty-state__title">No Steps Yet</h3>
                    <p class="empty-state__description">
                        Add task steps (automated) and approval steps (human-in-the-loop) to create your workflow pipeline.
                    </p>
                </div>
            `;
            return;
        }

        const stepsHTML = this.steps.map((step, index) => {
            const stepNumber = index + 1;
            const isLast = index === this.steps.length - 1;

            if (step.type === 'task') {
                return `
                    <div class="step-card" data-step-index="${index}">
                        <div class="step-card__header">
                            <div class="step-card__number">${stepNumber}</div>
                            <div class="step-card__type">
                                <span class="badge badge--info">${Icons.commandLine(14)} Task</span>
                            </div>
                            <button class="btn-icon btn-icon--sm" onclick="StepBuilder.removeStep(${index})" title="Remove step">
                                ${Icons.trash(16)}
                            </button>
                        </div>
                        <div class="step-card__body">
                            <div class="form-group">
                                <label class="form-label form-label--sm">Handler Name</label>
                                <input type="text" class="form-input form-input--sm"
                                       value="${step.handler || ''}"
                                       placeholder="example_task"
                                       onchange="StepBuilder.updateStep(${index}, 'handler', this.value)">
                            </div>
                            <div class="form-group">
                                <label class="form-label form-label--sm">Input Data (JSON)</label>
                                <textarea class="form-textarea form-textarea--sm"
                                          placeholder='{"action": "backup_database"}'
                                          onchange="StepBuilder.updateStep(${index}, 'input', this.value)"
                                          style="min-height: 60px; font-family: 'SF Mono', Monaco, monospace; font-size: 12px;">${JSON.stringify(step.input, null, 2)}</textarea>
                            </div>
                        </div>
                        ${!isLast ? `<div class="step-connector">${Icons.arrowDown(20)}</div>` : ''}
                    </div>
                `;
            } else {
                return `
                    <div class="step-card step-card--approval" data-step-index="${index}">
                        <div class="step-card__header">
                            <div class="step-card__number">${stepNumber}</div>
                            <div class="step-card__type">
                                <span class="badge badge--warning">${Icons.userCircle(14)} Approval</span>
                            </div>
                            <button class="btn-icon btn-icon--sm" onclick="StepBuilder.removeStep(${index})" title="Remove step">
                                ${Icons.trash(16)}
                            </button>
                        </div>
                        <div class="step-card__body">
                            <div class="form-group">
                                <label class="form-label form-label--sm">Approval Title</label>
                                <input type="text" class="form-input form-input--sm"
                                       value="${step.input.ui_schema.title || ''}"
                                       placeholder="Approve Deployment"
                                       onchange="StepBuilder.updateStep(${index}, 'title', this.value)">
                            </div>
                            <div class="form-group">
                                <label class="form-label form-label--sm">Description</label>
                                <textarea class="form-textarea form-textarea--sm"
                                          placeholder="Review and approve this step"
                                          onchange="StepBuilder.updateStep(${index}, 'description', this.value)"
                                          style="min-height: 60px;">${step.input.ui_schema.description || ''}</textarea>
                            </div>
                            <div class="form-group">
                                <label class="form-label form-label--sm">Timeout (seconds)</label>
                                <input type="number" class="form-input form-input--sm"
                                       value="${step.input.timeout_seconds || 3600}"
                                       min="60"
                                       onchange="StepBuilder.updateStep(${index}, 'timeout', this.value)">
                            </div>
                        </div>
                        ${!isLast ? `<div class="step-connector">${Icons.arrowDown(20)}</div>` : ''}
                    </div>
                `;
            }
        }).join('');

        container.innerHTML = stepsHTML;
    }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.StepBuilder = StepBuilder;
}
