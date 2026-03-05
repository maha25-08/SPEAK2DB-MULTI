/**
 * 🎨 ROLE-BASED UI JAVASCRIPT
 * Dynamic interface adaptation based on user roles and permissions
 */

class RBACUI {
    constructor() {
        this.userRole = null;
        this.userPermissions = [];
        this.uiConfig = null;
        this.init();
    }

    async init() {
        // Load user information from API
        await this.loadUserInfo();
        
        // Apply role-based styling
        this.applyRoleStyling();
        
        // Initialize dynamic components
        this.initializeComponents();
        
        // Set up event listeners
        this.setupEventListeners();
        
        // Load dashboard widgets
        this.loadDashboardWidgets();
    }

    async loadUserInfo() {
        try {
            const response = await fetch('/api/user/info');
            if (response.ok) {
                const data = await response.json();
                this.userRole = data.role;
                this.userPermissions = data.permissions;
                this.uiConfig = await this.loadUIConfig();
            }
        } catch (error) {
            console.error('Failed to load user info:', error);
            // Fallback to basic functionality
            this.userRole = 'Student';
            this.userPermissions = ['search_books', 'view_my_loans'];
        }
    }

    async loadUIConfig() {
        try {
            const response = await fetch('/api/menu');
            if (response.ok) {
                return await response.json();
            }
        } catch (error) {
            console.error('Failed to load UI config:', error);
            return { menu_items: [] };
        }
    }

    applyRoleStyling() {
        const body = document.body;
        const dashboard = document.querySelector('.dashboard');
        
        // Remove existing role classes
        body.classList.remove('student-theme', 'librarian-theme', 'admin-theme');
        dashboard.classList.remove('student-theme', 'librarian-theme', 'admin-theme');
        
        // Apply current role class
        const roleClass = `${this.userRole.toLowerCase()}-theme`;
        body.classList.add(roleClass);
        dashboard.classList.add(roleClass);
        
        // Apply role-specific CSS variables
        this.applyCSSVariables();
        
        // Update role badge
        this.updateRoleBadge();
    }

    applyCSSVariables() {
        const root = document.documentElement;
        const themeConfig = this.getThemeConfig();
        
        Object.keys(themeConfig).forEach(key => {
            root.style.setProperty(`--${key}`, themeConfig[key]);
        });
    }

    getThemeConfig() {
        const themes = {
            'Student': {
                'primary-color': '#4CAF50',
                'secondary-color': '#2196F3',
                'accent-color': '#FF9800',
                'background-color': '#f1f8e9',
                'sidebar-color': '#2E7D32',
                'card-shadow': '0 4px 8px rgba(76, 175, 80, 0.15)'
            },
            'Librarian': {
                'primary-color': '#2196F3',
                'secondary-color': '#FF9800',
                'accent-color': '#4CAF50',
                'background-color': '#e3f2fd',
                'sidebar-color': '#1565C0',
                'card-shadow': '0 4px 8px rgba(33, 150, 243, 0.15)'
            },
            'Administrator': {
                'primary-color': '#9C27B0',
                'secondary-color': '#F44336',
                'accent-color': '#2196F3',
                'background-color': '#f3e5f5',
                'sidebar-color': '#6A1B9A',
                'card-shadow': '0 4px 8px rgba(156, 39, 176, 0.15)'
            }
        };
        
        return themes[this.userRole] || themes['Student'];
    }

    updateRoleBadge() {
        const roleBadge = document.querySelector('.role-badge');
        if (roleBadge) {
            roleBadge.textContent = this.userRole;
            roleBadge.className = `role-badge badge-${this.userRole.toLowerCase()}`;
        }
    }

    initializeComponents() {
        // Initialize search functionality
        this.initializeSearch();
        
        // Initialize navigation
        this.initializeNavigation();
        
        // Initialize widgets
        this.initializeWidgets();
        
        // Initialize notifications
        this.initializeNotifications();
    }

    initializeSearch() {
        const searchInput = document.getElementById('searchInput');
        const suggestionsDropdown = document.getElementById('suggestionsDropdown');
        
        if (!searchInput) return;

        // Role-based search suggestions
        const suggestions = this.getSearchSuggestions();
        
        searchInput.addEventListener('focus', () => {
            this.showSuggestions(suggestions);
        });

        searchInput.addEventListener('input', (e) => {
            const value = e.target.value.toLowerCase();
            const filtered = suggestions.filter(s => 
                s.toLowerCase().includes(value)
            );
            this.showSuggestions(filtered);
        });

        searchInput.addEventListener('blur', () => {
            setTimeout(() => this.hideSuggestions(), 200);
        });

        // Handle search submission
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.handleSearch(e.target.value);
            }
        });
    }

    getSearchSuggestions() {
        const suggestions = {
            'Student': [
                'My current books',
                'My overdue books',
                'My fines',
                'Books by my department',
                'Recommended for me',
                'My borrowing history',
                'My reservations'
            ],
            'Librarian': [
                'All overdue books',
                'Books issued today',
                'Student borrowing history',
                'Circulation report',
                'Library statistics',
                'Popular books this month',
                'Student fine reports'
            ],
            'Administrator': [
                'User management',
                'Role assignments',
                'System configuration',
                'Audit logs',
                'Financial reports',
                'Department statistics',
                'Security alerts',
                'System performance'
            ]
        };
        
        return suggestions[this.userRole] || suggestions['Student'];
    }

    showSuggestions(suggestions) {
        const dropdown = document.getElementById('suggestionsDropdown');
        if (!dropdown) return;
        
        dropdown.innerHTML = suggestions.map(suggestion => `
            <div class="suggestion-item" onclick="rbacUI.selectSuggestion('${suggestion.replace(/'/g, "\\'")}')">
                💡 ${suggestion}
            </div>
        `).join('');
        
        dropdown.style.display = 'block';
    }

    hideSuggestions() {
        const dropdown = document.getElementById('suggestionsDropdown');
        if (dropdown) {
            dropdown.style.display = 'none';
        }
    }

    selectSuggestion(suggestion) {
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.value = suggestion;
        }
        this.hideSuggestions();
    }

    handleSearch(query) {
        if (!query.trim()) return;
        
        // Submit search via AJAX
        fetch('/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ query: query })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.displaySearchResults(data);
            } else {
                this.showError(data.error);
            }
        })
        .catch(error => {
            console.error('Search error:', error);
            this.showError('Search failed. Please try again.');
        });
    }

    displaySearchResults(data) {
        // Implementation for displaying search results
        console.log('Search results:', data);
        // You can customize this based on your needs
    }

    showError(message) {
        // Implementation for displaying errors
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.innerHTML = `
            <div class="error-content">
                <span class="error-icon">❌</span>
                <span class="error-text">${message}</span>
            </div>
        `;
        
        // Insert error message at the top of the main content
        const mainContent = document.querySelector('.main-content');
        if (mainContent) {
            mainContent.insertBefore(errorDiv, mainContent.firstChild);
            
            // Auto-remove after 5 seconds
            setTimeout(() => {
                errorDiv.remove();
            }, 5000);
        }
    }

    initializeNavigation() {
        // Add smooth scrolling to navigation links
        const navLinks = document.querySelectorAll('.quick-action');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                if (this.hasPermission(link.dataset.permission)) {
                    // Smooth transition effect
                    e.preventDefault();
                    this.showPageTransition();
                    
                    setTimeout(() => {
                        window.location.href = link.href;
                    }, 300);
                } else {
                    e.preventDefault();
                    this.showPermissionDenied(link.dataset.permission);
                }
            });
        });
    }

    hasPermission(permission) {
        return !permission || this.userPermissions.includes(permission);
    }

    showPermissionDenied(permission) {
        this.showError(`Permission denied: ${permission}`);
    }

    showPageTransition() {
        const overlay = document.createElement('div');
        overlay.className = 'page-transition-overlay';
        overlay.innerHTML = `
            <div class="transition-content">
                <div class="spinner"></div>
                <div>Loading...</div>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    initializeWidgets() {
        // Add interactive features to widgets
        const widgets = document.querySelectorAll('.widget');
        widgets.forEach(widget => {
            widget.addEventListener('mouseenter', () => {
                widget.style.transform = 'translateY(-8px) scale(1.02)';
            });
            
            widget.addEventListener('mouseleave', () => {
                widget.style.transform = 'translateY(0) scale(1)';
            });
        });
    }

    loadDashboardWidgets() {
        // Load widget data based on user role
        const widgetTypes = this.getWidgetTypes();
        
        widgetTypes.forEach((widgetType, index) => {
            this.loadWidgetData(widgetType, index + 1);
        });
    }

    getWidgetTypes() {
        const widgetTypes = {
            'Student': [
                'current_books',
                'overdue_alerts',
                'fine_summary',
                'reading_stats'
            ],
            'Librarian': [
                'library_stats',
                'circulation_chart',
                'overdue_books',
                'popular_books',
                'quick_checkout',
                'student_activity'
            ],
            'Administrator': [
                'system_overview',
                'user_statistics',
                'role_distribution',
                'activity_monitor',
                'financial_overview',
                'system_health',
                'security_alerts',
                'performance_metrics'
            ]
        };
        
        return widgetTypes[this.userRole] || widgetTypes['Student'];
    }

    async loadWidgetData(widgetType, widgetIndex) {
        const widgetElement = document.getElementById(`widget-${widgetIndex}`);
        if (!widgetElement) return;

        try {
            // Show loading state
            widgetElement.innerHTML = this.getLoadingHTML();
            
            // Load widget-specific data
            const data = await this.fetchWidgetData(widgetType);
            
            // Render widget content
            widgetElement.innerHTML = this.renderWidget(widgetType, data);
            
        } catch (error) {
            console.error(`Failed to load widget ${widgetType}:`, error);
            widgetElement.innerHTML = this.getErrorHTML(widgetType);
        }
    }

    async fetchWidgetData(widgetType) {
        const response = await fetch(`/api/widget/${widgetType}`);
        if (response.ok) {
            return await response.json();
        }
        throw new Error(`Failed to fetch widget data for ${widgetType}`);
    }

    getLoadingHTML() {
        return `
            <div style="text-align: center; padding: 40px;">
                <div class="spinner"></div>
                <div style="margin-top: 10px; color: #999;">Loading...</div>
            </div>
        `;
    }

    getErrorHTML(widgetType) {
        return `
            <div style="text-align: center; padding: 40px;">
                <div style="color: #999; font-size: 48px;">⚠️</div>
                <div style="margin-top: 10px; color: #666;">Failed to load ${widgetType}</div>
            </div>
        `;
    }

    renderWidget(widgetType, data) {
        const renderers = {
            'current_books': this.renderCurrentBooks,
            'library_stats': this.renderLibraryStats,
            'system_overview': this.renderSystemOverview,
            'circulation_chart': this.renderCirculationChart,
            'overdue_alerts': this.renderOverdueAlerts,
            'fine_summary': this.renderFineSummary,
            'reading_stats': this.renderReadingStats,
            'popular_books': this.renderPopularBooks,
            'user_statistics': this.renderUserStatistics,
            'role_distribution': this.renderRoleDistribution
        };
        
        const renderer = renderers[widgetType];
        return renderer ? renderer.call(this, data) : this.getDefaultWidgetHTML(widgetType, data);
    }

    renderCurrentBooks(data) {
        return `
            <div class="current-books-widget">
                ${data.books.length > 0 ? data.books.map(book => `
                    <div class="book-item">
                        <div class="book-title">${book.title}</div>
                        <div class="book-author">${book.author}</div>
                        <div class="book-due">Due: ${book.due_date}</div>
                    </div>
                `).join('') : `
                    <div style="text-align: center; padding: 20px;">
                        <div style="color: #999;">No books currently issued</div>
                    </div>
                `}
            </div>
        `;
    }

    renderLibraryStats(data) {
        return `
            <div class="library-stats-widget">
                <canvas id="libraryChart-${Date.now()}" width="100%" height="200"></canvas>
            </div>
        `;
    }

    renderSystemOverview(data) {
        return `
            <div class="system-overview-widget">
                <div class="system-status">
                    <div class="status-indicator ${data.status}"></div>
                    <div class="status-text">System ${data.status}</div>
                </div>
                <div class="system-metrics">
                    ${data.metrics.map(metric => `
                        <div class="metric">
                            <div class="metric-value">${metric.value}</div>
                            <div class="metric-label">${metric.label}</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    renderCirculationChart(data) {
        const chartId = `circulation-chart-${Date.now()}`;
        return `
            <div class="circulation-chart-widget">
                <canvas id="${chartId}" width="100%" height="200"></canvas>
            </div>
        `;
    }

    renderOverdueAlerts(data) {
        return `
            <div class="overdue-alerts-widget">
                ${data.alerts.length > 0 ? data.alerts.map(alert => `
                    <div class="alert-item overdue">
                        <div class="alert-icon">⚠️</div>
                        <div class="alert-content">
                            <div class="alert-title">${alert.title}</div>
                            <div class="alert-description">${alert.description}</div>
                        </div>
                    </div>
                `).join('') : `
                    <div style="text-align: center; padding: 20px;">
                        <div style="color: #4CAF50; font-size: 24px;">✅</div>
                        <div style="margin-top: 10px;">No overdue items</div>
                    </div>
                `}
            </div>
        `;
    }

    renderFineSummary(data) {
        return `
            <div class="fine-summary-widget">
                <div class="fine-total">
                    <div class="fine-amount">$${data.total_fines}</div>
                    <div class="fine-label">Total Fines</div>
                </div>
                ${data.unpaid_fines > 0 ? `
                    <div class="unpaid-warning">
                        <div class="warning-icon">💳</div>
                        <div class="warning-text">${data.unpaid_fines} unpaid fines</div>
                    </div>
                ` : ''}
            </div>
        `;
    }

    renderReadingStats(data) {
        return `
            <div class="reading-stats-widget">
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-value">${data.books_read}</div>
                        <div class="stat-label">Books Read</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">${data.favorite_genre}</div>
                        <div class="stat-label">Favorite Genre</div>
                    </div>
                </div>
            </div>
        `;
    }

    getDefaultWidgetHTML(widgetType, data) {
        return `
            <div class="default-widget">
                <div style="text-align: center; padding: 20px;">
                    <div style="color: #999; font-size: 48px;">📊</div>
                    <div style="margin-top: 10px; color: #666;">${widgetType}</div>
                </div>
            </div>
        `;
    }

    initializeNotifications() {
        // Set up real-time notifications
        this.setupWebSocket();
        this.setupPolling();
    }

    setupWebSocket() {
        if (typeof WebSocket !== 'undefined') {
            try {
                const ws = new WebSocket(`ws://${window.location.host}/ws`);
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    this.handleNotification(data);
                };
            } catch (error) {
                console.log('WebSocket not available, falling back to polling');
            }
        }
    }

    setupPolling() {
        // Poll for updates every 30 seconds
        setInterval(() => {
            this.checkForUpdates();
        }, 30000);
    }

    async checkForUpdates() {
        try {
            const response = await fetch('/api/updates');
            if (response.ok) {
                const updates = await response.json();
                updates.forEach(update => this.handleNotification(update));
            }
        } catch (error) {
            console.error('Failed to check for updates:', error);
        }
    }

    handleNotification(notification) {
        // Display notification based on type and user permissions
        if (this.hasPermission(notification.permission)) {
            this.showNotification(notification);
        }
    }

    showNotification(notification) {
        const notificationDiv = document.createElement('div');
        notificationDiv.className = 'notification';
        notificationDiv.innerHTML = `
            <div class="notification-content">
                <span class="notification-icon">${notification.icon}</span>
                <span class="notification-message">${notification.message}</span>
                <button class="notification-close" onclick="this.parentElement.parentElement.remove()">×</button>
            </div>
        `;
        
        document.body.appendChild(notificationDiv);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notificationDiv.parentElement) {
                notificationDiv.remove();
            }
        }, 5000);
    }

    setupEventListeners() {
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                switch(e.key) {
                    case 'k':
                        e.preventDefault();
                        document.getElementById('searchInput')?.focus();
                        break;
                    case '/':
                        e.preventDefault();
                        document.getElementById('searchInput')?.focus();
                        break;
                }
            }
        });

        // Responsive sidebar toggle
        const toggleBtn = document.querySelector('.sidebar-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                document.querySelector('.sidebar').classList.toggle('collapsed');
            });
        }
    }
}

// Initialize the RBAC UI system
const rbacUI = new RBACUI();

// Export for global access
window.rbacUI = rbacUI;
