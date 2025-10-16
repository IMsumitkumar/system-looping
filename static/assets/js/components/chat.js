/**
 * Chat Component
 * AI Assistant for Deployment Workflows
 * Simple, production-ready chat interface
 */

const Chat = {
  currentConversationId: null,
  pollInterval: null,
  activeWorkflows: new Set(),

  /**
   * Initialize chat page
   */
  async init() {
    await this.loadConversations();
    this.attachEventListeners();
    this.startNewChat();
  },

  /**
   * Attach event listeners
   */
  attachEventListeners() {
    const form = document.getElementById('chatForm');
    if (form) {
      form.addEventListener('submit', (e) => this.handleSubmit(e));
    }

    const newChatBtn = document.getElementById('newChatBtn');
    if (newChatBtn) {
      newChatBtn.addEventListener('click', () => this.startNewChat());
    }
  },

  /**
   * Handle message submission
   */
  async handleSubmit(e) {
    e.preventDefault();

    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;

    // Clear input and disable
    input.value = '';
    input.disabled = true;

    // Add user message to UI
    this.addMessage('user', message);

    try {
      // Send to API
      const response = await API.sendChatMessage(
        this.currentConversationId,
        message
      );

      this.currentConversationId = response.conversation_id;

      // Add assistant response
      this.addMessage('assistant', response.response, response.workflow_id);

      // If workflow created, start polling
      if (response.workflow_id) {
        this.trackWorkflow(response.workflow_id);
      }

      // Reload conversation list to update timestamps
      await this.loadConversations();

    } catch (error) {
      Toast.error('Failed to send message');
// console.error('Chat error:', error);
      this.addMessage('assistant', 'Sorry, I encountered an error processing your message. Please try again.');
    } finally {
      input.disabled = false;
      input.focus();
    }
  },

  /**
   * Add message to chat UI
   */
  addMessage(role, content, workflowId = null) {
    const messagesContainer = document.getElementById('chatMessages');

    // Remove welcome message if exists
    const welcome = messagesContainer.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message chat-message--${role}`;

    let workflowBadge = '';
    if (workflowId) {
      workflowBadge = `
        <div class="workflow-badge" data-workflow-id="${workflowId}">
          <span class="workflow-badge__icon">${Icons.layers(16)}</span>
          Workflow: ${workflowId.substring(0, 8)}...
          <span class="workflow-status" id="status-${workflowId}">
            Checking...
          </span>
        </div>
      `;
    }

    // Format message content (simple markdown-like)
    const formattedContent = this.formatMessage(content);

    messageDiv.innerHTML = `
      <div class="chat-message__content">
        ${formattedContent}
        ${workflowBadge}
      </div>
      <div class="chat-message__time">${this.formatTime(new Date())}</div>
    `;

    messagesContainer.appendChild(messageDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  },

  /**
   * Format message with basic markdown-like syntax
   */
  formatMessage(content) {
    return content
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')  // Bold
      .replace(/`([^`]+)`/g, '<code>$1</code>')  // Inline code
      .replace(/\n/g, '<br>');  // Line breaks
  },

  /**
   * Format time for display
   */
  formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  },

  /**
   * Track workflow status and poll for updates
   */
  trackWorkflow(workflowId) {
    if (this.activeWorkflows.has(workflowId)) {
      return; // Already tracking
    }

    this.activeWorkflows.add(workflowId);

    // Start polling this workflow
    const pollWorkflow = async () => {
      try {
        const workflow = await API.getWorkflow(workflowId);
        const statusEl = document.getElementById(`status-${workflowId}`);

        if (statusEl) {
          const badgeClass = Utils.getStateBadgeClass(workflow.state);
          statusEl.className = `workflow-status badge ${badgeClass}`;
          statusEl.textContent = workflow.state;

          // Stop polling if terminal state
          if (['COMPLETED', 'REJECTED', 'FAILED', 'TIMEOUT'].includes(workflow.state)) {
            this.activeWorkflows.delete(workflowId);

            // Add status update message
            const statusMessage = this.getStatusMessage(workflow.state);
            this.addMessage('assistant', statusMessage);
          }
        }
      } catch (error) {
// console.error('Polling error:', error);
      }
    };

    // Poll immediately, then every 3 seconds
    pollWorkflow();
    const intervalId = setInterval(() => {
      if (this.activeWorkflows.has(workflowId)) {
        pollWorkflow();
      } else {
        clearInterval(intervalId);
      }
    }, 3000);
  },

  /**
   * Get human-readable status message
   */
  getStatusMessage(state) {
    const messages = {
      'COMPLETED': 'Workflow completed successfully!',
      'REJECTED': 'Workflow was rejected.',
      'FAILED': 'Workflow failed.',
      'TIMEOUT': 'Workflow timed out.'
    };
    return messages[state] || `Status: ${state}`;
  },

  /**
   * Load conversations list
   */
  async loadConversations() {
    const historyDiv = document.getElementById('chatHistory');
    if (!historyDiv) return;

    try {
      const conversations = await API.getConversations();

      if (conversations.length === 0) {
        historyDiv.innerHTML = '<p class="empty-text">No conversations yet</p>';
        return;
      }

      historyDiv.innerHTML = conversations.map(conv => `
        <div class="chat-history-item" data-id="${conv.id}">
          <div class="chat-history-item__title">${this.escapeHtml(conv.title)}</div>
          <div class="chat-history-item__time">
            ${Utils.formatTimeAgo(conv.updated_at)}
          </div>
        </div>
      `).join('');

      // Add click handlers
      historyDiv.querySelectorAll('.chat-history-item').forEach(item => {
        item.addEventListener('click', () => {
          this.loadConversation(item.dataset.id);
        });
      });

    } catch (error) {
// console.error('Failed to load conversations:', error);
      historyDiv.innerHTML = '<p class="empty-text text-danger">Failed to load conversations</p>';
    }
  },

  /**
   * Load a specific conversation
   */
  async loadConversation(conversationId) {
    try {
      const messages = await API.getConversationMessages(conversationId);
      this.currentConversationId = conversationId;

      const messagesContainer = document.getElementById('chatMessages');
      messagesContainer.innerHTML = '';

      messages.forEach(msg => {
        this.addMessage(msg.role, msg.content, msg.workflow_id);

        // Track workflows that are still active
        if (msg.workflow_id) {
          this.trackWorkflow(msg.workflow_id);
        }
      });

      // Update active state in sidebar
      document.querySelectorAll('.chat-history-item').forEach(item => {
        item.classList.remove('chat-history-item--active');
        if (item.dataset.id === conversationId) {
          item.classList.add('chat-history-item--active');
        }
      });

    } catch (error) {
      Toast.error('Failed to load conversation');
// console.error(error);
    }
  },

  /**
   * Start new chat
   */
  startNewChat() {
    this.currentConversationId = null;
    const messagesContainer = document.getElementById('chatMessages');

    messagesContainer.innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome__icon">${Icons.chatBubble(64)}</div>
        <h2 class="chat-welcome__title">AI Deployment Assistant</h2>
        <p class="chat-welcome__description">
          I can help you create deployment workflows and check their status.
        </p>
        <div class="chat-welcome__examples">
          <p><strong>Try asking:</strong></p>
          <button class="btn btn--ghost btn--sm" onclick="Chat.fillExample('Deploy version 1.2.3 to production')">
            Deploy version 1.2.3 to production
          </button>
          <button class="btn btn--ghost btn--sm" onclick="Chat.fillExample('Release to staging')">
            Release to staging
          </button>
        </div>
      </div>
    `;

    // Remove active state from all history items
    document.querySelectorAll('.chat-history-item').forEach(item => {
      item.classList.remove('chat-history-item--active');
    });

    document.getElementById('chatInput').focus();
  },

  /**
   * Fill example message in input
   */
  fillExample(text) {
    const input = document.getElementById('chatInput');
    input.value = text;
    input.focus();
  },

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Chat = Chat;
}
