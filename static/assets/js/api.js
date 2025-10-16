/**
 * API Functions
 * Centralized API communication layer with error handling
 */

const API = {
  /**
   * Generic fetch wrapper with error handling
   * @param {string} endpoint - API endpoint (e.g., '/api/workflows')
   * @param {object} options - Fetch options (method, headers, body)
   * @returns {Promise} Response data
   */
  async request(endpoint, options = {}) {
    const url = `${CONFIG.API_BASE_URL}${endpoint}`;
    const defaultHeaders = {
      'Content-Type': 'application/json'
    };

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          ...defaultHeaders,
          ...options.headers
        }
      });

      const data = await response.json();

      if (!response.ok) {
        const error = new Error(data.detail || data.message || CONFIG.MESSAGES.ERROR.GENERIC);
        error.status = response.status;
        error.data = data;
        throw error;
      }

      return data;
    } catch (error) {
// console.error('API Error:', error);

      // Network errors
      if (error instanceof TypeError && error.message === 'Failed to fetch') {
        throw new Error(CONFIG.MESSAGES.ERROR.NETWORK);
      }

      throw error;
    }
  },

  /**
   * GET request helper
   */
  async get(endpoint, params = {}) {
    const queryString = new URLSearchParams(params).toString();
    const url = queryString ? `${endpoint}?${queryString}` : endpoint;
    return this.request(url, { method: 'GET' });
  },

  /**
   * POST request helper
   */
  async post(endpoint, data, headers = {}) {
    return this.request(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(data)
    });
  },

  /**
   * DELETE request helper
   */
  async delete(endpoint) {
    return this.request(endpoint, { method: 'DELETE' });
  },

  // ===========================================
  // Metrics API
  // ===========================================

  async getMetrics() {
    return this.get('/metrics');
  },

  // ===========================================
  // Workflows API
  // ===========================================

  async getWorkflows(params = {}) {
    return this.get('/api/workflows', params);
  },

  async getWorkflowById(workflowId) {
    return this.get(`/api/workflows/${workflowId}`);
  },

  async getWorkflowEvents(workflowId) {
    return this.get(`/api/workflows/${workflowId}/events`);
  },

  async createWorkflow(payload, idempotencyKey = null) {
    const headers = idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {};
    return this.post('/api/workflows', payload, headers);
  },

  // ===========================================
  // Approvals API
  // ===========================================

  async getPendingApprovals() {
    return this.get('/api/approvals');
  },

  async getApproval(approvalId) {
    return this.get(`/api/approvals/${approvalId}`);
  },

  async submitApproval(callbackToken, decision, responseData) {
    return this.post(`/api/callbacks/${callbackToken}`, {
      decision,
      response_data: responseData
    });
  },

  async rollbackApproval(approvalId) {
    return this.post(`/api/approvals/${approvalId}/rollback`);
  },

  // ===========================================
  // Dead Letter Queue API
  // ===========================================

  async getDLQ(params = {}) {
    return this.get('/api/admin/dlq', {
      limit: CONFIG.MAX_DLQ_DISPLAY,
      ...params
    });
  },

  async retryDLQEntry(entryId) {
    return this.post(`/api/admin/dlq/${entryId}/retry`);
  },

  async deleteDLQEntry(entryId) {
    return this.delete(`/api/admin/dlq/${entryId}`);
  },

  async retryAllDLQ() {
    return this.post('/api/admin/dlq/retry-all');
  },

  async clearAllDLQ() {
    return this.delete('/api/admin/dlq/clear');
  },

  async testDLQ() {
    return this.post('/api/admin/test-dlq');
  },

  // ===========================================
  // Chat API
  // ===========================================

  async sendChatMessage(conversationId, message) {
    return this.post('/api/chat', {
      conversation_id: conversationId,
      message: message
    });
  },

  async getConversations(userId = 'default_user', limit = 50) {
    return this.get('/api/conversations', { user_id: userId, limit });
  },

  async getConversationMessages(conversationId) {
    return this.get(`/api/conversations/${conversationId}/messages`);
  },

  async deleteConversation(conversationId) {
    return this.delete(`/api/conversations/${conversationId}`);
  },

  async getWorkflow(workflowId) {
    return this.get(`/api/workflows/${workflowId}`);
  },

  async getWorkflowSteps(workflowId) {
    return this.get(`/api/workflows/${workflowId}/steps`);
  },

  async retryWorkflow(workflowId) {
    return this.post(`/api/workflows/${workflowId}/retry`);
  },

  async cancelWorkflow(workflowId) {
    return this.post(`/api/workflows/${workflowId}/cancel`);
  },

  async rollbackWorkflow(workflowId, targetState, reason = 'Manual rollback') {
    return this.post(`/api/workflows/${workflowId}/rollback`, {
      target_state: targetState,
      reason: reason,
      rollback_by: 'user'
    });
  },

  async getRollbackHistory(workflowId) {
    return this.get(`/api/workflows/${workflowId}/rollback-history`);
  },

  async canRollback(workflowId, targetState) {
    return this.get(`/api/workflows/${workflowId}/can-rollback/${targetState}`);
  },

  // ===========================================
  // DLQ Bulk Operations (Extended)
  // ===========================================

  async bulkRetryDLQ(entryIds) {
    return this.post('/api/admin/dlq/bulk-retry', { entry_ids: entryIds });
  },

  async bulkDeleteDLQ(entryIds) {
    return this.post('/api/admin/dlq/bulk-delete', { entry_ids: entryIds });
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.API = API;
}
