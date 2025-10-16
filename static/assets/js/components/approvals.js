/**
 * Approvals Component
 * Approval cards and submission with CUSTOM MODALS (no native dialogs)
 */

const Approvals = {
  /**
   * Load pending approvals
   */
  async load() {
    const container = document.getElementById('approvalsList');
    if (!container) return;

    try {
      State.setLoading('approvals', true);

      const approvals = await API.getPendingApprovals();
      State.setApprovals(approvals);

      if (!approvals || approvals.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state__icon">${Icons.checkCircle(64)}</div>
            <h3 class="empty-state__title">All Caught Up!</h3>
            <p class="empty-state__description">No pending approvals right now.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = approvals.map(approval => this.renderApprovalCard(approval)).join('');

    } catch (error) {
// console.error('Failed to load approvals:', error);
      Toast.error('Failed to load approvals');
    } finally {
      State.setLoading('approvals', false);
    }
  },

  /**
   * Render single approval card
   */
  renderApprovalCard(approval) {
    // Calculate time remaining based on requested_at and expires_at
    const now = Date.now() / 1000; // Convert to seconds
    const secondsRemaining = approval.expires_at - now;
    const minutesRemaining = Math.floor(secondsRemaining / 60);
    const isUrgent = minutesRemaining < 60;

    let timeRemainingText;
    if (secondsRemaining < 0) {
      timeRemainingText = 'EXPIRED';
    } else if (minutesRemaining < 60) {
      timeRemainingText = `${minutesRemaining}m remaining`;
    } else {
      const hoursRemaining = Math.floor(minutesRemaining / 60);
      timeRemainingText = `${hoursRemaining}h remaining`;
    }

    // Extract title and description from ui_schema
    const title = approval.ui_schema?.title || 'Approval Request';
    const description = approval.ui_schema?.description || 'Please review and approve this request';

    return `
      <div class="card-approval ${isUrgent ? 'card-approval--urgent' : ''}">
        ${isUrgent && secondsRemaining > 0 ? `
          <div class="alert alert--warning" style="margin-bottom: 12px;">
            ${Icons.exclamationTriangle(16)} <strong>Urgent:</strong> This approval expires in ${minutesRemaining} minutes!
          </div>
        ` : ''}
        ${secondsRemaining < 0 ? `
          <div class="alert alert--danger" style="margin-bottom: 12px;">
            ${Icons.xCircle(16)} <strong>Expired:</strong> This approval has timed out.
          </div>
        ` : ''}
        <div class="card-approval__header">
          <div>
            <h3 class="card-approval__title">${title}</h3>
            <div class="card-approval__time ${isUrgent ? 'card-approval__time--urgent' : ''}">
              ${isUrgent ? Icons.clock(16) + ' ' : ''}${timeRemainingText}
            </div>
          </div>
        </div>

        <div class="card-approval__context">${description}</div>

        <div class="card-approval__meta">
          <div class="card-approval__meta-item">
            <strong>Approval ID:</strong> ${approval.id.substring(0, 12)}...
          </div>
          <div class="card-approval__meta-item">
            <strong>Workflow ID:</strong> ${approval.workflow_id.substring(0, 12)}...
          </div>
          <div class="card-approval__meta-item">
            <strong>Requested:</strong> ${Utils.formatTimeAgo(approval.requested_at)}
          </div>
        </div>

        <div class="card-approval__actions">
          <button class="btn btn--primary" onclick="Approvals.handleApprovalById('${approval.id}', 'approve')">
            ${Icons.check(16)} Approve
          </button>
          <button class="btn btn--danger" onclick="Approvals.handleApprovalById('${approval.id}', 'reject')">
            ${Icons.x(16)} Reject
          </button>
        </div>
      </div>
    `;
  },

  // Track in-progress approvals to prevent double-clicks
  inProgressApprovals: new Set(),

  /**
   * Handle approval by approval ID directly - for new multi-step approvals
   */
  async handleApprovalById(approvalId, decision) {
    // Prevent duplicate handling if already in progress
    const key = `${approvalId}:${decision}`;
    if (this.inProgressApprovals.has(key)) {
// console.log('Approval already being processed, ignoring duplicate click');
      return;
    }

    try {
      this.inProgressApprovals.add(key);
      const approval = await API.getApproval(approvalId);

      // Show approval modal
      await this.showApprovalModal(approval, decision, approval.workflow_id);

    } catch (error) {
// console.error('Error handling approval:', error);
      Toast.error('Failed to load approval form');
    } finally {
      // Remove from in-progress set after modal is shown
      // (not after submission, because modal handles that)
      this.inProgressApprovals.delete(key);
    }
  },

  /**
   * Handle approval (approve/reject) - Uses CUSTOM MODAL
   * Legacy method for old-style workflows - kept for backwards compatibility
   */
  async handleApproval(workflowId, decision) {
    // Prevent duplicate handling if already in progress
    const key = `${workflowId}:${decision}`;
    if (this.inProgressApprovals.has(key)) {
// console.log('Approval already being processed, ignoring duplicate click');
      return;
    }

    try {
      this.inProgressApprovals.add(key);

      // Fetch workflow events to get approval_id
      const eventsData = await API.getWorkflowEvents(workflowId);
      if (!eventsData || !eventsData.events) {
        Toast.error('Failed to load workflow events');
        return;
      }

      const approvalEvent = eventsData.events.find(e => e.event_type === 'approval.requested');
      if (!approvalEvent || !approvalEvent.event_data.approval_id) {
        Toast.error('No approval request found');
        return;
      }

      const approvalId = approvalEvent.event_data.approval_id;
      const approval = await API.getApproval(approvalId);

      // Show approval modal
      await this.showApprovalModal(approval, decision, workflowId);

    } catch (error) {
// console.error('Error handling approval:', error);
      Toast.error('Failed to load approval form');
    } finally {
      // Remove from in-progress set after modal is shown
      this.inProgressApprovals.delete(key);
    }
  },

  /**
   * Render approval form HTML (reusable for modal and inline)
   * @param {object} approval - Approval data
   * @param {string} decision - 'approve' or 'reject'
   * @returns {object} {fieldsHTML, rejectFieldHTML} - Form HTML components
   */
  renderApprovalFormHTML(approval, decision) {
    const isReject = decision === 'reject';

    // Build form fields HTML
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

    const rejectFieldHTML = isReject ? `
      <div class="form-group">
        <label class="form-label form-label--required">Rejection Reason</label>
        <textarea name="rejection_reason" class="form-textarea" required
                  placeholder="Please provide a reason for rejection..." style="min-height: 100px;"></textarea>
      </div>
    ` : '';

    return { fieldsHTML, rejectFieldHTML };
  },

  /**
   * Show approval modal with form
   */
  async showApprovalModal(approval, decision, workflowId) {
    const isReject = decision === 'reject';

    // Use extracted form rendering function
    const { fieldsHTML, rejectFieldHTML } = this.renderApprovalFormHTML(approval, decision);

    const content = `
      <p class="mb-6">${approval.ui_schema.description || 'Please review and provide your decision.'}</p>
      <form id="approvalForm">
        ${fieldsHTML}
        ${rejectFieldHTML}
      </form>
    `;

    const footer = `
      <button class="btn btn--secondary" data-action="close">Cancel</button>
      <button class="btn btn--${isReject ? 'danger' : 'primary'}" id="submitApprovalBtn">
        ${isReject ? Icons.x(16) + ' Reject' : Icons.check(16) + ' Approve'}
      </button>
    `;

    const modal = Modal.custom({
      title: approval.ui_schema.title || 'Approval Request',
      content: content,
      footer: footer,
      variant: isReject ? 'danger' : 'default'
    });

    // Handle submit
    const submitBtn = modal.querySelector('#submitApprovalBtn');
    const form = modal.querySelector('#approvalForm');

    submitBtn.addEventListener('click', async () => {
      // CRITICAL: Prevent double-submission race condition
      // Check if button is already disabled (submission in progress)
      if (submitBtn.disabled) {
// console.log('Submission already in progress, ignoring duplicate click');
        return;
      }

      if (!form.checkValidity()) {
        form.reportValidity();
        return;
      }

      // Collect form data
      const formData = new FormData(form);
      const responseData = {};
      for (let [key, value] of formData.entries()) {
        responseData[key] = value;
      }

      // Disable button to prevent double-submission
      submitBtn.disabled = true;
      submitBtn.innerHTML = `${Icons.loader(16)} Submitting...`;

      try {
        const result = await API.submitApproval(approval.callback_token, decision, responseData);

        if (result && result.success) {
          Toast.success(`Workflow ${decision}ed successfully!`);
          Modal.close(modal);

          // Wait a bit for backend to fully process events before refreshing
          setTimeout(() => {
            // Refresh current page
            const currentPage = State.get('currentPage');
            if (currentPage === 'dashboard') {
              Dashboard.load();
            } else if (currentPage === 'approvals') {
              this.load();
            }
          }, 500);
        } else {
          Toast.error('Failed to submit approval');
          submitBtn.disabled = false;
          submitBtn.innerHTML = isReject ? `${Icons.x(16)} Reject` : `${Icons.check(16)} Approve`;
        }
      } catch (error) {
// console.error('Error submitting approval:', error);
        Toast.error('Error submitting approval');
        submitBtn.disabled = false;
        submitBtn.innerHTML = isReject ? `${Icons.x(16)} Reject` : `${Icons.check(16)} Approve`;
      }
    });
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Approvals = Approvals;
}
