// Common JavaScript functions for all pages
const API_URL = '/api/v1';
const API_KEY = 'c94525f138d5be1c2bc70ca407895cef8ae2baf5d3db3fc2b01097e5f1fc9615';

// Fetch from API with authentication
async function fetchAPI(endpoint) {
    try {
        const response = await fetch(`${API_URL}${endpoint}`, {
            headers: {
                'X-API-Key': API_KEY
            }
        });

        if (!response.ok) {
            console.error(`API error for ${endpoint}: ${response.status}`);
            throw new Error(`API error: ${response.status}`);
        }

        const data = await response.json();
        console.log(`API response for ${endpoint}:`, data);
        return data;
    } catch (error) {
        console.error(`Error fetching ${endpoint}:`, error);
        throw error;
    }
}

// Get strength badge class
function getStrengthClass(strength) {
    switch (strength) {
        case 'WEAK': return 'bg-secondary';
        case 'MEDIUM': return 'bg-warning';
        case 'STRONG': return 'bg-orange';
        case 'EXTREME': return 'bg-danger';
        default: return 'bg-secondary';
    }
}

// Format time
function formatTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;

    return date.toLocaleString();
}

// Get confidence class
function getConfidenceClass(confidence) {
    if (confidence >= 80) return 'confidence-extreme';
    if (confidence >= 60) return 'confidence-high';
    if (confidence >= 40) return 'confidence-medium';
    return 'confidence-low';
}

// Export data to CSV
function exportToCSV(data, filename) {
    if (!data || data.length === 0) {
        alert('No data to export');
        return;
    }

    const headers = Object.keys(data[0]);
    const csv = [
        headers.join(','),
        ...data.map(row =>
            headers.map(header => {
                const value = row[header];
                return typeof value === 'string' && value.includes(',') ?
                    `"${value}"` : value;
            }).join(',')
        )
    ].join('\n');

    downloadFile(csv, filename, 'text/csv');
}

// Download file
function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

// Show loading spinner
function showLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = '<div class="text-center"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>';
    }
}

// Hide loading spinner
function hideLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = '';
    }
}

// Show error message
function showError(message, elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = `<div class="alert alert-danger" role="alert">${message}</div>`;
    }
}

// Initialize tooltips
function initTooltips() {
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
}

// Update current time in navbar
function updateTime() {
    const element = document.getElementById('current-time');
    if (element) {
        const now = new Date();
        element.textContent = now.toLocaleTimeString();
    }
}

// Document ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('Common JS loaded');
    initTooltips();

    // Start time update
    updateTime();
    setInterval(updateTime, 1000);
});