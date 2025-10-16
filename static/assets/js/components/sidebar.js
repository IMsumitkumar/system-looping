/**
 * Sidebar Component
 * Navigation sidebar with collapse/expand functionality
 */

const Sidebar = {
  /**
   * Initialize sidebar
   */
  init() {
    this.renderSidebar();
    this.attachEventListeners();
    this.restoreState();
  },

  /**
   * Render sidebar HTML
   */
  renderSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;

    sidebar.innerHTML = `
      <div class="sidebar__header">
        <div class="sidebar__logo">Workflow</div>
        <button class="sidebar__toggle" aria-label="Toggle sidebar" id="sidebar-toggle">
          ${Icons.bars3(20)}
        </button>
      </div>

      <nav class="sidebar__nav">
        <a href="#" class="nav-item nav-item--active" data-page="dashboard" data-tooltip="Dashboard">
          <span class="nav-item__icon">${Icons.home(20)}</span>
          <span class="nav-item__label">Dashboard</span>
        </a>

        <a href="#" class="nav-item" data-page="workflows" data-tooltip="Workflows">
          <span class="nav-item__icon">${Icons.layers(20)}</span>
          <span class="nav-item__label">Workflows</span>
        </a>

        <a href="#" class="nav-item" data-page="approvals" data-tooltip="Approvals">
          <span class="nav-item__icon">${Icons.checkCircle(20)}</span>
          <span class="nav-item__label">Approvals</span>
          <span class="nav-item__badge" id="approvalsBadge">0</span>
        </a>

        <a href="#" class="nav-item" data-page="create" data-tooltip="Create New">
          <span class="nav-item__icon">${Icons.plus(20)}</span>
          <span class="nav-item__label">Create New</span>
        </a>

        <a href="#" class="nav-item" data-page="dlq" data-tooltip="Dead Letter Queue">
          <span class="nav-item__icon">${Icons.exclamationTriangle(20)}</span>
          <span class="nav-item__label">Dead Letter Queue</span>
          <span class="nav-item__badge" id="dlqBadge">0</span>
        </a>

        <a href="#" class="nav-item" data-page="chat" data-tooltip="Chat">
          <span class="nav-item__icon">${Icons.chatBubble(20)}</span>
          <span class="nav-item__label">Chat</span>
          <span class="nav-item__badge nav-item__badge--soon">Soon</span>
        </a>
      </nav>
    `;
  },

  /**
   * Attach event listeners
   */
  attachEventListeners() {
    // Toggle sidebar
    const toggleBtn = document.getElementById('sidebar-toggle');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => this.toggle());
    }

    // Navigation items
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;
        if (page && page !== 'chat') { // Chat is coming soon
          this.navigateTo(page);
        } else if (page === 'chat') {
          Toast.info('Chat feature coming soon!');
        }
      });
    });
  },

  /**
   * Toggle sidebar collapse state
   */
  toggle() {
    const sidebar = document.getElementById('sidebar');
    const isCollapsed = sidebar.classList.toggle('sidebar--collapsed');
    State.setSidebarCollapsed(isCollapsed);
  },

  /**
   * Navigate to page
   */
  navigateTo(page) {
    // Update active state
    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.remove('nav-item--active');
      if (item.dataset.page === page) {
        item.classList.add('nav-item--active');
      }
    });

    // Update bottom nav active state (mobile)
    document.querySelectorAll('.bottom-nav__item').forEach(item => {
      item.classList.remove('bottom-nav__item--active');
      if (item.dataset.page === page) {
        item.classList.add('bottom-nav__item--active');
      }
    });

    // Update state and trigger page load
    State.setCurrentPage(page);
    App.loadPage(page);
  },

  /**
   * Update badge counts
   */
  updateBadges(metrics) {
    // Approvals badge
    const approvalsBadge = document.getElementById('approvalsBadge');
    const pendingApprovals = metrics.approvals?.by_status?.PENDING || 0;
    if (approvalsBadge) {
      approvalsBadge.textContent = pendingApprovals;
      approvalsBadge.style.display = pendingApprovals > 0 ? 'flex' : 'none';
    }

    // DLQ badge (would need actual count from API)
    const dlqBadge = document.getElementById('dlqBadge');
    if (dlqBadge) {
      // This would be populated from DLQ API call
      dlqBadge.style.display = 'none';
    }
  },

  /**
   * Restore sidebar state from localStorage
   */
  restoreState() {
    const sidebar = document.getElementById('sidebar');
    if (State.get('sidebarCollapsed')) {
      sidebar.classList.add('sidebar--collapsed');
    }
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Sidebar = Sidebar;
}
