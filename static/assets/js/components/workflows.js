/**
 * Workflows Component
 * Workflow list and management
 */

const Workflows = {
  /**
   * Load and render workflows
   */
  async load() {
    const stateFilter = document.getElementById('stateFilter')?.value || '';
    const container = document.getElementById('workflowList');
    if (!container) return;

    try {
      State.setLoading('workflows', true);

      const workflows = await API.getWorkflows(stateFilter ? { state: stateFilter } : {});
      State.setWorkflows(workflows);

      if (!workflows || workflows.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state__icon">${Icons.layers(64)}</div>
            <h3 class="empty-state__title">No Workflows Found</h3>
            <p class="empty-state__description">
              ${stateFilter ? `No workflows with state "${stateFilter}"` : 'Create your first workflow to get started'}
            </p>
          </div>
        `;
        return;
      }

      container.innerHTML = workflows.map(wf => this.renderWorkflowItem(wf)).join('');

    } catch (error) {
// console.error('Failed to load workflows:', error);
      Toast.error('Failed to load workflows');
      container.innerHTML = `
        <div class="empty-state text-danger">
          <div class="empty-state__title">Error loading workflows</div>
          <div class="empty-state__description">${error.message}</div>
        </div>
      `;
    } finally {
      State.setLoading('workflows', false);
    }
  },

  /**
   * Render single workflow item
   */
  renderWorkflowItem(workflow) {
    // For display purposes, we use the workflow state directly
    // The backend should maintain correct state for multi-step workflows
    const displayState = workflow.state;
    const badgeClass = `badge--${displayState.toLowerCase().replace('_', '')}`;
    const hasRetries = workflow.retry_count > 0;
    // Can only retry FAILED or TIMEOUT workflows (not REJECTED - that's a user decision)
    const canRetry = ['FAILED', 'TIMEOUT'].includes(workflow.state)
                     && workflow.retry_count < workflow.max_retries;

    // Calculate step progress if steps data is available
    let stepProgressHTML = '';
    if (workflow.steps && workflow.steps.length > 0) {
      const completedSteps = workflow.steps.filter(s => s.status === 'completed').length;
      const totalSteps = workflow.steps.length;
      const progressPercentage = (completedSteps / totalSteps) * 100;

      stepProgressHTML = `
        <div class="step-progress" style="margin-top: 8px;">
          <div class="step-progress__bar" style="background: var(--gray-200); height: 6px; border-radius: 3px; overflow: hidden;">
            <div style="width: ${progressPercentage}%; height: 100%; background: var(--color-primary); transition: width 0.3s;"></div>
          </div>
          <span class="step-progress__text" style="font-size: 11px; color: var(--gray-600); margin-top: 4px; display: inline-block;">
            ${completedSteps}/${totalSteps} steps completed
          </span>
        </div>
      `;
    }

    return `
      <div class="workflow-item" onclick="Modal.showWorkflowDetail('${workflow.id}')" style="cursor: pointer;">
        <div class="workflow-item__info">
          <div class="workflow-item__id">
            <span class="text-mono">${workflow.id}</span>
            <button class="copy-btn" onclick="event.stopPropagation(); Utils.copyToClipboard('${workflow.id}')" aria-label="Copy ID">
              ${Icons.clipboard(14)}
            </button>
          </div>
          <div class="workflow-item__type">${workflow.workflow_type}</div>
          <div class="workflow-item__meta">
            Created: ${Utils.formatTimeAgo(workflow.created_at)}
            ${hasRetries ? `<span class="text-warning"> • Retry ${workflow.retry_count}/${workflow.max_retries}</span>` : ''}
          </div>
          ${stepProgressHTML}
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          ${canRetry ? `
            <button class="btn btn--sm btn--warning" onclick="event.stopPropagation(); Workflows.retryWorkflow('${workflow.id}')" title="Retry workflow">
              ${Icons.arrowPath(14)} Retry (${workflow.retry_count}/${workflow.max_retries})
            </button>
          ` : ''}
          <span class="badge badge--workflow-type">${workflow.is_multi_step ? 'Multi-Step' : 'Single'}</span>
          <span class="badge ${badgeClass}">${displayState}</span>
        </div>
      </div>
    `;
  },

  /**
   * Filter workflows by search
   */
  filter() {
    const search = document.getElementById('workflowSearch')?.value.toLowerCase() || '';
    const items = document.querySelectorAll('.workflow-item');

    items.forEach(item => {
      const text = item.textContent.toLowerCase();
      item.style.display = text.includes(search) ? 'flex' : 'none';
    });
  },

  /**
   * Retry a failed or timeout workflow
   */
  async retryWorkflow(workflowId) {
    const confirmed = await Modal.confirm({
      title: 'Retry Workflow?',
      message: 'This will retry the failed workflow execution.',
      variant: 'warning',
      confirmText: 'Retry',
      cancelText: 'Cancel'
    });

    if (!confirmed) return;

    try {
      await API.retryWorkflow(workflowId);
      Toast.success('Workflow retry initiated');
      await this.load();
    } catch (error) {
// console.error('Failed to retry workflow:', error);
      Toast.error(error.message || 'Failed to retry workflow');
    }
  },

  /**
   * Cancel a running workflow
   */
  async cancelWorkflow(workflowId) {
    const confirmed = await Modal.confirm({
      title: 'Cancel Workflow?',
      message: 'This will mark the workflow as failed and stop execution.',
      variant: 'danger',
      confirmText: 'Cancel Workflow',
      cancelText: 'Keep Running'
    });

    if (!confirmed) return;

    try {
      await API.cancelWorkflow(workflowId);
      Toast.success('Workflow cancelled');
      await this.load();
    } catch (error) {
// console.error('Failed to cancel workflow:', error);
      Toast.error(error.message || 'Failed to cancel workflow');
    }
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Workflows = Workflows;
}
