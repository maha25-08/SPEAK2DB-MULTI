// =============================================
// Speak2DB - Basic Frontend JavaScript
// =============================================

// ===== CHART STATE =====
var currentChart = null;
var lastResult = null;
var currentChartType = 'bar';

// ===== SAFE DOM HELPERS =====
function getEl(id) {
    return document.getElementById(id);
}

function hideEl(id) {
    var el = getEl(id);
    if (el) el.style.display = 'none';
}

function showEl(id, display) {
    var el = getEl(id);
    if (el) el.style.display = display || 'block';
}

// ===== VOICE INPUT (Web Speech API) =====
var recognition = null;
var isListening = false;

function initVoice() {
    var SR = window.SpeechRecognition ||
        window.webkitSpeechRecognition;
    if (!SR) {
        console.warn("Speech Recognition not supported");
        var micBtn = getEl('micBtn');
        if (micBtn) {
            micBtn.title = "Voice not supported — Use Chrome";
            micBtn.style.opacity = '0.4';
            micBtn.style.cursor = 'not-allowed';
        }
        return;
    }

    recognition = new SR();
    recognition.lang = 'en-US';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = function () {
        isListening = true;
        var mb = getEl('micBtn');
        if (mb) {
            mb.classList.add('recording');
            mb.innerHTML = '🔴';
        }
        setStatus('🎤 Listening... speak now',
            'status-listening');
    };

    recognition.onresult = function(event){

        let finalTranscript = "";

        for(let i = event.resultIndex; i < event.results.length; i++){

            const transcript = event.results[i][0].transcript;

            if(event.results[i].isFinal){
                finalTranscript += transcript;
            }

        }

        console.log("Final speech:", finalTranscript);

        // Clean speech noise before processing
        finalTranscript = cleanSpeech(finalTranscript);
        console.log("Cleaned speech:", finalTranscript);

        var inp = getEl('queryInput');
        if (inp) {
            inp.value = finalTranscript;
            submitQuery();  // Auto-execute query after voice input
        }
    };

    recognition.onerror = function (event) {
        isListening = false;
        var mb = getEl('micBtn');
        if (mb) {
            mb.classList.remove('recording');
            mb.innerHTML = '🎤';
        }
        setStatus('❌ Error: ' + event.error, 'status-error');
    };

    recognition.onend = function () {
        isListening = false;
        var mb = getEl('micBtn');
        if (mb) {
            mb.classList.remove('recording');
            mb.innerHTML = '🎤';
        }
        setStatus('Ready', 'status-ready');
    };
}

function cleanSpeech(text){

    return text
    .replace(/please/gi,"")
    .replace(/can you/gi,"")
    .replace(/could you/gi,"")
    .replace(/uh/gi,"")
    .replace(/um/gi,"")
    .replace(/like/gi,"")
    .replace(/just/gi,"")
    .trim();

}

function toggleMic() {
    if (!recognition) {
        initVoice();
        return;
    }

    if (isListening) {
        recognition.stop();
    } else {
        recognition.start();
    }
}

function setStatus(msg, cls) {
    var st = getEl('status');
    if (st) {
        st.textContent = msg;
        st.className = 'status ' + cls;
    }
}

// ===== QUERY EXECUTION =====
async function submitQuery() {
    var input = getEl('queryInput');
    if (!input) return;
    var query = input.value.trim();
    if (!query) {
        showToast('⚠️ Enter or speak a query first.', 'error');
        input.focus();
        return;
    }

    var runBtn = getEl('queryBtn');
    if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = '⏳ Processing...';
    }

    hideEl('resultsSection');
    hideEl('visualizationSection');
    showEl('loadingOverlay');

    try {
        var response = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        });
        var result = await response.json();

        if (result.clarification) {
            showClarification(result.message, result.suggestions);
            showToast('🤔 Ambiguous — pick a suggestion', 'info');
            return;
        }

        if (!response.ok) {
            showToast('❌ ' + (result.error || 'Error'), 'error');
            return;
        }

        displayResults(result);
        showToast('✅ ' + (result.data ? result.data.length : 0) + ' rows from ' + (result.database || 'library_main.db'), 'info');
    } catch (err) {
        showToast('❌ Network: ' + err.message, 'error');
    } finally {
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = '▶ Run';
        }
        hideEl('loadingOverlay');
    }
}

function clearQuery() {
    var input = getEl('queryInput');
    if (input) {
        input.value = '';
        input.focus();
    }
    hideEl('resultsSection');
    hideEl('visualizationSection');
}

// ===== RESULTS DISPLAY =====
function displayResults(result) {
    lastResult = result;
    currentChartType = 'bar';

    hideEl('welcomeScreen');
    hideEl('clarificationCard');
    showEl('resultsSection');

    var badgesEl = getEl('resultBadges');
    if (badgesEl) {
        var dbBadge = result.database === 'library_archive.db' ? 'badge-archive' : 'badge-main';
        var dbLabel = result.database === 'library_archive.db' ? 'Archive DB' : 'Main DB';
        badgesEl.innerHTML = '<span class="badge badge-ai">AI + NLP</span>' + '<span class="badge ' + dbBadge + '">' + dbLabel + '</span>';
    }

    var sqlCode = getEl('sqlCode');
    if (sqlCode) sqlCode.textContent = result.sql;

    var thead = getEl('tableHead');
    var tbody = getEl('tableBody');
    var noRes = getEl('noResults');
    if (thead) thead.innerHTML = '';
    if (tbody) tbody.innerHTML = '';

    if (!result.data || result.data.length === 0) {
        if (noRes) noRes.style.display = 'block';
        hideEl('chartsGrid');
        return;
    }
    if (noRes) noRes.style.display = 'none';

    if (thead) {
        var headerRow = document.createElement('tr');
        result.columns.forEach(function(col) {
            var th = document.createElement('th');
            th.textContent = col;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
    }

    if (tbody) {
        result.data.forEach(function(row) {
            var tr = document.createElement('tr');
            result.columns.forEach(function(col) {
                var td = document.createElement('td');
                var val = row[col];
                td.textContent = (val !== null && val !== undefined) ? val : '—';
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    }

    // Build chart after a short delay to ensure DOM is rendered
    setTimeout(function () {
        buildChart(result, 'bar');
    }, 100);
}

// ===== CHARTS =====
function buildChart(result, type) {
    var chartsGrid = getEl('chartsGrid');
    var chartContainer = getEl('chartContainer');
    var heatmapContainer = getEl('heatmapContainer');

    // Destroy any existing chart
    if (currentChart) {
        currentChart.destroy();
        currentChart = null;
    }

    if (!chartsGrid || !chartContainer || !heatmapContainer) {
        console.warn('[Charts] Missing DOM elements');
        return;
    }

    if (!result.data || result.data.length === 0 || result.columns.length < 2) {
        chartsGrid.style.display = 'none';
        return;
    }

    chartsGrid.style.display = 'block';
    var cData = result.data.slice(0, 20);

    // Heatmap is special — uses a table
    if (type === 'heatmap') {
        chartContainer.style.display = 'none';
        heatmapContainer.style.display = 'block';
        buildHeatmap(cData, info.labelCol, info.valueCols);
        return;
    }

    chartContainer.style.display = 'block';
    heatmapContainer.style.display = 'none';

    // IMPORTANT: Recreate the canvas element each time
    // to avoid Chart.js "Canvas is already in use" errors
    var oldCanvas = getEl('resultChart');
    if (oldCanvas) {
        var parent = oldCanvas.parentNode;
        parent.removeChild(oldCanvas);
        var newCanvas = document.createElement('canvas');
        newCanvas.id = 'resultChart';
        parent.appendChild(newCanvas);
    }

    var labels = cData.map(function (r) {
        return String(r[info.labelCol]).substring(0, 25);
    });

    var isPolar = (type === 'pie' || type === 'doughnut' || type === 'polarArea');

    var datasets;
    if (isPolar) {
        // Single dataset for pie/doughnut/polar
        var col = info.valueCols[0];
        datasets = [{
            label: col,
            data: cData.map(function (r) {
                return parseFloat(r[col]) || 0;
            }),
            backgroundColor: cData.map(function (_, j) {
                return CHART_COLORS[j % CHART_COLORS.length];
            }),
            borderColor: 'rgba(0,0,0,0.3)',
            borderWidth: 2
        }];
    } else if (type === 'radar') {
        datasets = info.valueCols.map(function (col, i) {
            return {
                label: col,
                data: cData.map(function (r) {
                    return parseFloat(r[col]) || 0;
                }),
                backgroundColor: CHART_COLORS[i % CHART_COLORS.length].replace('0.8', '0.2'),
                borderColor: CHART_COLORS[i % CHART_COLORS.length],
                borderWidth: 2,
                pointBackgroundColor: CHART_COLORS[i % CHART_COLORS.length]
            };
        });
    } else {
        // bar, line
        datasets = info.valueCols.map(function (col, i) {
            var ds = {
                label: col,
                data: cData.map(function (r) {
                    return parseFloat(r[col]) || 0;
                }),
                borderWidth: 2
            };
            if (type === 'line') {
                ds.borderColor = CHART_COLORS[i % CHART_COLORS.length];
                ds.backgroundColor = CHART_COLORS[i % CHART_COLORS.length].replace('0.8', '0.15');
                ds.fill = true;
                ds.tension = 0.4;
                ds.pointRadius = 4;
                ds.pointBackgroundColor = CHART_COLORS[i % CHART_COLORS.length];
            } else {
                ds.backgroundColor = cData.map(function (_, j) {
                    return CHART_COLORS[j % CHART_COLORS.length];
                });
                ds.borderColor = cData.map(function (_, j) {
                    return CHART_COLORS[j % CHART_COLORS.length].replace('0.8', '1');
                });
                ds.borderRadius = 6;
            }
            return ds;
        });
    }

    var options = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                labels: {
                    color: '#94a3b8',
                    font: { family: 'Inter', size: 12 }
                }
            }
        }
    };

    if (!isPolar && type !== 'radar') {
        options.scales = {
            x: {
                ticks: {
                    color: '#64748b',
                    font: { family: 'Inter', size: 11 }
                },
                grid: {
                    color: 'rgba(255,255,255,0.05)'
                }
            },
            y: {
                beginAtZero: true,
                ticks: {
                    color: '#64748b',
                    font: { family: 'Inter', size: 11 }
                },
                grid: {
                    color: 'rgba(255,255,255,0.05)'
                }
            }
        };
    }

    if (type === 'radar') {
        options.scales = {
            r: {
                ticks: { color: '#64748b' },
                grid: {
                    color: 'rgba(255,255,255,0.1)'
                },
                pointLabels: {
                    color: '#94a3b8',
                    font: { family: 'Inter', size: 11 }
                }
            }
        };
    }

    var canvas = getEl('resultChart');
    if (!canvas) {
        console.warn('[Charts] Canvas not found');
        return;
    }
    var ctx = canvas.getContext('2d');
    currentChart = new Chart(ctx, {
        type: type,
        data: { labels: labels, datasets: datasets },
        options: options
    });
}

function buildHeatmap(data, labelCol, valueCols) {
    var table = getEl('heatmapTable');
    if (!table) return;
    table.innerHTML = '';

    // Find min and max across all numeric values
    var allVals = [];
    data.forEach(function (row) {
        valueCols.forEach(function (col) {
            var v = parseFloat(row[col]);
            if (!isNaN(v)) allVals.push(v);
        });
    });
    if (allVals.length === 0) return;
    var minVal = Math.min.apply(null, allVals);
    var maxVal = Math.max.apply(null, allVals);
    var range = maxVal - minVal || 1;

    // Header row
    var thead = document.createElement('thead');
    var hrow = document.createElement('tr');
    var thLabel = document.createElement('th');
    thLabel.textContent = labelCol;
    hrow.appendChild(thLabel);
    valueCols.forEach(function (col) {
        var th = document.createElement('th');
        th.textContent = col;
        hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    // Data rows
    var tbody = document.createElement('tbody');
    data.forEach(function (row) {
        var tr = document.createElement('tr');
        var tdLabel = document.createElement('td');
        tdLabel.textContent = String(row[labelCol]).substring(0, 25);
        tr.appendChild(tdLabel);

        valueCols.forEach(function (col) {
            var td = document.createElement('td');
            var v = parseFloat(row[col]);
            td.textContent = isNaN(v) ? '—' : v;

            if (!isNaN(v)) {
                var norm = (v - minVal) / range;
                var level = Math.min(5, Math.floor(norm * 5.99));
                td.className = 'heat-' + level;
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
}

// ===== VISUALIZATION =====
function showVisualization() {
    if (!currentData || currentData.length === 0) {
        showToast('No data available for visualization', 'warning');
        return;
    }
    showEl('visualizationSection');
    hideEl('resultsSection');
}

function updateVisualization() {
    if (!currentData || currentData.length === 0) return;
    var chartType = document.getElementById('chartType').value;
    buildChart(currentData, chartType);
}

// ===== EXPORT =====
function exportResults() {
    if (!currentData || currentData.length === 0) {
        showToast('No data to export', 'warning');
        return;
    }
    
    var csvContent = currentData.map(row => 
        Object.values(row).join(',')
    ).join('\n');
    
    var blob = new Blob([csvContent], { type: 'text/csv' });
    var url = window.URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'query_results.csv';
    a.click();
    window.URL.revokeObjectURL(url);
    
    showToast('Results exported successfully', 'success');
}

// ===== TOAST NOTIFICATIONS =====
function showToast(message, type) {
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.textContent = message;
    
    var container = document.getElementById('toastContainer');
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Setup event listeners
    document.getElementById('queryBtn').addEventListener('click', submitQuery);
    document.getElementById('clearBtn').addEventListener('click', clearQuery);
    document.getElementById('micBtn').addEventListener('click', toggleMic);
    document.getElementById('exportBtn').addEventListener('click', exportResults);
    document.getElementById('visualizeBtn').addEventListener('click', showVisualization);
    document.getElementById('updateVizBtn').addEventListener('click', updateVisualization);
    
    // Setup enter key for query input
    document.getElementById('queryInput').addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submitQuery();
        }
    });
    document.getElementById('queryInput').focus();
    
    // Initialize voice
    initVoice();
}
