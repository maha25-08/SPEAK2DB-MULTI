// Student Dashboard JavaScript

// ===== DASHBOARD DATA LOADING =====
document.addEventListener('DOMContentLoaded', function() {
    loadDashboardData();
    setupAutoRefresh();
});

function loadDashboardData() {
    // Show loading state
    showLoading();
    
    // Fetch dashboard data from API
    fetch('/student/api/dashboard')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load dashboard data');
            }
            return response.json();
        })
        .then(data => {
            updateDashboardUI(data);
            hideLoading();
        })
        .catch(error => {
            console.error('Error loading dashboard data:', error);
            showError('Failed to load dashboard data. Please refresh the page.');
            hideLoading();
        });
}

function updateDashboardUI(data) {
    // Update student info
    updateStudentInfo(data.student_info);
    
    // Update stats
    updateStats(data);
    
    // Update tables
    updateCurrentBooks(data.current_books);
    updateOverdueBooks(data.overdue_books);
    updateUnpaidFines(data.unpaid_fines);
    updateBorrowingHistory(data.borrowing_history);
}

function updateStudentInfo(studentInfo) {
    if (studentInfo) {
        const welcomeElement = document.querySelector('.student-welcome h2');
        const subtitleElement = document.querySelector('.student-welcome p');
        
        if (welcomeElement) {
            welcomeElement.innerHTML = `<i class="fas fa-graduation-cap"></i> Welcome back, ${studentInfo.name}!`;
        }
        
        if (subtitleElement) {
            subtitleElement.textContent = `${studentInfo.branch} • Year ${studentInfo.year} • ${studentInfo.student_type}`;
        }
    }
}

function updateStats(data) {
    const currentBooksCount = data.current_books.length;
    const overdueBooksCount = data.overdue_books.length;
    const unpaidFinesCount = data.unpaid_fines.length;
    const totalBorrowedCount = data.borrowing_history.length;
    
    // Update stat cards
    updateStatCard('current-books', currentBooksCount);
    updateStatCard('overdue-books', overdueBooksCount);
    updateStatCard('unpaid-fines', unpaidFinesCount);
    updateStatCard('total-borrowed', totalBorrowedCount);
}

function updateStatCard(cardId, count) {
    const card = document.querySelector(`#${cardId} h3`);
    if (card) {
        card.textContent = count;
        card.classList.add('fade-in');
    }
}

function updateCurrentBooks(books) {
    const tbody = document.querySelector('#current-books-tbody');
    if (!tbody) return;
    
    if (books.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted">No books currently borrowed.</td></tr>';
        return;
    }
    
    tbody.innerHTML = books.map(book => `
        <tr class="fade-in">
            <td>${book.title}</td>
            <td>${book.author}</td>
            <td>${book.isbn}</td>
            <td>${formatDate(book.issue_date)}</td>
            <td>${formatDate(book.due_date)}</td>
            <td>
                <span class="badge bg-${getStatusColor(book.status)} badge-status">
                    ${book.status}
                </span>
            </td>
        </tr>
    `).join('');
}

function updateOverdueBooks(books) {
    const tbody = document.querySelector('#overdue-books-tbody');
    if (!tbody) return;
    
    if (books.length === 0) {
        // Hide overdue section if no overdue books
        const overdueSection = document.querySelector('#overdue-section');
        if (overdueSection) {
            overdueSection.style.display = 'none';
        }
        return;
    }
    
    tbody.innerHTML = books.map(book => {
        const daysOverdue = calculateDaysOverdue(book.due_date);
        return `
            <tr class="fade-in">
                <td>${book.title}</td>
                <td>${book.author}</td>
                <td>${formatDate(book.due_date)}</td>
                <td>
                    <span class="badge bg-danger">
                        ${daysOverdue} days
                    </span>
                </td>
            </tr>
        `;
    }).join('');
}

function updateUnpaidFines(fines) {
    const tbody = document.querySelector('#unpaid-fines-tbody');
    if (!tbody) return;
    
    if (fines.length === 0) {
        // Hide fines section if no unpaid fines
        const finesSection = document.querySelector('#fines-section');
        if (finesSection) {
            finesSection.style.display = 'none';
        }
        return;
    }
    
    tbody.innerHTML = fines.map(fine => `
        <tr class="fade-in">
            <td>${fine.fine_type}</td>
            <td>₹${fine.fine_amount}</td>
            <td>${formatDate(fine.fine_date)}</td>
            <td>
                <span class="badge bg-danger">${fine.status}</span>
            </td>
        </tr>
    `).join('');
}

function updateBorrowingHistory(history) {
    const tbody = document.querySelector('#history-tbody');
    if (!tbody) return;
    
    if (history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-muted">No borrowing history available.</td></tr>';
        return;
    }
    
    tbody.innerHTML = history.map(record => `
        <tr class="fade-in">
            <td>${record.title}</td>
            <td>${record.author}</td>
            <td>${formatDate(record.issue_date)}</td>
            <td>${record.return_date || 'Not returned'}</td>
            <td>
                <span class="badge bg-${getStatusColor(record.status)} badge-status">
                    ${record.status}
                </span>
            </td>
        </tr>
    `).join('');
}

// ===== UTILITY FUNCTIONS =====
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric' 
    });
}

function calculateDaysOverdue(dueDate) {
    const due = new Date(dueDate);
    const today = new Date();
    const diffTime = Math.abs(today - due);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
}

function getStatusColor(status) {
    const colorMap = {
        'Normal': 'success',
        'Overdue': 'warning',
        'Lost': 'danger',
        'Damaged': 'info',
        'Extended': 'primary'
    };
    return colorMap[status] || 'secondary';
}

// ===== LOADING STATES =====
function showLoading() {
    const loadingElements = document.querySelectorAll('.loading-spinner');
    loadingElements.forEach(el => el.style.display = 'inline-block');
}

function hideLoading() {
    const loadingElements = document.querySelectorAll('.loading-spinner');
    loadingElements.forEach(el => el.style.display = 'none');
}

function showError(message) {
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-danger alert-dismissible fade show';
    alertDiv.innerHTML = `
        <i class="fas fa-exclamation-triangle"></i> ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    const container = document.querySelector('.container');
    if (container) {
        container.insertBefore(alertDiv, container.firstChild);
    }
}

// ===== AUTO REFRESH =====
function setupAutoRefresh() {
    // Refresh dashboard data every 5 minutes
    setInterval(loadDashboardData, 5 * 60 * 1000);
}

// ===== PROFILE PAGE =====
function loadProfileData() {
    fetch('/student/api/dashboard')
        .then(response => response.json())
        .then(data => {
            updateProfileUI(data.student_info);
        })
        .catch(error => {
            console.error('Error loading profile data:', error);
        });
}

function updateProfileUI(studentInfo) {
    if (!studentInfo) return;
    
    // Update profile fields
    const fields = {
        'student-id': studentInfo.id,
        'student-name': studentInfo.name,
        'student-branch': studentInfo.branch,
        'student-year': studentInfo.year,
        'student-type': studentInfo.student_type,
        'student-email': studentInfo.email,
        'student-phone': studentInfo.phone
    };
    
    Object.keys(fields).forEach(fieldId => {
        const element = document.getElementById(fieldId);
        if (element) {
            element.textContent = fields[fieldId];
        }
    });
}

// ===== NAVIGATION =====
function navigateToDashboard() {
    window.location.href = '/student/dashboard';
}

function navigateToProfile() {
    window.location.href = '/student/profile';
}

function logout() {
    window.location.href = '/logout';
}

// ===== SEARCH AND FILTER =====
function setupSearch() {
    const searchInput = document.querySelector('#search-input');
    if (!searchInput) return;
    
    searchInput.addEventListener('input', function(e) {
        const searchTerm = e.target.value.toLowerCase();
        filterTables(searchTerm);
    });
}

function filterTables(searchTerm) {
    const tables = document.querySelectorAll('.book-table tbody tr');
    
    tables.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

// Initialize search if on dashboard
if (document.querySelector('#search-input')) {
    setupSearch();
}
