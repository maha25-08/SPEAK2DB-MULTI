// =============================================
// Speak2DB - Basic Frontend JavaScript
// =============================================

// ===== CHART STATE =====
var currentChart = null;
var lastResult = null;
var currentChartType = 'bar';
var currentData = null;

// Track the last original query for clarification resubmission
var _pendingOriginalQuery = '';

// Chart colors
const CHART_COLORS = [
    'rgba(74, 144, 226, 0.8)',
    'rgba(92, 184, 92, 0.8)',
    'rgba(240, 173, 78, 0.8)',
    'rgba(217, 83, 79, 0.8)',
    'rgba(91, 192, 222, 0.8)',
    'rgba(155, 89, 182, 0.8)',
    'rgba(52, 73, 94, 0.8)'
];

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
    recognition.maxAlternatives = 3;

    recognition.onstart = function () {
        isListening = true;
        var mb = getEl('micBtn');
        if (mb) {
            mb.classList.add('recording');
            mb.innerHTML = '🔴';
        }
    };

    recognition.onresult = function(event){
        let finalTranscript = "";
        let bestTranscript = "";

        for(let i = event.resultIndex; i < event.results.length; i++){
            if(event.results[i].isFinal){
                // Get the best alternative from all available alternatives
                const alternatives = event.results[i];
                let bestConfidence = 0;
                
                for(let j = 0; j < alternatives.length; j++){
                    if(alternatives[j].confidence > bestConfidence){
                        bestConfidence = alternatives[j].confidence;
                        bestTranscript = alternatives[j].transcript;
                    }
                }
                
                finalTranscript = bestTranscript;
                break;
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
    };

    recognition.onend = function () {
        isListening = false;
        var mb = getEl('micBtn');
        if (mb) {
            mb.classList.remove('recording');
            mb.innerHTML = '🎤';
        }
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

// ===== QUERY EXECUTION =====
async function submitQuery() {
    const query = document.getElementById("queryInput").value;
    const loader = document.getElementById("loadingOverlay");
    const resultBox = document.getElementById("result");

    if (!query || query.trim() === '') {
        showToast('⚠️ Enter or speak a query first.', 'error');
        document.getElementById("queryInput").focus();
        return;
    }

    // Show loader
    if (loader) loader.style.display = "flex";
    if (resultBox) resultBox.innerHTML = "";

    // Disable button
    var runBtn = getEl('queryBtn');
    if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = '⏳ Processing...';
    }

    // Add timeout to prevent infinite loading
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        console.log("Sending query:", query);
        
        const response = await fetch("/query", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ query: query }),
            signal: controller.signal
        });

        clearTimeout(timeoutId);
        console.log("Response received:", response.status);

        // Safe JSON parsing with content-type check
        let data;
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            data = await response.json();
            console.log("Response data:", data);
        } else {
            throw new Error("Server did not return JSON");
        }

        // Hide loader
        if (loader) loader.style.display = "none";

        // ── Handle clarification request ──────────────────────────────────
        if (data.needs_clarification) {
            _pendingOriginalQuery = query;
            renderClarification(data.clarification);
            return;
        }

        if (data.error) {
            showToast('❌ Error: ' + data.error, 'error');
            if (resultBox) resultBox.innerHTML = "Error: " + data.error;
        } else {
            // Hide clarification card and display results
            hideEl('clarificationCard');
            displayResults(data);
            showToast('✅ ' + (data.data ? data.data.length : 0) + ' rows from ' + (data.database || 'library_main.db'), 'info');
        }

    } catch (error) {
        clearTimeout(timeoutId);
        if (loader) loader.style.display = "none";
        
        let errorMsg = "Server error. Please try again.";
        if (error.name === 'AbortError') {
            errorMsg = "Request timed out. Please try again.";
        } else {
            console.error("Query error:", error);
        }
        
        showToast('❌ ' + errorMsg, 'error');
        if (resultBox) resultBox.innerHTML = errorMsg;
    } finally {
        // Always hide loader and re-enable button
        if (loader) loader.style.display = "none";
        
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = '▶ Run';
        }
    }
}

// ===== CLARIFICATION UI =====

/**
 * Render the clarification card with question and option buttons.
 * @param {Object} clarif - { question, options: [{label, value}], original_query, entity }
 */
function renderClarification(clarif) {
    var card = getEl('clarificationCard');
    var questionEl = getEl('clarificationQuestion');
    var optionsEl = getEl('clarificationOptions');

    if (!card || !questionEl || !optionsEl) {
        console.warn('[Clarification] Missing DOM elements');
        return;
    }

    // Populate question text
    if (questionEl) questionEl.textContent = clarif.question || 'Please choose an option:';

    // Build option buttons
    if (optionsEl) {
        optionsEl.innerHTML = '';
        (clarif.options || []).forEach(function(opt) {
            var btn = document.createElement('button');
            btn.className = 'btn-clarification';
            btn.textContent = opt.label;
            btn.onclick = function() {
                submitWithClarification(opt.value);
            };
            optionsEl.appendChild(btn);
        });
    }

    // Show card, hide other sections
    hideEl('resultsSection');
    hideEl('visualizationSection');
    showEl('clarificationCard');
}

/**
 * Re-submit the query to /query with the chosen clarification value.
 * @param {string} choiceValue - The "value" field from the chosen option.
 */
async function submitWithClarification(choiceValue) {
    var loader = getEl('loadingOverlay');
    if (loader) loader.style.display = "flex";

    hideEl('clarificationCard');

    var runBtn = getEl('queryBtn');
    if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = '⏳ Processing...';
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        console.log("Submitting clarification choice:", choiceValue);

        const response = await fetch("/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query: _pendingOriginalQuery,
                clarification_choice: choiceValue
            }),
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        let data;
        const ct = response.headers.get("content-type");
        if (ct && ct.includes("application/json")) {
            data = await response.json();
        } else {
            throw new Error("Server did not return JSON");
        }

        if (loader) loader.style.display = "none";

        if (data.error) {
            showToast('❌ Error: ' + data.error, 'error');
        } else {
            // Update the input to reflect the chosen query
            var inp = getEl('queryInput');
            if (inp) inp.value = choiceValue;

            displayResults(data);
            showToast('✅ ' + (data.data ? data.data.length : 0) + ' rows from ' + (data.database || 'library_main.db'), 'info');
        }

    } catch (error) {
        clearTimeout(timeoutId);
        if (loader) loader.style.display = "none";
        
        var errorMsg = error.name === 'AbortError' ? "Request timed out." : "Server error.";
        showToast('❌ ' + errorMsg, 'error');
    } finally {
        if (loader) loader.style.display = "none";
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = '▶ Run';
        }
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
    currentData = result.data;
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
    var chartContainer = getEl('chartContainer');
    var canvas = getEl('dataChart');

    // Destroy any existing chart
    if (currentChart) {
        currentChart.destroy();
        currentChart = null;
    }

    if (!chartContainer || !canvas) {
        console.warn('[Charts] Missing DOM elements');
        return;
    }

    if (!result.data || result.data.length === 0 || result.columns.length < 2) {
        console.warn('No data available for chart');
        return;
    }

    var cData = result.data.slice(0, 20);
    var labels = cData.map(function (r) {
        return String(r[result.columns[0]]).substring(0, 25);
    });

    var datasets = [];
    var valueCols = result.columns.slice(1);

    if (type === 'pie' || type === 'doughnut') {
        var col = valueCols[0];
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
    } else {
        datasets = valueCols.map(function (col, i) {
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
            } else {
                ds.backgroundColor = CHART_COLORS[i % CHART_COLORS.length];
                ds.borderColor = CHART_COLORS[i % CHART_COLORS.length].replace('0.8', '1');
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
                    color: '#ffffff',
                    font: { family: 'Inter', size: 12 }
                }
            }
        }
    };

    if (type !== 'pie' && type !== 'doughnut') {
        options.scales = {
            x: {
                ticks: {
                    color: '#cccccc',
                    font: { family: 'Inter', size: 11 }
                },
                grid: {
                    color: 'rgba(255,255,255,0.1)'
                }
            },
            y: {
                beginAtZero: true,
                ticks: {
                    color: '#cccccc',
                    font: { family: 'Inter', size: 11 }
                },
                grid: {
                    color: 'rgba(255,255,255,0.1)'
                }
            }
        };
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
    if (!lastResult || !lastResult.data || lastResult.data.length === 0) {
        showToast('No data available for visualization', 'warning');
        return;
    }
    showEl('visualizationSection');
    hideEl('resultsSection');
}

function updateVisualization() {
    if (!lastResult || !lastResult.data || lastResult.data.length === 0) return;
    var chartType = document.getElementById('chartType').value;
    buildChart(lastResult, chartType);
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
