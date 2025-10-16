/**
 * Custom Modal & Toast System
 * Replaces ALL native confirm() and alert() dialogs with branded modals
 */

const Modal = {
  /**
   * Confirmation Modal
   * Replaces native confirm() with a beautiful branded dialog
   * @param {object} options - Modal configuration
   * @returns {Promise<boolean>} Resolves to true if confirmed, false if cancelled
   */
  confirm({
    title = 'Confirm Action',
    message = 'Are you sure you want to proceed?',
    variant = 'default', // 'default', 'warning', 'danger', 'success'
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    icon = null
  }) {
    return new Promise((resolve) => {
      // Create modal overlay
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-labelledby', 'modal-title');

      // Icon mapping
      const iconMap = {
        default: Icons.informationCircle(48),
        warning: Icons.exclamationTriangle(48),
        danger: Icons.xCircle(48),
        success: Icons.checkCircle(48)
      };

      const modalIcon = icon || iconMap[variant];

      // Create modal content
      overlay.innerHTML = `
        <div class="modal modal--${variant}">
          <div class="modal__header">
            <h2 id="modal-title" class="modal__title">${title}</h2>
            <button class="modal__close" aria-label="Close modal" data-action="cancel">
              ${Icons.x(20)}
            </button>
          </div>
          <div class="modal__body">
            <div class="modal__icon modal__icon--${variant}">
              ${modalIcon}
            </div>
            <div class="modal__message">${message}</div>
          </div>
          <div class="modal__footer">
            <button class="btn btn--secondary" data-action="cancel">
              ${cancelText}
            </button>
            <button class="btn btn--${variant === 'danger' ? 'danger' : 'primary'}" data-action="confirm">
              ${confirmText}
            </button>
          </div>
        </div>
      `;

      // Add to DOM
      document.body.appendChild(overlay);

      // Focus first button
      setTimeout(() => {
        overlay.querySelector('[data-action="confirm"]').focus();
      }, 100);

      // Handle clicks
      const handleAction = (action) => {
        this.close(overlay);
        resolve(action === 'confirm');
      };

      // Event listeners
      overlay.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          handleAction(btn.dataset.action);
        });
      });

      // Click outside to cancel (optional)
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
          handleAction('cancel');
        }
      });

      // ESC key to cancel
      const escHandler = (e) => {
        if (e.key === 'Escape') {
          handleAction('cancel');
          document.removeEventListener('keydown', escHandler);
        }
      };
      document.addEventListener('keydown', escHandler);
    });
  },

  /**
   * Alert Modal (Informational)
   * Replaces native alert() with a better dialog
   */
  alert({
    title = 'Notice',
    message = '',
    variant = 'default',
    buttonText = 'OK'
  }) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'modal-overlay';

      const iconMap = {
        default: Icons.informationCircle(48),
        success: Icons.checkCircle(48),
        warning: Icons.exclamationTriangle(48),
        error: Icons.xCircle(48)
      };

      overlay.innerHTML = `
        <div class="modal modal--${variant}">
          <div class="modal__header">
            <h2 class="modal__title">${title}</h2>
            <button class="modal__close" aria-label="Close" data-action="close">
              ${Icons.x(20)}
            </button>
          </div>
          <div class="modal__body">
            <div class="modal__icon modal__icon--${variant}">
              ${iconMap[variant]}
            </div>
            <div class="modal__message">${message}</div>
          </div>
          <div class="modal__footer">
            <button class="btn btn--primary" data-action="close">
              ${buttonText}
            </button>
          </div>
        </div>
      `;

      document.body.appendChild(overlay);

      const handleClose = () => {
        this.close(overlay);
        resolve(true);
      };

      overlay.querySelectorAll('[data-action="close"]').forEach(btn => {
        btn.addEventListener('click', handleClose);
      });

      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) handleClose();
      });

      document.addEventListener('keydown', function escHandler(e) {
        if (e.key === 'Escape') {
          handleClose();
          document.removeEventListener('keydown', escHandler);
        }
      });
    });
  },

  /**
   * Custom Modal (For forms and complex content)
   * @param {object} options - Modal configuration
   */
  custom({
    title = '',
    content = '',
    footer = '',
    variant = 'default',
    onClose = null
  }) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    overlay.innerHTML = `
      <div class="modal modal--${variant}">
        <div class="modal__header">
          <h2 class="modal__title">${title}</h2>
          <button class="modal__close" aria-label="Close" data-action="close">
            ${Icons.x(20)}
          </button>
        </div>
        <div class="modal__body">
          ${content}
        </div>
        ${footer ? `<div class="modal__footer">${footer}</div>` : ''}
      </div>
    `;

    document.body.appendChild(overlay);

    const handleClose = () => {
      this.close(overlay);
      if (onClose) onClose();
    };

    overlay.querySelectorAll('[data-action="close"]').forEach(btn => {
      btn.addEventListener('click', handleClose);
    });

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) handleClose();
    });

    return overlay;
  },

  /**
   * Close modal with animation
   */
  close(modalElement) {
    modalElement.style.animation = 'modal-fade-out 0.2s ease';
    setTimeout(() => {
      if (modalElement && modalElement.parentNode) {
        modalElement.remove();
      }
    }, 200);
  },

  /**
   * Show workflow detail modal with steps
   */
  async showWorkflowDetail(workflowId) {
    try {
      // Load workflow details
      const workflow = await API.getWorkflow(workflowId);
      const eventsData = await API.getWorkflowEvents(workflowId);

      // Try to get steps (may not exist for simple workflows)
      let steps = [];
      try {
        steps = await API.getWorkflowSteps(workflowId);
      } catch (e) {
        // No steps, it's a simple workflow
// console.log('No steps for workflow:', workflowId);
      }

      // Build steps HTML if exists (with inline approvals for running approval steps)
      let stepsHTML = '';
      if (steps && steps.length > 0) {
        // Fetch approval details for running approval steps
        const runningApprovalSteps = steps.filter(s => s.step_type === 'approval' && s.status === 'running' && s.approval_id);
        const approvalDetailsMap = {};

        if (runningApprovalSteps.length > 0) {
          try {
            const approvalPromises = runningApprovalSteps.map(async (step) => {
              try {
                const approval = await API.getApproval(step.approval_id);
                approvalDetailsMap[step.id] = approval;
              } catch (e) {
// console.error('Failed to load approval:', step.approval_id, e);
              }
            });
            await Promise.all(approvalPromises);
          } catch (e) {
// console.error('Failed to load approval details:', e);
          }
        }

        stepsHTML = `
          <div class="mb-6">
            <h4 class="mb-4" style="font-size: 16px; font-weight: 600;">Workflow Steps</h4>
            <div class="step-timeline">
              ${steps.map((step, index) => {
                const statusColor = {
                  'completed': 'success',
                  'running': 'info',
                  'failed': 'danger',
                  'pending': 'secondary'
                }[step.status] || 'secondary';

                // Check if this is a running approval step with approval details
                const isRunningApproval = step.step_type === 'approval' && step.status === 'running';
                const approval = approvalDetailsMap[step.id];

                // Check if this is a failed approval step (rejected)
                const isFailedApproval = step.step_type === 'approval' && step.status === 'failed' && step.task_output && step.task_output.decision === 'rejected';

                // Generate inline approval form if available
                let inlineApprovalHTML = '';
                if (isRunningApproval && approval) {
                  // Build form fields HTML inline
                  const fieldsHTML = (approval.ui_schema.fields || []).map(field => `
                    <div class="form-group">
                      <label class="form-label ${field.required ? 'form-label--required' : ''}">
                        ${field.label}
                      </label>
                      ${field.type === 'select' ? `
                        <select name="${field.name}" class="form-select" ${field.required ? 'required' : ''}>
                          ${(field.options || []).map(opt => `
                            <option value="${opt.value || opt}">${opt.label || opt}</option>
                          `).join('')}
                        </select>
                      ` : field.type === 'textarea' ? `
                        <textarea name="${field.name}" class="form-textarea" ${field.required ? 'required' : ''}
                                  placeholder="${field.placeholder || ''}"></textarea>
                      ` : `
                        <input type="${field.type || 'text'}" name="${field.name}" class="form-input"
                               ${field.required ? 'required' : ''} placeholder="${field.placeholder || ''}">
                      `}
                    </div>
                  `).join('');

                  inlineApprovalHTML = `
                    <div class="inline-approval-form" style="margin-top: 12px; padding: 12px; background: var(--surface-secondary); border-radius: 6px; border: 2px solid var(--color-info);">
                      <div style="margin-bottom: 12px;">
                        <h5 style="font-size: 14px; font-weight: 600; margin-bottom: 4px;">${approval.ui_schema.title || 'Approval Required'}</h5>
                        <p style="font-size: 13px; color: var(--gray-600); margin: 0;">${approval.ui_schema.description || 'Please review and approve'}</p>
                      </div>
                      <div style="display: flex; gap: 8px; margin-top: 12px;">
                        <button class="btn btn--sm btn--primary" onclick="event.stopPropagation(); Modal.close(document.querySelector('.modal-overlay')); Approvals.handleApprovalById('${approval.id}', 'approve')">
                          ${Icons.check(14)} Approve
                        </button>
                        <button class="btn btn--sm btn--danger" onclick="event.stopPropagation(); Modal.close(document.querySelector('.modal-overlay')); Approvals.handleApprovalById('${approval.id}', 'reject')">
                          ${Icons.x(14)} Reject
                        </button>
                      </div>
                    </div>
                  `;
                }

                // Add rollback button for rejected approvals
                if (isFailedApproval && step.approval_id) {
                  inlineApprovalHTML = `
                    <div class="inline-approval-form" style="margin-top: 12px; padding: 12px; background: var(--surface-secondary); border-radius: 6px; border: 2px solid var(--color-danger);">
                      <div style="margin-bottom: 12px;">
                        <h5 style="font-size: 14px; font-weight: 600; margin-bottom: 4px; color: var(--color-danger);">Approval Rejected</h5>
                        <p style="font-size: 13px; color: var(--gray-600); margin: 0;">This approval was rejected. You can rollback to retry.</p>
                      </div>
                      <div style="display: flex; gap: 8px; margin-top: 12px;">
                        <button class="btn btn--sm btn--primary" onclick="Modal.handleStepRollback('${step.approval_id}', '${workflowId}')">
                          ${Icons.arrowPath(14)} Rollback & Retry
                        </button>
                      </div>
                    </div>
                  `;
                }

                return `
                  <div class="step-timeline-item step-timeline-item--${statusColor}">
                    <div class="step-timeline-marker">${index + 1}</div>
                    <div class="step-timeline-content">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div>
                          <span class="badge badge--${statusColor} badge--sm">${step.step_type}</span>
                          ${step.task_handler ? `<code style="margin-left: 8px; font-size: 12px;">${step.task_handler}</code>` : ''}
                        </div>
                        <span class="badge badge--${statusColor}">${step.status}</span>
                      </div>
                      ${step.task_input ? `<div style="margin-bottom: 4px;"><strong style="font-size: 11px;">Input:</strong><pre>${JSON.stringify(step.task_input, null, 2)}</pre></div>` : ''}
                      ${step.task_output ? `<div><strong style="font-size: 11px;">Output:</strong><pre>${JSON.stringify(step.task_output, null, 2)}</pre></div>` : ''}
                      ${inlineApprovalHTML}
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        `;
      }

      // Build events HTML
      const eventsHTML = eventsData.events && eventsData.events.length > 0 ? `
        <div class="mb-6">
          <h4 class="mb-4" style="font-size: 16px; font-weight: 600;">Events Timeline</h4>
          <div class="timeline">
            ${eventsData.events.map(event => {
              // Format event title with state transition details
              let eventTitle = event.event_type;
              if (event.event_type === 'workflow.state_changed' && event.event_data) {
                const from = event.event_data.from_state || 'UNKNOWN';
                const to = event.event_data.to_state || 'UNKNOWN';
                eventTitle = `${event.event_type} • <span style="font-size: 12px; color: var(--gray-600);">${from} → ${to}</span>`;
              }
              return `
                <div class="timeline-item">
                  <div class="timeline-item__title">${eventTitle}</div>
                  <div class="timeline-item__meta">
                    <span>${Utils.formatTimeAgo(event.occurred_at)}</span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      ` : '';

      // Build action buttons
      const canRetry = ['FAILED', 'TIMEOUT'].includes(workflow.state) && workflow.retry_count < workflow.max_retries;
      const canCancel = ['RUNNING', 'WAITING_APPROVAL'].includes(workflow.state);


      const canRollback = workflow.state === 'REJECTED' && workflow.is_multi_step;

      const actionsHTML = (canRetry || canCancel || canRollback) ? `
        <div class="modal-actions" style="display: flex; gap: 8px; margin-bottom: 16px; padding: 12px; background: var(--surface-secondary); border-radius: 8px;">
          ${canRetry ? `
            <button class="btn btn--sm btn--warning" onclick="Modal.handleRetry('${workflow.id}')">
              ${Icons.arrowPath(16)} Retry Workflow
            </button>
          ` : ''}
          ${canCancel ? `
            <button class="btn btn--sm btn--danger" onclick="Modal.handleCancel('${workflow.id}')">
              ${Icons.xCircle(16)} Cancel
            </button>
          ` : ''}
          ${canRollback ? `
            <button class="btn btn--sm btn--primary" onclick="Modal.handleRollback('${workflow.id}')">
              ${Icons.arrowPath(16)} Rollback Rejection
            </button>
          ` : ''}
        </div>
      ` : '';

      const content = `
        ${actionsHTML}
        <div style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <span class="badge badge--${workflow.state.toLowerCase().replace('_', '')}">${workflow.state}</span>
            <span style="font-size: 12px; color: var(--gray-600);">Created ${Utils.formatTimeAgo(workflow.created_at)}</span>
          </div>
          <div style="font-size: 14px; color: var(--gray-600); margin-bottom: 8px;">
            <strong>Type:</strong> ${workflow.workflow_type}
          </div>
          <div style="font-size: 14px; color: var(--gray-600); margin-bottom: 8px;">
            <strong>ID:</strong> <code style="font-size: 12px;">${workflow.id}</code>
          </div>
          <div style="font-size: 14px; color: var(--gray-600); margin-bottom: 8px;">
            <strong>Version:</strong> ${workflow.version || 1} ${workflow.updated_at ? `• Updated ${Utils.formatTimeAgo(workflow.updated_at)}` : ''}
          </div>
          ${workflow.retry_count > 0 ? `
            <div style="font-size: 14px; color: var(--gray-600);">
              <strong>Retries:</strong> ${workflow.retry_count}/${workflow.max_retries}
              ${workflow.last_retry_at ? ` • Last retry ${Utils.formatTimeAgo(workflow.last_retry_at)}` : ''}
            </div>
          ` : ''}
        </div>
        ${workflow.context && Object.keys(workflow.context).length > 0 ? `
          <div style="margin-bottom: 16px;">
            <h4 style="font-size: 14px; font-weight: 600; margin-bottom: 8px;">Context</h4>
            <pre style="background: var(--surface-secondary); padding: 12px; border-radius: 6px; font-size: 12px; overflow-x: auto;">${JSON.stringify(workflow.context, null, 2)}</pre>
          </div>
        ` : ''}
        ${stepsHTML}
        ${eventsHTML}
      `;

      this.custom({
        title: `Workflow Details`,
        content: content,
        variant: 'default'
      });

    } catch (error) {
// console.error('Error loading workflow details:', error);
      Toast.error('Failed to load workflow details');
    }
  },

  /**
   * Handle workflow retry from modal
   */
  async handleRetry(workflowId) {
    // Close current modal
    const currentModal = document.querySelector('.modal-overlay');
    if (currentModal) this.close(currentModal);

    // Call the retry function
    await Workflows.retryWorkflow(workflowId);
  },

  /**
   * Handle workflow cancel from modal
   */
  async handleCancel(workflowId) {
    // Close current modal
    const currentModal = document.querySelector('.modal-overlay');
    if (currentModal) this.close(currentModal);

    // Call the cancel function
    await Workflows.cancelWorkflow(workflowId);
  },

  /**
   * Handle approval rollback from modal
   */
  async handleRollback(workflowId) {
    try {
      // Get workflow to find the rejected approval
      const workflow = await API.getWorkflow(workflowId);

      let approvalId = null;

      // Check if this is a multi-step workflow
      if (workflow.is_multi_step) {
        // For multi-step workflows, find the failed approval step
        const steps = await API.getWorkflowSteps(workflowId);
        const failedApprovalStep = steps.find(s =>
          s.step_type === 'approval' &&
          s.status === 'failed' &&
          s.approval_id
        );

        if (failedApprovalStep) {
          approvalId = failedApprovalStep.approval_id;
        }
      } else {
        // For simple workflows, check events
        const eventsData = await API.getWorkflowEvents(workflowId);
        const rejectionEvent = eventsData.events.find(e =>
          e.event_type === 'approval.received' &&
          e.event_data.decision === 'reject'
        );

        if (rejectionEvent && rejectionEvent.event_data.approval_id) {
          approvalId = rejectionEvent.event_data.approval_id;
        }
      }

      if (!approvalId) {
        Toast.error('Could not find rejected approval');
        return;
      }

      // Confirm rollback
      const confirmed = await this.confirm({
        title: 'Rollback Rejection?',
        message: 'This will reset the approval back to running state, allowing you to approve or reject again.',
        variant: 'warning',
        confirmText: 'Rollback',
        cancelText: 'Cancel'
      });

      if (!confirmed) return;

      // Rollback the approval
      await API.rollbackApproval(approvalId);
      Toast.success('Approval rolled back successfully');

      // Close current modal
      const currentModal = document.querySelector('.modal-overlay');
      if (currentModal) this.close(currentModal);

      // Re-open with fresh data to show updated state
      setTimeout(() => {
        this.showWorkflowDetail(workflowId);
      }, 300);

    } catch (error) {
// console.error('Error rolling back approval:', error);
      Toast.error(error.message || 'Failed to rollback approval');
    }
  },

  /**
   * Handle approval rollback from step node
   */
  async handleStepRollback(approvalId, workflowId) {
    try {
      // Confirm rollback
      const confirmed = await this.confirm({
        title: 'Rollback Rejection?',
        message: 'This will reset the approval back to running state, allowing you to approve or reject again.',
        variant: 'warning',
        confirmText: 'Rollback',
        cancelText: 'Cancel'
      });

      if (!confirmed) return;

      // Rollback the approval
      await API.rollbackApproval(approvalId);
      Toast.success('Approval rolled back successfully');

      // Close current modal
      const currentModal = document.querySelector('.modal-overlay');
      if (currentModal) this.close(currentModal);

      // Re-open with fresh data to show updated state
      setTimeout(() => {
        this.showWorkflowDetail(workflowId);
      }, 300);

    } catch (error) {
// console.error('Error rolling back approval:', error);
      Toast.error(error.message || 'Failed to rollback approval');
    }
  },

};

// ===========================================
// Toast Notification System
// ===========================================

const Toast = {
  container: null,

  /**
   * Initialize toast container
   */
  init() {
    if (!this.container) {
      this.container = document.getElementById('toast-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        document.body.appendChild(this.container);
      }
    }
  },

  /**
   * Show toast notification
   * @param {string} message - Toast message
   * @param {string} type - Toast type: 'success', 'error', 'warning', 'info'
   * @param {number} duration - Auto-dismiss duration (ms), 0 for no auto-dismiss
   */
  show(message, type = 'info', duration = CONFIG.TOAST_DURATION) {
    this.init();

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'polite');

    // Icon mapping
    const iconMap = {
      success: Icons.checkCircle(20),
      error: Icons.xCircle(20),
      warning: Icons.exclamationTriangle(20),
      info: Icons.informationCircle(20)
    };

    toast.innerHTML = `
      <span class="toast__icon">${iconMap[type]}</span>
      <span class="toast__message">${message}</span>
      <button class="toast__close" aria-label="Close notification">
        ${Icons.x(16)}
      </button>
      ${duration > 0 ? `<div class="toast__progress" style="animation-duration: ${duration}ms"></div>` : ''}
    `;

    this.container.appendChild(toast);

    // Close button handler
    toast.querySelector('.toast__close').addEventListener('click', () => {
      this.dismiss(toast);
    });

    // Auto-dismiss
    if (duration > 0) {
      setTimeout(() => {
        this.dismiss(toast);
      }, duration);
    }

    return toast;
  },

  /**
   * Dismiss toast with animation
   */
  dismiss(toastElement) {
    toastElement.style.animation = 'toast-slide-out 0.3s ease';
    setTimeout(() => {
      if (toastElement && toastElement.parentNode) {
        toastElement.remove();
      }
    }, 300);
  },

  // Convenience methods
  success(message, duration) {
    return this.show(message, 'success', duration);
  },

  error(message, duration) {
    return this.show(message, 'error', duration);
  },

  warning(message, duration) {
    return this.show(message, 'warning', duration);
  },

  info(message, duration) {
    return this.show(message, 'info', duration);
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Modal = Modal;
  window.Toast = Toast;
}
