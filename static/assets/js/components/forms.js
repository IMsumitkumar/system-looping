/**
 * Forms Component
 * Create workflow form and other forms
 */

// console.log('[INIT] forms.js loading...');

const CreateWorkflow = {
  currentMode: 'simple',

  setMode(mode) {
// console.log('[DEBUG CreateWorkflow.setMode] Called with mode:', mode);
    this.currentMode = mode;

    // Get all elements with null checks
    const simpleBtn = document.getElementById('toggleSimpleWorkflow');
    const multiStepBtn = document.getElementById('toggleMultiStepWorkflow');
    const simpleSection = document.getElementById('simpleWorkflowSection');
    const multiStepSection = document.getElementById('multiStepWorkflowSection');

// console.log('[DEBUG CreateWorkflow.setMode] Elements found:', {
      simpleBtn: !!simpleBtn,
      multiStepBtn: !!multiStepBtn,
      simpleSection: !!simpleSection,
      multiStepSection: !!multiStepSection
    });

    if (!simpleBtn || !multiStepBtn || !simpleSection || !multiStepSection) {
// console.error('[DEBUG CreateWorkflow.setMode] ERROR: Some elements not found!');
      return;
    }

    // Update button states
    simpleBtn.classList.toggle('btn--primary', mode === 'simple');
    simpleBtn.classList.toggle('btn--secondary', mode !== 'simple');
    multiStepBtn.classList.toggle('btn--primary', mode === 'multi-step');
    multiStepBtn.classList.toggle('btn--secondary', mode !== 'multi-step');

    // Toggle sections
    simpleSection.classList.toggle('hidden', mode !== 'simple');
    multiStepSection.classList.toggle('hidden', mode !== 'multi-step');

// console.log('[DEBUG CreateWorkflow.setMode] After toggle, classes:', {
      simpleSection: simpleSection.className,
      multiStepSection: multiStepSection.className
    });

    // Initialize step builder if switching to multi-step
    if (mode === 'multi-step') {
// console.log('[DEBUG CreateWorkflow.setMode] Initializing StepBuilder...');
      if (typeof StepBuilder !== 'undefined') {
        StepBuilder.init();
      } else {
// console.error('[DEBUG CreateWorkflow.setMode] ERROR: StepBuilder is not defined!');
      }
    }

// console.log('[DEBUG CreateWorkflow.setMode] Completed');
  }
};

const Forms = {
  /**
   * Initialize create workflow form
   */
  initCreateWorkflow() {
// console.log('[DEBUG Forms.initCreateWorkflow] ========== CALLED ==========');

    const form = document.getElementById('createWorkflowForm');
// console.log('[DEBUG Forms.initCreateWorkflow] Form found:', !!form);

    if (!form) {
// console.error('[DEBUG Forms.initCreateWorkflow] ERROR: Form not found! Exiting.');
      return;
    }

    form.addEventListener('submit', (e) => this.handleCreateWorkflow(e));
// console.log('[DEBUG Forms.initCreateWorkflow] Form submit listener attached');

    // Initialize to simple mode
// console.log('[DEBUG Forms.initCreateWorkflow] Calling CreateWorkflow.setMode("simple")...');
    CreateWorkflow.setMode('simple');

    // Example buttons (if they exist)
    const exampleButtons = document.querySelectorAll('[data-example]');
// console.log('[DEBUG Forms.initCreateWorkflow] Example buttons found:', exampleButtons.length);
    exampleButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const exampleType = btn.dataset.example;
        this.loadExample(exampleType);
      });
    });

    // Mode toggle buttons - add event listeners
    const simpleBtn = document.getElementById('toggleSimpleWorkflow');
    const multiStepBtn = document.getElementById('toggleMultiStepWorkflow');

// console.log('[DEBUG Forms.initCreateWorkflow] Toggle buttons:', {
      simpleBtn: !!simpleBtn,
      multiStepBtn: !!multiStepBtn
    });

    if (simpleBtn) {
      // Use capture phase to intercept before extensions
      simpleBtn.addEventListener('click', (e) => {
// console.log('[DEBUG Forms.initCreateWorkflow] ★★★ SIMPLE BUTTON CLICKED ★★★');
        e.preventDefault();
        e.stopPropagation(); // Prevent extension interference
        e.stopImmediatePropagation(); // Stop other listeners
        CreateWorkflow.setMode('simple');
      }, true); // true = capture phase (fires before bubbling)
// console.log('[DEBUG Forms.initCreateWorkflow] Simple button listener attached (capture phase)');
    } else {
// console.error('[DEBUG Forms.initCreateWorkflow] ERROR: Simple button not found!');
    }

    if (multiStepBtn) {
      // Use capture phase to intercept before extensions
      multiStepBtn.addEventListener('click', (e) => {
// console.log('[DEBUG Forms.initCreateWorkflow] ★★★ MULTI-STEP BUTTON CLICKED ★★★');
        e.preventDefault();
        e.stopPropagation(); // Prevent extension interference
        e.stopImmediatePropagation(); // Stop other listeners
        CreateWorkflow.setMode('multi-step');
      }, true); // true = capture phase (fires before bubbling)
// console.log('[DEBUG Forms.initCreateWorkflow] Multi-step button listener attached (capture phase)');
    } else {
// console.error('[DEBUG Forms.initCreateWorkflow] ERROR: Multi-step button not found!');
    }

// console.log('[DEBUG Forms.initCreateWorkflow] ========== COMPLETED ==========');
  },

  /**
   * Handle create workflow form submission
   */
  async handleCreateWorkflow(event) {
    event.preventDefault();

    // Prevent double submission
    const submitBtn = event.target.querySelector('button[type="submit"]');
    if (!submitBtn) return;

    if (submitBtn.disabled) {
// console.log('Form already submitting, ignoring duplicate submission');
      return;
    }

    // Disable button and show loading state
    submitBtn.disabled = true;
    const originalText = submitBtn.innerHTML;
    submitBtn.textContent = 'Creating...';

    const workflowType = document.getElementById('workflowType').value;
    const contextStr = document.getElementById('workflowContext').value;
    const idempotencyKey = document.getElementById('idempotencyKey').value;

    // Parse context JSON
    let context = {};
    try {
      if (contextStr.trim()) {
        context = JSON.parse(contextStr);
      }
    } catch (e) {
      Toast.error(CONFIG.MESSAGES.ERROR.INVALID_JSON);
      // Re-enable button on error
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalText;
      return;
    }

    // Check mode
    const mode = CreateWorkflow.currentMode || 'simple';

    let payload = {
      workflow_type: workflowType,
      context: context
    };

    if (mode === 'simple') {
      // Simple workflow with single approval
      const title = document.getElementById('approvalTitle').value;
      const description = document.getElementById('approvalDescription').value;
      const timeout = parseInt(document.getElementById('approvalTimeout').value);

      if (title || description) {
        payload.approval_schema = {
          title: title || 'Approval Required',
          description: description || 'Please review and approve',
          fields: [
            {
              name: 'reviewer_name',
              type: 'text',
              label: 'Your Name',
              required: true
            }
          ],
          buttons: [
            { action: 'approve', label: 'Approve', style: 'primary' },
            { action: 'reject', label: 'Reject', style: 'danger' }
          ]
        };
        payload.approval_timeout_seconds = timeout;
      }
    } else {
      // Multi-step workflow
      const steps = StepBuilder.getSteps();
      if (steps.length === 0) {
        Toast.error('Please add at least one step');
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
        return;
      }
      payload.steps = steps;
    }

    try {
      // Pass idempotencyKey if provided
      const result = await API.createWorkflow(payload, idempotencyKey || null);

      if (result) {
        Toast.success(`Workflow created: ${result.id}`);
        // Reset form
        event.target.reset();
        if (mode === 'multi-step') {
          StepBuilder.init();
        }
        // Navigate to dashboard
        setTimeout(() => Sidebar.navigateTo('dashboard'), 1000);
      }
    } catch (error) {
// console.error('Error creating workflow:', error);
      Toast.error('Failed to create workflow');
      // Re-enable button on error
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalText;
    } finally {
      // Re-enable button after successful submission or navigation
      setTimeout(() => {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
      }, 1500);
    }
  },

  /**
   * Load example workflow
   */
  loadExample(type) {
    const mode = CreateWorkflow.currentMode || 'simple';

    // Check if it's multi-step mode
    if (mode === 'multi-step') {
      this.loadMultiStepExample(type);
      return;
    }

    // Single-step examples (existing logic)
    const examples = {
      deployment: {
        workflowType: 'deployment',
        context: JSON.stringify({
          env: 'production',
          service: 'payment-api',
          version: 'v2.5.0',
          deployer: 'alice@company.com'
        }, null, 2),
        title: 'Production Deployment Approval',
        description: 'Deploy payment-api v2.5.0 to production environment.',
        timeout: 3600
      },
      purchase: {
        workflowType: 'purchase_order',
        context: JSON.stringify({
          vendor: 'AWS',
          amount: 50000,
          currency: 'USD',
          category: 'Cloud Infrastructure'
        }, null, 2),
        title: 'Purchase Order Approval',
        description: 'AWS infrastructure spend: $50,000 for Q1 2025.',
        timeout: 7200
      },
      migration: {
        workflowType: 'database_migration',
        context: JSON.stringify({
          database: 'production-postgres',
          migration_script: 'add_user_preferences_table.sql',
          backup_taken: true
        }, null, 2),
        title: 'Database Migration Approval',
        description: 'Run migration script on production database.',
        timeout: 1800
      },
      feature: {
        workflowType: 'feature_flag',
        context: JSON.stringify({
          flag_name: 'new_checkout_flow',
          environment: 'production',
          rollout_percentage: 10
        }, null, 2),
        title: 'Feature Flag Approval',
        description: 'Enable new checkout flow for 10% of users.',
        timeout: 3600
      },
      contract: {
        workflowType: 'contract_signing',
        context: JSON.stringify({
          client: 'Acme Corporation',
          contract_value: 100000,
          duration: '12 months'
        }, null, 2),
        title: 'Contract Approval',
        description: 'Sign 12-month contract with Acme Corporation.',
        timeout: 86400
      },
      refund: {
        workflowType: 'customer_refund',
        context: JSON.stringify({
          customer_id: 'CUST-12345',
          order_id: 'ORD-98765',
          amount: 599.99,
          reason: 'Product defect'
        }, null, 2),
        title: 'Customer Refund Approval',
        description: 'Issue $599.99 refund for defective product.',
        timeout: 7200
      }
    };

    const example = examples[type];
    if (example) {
      document.getElementById('workflowType').value = example.workflowType;
      document.getElementById('workflowContext').value = example.context;
      document.getElementById('approvalTitle').value = example.title;
      document.getElementById('approvalDescription').value = example.description;
      document.getElementById('approvalTimeout').value = example.timeout;

      Toast.success(`Loaded ${type} example`);
    }
  },

  /**
   * Load multi-step workflow example
   */
  loadMultiStepExample(type) {
    const multiStepExamples = {
      deployment: {
        workflowType: 'deployment_pipeline',
        context: JSON.stringify({
          env: 'production',
          service: 'payment-api',
          version: 'v2.5.0',
          deployer: 'alice@company.com'
        }, null, 2),
        steps: [
          {
            type: 'task',
            handler: 'validate_environment',
            input: { env: 'production', service: 'payment-api' }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Pre-Deployment Security Review',
                description: 'Review security checks before deployment',
                fields: [
                  { name: 'reviewer_name', type: 'text', label: 'Reviewer Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 1800
            }
          },
          {
            type: 'task',
            handler: 'deploy_to_production',
            input: { version: 'v2.5.0', service: 'payment-api' }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Post-Deployment Verification',
                description: 'Verify deployment success and health checks',
                fields: [
                  { name: 'reviewer_name', type: 'text', label: 'Reviewer Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 3600
            }
          }
        ]
      },
      purchase: {
        workflowType: 'purchase_approval_chain',
        context: JSON.stringify({
          vendor: 'AWS',
          amount: 50000,
          currency: 'USD',
          category: 'Cloud Infrastructure'
        }, null, 2),
        steps: [
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Manager Approval',
                description: 'AWS infrastructure spend: $50,000 for Q1 2025',
                fields: [
                  { name: 'manager_name', type: 'text', label: 'Manager Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 3600
            }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Finance Approval',
                description: 'Budget verification for $50,000 AWS spend',
                fields: [
                  { name: 'finance_reviewer', type: 'text', label: 'Finance Reviewer', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 7200
            }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Executive Approval',
                description: 'Final executive sign-off for infrastructure spend',
                fields: [
                  { name: 'executive_name', type: 'text', label: 'Executive Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 14400
            }
          },
          {
            type: 'task',
            handler: 'process_purchase_order',
            input: { vendor: 'AWS', amount: 50000 }
          }
        ]
      },
      migration: {
        workflowType: 'database_migration_pipeline',
        context: JSON.stringify({
          database: 'production-postgres',
          migration_script: 'add_user_preferences_table.sql',
          backup_taken: true
        }, null, 2),
        steps: [
          {
            type: 'task',
            handler: 'backup_database',
            input: { database: 'production-postgres' }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Backup Verification',
                description: 'Verify database backup completed successfully',
                fields: [
                  { name: 'dba_name', type: 'text', label: 'DBA Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 1800
            }
          },
          {
            type: 'task',
            handler: 'run_migration_script',
            input: { script: 'add_user_preferences_table.sql' }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Migration Success Verification',
                description: 'Confirm migration completed without errors',
                fields: [
                  { name: 'reviewer_name', type: 'text', label: 'Reviewer Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 1800
            }
          }
        ]
      },
      feature: {
        workflowType: 'feature_rollout_pipeline',
        context: JSON.stringify({
          flag_name: 'new_checkout_flow',
          environment: 'production',
          rollout_percentage: 10
        }, null, 2),
        steps: [
          {
            type: 'task',
            handler: 'validate_feature_flag',
            input: { flag_name: 'new_checkout_flow' }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Product Manager Approval',
                description: 'Approve feature rollout to 10% of users',
                fields: [
                  { name: 'pm_name', type: 'text', label: 'Product Manager', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 3600
            }
          },
          {
            type: 'task',
            handler: 'enable_feature_flag',
            input: { flag_name: 'new_checkout_flow', percentage: 10 }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Post-Rollout Monitoring',
                description: 'Verify metrics and user feedback after rollout',
                fields: [
                  { name: 'engineer_name', type: 'text', label: 'Engineer Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 7200
            }
          }
        ]
      },
      contract: {
        workflowType: 'contract_signing_workflow',
        context: JSON.stringify({
          client: 'Acme Corporation',
          contract_value: 100000,
          duration: '12 months'
        }, null, 2),
        steps: [
          {
            type: 'task',
            handler: 'generate_contract',
            input: { client: 'Acme Corporation', value: 100000 }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Legal Review',
                description: 'Legal team review of contract terms',
                fields: [
                  { name: 'legal_reviewer', type: 'text', label: 'Legal Reviewer', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 86400
            }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Executive Sign-Off',
                description: '12-month contract with Acme Corporation',
                fields: [
                  { name: 'executive_name', type: 'text', label: 'Executive Name', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 86400
            }
          }
        ]
      },
      refund: {
        workflowType: 'customer_refund_workflow',
        context: JSON.stringify({
          customer_id: 'CUST-12345',
          order_id: 'ORD-98765',
          amount: 599.99,
          reason: 'Product defect'
        }, null, 2),
        steps: [
          {
            type: 'task',
            handler: 'validate_refund_request',
            input: { customer_id: 'CUST-12345', order_id: 'ORD-98765' }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Customer Service Approval',
                description: 'Review refund request for product defect',
                fields: [
                  { name: 'cs_agent', type: 'text', label: 'CS Agent', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 3600
            }
          },
          {
            type: 'approval',
            input: {
              ui_schema: {
                title: 'Finance Approval',
                description: 'Approve $599.99 refund to customer',
                fields: [
                  { name: 'finance_reviewer', type: 'text', label: 'Finance Reviewer', required: true }
                ],
                buttons: [
                  { action: 'approve', label: 'Approve', style: 'primary' },
                  { action: 'reject', label: 'Reject', style: 'danger' }
                ]
              },
              timeout_seconds: 7200
            }
          },
          {
            type: 'task',
            handler: 'process_refund',
            input: { customer_id: 'CUST-12345', amount: 599.99 }
          }
        ]
      }
    };

    const example = multiStepExamples[type];
    if (example) {
      // Populate workflow type and context
      document.getElementById('workflowType').value = example.workflowType;
      document.getElementById('workflowContext').value = example.context;

      // Initialize StepBuilder with the steps
      StepBuilder.init();
      StepBuilder.steps = example.steps;
      StepBuilder.render();

      Toast.success(`Loaded ${type} multi-step example`);
    }
  }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
  window.Forms = Forms;
  window.CreateWorkflow = CreateWorkflow;
}
