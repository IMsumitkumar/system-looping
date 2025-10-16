/**
 * Configuration & Constants
 * Centralized configuration for the dashboard
 */

// console.log('[INIT] config.js loading...');

const CONFIG = {
  // API Configuration - Now environment-controlled!
  // These values are injected from backend via ENV_CONFIG (see index.html)
  // Fallback to production URLs if ENV_CONFIG not available
  API_BASE_URL: window.ENV_CONFIG?.API_BASE_URL || 'https://lyzr-human-in-loop-workflow-b3agasdpfab8d7hd.centralindia-01.azurewebsites.net/',
  CHAT_AGENT_URL: window.ENV_CONFIG?.CHAT_AGENT_URL || 'https://lyzr-workflow-chat-demo-c6f8gbbwcyf4bjdj.centralindia-01.azurewebsites.net/',
  // Polling & Refresh Intervals (ms)
  AUTO_REFRESH_INTERVAL: 30000, // 30 seconds
  TOAST_DURATION: 5000, // 5 seconds
  MODAL_ANIMATION_DURATION: 300,

  // Pagination & Limits
  DEFAULT_PAGE_SIZE: 50,
  MAX_WORKFLOWS_DISPLAY: 100,
  MAX_DLQ_DISPLAY: 50,

  // Timeout Thresholds (seconds)
  URGENT_APPROVAL_THRESHOLD: 3600, // 1 hour
  EXPIRING_APPROVAL_THRESHOLD: 21600, // 6 hours
  DEFAULT_APPROVAL_TIMEOUT: 3600,

  // State Colors (for charts and visualizations)
  STATE_COLORS: {
    CREATED: '#52525b',
    RUNNING: '#1e40af',
    WAITING_APPROVAL: '#d97706',
    APPROVED: '#1e40af',
    COMPLETED: '#15803d',
    REJECTED: '#be123c',
    TIMEOUT: '#ca8a04',
    FAILED: '#dc2626'
  },

  // Feature Flags
  FEATURES: {
    AUTO_REFRESH: true,
    STAGGER_ANIMATIONS: true,
    KEYBOARD_SHORTCUTS: true,
    ANALYTICS: false, // Future: track user interactions
    DARK_MODE: false  // Future: dark theme support
  },

  // Local Storage Keys
  STORAGE_KEYS: {
    SIDEBAR_COLLAPSED: 'dashboard_sidebar_collapsed',
    THEME: 'dashboard_theme',
    USER_PREFERENCES: 'dashboard_user_prefs'
  },

  // Keyboard Shortcuts
  SHORTCUTS: {
    REFRESH: 'r',
    SEARCH: '/',
    ESCAPE: 'Escape',
    TOGGLE_SIDEBAR: 's'
  },

  // Validation Rules
  VALIDATION: {
    MAX_WORKFLOW_TYPE_LENGTH: 100,
    MAX_CONTEXT_SIZE: 10000, // characters
    MIN_TIMEOUT: 60, // 1 minute
    MAX_TIMEOUT: 604800 // 7 days
  },

  // Status Messages
  MESSAGES: {
    SUCCESS: {
      WORKFLOW_CREATED: 'Workflow created successfully',
      APPROVAL_SUBMITTED: 'Approval submitted successfully',
      DLQ_RETRIED: 'Event retried successfully',
      DLQ_DELETED: 'Entry deleted successfully',
      COPIED: 'Copied to clipboard'
    },
    ERROR: {
      GENERIC: 'An error occurred. Please try again.',
      NETWORK: 'Network error. Please check your connection.',
      UNAUTHORIZED: 'Unauthorized. Please log in.',
      NOT_FOUND: 'Resource not found.',
      INVALID_JSON: 'Invalid JSON format',
      VALIDATION_FAILED: 'Validation failed. Please check your input.'
    }
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.CONFIG = CONFIG;
}
