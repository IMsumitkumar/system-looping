/**
 * Main Application Orchestrator
 * Initializes and coordinates all components
 */

// console.log('[INIT] app.js loading...');

const App = {
  /**
   * Initialize application
   */
  async init() {
    // console.log('Initializing Workflow Dashboard...');

    // Initialize sidebar
    Sidebar.init();

    // Initialize toast system
    Toast.init();

    // Render bottom navigation (mobile)
    this.renderBottomNav();

    // Load initial page
    await this.loadPage(State.get('currentPage'));

    // Setup auto-refresh
    if (CONFIG.FEATURES.AUTO_REFRESH) {
      this.setupAutoRefresh();
    }

    // Setup keyboard shortcuts
    if (CONFIG.FEATURES.KEYBOARD_SHORTCUTS) {
      this.setupKeyboardShortcuts();
    }

    // console.log('Dashboard initialized successfully');
  },

  /**
   * Load page based on route
   */
  async loadPage(page) {
    // Hide all pages
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));

    // Show selected page
    const pageElement = document.getElementById(`page-${page}`);
    if (pageElement) {
      pageElement.classList.remove('hidden');

      // Add page transition animation
      if (CONFIG.FEATURES.STAGGER_ANIMATIONS) {
        pageElement.classList.add('page-transition-enter');
        setTimeout(() => {
          pageElement.classList.remove('page-transition-enter');
        }, 300);
      }
    }

    // Load page-specific content
    switch (page) {
      case 'dashboard':
        await Dashboard.load();
        break;
      case 'workflows':
        await Workflows.load();
        break;
      case 'approvals':
        await Approvals.load();
        break;
      case 'create':
        // console.log('[DEBUG App.loadPage] Loading CREATE page...');
        // console.log('[DEBUG App.loadPage] Forms object exists:', typeof Forms !== 'undefined');
        // console.log('[DEBUG App.loadPage] Calling Forms.initCreateWorkflow()...');
        Forms.initCreateWorkflow();
        // console.log('[DEBUG App.loadPage] Forms.initCreateWorkflow() completed');
        break;
      case 'dlq':
        await DLQ.load();
        break;
      default:
        // console.warn(`Unknown page: ${page}`);
    }
  },

  /**
   * Setup auto-refresh for dashboard
   */
  setupAutoRefresh() {
    setInterval(async () => {
      const currentPage = State.get('currentPage');

      // Only refresh dashboard if it's the current page
      if (currentPage === 'dashboard') {
        await Dashboard.load();
      }

      // Always update badges
      try {
        const metrics = await API.getMetrics();
        Sidebar.updateBadges(metrics);
      } catch (error) {
        // Silently fail - badge updates are non-critical
      }
    }, CONFIG.AUTO_REFRESH_INTERVAL);
  },

  /**
   * Setup keyboard shortcuts
   */
  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ignore if user is typing in an input
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
        return;
      }

      switch (e.key) {
        case CONFIG.SHORTCUTS.REFRESH:
          e.preventDefault();
          this.refreshCurrentPage();
          break;
        case CONFIG.SHORTCUTS.TOGGLE_SIDEBAR:
          e.preventDefault();
          Sidebar.toggle();
          break;
        case CONFIG.SHORTCUTS.SEARCH:
          e.preventDefault();
          const searchBox = document.querySelector('.form-input[type="text"]');
          if (searchBox) searchBox.focus();
          break;
      }
    });
  },

  /**
   * Refresh current page
   */
  async refreshCurrentPage() {
    const currentPage = State.get('currentPage');
    Toast.info('Refreshing...');
    await this.loadPage(currentPage);
  },

  /**
   * Render mobile bottom navigation
   */
  renderBottomNav() {
    const bottomNav = document.querySelector('.bottom-nav');
    if (!bottomNav) return;

    bottomNav.innerHTML = `
      <div class="bottom-nav__items">
        <a href="#" class="bottom-nav__item bottom-nav__item--active" data-page="dashboard">
          <span class="bottom-nav__icon">${Icons.home(24)}</span>
          <span class="bottom-nav__label">Dashboard</span>
        </a>
        <a href="#" class="bottom-nav__item" data-page="workflows">
          <span class="bottom-nav__icon">${Icons.layers(24)}</span>
          <span class="bottom-nav__label">Workflows</span>
        </a>
        <a href="#" class="bottom-nav__item" data-page="approvals">
          <span class="bottom-nav__icon">${Icons.checkCircle(24)}</span>
          <span class="bottom-nav__label">Approvals</span>
        </a>
        <a href="#" class="bottom-nav__item" data-page="create">
          <span class="bottom-nav__icon">${Icons.plus(24)}</span>
          <span class="bottom-nav__label">Create</span>
        </a>
      </div>
    `;

    // Attach event listeners
    bottomNav.querySelectorAll('.bottom-nav__item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;
        if (page) {
          Sidebar.navigateTo(page);
        }
      });
    });
  }
};

/**
 * Dashboard Page
 */
const Dashboard = {
  async load() {
    try {
      // Load metrics
      const metricsContainer = document.getElementById('metricsGrid');
      await Metrics.render(metricsContainer);

      // Load urgent approvals
      await this.loadUrgentApprovals();

      // Load recent activity
      await this.loadRecentActivity();

    } catch (error) {
      Toast.error('Failed to load dashboard data');
    }
  },

  async loadUrgentApprovals() {
    const container = document.getElementById('urgentApprovalsList');
    if (!container) return;

    try {
      const approvals = await API.getPendingApprovals();

      if (!approvals || approvals.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state__icon">${Icons.checkCircle(64)}</div>
            <h3 class="empty-state__title">All Clear!</h3>
            <p class="empty-state__description">No pending approvals at the moment.</p>
          </div>
        `;
        return;
      }

      // Show max 5 most recent
      const urgentApprovals = approvals.slice(0, 5);
      container.innerHTML = urgentApprovals.map(approval => Approvals.renderApprovalCard(approval)).join('');

    } catch (error) {
      // Silently fail - will show empty state
    }
  },

  async loadRecentActivity() {
    const container = document.getElementById('recentTimeline');
    if (!container) return;

    try {
      const workflows = await API.getWorkflows({});
      const recent = workflows.slice(0, 10);

      if (!recent || recent.length === 0) {
        container.innerHTML = '<div class="empty-state">No recent activity</div>';
        return;
      }

      container.innerHTML = recent.map(wf => {
        const badgeClass = Utils.getStateBadgeClass(wf.state);
        return `
          <div class="timeline-item">
            <div class="timeline-item__title">${wf.workflow_type}</div>
            <div class="timeline-item__meta">
              <span class="timeline-item__id" onclick="Utils.copyToClipboard('${wf.id}')">${wf.id.substring(0, 12)}...</span>
              <span class="badge ${badgeClass}">${wf.state}</span>
              <span>${Utils.formatTimeAgo(wf.created_at)}</span>
            </div>
          </div>
        `;
      }).join('');

    } catch (error) {
      // Silently fail - will show empty state
    }
  }
};

/**
 * Dead Letter Queue Page
 */
const DLQ = {
  async load() {
    const filter = document.getElementById('dlqFilter')?.value || '';
    const container = document.getElementById('dlqList');
    if (!container) return;

    try {
      State.setLoading('dlq', true);

      const data = await API.getDLQ(filter ? { event_type: filter } : {});
      State.setDLQEntries(data.entries || []);

      if (!data.entries || data.entries.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state__icon">${Icons.checkCircle(64)}</div>
            <h3 class="empty-state__title">No Failed Events</h3>
            <p class="empty-state__description">Your Dead Letter Queue is empty.</p>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <div class="mb-4 text-secondary">
          <strong>Total: ${data.entries.length}</strong> failed event${data.entries.length === 1 ? '' : 's'}
        </div>
        ${data.entries.map(entry => this.renderDLQEntry(entry)).join('')}
      `;

    } catch (error) {
      Toast.error('Failed to load DLQ');
      container.innerHTML = '<div class="empty-state text-danger">Error loading DLQ</div>';
    } finally {
      State.setLoading('dlq', false);
    }
  },

  renderDLQEntry(entry) {
    return `
      <div class="card" style="border-left: 4px solid var(--color-danger); margin-bottom: 16px;">
        <div class="flex justify-between items-start mb-4">
          <div>
            <div class="font-semibold mb-1">${entry.original_event_type}</div>
            <div class="text-xs text-mono text-secondary">ID: ${entry.id}</div>
          </div>
          <div class="flex gap-2">
            <button class="btn btn--primary btn--sm" onclick="DLQ.retry(${entry.id})">
              ${Icons.arrowPath(14)} Retry
            </button>
            <button class="btn btn--danger btn--sm" onclick="DLQ.delete(${entry.id})">
              ${Icons.trash(14)} Delete
            </button>
          </div>
        </div>
        <div class="text-sm text-danger font-medium mb-2">Error: ${entry.error_message}</div>
        <div class="text-xs text-secondary mb-2">
          Retry Count: ${entry.retry_count} | Failed: ${Utils.formatTimeAgo(entry.created_at)}
          ${entry.workflow_id ? ` | Workflow: ${entry.workflow_id.substring(0, 8)}...` : ''}
        </div>
        <details class="mt-2">
          <summary class="text-xs text-secondary cursor-pointer select-none">View Event Data</summary>
          <pre class="text-xs mt-2 p-2 bg-gray-50 rounded overflow-x-auto">${JSON.stringify(entry.event_data, null, 2)}</pre>
        </details>
      </div>
    `;
  },

  async retry(entryId) {
    const confirmed = await Modal.confirm({
      title: 'Retry Event?',
      message: 'Make sure you\'ve fixed the bug that caused the failure first.',
      variant: 'warning',
      confirmText: 'Retry',
      cancelText: 'Cancel'
    });

    if (!confirmed) return;

    try {
      const result = await API.retryDLQEntry(entryId);
      if (result && result.success) {
        Toast.success('Event retried successfully');
        setTimeout(() => this.load(), 1000);
      }
    } catch (error) {
      Toast.error('Failed to retry event');
    }
  },

  async delete(entryId) {
    const confirmed = await Modal.confirm({
      title: 'Delete DLQ Entry?',
      message: 'This action cannot be undone.',
      variant: 'danger',
      confirmText: 'Delete',
      cancelText: 'Cancel'
    });

    if (!confirmed) return;

    try {
      const result = await API.deleteDLQEntry(entryId);
      if (result && result.success) {
        Toast.success('Entry deleted');
        this.load();
      }
    } catch (error) {
      Toast.error('Failed to delete entry');
    }
  },

  async testDLQ() {
    const confirmed = await Modal.confirm({
      title: 'Test DLQ?',
      message: 'This will publish a test event that will fail and be moved to the DLQ. Check the DLQ in 10 seconds.',
      variant: 'default',
      confirmText: 'Test',
      cancelText: 'Cancel'
    });

    if (!confirmed) return;

    try {
      const result = await API.testDLQ();
      if (result && result.success) {
        Toast.info('Test event published. Check DLQ in 10 seconds.');
      }
    } catch (error) {
      Toast.error('Failed to test DLQ');
    }
  },

  async retryAll() {
    const confirmed = await Modal.confirm({
      title: 'Retry All DLQ Entries?',
      message: 'This will retry ALL failed events in the DLQ. Make sure you have fixed the underlying issues first.',
      variant: 'warning',
      confirmText: 'Retry All',
      cancelText: 'Cancel'
    });

    if (!confirmed) return;

    try {
      const result = await API.retryAllDLQ();
      if (result) {
        Toast.success(`Retried ${result.retried_count || 0} event(s)`);
        setTimeout(() => this.load(), 1000);
      }
    } catch (error) {
      Toast.error('Failed to retry all entries');
    }
  },

  async clearAll() {
    const confirmed = await Modal.confirm({
      title: 'Clear All DLQ Entries?',
      message: 'This will permanently delete ALL entries in the DLQ. This action cannot be undone.',
      variant: 'danger',
      confirmText: 'Clear All',
      cancelText: 'Cancel'
    });

    if (!confirmed) return;

    try {
      const result = await API.clearAllDLQ();
      if (result) {
        Toast.success(`Deleted ${result.deleted_count || 0} entry(ies)`);
        this.load();
      }
    } catch (error) {
      Toast.error('Failed to clear DLQ');
    }
  }
};

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.App = App;
  window.Dashboard = Dashboard;
  window.DLQ = DLQ;
}
