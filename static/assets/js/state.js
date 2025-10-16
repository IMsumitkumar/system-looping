/**
 * Application State Management
 * Simple reactive state management without frameworks
 */

const State = {
  // Current state
  data: {
    currentPage: 'dashboard',
    workflows: [],
    approvals: [],
    metrics: {},
    dlqEntries: [],
    sidebarCollapsed: localStorage.getItem(CONFIG.STORAGE_KEYS.SIDEBAR_COLLAPSED) === 'true',
    loading: {
      dashboard: false,
      workflows: false,
      approvals: false,
      dlq: false
    }
  },

  // Subscribers for reactive updates
  subscribers: {},

  /**
   * Get current state value
   * @param {string} key - State key (supports nested keys like 'loading.dashboard')
   */
  get(key) {
    const keys = key.split('.');
    let value = this.data;
    for (const k of keys) {
      value = value?.[k];
    }
    return value;
  },

  /**
   * Set state value and notify subscribers
   * @param {string} key - State key
   * @param {any} value - New value
   */
  set(key, value) {
    const keys = key.split('.');
    const lastKey = keys.pop();
    let target = this.data;

    for (const k of keys) {
      if (!target[k]) target[k] = {};
      target = target[k];
    }

    target[lastKey] = value;
    this.notify(key, value);
  },

  /**
   * Update multiple state values at once
   * @param {object} updates - Object with key-value pairs
   */
  update(updates) {
    for (const [key, value] of Object.entries(updates)) {
      this.set(key, value);
    }
  },

  /**
   * Subscribe to state changes
   * @param {string} key - State key to watch
   * @param {function} callback - Callback function
   * @returns {function} Unsubscribe function
   */
  subscribe(key, callback) {
    if (!this.subscribers[key]) {
      this.subscribers[key] = [];
    }
    this.subscribers[key].push(callback);

    // Return unsubscribe function
    return () => {
      this.subscribers[key] = this.subscribers[key].filter(cb => cb !== callback);
    };
  },

  /**
   * Notify subscribers of state changes
   * @param {string} key - State key
   * @param {any} value - New value
   */
  notify(key, value) {
    if (this.subscribers[key]) {
      this.subscribers[key].forEach(callback => callback(value));
    }
  },

  /**
   * Save state to localStorage
   * @param {string} key - State key
   */
  persist(key) {
    const value = this.get(key);
    localStorage.setItem(key, JSON.stringify(value));
  },

  /**
   * Load state from localStorage
   * @param {string} key - State key
   * @param {any} defaultValue - Default value if not found
   */
  restore(key, defaultValue = null) {
    const stored = localStorage.getItem(key);
    if (stored) {
      try {
        return JSON.parse(stored);
      } catch (e) {
// console.error('Failed to parse stored state:', e);
        return defaultValue;
      }
    }
    return defaultValue;
  },

  /**
   * Clear all state
   */
  reset() {
    this.data = {
      currentPage: 'dashboard',
      workflows: [],
      approvals: [],
      metrics: {},
      dlqEntries: [],
      sidebarCollapsed: false,
      loading: {
        dashboard: false,
        workflows: false,
        approvals: false,
        dlq: false
      }
    };
    this.notify('*', this.data);
  },

  // ===========================================
  // Convenience Methods
  // ===========================================

  setLoading(page, isLoading) {
    this.set(`loading.${page}`, isLoading);
  },

  setSidebarCollapsed(collapsed) {
    this.set('sidebarCollapsed', collapsed);
    localStorage.setItem(CONFIG.STORAGE_KEYS.SIDEBAR_COLLAPSED, collapsed);
  },

  setCurrentPage(page) {
    this.set('currentPage', page);
  },

  setWorkflows(workflows) {
    this.set('workflows', workflows);
  },

  setApprovals(approvals) {
    this.set('approvals', approvals);
  },

  setMetrics(metrics) {
    this.set('metrics', metrics);
  },

  setDLQEntries(entries) {
    this.set('dlqEntries', entries);
  },

  // Get computed values
  getPendingApprovals() {
    return this.get('metrics')?.approvals?.by_status?.PENDING || 0;
  },

  getActiveWorkflows() {
    const metrics = this.get('metrics');
    const running = metrics?.workflows?.by_state?.RUNNING || 0;
    const waiting = metrics?.workflows?.by_state?.WAITING_APPROVAL || 0;
    return running + waiting;
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.State = State;
}
