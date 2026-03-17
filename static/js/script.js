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

// Priority keywords for query compression
var VOICE_KEYWORDS = ["books","students","fines","issued","overdue","reservations"];

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
    recognition.maxAlternatives = 5;

    recognition.onstart = function () {
        isListening = true;
        var mb = getEl('micBtn');
        if (mb) {
            mb.classList.add('recording');
            mb.innerHTML = '🔴';
            mb.title = 'Listening...';
        }
        setStatus('🎤 Listening... speak now', 'status-listening');
    };

    recognition.onresult = function(event){
        let finalTranscript = "";
        let bestTranscript = "";
        let hasFinal = false;

        for(let i = event.resultIndex; i < event.results.length; i++){
            if(event.results[i].isFinal){
                hasFinal = true;

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

        if(!hasFinal || !finalTranscript) return;

        // Stop listening once final result is received for faster response
        recognition.stop();

        console.log("Raw speech:", finalTranscript);
        console.log("[VOICE FINAL]", finalTranscript);

        // Clean filler words first
        finalTranscript = cleanSpeech(finalTranscript);

        // Normalize accent misrecognitions on cleaned text
        finalTranscript = normalizeAccent(finalTranscript);

        // Correct domain-specific keyword plurals
        finalTranscript = correctDomain(finalTranscript);

        // Compress overly long queries to essential keywords
        finalTranscript = compressQuery(finalTranscript);

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
            mb.title = '';
        }
        setStatus('❌ Error: ' + event.error, 'status-error');
    };

    recognition.onend = function () {
        isListening = false;
        var mb = getEl('micBtn');
        if (mb) {
            mb.classList.remove('recording');
            mb.innerHTML = '🎤';
            mb.title = '';
        }
    };
}

function cleanSpeech(text){

    return text
    .toLowerCase()
    .replace(/\bcan you\b/gi,"")
    .replace(/\bcould you\b/gi,"")
    .replace(/\bi want\b/gi,"")
    .replace(/\bgive me\b/gi,"")
    .replace(/\bplease\b/gi,"")
    .replace(/\bshow me\b/gi,"")
    .replace(/\btell me\b/gi,"")
    .replace(/\buh\b/gi,"")
    .replace(/\bum\b/gi,"")
    .replace(/\bah\b/gi,"")
    .replace(/\byou know\b/gi,"")
    .replace(/\bokay\b/gi,"")
    .replace(/\balright\b/gi,"")
    .replace(/\bjust\b/gi,"")
    .replace(/\s+/g," ")
    .trim();

}

function normalizeAccent(text){
    const accentMap = {
        "bok": "book",
        "buk": "book",
        "studant": "student",
        "studen": "student",
        "fin": "fine"
    };
    for(const key in accentMap){
        text = text.replace(new RegExp("\\b" + key + "\\b","gi"), accentMap[key]);
    }
    return text;
}

function correctDomain(text){
    if(text.includes("book") && !text.includes("books")) text = text.replace(/\bbook\b/g,"books");
    if(text.includes("fine") && !text.includes("fines")) text = text.replace(/\bfine\b/g,"fines");
    if(text.includes("student") && !text.includes("students")) text = text.replace(/\bstudent\b/g,"students");
    return text;
}

function compressQuery(text){
    const words = text.split(/\s+/);
    if(words.length <= 6) return text;

    // Extract keywords that appear in the text, preserving their original order
    let result = [];
    VOICE_KEYWORDS.forEach(function(k){
        if(new RegExp("\\b" + k + "\\b","i").test(text)) result.push(k);
    });
    return result.length > 0 ? result.join(" ") : text;
}

function setStatus(msg, cls) {
    var st = getEl('status');
    if (st) {
        st.textContent = msg;
        st.className = 'status ' + (cls || '');
    }
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

    // Update row count badge (used in dashboard pages)
    var rowBadge = getEl('rowCountBadge');
    if (rowBadge) rowBadge.textContent = (result.data ? result.data.length : 0) + ' rows';

    console.log("SQL received:", result.sql);
    var sqlCode = getEl('sqlCode');
    var sqlSection = getEl('sqlSection');
    if (sqlCode && result.sql) {
        sqlCode.textContent = result.sql;
        if (sqlSection) sqlSection.style.display = 'block';
    } else if (sqlSection) {
        sqlSection.style.display = 'none';
    }

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
    if (!container) {
        // Fallback: create a temporary container
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.style.cssText = 'position:fixed;bottom:1rem;right:1rem;z-index:10000;display:flex;flex-direction:column;gap:.5rem;';
        document.body.appendChild(container);
    }
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// ===== INITIALIZATION =====
// ===== FULL DASHBOARD =====
function loadFullDashboard() {
    console.log("Button clicked: Full Dashboard");
    window.location.href = "/analytics";
}

// ===== QUERY SUGGESTIONS =====
var QUERY_SUGGESTIONS = [
    'show books',
    'show students',
    'show fines',
    'show issued books',
    'list books',
    'list students',
    'list fines',
    'issued books',
    'overdue books',
    'available books',
    'library statistics',
    'database statistics',
    'students with fines',
    'show reservations',
    'show faculty',
    'find books by author',
    'books by category',
    'top borrowed books',
    'students with overdue books',
    'unpaid fines',
];

function filterSuggestions(value) {
    if (!value || value.trim().length < 2) return [];
    var lower = value.toLowerCase().trim();
    return QUERY_SUGGESTIONS.filter(function(s) {
        return s.indexOf(lower) !== -1;
    });
}

function showSuggestions(matches) {
    var box = getEl('querySuggestions');
    if (!box) return;
    if (!matches || matches.length === 0) {
        box.style.display = 'none';
        box.innerHTML = '';
        return;
    }
    box.innerHTML = '';
    matches.forEach(function(text) {
        var li = document.createElement('li');
        li.textContent = text;
        li.style.cssText = 'padding:0.55rem 1rem; cursor:pointer; color:#1a3a6b; font-size:0.9rem; border-bottom:1px solid #edf2fb;';
        li.addEventListener('mouseenter', function() { li.style.background = '#e8f0fe'; });
        li.addEventListener('mouseleave', function() { li.style.background = ''; });
        li.addEventListener('mousedown', function(e) {
            // mousedown fires before blur – use it to populate without losing focus
            e.preventDefault();
            var inp = getEl('queryInput');
            if (inp) inp.value = text;
            box.style.display = 'none';
        });
        box.appendChild(li);
    });
    box.style.display = 'block';
}

function initSuggestions() {
    var inp = getEl('queryInput');
    var box = getEl('querySuggestions');
    if (!inp || !box) return;

    inp.addEventListener('input', function() {
        showSuggestions(filterSuggestions(inp.value));
    });

    inp.addEventListener('focus', function() {
        if (inp.value.trim().length >= 2) {
            showSuggestions(filterSuggestions(inp.value));
        }
    });

    inp.addEventListener('blur', function() {
        // Delay hide so that mousedown on an item fires first
        setTimeout(function() { box.style.display = 'none'; }, 150);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    initSuggestions();
});

function initializeApp() {
    // Setup event listeners with null guards (some buttons only exist on index.html)
    var qBtn = getEl('queryBtn');
    if (qBtn) qBtn.addEventListener('click', submitQuery);

    var cBtn = getEl('clearBtn');
    if (cBtn) cBtn.addEventListener('click', clearQuery);

    var mBtn = getEl('micBtn');
    if (mBtn) mBtn.addEventListener('click', toggleMic);

    var eBtn = getEl('exportBtn');
    if (eBtn) eBtn.addEventListener('click', exportResults);

    var vBtn = getEl('visualizeBtn');
    if (vBtn) vBtn.addEventListener('click', showVisualization);

    var uBtn = getEl('updateVizBtn');
    if (uBtn) uBtn.addEventListener('click', updateVisualization);

    // Setup enter key for query input
    var qInput = getEl('queryInput');
    if (qInput) {
        qInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitQuery();
            }
        });
        qInput.focus();
    }

    // Initialize voice only when mic button is present
    if (getEl('micBtn')) initVoice();
    loadUiConfig();
}

async function loadUiConfig() {
    try {
        const response = await fetch('/api/ui-config');
        if (!response.ok) return;
        const config = await response.json();
        const settings = config.settings || {};
        const micBtn = getEl('micBtn');
        if (micBtn && settings.voice_input_enabled === false) {
            micBtn.disabled = true;
            micBtn.style.opacity = '0.5';
            micBtn.title = 'Voice input disabled by administrator';
        }
    } catch (error) {
        console.warn('UI config unavailable', error);
    }
}
