// Pump Detection Dashboard JavaScript
// API_URL and API_KEY are defined in common.js
let signalChart = null;
let strengthChart = null;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing Pump Detection Dashboard...');
    initCharts();
    updateTime();
    loadDashboard();

    // Auto-refresh every 10 seconds
    setInterval(loadDashboard, 10000);
    setInterval(updateTime, 1000);
});

// Update current time
function updateTime() {
    const now = new Date();
    document.getElementById('current-time').textContent = now.toLocaleTimeString();
}

// Load dashboard data
async function loadDashboard() {
    try {
        // Load statistics
        const stats = await fetchAPI('/status');
        updateStatistics(stats);

        // Load active signals
        const signals = await fetchAPI('/signals/active');
        updateSignalsTable(signals);

        // Load history
        const history = await fetchAPI('/signals/history?limit=10');
        updateHistoryTable(history);

        // Update charts
        const chartData = await fetchAPI('/statistics');
        updateCharts(chartData);

    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}

// fetchAPI function is already defined in common.js

// Update statistics cards
function updateStatistics(data) {
    if (data.statistics) {
        document.getElementById('active-signals').textContent =
            data.statistics.active_signals || 0;
        document.getElementById('signals-24h').textContent =
            data.statistics.signals_24h || 0;

        // Show 7-day pumps if no 24h pumps (more informative)
        const pumps24h = data.statistics.pumps_24h || 0;
        const pumps7d = data.statistics.pumps_7d || 0;

        if (pumps24h === 0 && pumps7d > 0) {
            // Show 7-day stats if no 24h pumps
            document.getElementById('pumps-24h').textContent = pumps7d;
            // Update the label to indicate 7-day period
            const pumpCard = document.querySelector('#pumps-24h').closest('.card-body');
            if (pumpCard) {
                const subtitle = pumpCard.querySelector('.card-subtitle');
                if (subtitle) subtitle.textContent = '7d Confirmed Pumps';
                const badge = pumpCard.querySelector('.text-info');
                if (badge) badge.innerHTML = '<i class="bi bi-check-circle"></i> 7 days';
            }
        } else {
            document.getElementById('pumps-24h').textContent = pumps24h;
        }

        // Calculate accuracy based on available data
        const total = data.statistics.signals_7d || data.statistics.signals_24h || 0;
        const confirmed = pumps7d || pumps24h || 0;
        const accuracy = total > 0 ? ((confirmed / total) * 100).toFixed(1) : 0;
        document.getElementById('accuracy').textContent = `${accuracy}%`;

        // Show average gain if available
        if (data.statistics.avg_gain_7d) {
            const accuracyCard = document.querySelector('#accuracy').closest('.card-body');
            if (accuracyCard) {
                const badge = accuracyCard.querySelector('.text-warning');
                if (badge) {
                    badge.innerHTML = `<i class="bi bi-graph-up"></i> Avg: ${data.statistics.avg_gain_7d.toFixed(1)}%`;
                }
            }
        }
    }
}

// Update signals table
function updateSignalsTable(data) {
    const tbody = document.getElementById('signals-tbody');
    const noSignals = document.getElementById('no-signals');

    // Check if data has signals array
    const signals = data.signals || [];

    if (!signals || signals.length === 0) {
        tbody.innerHTML = '';
        noSignals.style.display = 'block';
        document.getElementById('signals-table').style.display = 'none';
        return;
    }

    noSignals.style.display = 'none';
    document.getElementById('signals-table').style.display = 'table';

    tbody.innerHTML = signals.map(signal => {
        const strengthClass = getStrengthClass(signal.signal_strength);
        const confidence = signal.initial_confidence || signal.total_score || 0;
        const priceChange = signal.max_price_increase || 0;
        const priceChangeClass = priceChange > 0 ? 'price-up' :
                                 priceChange < 0 ? 'price-down' : 'price-neutral';
        const priceIcon = priceChange > 0 ? '↑' :
                         priceChange < 0 ? '↓' : '→';

        return `
            <tr>
                <td><strong>${signal.pair_symbol}</strong></td>
                <td>${formatTime(signal.signal_timestamp)}</td>
                <td><span class="badge ${strengthClass}">${signal.signal_strength || 'N/A'}</span></td>
                <td>${parseFloat(signal.futures_spike_ratio_7d || 0).toFixed(2)}x</td>
                <td>
                    <div class="confidence-bar">
                        <div class="confidence-fill ${getConfidenceClass(confidence)}"
                             style="width: ${confidence}%"></div>
                    </div>
                    <small>${confidence}%</small>
                </td>
                <td class="${priceChangeClass}">
                    ${priceIcon} ${Math.abs(priceChange).toFixed(2)}%
                </td>
                <td><span class="badge bg-warning">${signal.status}</span></td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="viewSignal(${signal.id})">
                        <i class="bi bi-eye"></i>
                    </button>
                    <a href="https://www.binance.com/en/trade/${signal.pair_symbol}"
                       target="_blank" class="btn btn-sm btn-success">
                        <i class="bi bi-box-arrow-up-right"></i>
                    </a>
                </td>
            </tr>
        `;
    }).join('');
}

// Update history table
function updateHistoryTable(data) {
    const tbody = document.getElementById('history-tbody');

    // Check if data has signals array
    const history = data.signals || [];

    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No history available</td></tr>';
        return;
    }

    tbody.innerHTML = history.map(item => {
        const resultBadge = item.pump_realized ?
            '<span class="badge bg-success">PUMP</span>' :
            '<span class="badge bg-secondary">NO PUMP</span>';

        const gain = item.max_price_increase || 0;
        const gainClass = gain > 0 ? 'price-up' : 'price-neutral';

        return `
            <tr>
                <td>${formatTime(item.signal_timestamp)}</td>
                <td>${item.pair_symbol}</td>
                <td>${resultBadge}</td>
                <td class="${gainClass}">${parseFloat(gain).toFixed(2)}%</td>
                <td>${item.signal_strength || 'N/A'}</td>
            </tr>
        `;
    }).join('');
}

// Initialize charts
function initCharts() {
    // Signal activity chart
    const signalCtx = document.getElementById('signalChart').getContext('2d');
    signalChart = new Chart(signalCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Signals',
                data: [],
                borderColor: '#58a6ff',
                backgroundColor: 'rgba(88, 166, 255, 0.1)',
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: '#30363d' },
                    ticks: { color: '#8b949e' }
                },
                x: {
                    grid: { color: '#30363d' },
                    ticks: { color: '#8b949e' }
                }
            }
        }
    });

    // Strength distribution chart
    const strengthCtx = document.getElementById('strengthChart').getContext('2d');
    strengthChart = new Chart(strengthCtx, {
        type: 'doughnut',
        data: {
            labels: ['WEAK', 'MEDIUM', 'STRONG', 'EXTREME'],
            datasets: [{
                data: [0, 0, 0, 0],
                backgroundColor: [
                    '#6c757d',
                    '#f0c674',
                    '#ff8c00',
                    '#f85149'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#c9d1d9' }
                }
            }
        }
    });
}

// Update charts
function updateCharts(data) {
    if (!data) return;

    // Update signal activity chart
    if (data.hourly_signals) {
        const hours = Object.keys(data.hourly_signals).slice(-24);
        const values = hours.map(h => data.hourly_signals[h] || 0);

        signalChart.data.labels = hours.map(h => `${h}:00`);
        signalChart.data.datasets[0].data = values;
        signalChart.update();
    }

    // Update strength distribution
    if (data.strength_distribution) {
        const distribution = data.strength_distribution;
        strengthChart.data.datasets[0].data = [
            distribution.WEAK || 0,
            distribution.MEDIUM || 0,
            distribution.STRONG || 0,
            distribution.EXTREME || 0
        ];
        strengthChart.update();
    }
}

// View signal details
async function viewSignal(signalId) {
    try {
        const response = await fetchAPI(`/signals/${signalId}`);
        const signal = response.signal || response;

        const modal = new bootstrap.Modal(document.getElementById('signalModal'));
        document.getElementById('signal-details').innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <h6>Signal Information</h6>
                    <p><strong>Pair:</strong> ${signal.pair_symbol}</p>
                    <p><strong>Time:</strong> ${formatTime(signal.signal_timestamp)}</p>
                    <p><strong>Strength:</strong> <span class="badge ${getStrengthClass(signal.signal_strength)}">${signal.signal_strength}</span></p>
                    <p><strong>Status:</strong> <span class="badge bg-warning">${signal.status}</span></p>
                </div>
                <div class="col-md-6">
                    <h6>Metrics</h6>
                    <p><strong>7D Spike:</strong> ${parseFloat(signal.futures_spike_ratio_7d || 0).toFixed(2)}x</p>
                    <p><strong>14D Spike:</strong> ${parseFloat(signal.futures_spike_ratio_14d || 0).toFixed(2)}x</p>
                    <p><strong>Confidence:</strong> ${signal.initial_confidence || signal.total_score || 0}%</p>
                    <p><strong>Max Gain:</strong> ${parseFloat(signal.max_price_increase || 0).toFixed(2)}%</p>
                </div>
            </div>
            <hr>
            <div class="text-center">
                <a href="https://www.binance.com/en/trade/${signal.pair_symbol}"
                   target="_blank" class="btn btn-success">
                    <i class="bi bi-box-arrow-up-right"></i> Open on Binance
                </a>
            </div>
        `;

        modal.show();
    } catch (error) {
        console.error('Error loading signal details:', error);
        alert('Failed to load signal details');
    }
}

// Refresh signals manually
function refreshSignals() {
    const btn = event.target;
    btn.innerHTML = '<span class="loading"></span> Loading...';
    btn.disabled = true;

    loadDashboard().finally(() => {
        btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Refresh';
        btn.disabled = false;
    });
}

// Helper functions
function getStrengthClass(strength) {
    switch (strength) {
        case 'WEAK': return 'signal-strength-weak';
        case 'MEDIUM': return 'signal-strength-medium';
        case 'STRONG': return 'signal-strength-strong';
        case 'EXTREME': return 'signal-strength-extreme';
        default: return 'badge-secondary';
    }
}

function getConfidenceClass(confidence) {
    if (confidence >= 80) return 'confidence-extreme';
    if (confidence >= 60) return 'confidence-high';
    if (confidence >= 40) return 'confidence-medium';
    return 'confidence-low';
}

function formatTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;

    return date.toLocaleString();
}