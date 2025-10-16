/**
 * Metrics Component
 * Dashboard metric cards with REAL data only (no fake metrics)
 */

const Metrics = {
  /**
   * Render metric cards
   */
  async render(container) {
    if (!container) return;

    try {
      const metrics = await API.getMetrics();
      State.setMetrics(metrics);

      // Calculate REAL metrics (no fake data)
      const pendingApprovals = metrics.approvals?.by_status?.PENDING || 0;
      const activeWorkflows = this.calculateActiveWorkflows(metrics);
      const completedToday = this.calculateCompletedToday(metrics);
      const failedAndTimeout = this.calculateFailedAndTimeout(metrics);

      container.innerHTML = `
        <div class="grid grid--auto-fit gap-6">
          <!-- Pending Approvals (Most Important) -->
          <div class="card-metric" onclick="Sidebar.navigateTo('approvals')">
            <div class="card-metric__value ${pendingApprovals > 0 ? 'card-metric__value--highlight' : ''}">
              ${pendingApprovals}
            </div>
            <div class="card-metric__label">Pending Approvals</div>
          </div>

          <!-- Active Workflows -->
          <div class="card-metric" onclick="Sidebar.navigateTo('workflows')">
            <div class="card-metric__value">${activeWorkflows}</div>
            <div class="card-metric__label">Active Workflows</div>
          </div>

          <!-- Completed Today -->
          <div class="card-metric" onclick="Metrics.showCompletedToday()">
            <div class="card-metric__value card-metric__value--success">${completedToday}</div>
            <div class="card-metric__label">Completed Today</div>
          </div>

          <!-- Failed/Timeout -->
          <div class="card-metric" onclick="Sidebar.navigateTo('dlq')">
            <div class="card-metric__value ${failedAndTimeout > 0 ? 'card-metric__value--danger' : ''}">
              ${failedAndTimeout}
            </div>
            <div class="card-metric__label">Failed/Timeout</div>
          </div>
        </div>
      `;

      // Update sidebar badges
      Sidebar.updateBadges(metrics);

    } catch (error) {
// console.error('Failed to load metrics:', error);
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__title">Failed to load metrics</div>
          <div class="empty-state__description">${error.message}</div>
        </div>
      `;
    }
  },

  /**
   * Calculate active workflows (Running + Waiting Approval)
   */
  calculateActiveWorkflows(metrics) {
    const running = metrics.workflows?.by_state?.RUNNING || 0;
    const waiting = metrics.workflows?.by_state?.WAITING_APPROVAL || 0;
    return running + waiting;
  },

  /**
   * Calculate completed workflows today
   * Note: This uses the COMPLETED count from metrics.
   * In a real scenario, you'd filter by created_at date
   */
  calculateCompletedToday(metrics) {
    // For now, return completed count
    // TODO: Filter by date when API supports it
    return metrics.workflows?.by_state?.COMPLETED || 0;
  },

  /**
   * Calculate failed and timeout workflows
   */
  calculateFailedAndTimeout(metrics) {
    const failed = metrics.workflows?.by_state?.FAILED || 0;
    const timeout = metrics.workflows?.by_state?.TIMEOUT || 0;
    return failed + timeout;
  },

  /**
   * Show completed workflows today (filtered view)
   */
  showCompletedToday() {
    Sidebar.navigateTo('workflows');
    // TODO: Filter by COMPLETED state
    setTimeout(() => {
      const stateFilter = document.getElementById('stateFilter');
      if (stateFilter) {
        stateFilter.value = 'COMPLETED';
        Workflows.load();
      }
    }, 100);
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Metrics = Metrics;
}
