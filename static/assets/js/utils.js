/**
 * Utility Functions
 * Helper functions used throughout the application
 */

const Utils = {
  /**
   * Format timestamp to "X ago" format
   */
  formatTimeAgo(timestamp) {
    const seconds = Math.floor(Date.now() / 1000 - timestamp);

    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  },

  /**
   * Calculate time remaining until timeout
   */
  calculateTimeRemaining(createdAt, timeoutSeconds) {
    const expiresAt = createdAt + timeoutSeconds;
    const now = Date.now() / 1000;
    const remaining = expiresAt - now;

    if (remaining < 0) {
      return { text: 'Expired', minutes: 0 };
    }

    const minutes = Math.floor(remaining / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) {
      return { text: `${days}d ${hours % 24}h remaining`, minutes };
    } else if (hours > 0) {
      return { text: `${hours}h ${minutes % 60}m remaining`, minutes };
    } else {
      return { text: `${minutes}m remaining`, minutes };
    }
  },

  /**
   * Format context object as summary string
   */
  formatContextSummary(context) {
    if (!context || Object.keys(context).length === 0) {
      return '<span class="text-muted">No context provided</span>';
    }

    const items = Object.entries(context).slice(0, 3).map(([key, value]) => {
      const displayKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      return `<strong>${displayKey}:</strong> ${value}`;
    });

    return items.join(' • ');
  },

  /**
   * Copy text to clipboard
   */
  async copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      Toast.success('Copied to clipboard');
    } catch (err) {
// console.error('Failed to copy:', err);
      Toast.error('Failed to copy');
    }
  },

  /**
   * Debounce function
   */
  debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  },

  /**
   * Escape HTML to prevent XSS
   */
  escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },

  /**
   * Validate JSON string
   */
  isValidJSON(str) {
    try {
      JSON.parse(str);
      return true;
    } catch (e) {
      return false;
    }
  },

  /**
   * Format file size
   */
  formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  },

  /**
   * Get state badge class
   */
  getStateBadgeClass(state) {
    const stateMap = {
      'CREATED': 'badge--created',
      'RUNNING': 'badge--running',
      'WAITING_APPROVAL': 'badge--waiting',
      'APPROVED': 'badge--approved',
      'COMPLETED': 'badge--completed',
      'REJECTED': 'badge--rejected',
      'TIMEOUT': 'badge--timeout',
      'FAILED': 'badge--failed'
    };
    return stateMap[state] || 'badge--created';
  },

  /**
   * Smooth scroll to element
   */
  scrollTo(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  },

  /**
   * Generate unique ID
   */
  generateId() {
    return `id-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Utils = Utils;
}
