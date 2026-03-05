// =============================================
// Speak2DB - Frontend JavaScript
// ALL FEATURES: Voice, Query, Multi-Chart,
//   Heatmap, Inline Chatbot
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
        var micBtn = getEl('micBtn');  // Fixed: was voiceBtn
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
        var mb = getEl('micBtn');  // Fixed: was voiceBtn
        if (mb) {
            mb.classList.add('recording');
            mb.innerHTML = '🔴';
        }
        setStatus('🎤 Listening... speak now',
            'status-listening');
    };

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
        var mb = getEl('micBtn');  // Fixed: was voiceBtn
        if (mb) {
            mb.classList.remove('recording');
            mb.innerHTML = '🎤';
        }
        var msgs = {
            'not-allowed': '⚠️ Mic blocked!',
            'no-speech': '😶 No speech. Try again.',
            'audio-capture': '🎙️ No mic found.',
            'network': '🌐 Network error.',
            'aborted': 'Cancelled.'
        };
        setStatus(msgs[event.error] || 'Error: ' +
            event.error, 'status-error');
    };

    recognition.onend = function () {
        isListening = false;
        var mb = getEl('micBtn');  // Fixed: was voiceBtn
        if (mb) {
            mb.classList.remove('recording');
            mb.innerHTML = '🎤';
        }
    };
}

function toggleMic() {
    if (!recognition) {
        setStatus('⚠️ Voice needs Chrome.', 'status-error');
        return;
    }
    if (isListening) {
        recognition.stop();
        setStatus('Mic stopped.', 'status-info');
    } else {
        var inp = getEl('queryInput');
        if (inp) { inp.value = ''; inp.focus(); }
        try { recognition.start(); } catch (e) {
            setStatus('Mic busy. Wait and retry.',
                'status-error');
        }
    }
}

// ===== STATUS DISPLAY =====
function setStatus(msg, cls) {
    var el = getEl('queryStatus');
    if (el) {
        el.textContent = msg;
        el.className = 'query-status ' + (cls || '');
    }
}

// ===== QUERY SUBMISSION =====
async function submitQuery() {
    var input = getEl('queryInput');
    if (!input) return;
    var query = input.value.trim();
    if (!query) {
        setStatus('⚠️ Enter or speak a query first.',
            'status-error');
        input.focus();
        return;
    }
    if (isListening && recognition) recognition.stop();

    var runBtn = getEl('runBtn');
    if (runBtn) {
        runBtn.disabled = true;
        runBtn.textContent = '⏳ Processing...';
    }
    setStatus('🔄 Generating SQL...', 'status-processing');

    hideEl('clarificationCard');
    hideEl('resultCard');
    hideEl('welcomeScreen');

    try {
        var response = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        });
        var result = await response.json();

        if (result.clarification) {
            showClarification(result.message,
                result.suggestions);
            setStatus('🤔 Ambiguous — pick a suggestion',
                'status-info');
            return;
        }

        if (!response.ok) {
            setStatus('❌ ' + (result.error || 'Error'),
                'status-error');
            return;
        }

        displayResults(result);
        setStatus(
    '✅ ' + (result.data ? result.data.length : 0) +
    ' rows from ' + (result.database || 'library_main.db') +
    'status-info'
);
    } catch (err) {
        setStatus('❌ Network: ' + err.message,
            'status-error');
    } finally {
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = '▶ Run';
        }
    }
}

// ===== CLARIFICATION (inline card) =====
function showClarification(message, suggestions) {
    hideEl('welcomeScreen');
    hideEl('resultCard');
    showEl('clarificationCard');

    var msgEl = getEl('clarificationMsg');
    if (msgEl) msgEl.textContent = message;

    var sugDiv = getEl('clarificationSuggestions');
    if (sugDiv) {
        sugDiv.innerHTML = '';
        suggestions.forEach(function (s) {
            var chip = document.createElement('span');
            chip.className = 'rec-chip';
            chip.textContent = s;
            chip.style.cursor = 'pointer';
            chip.style.display = 'inline-block';
            chip.style.marginRight = '8px';
            chip.style.marginBottom = '8px';
            chip.onclick = function () { tryQuery(s); };
            sugDiv.appendChild(chip);
        });
    }
}

// ===== DISPLAY RESULTS =====
function displayResults(result) {
    lastResult = result;
    currentChartType = 'bar';

    hideEl('welcomeScreen');
    hideEl('clarificationCard');
    showEl('resultCard');

    var badgesEl = getEl('resultBadges');
    if (badgesEl) {
        var dbBadge = result.database === 'library_archive.db'
            ? 'badge-archive' : 'badge-main';
        var dbLabel = result.database === 'library_archive.db'
            ? 'Archive DB' : 'Main DB';
        badgesEl.innerHTML =
            '<span class="badge badge-ai">AI + NLP</span>' +
            '<span class="badge ' + dbBadge + '">' +
            dbLabel + '</span>';
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
        result.columns.forEach(function (col) {
            var th = document.createElement('th');
            th.textContent = col;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
    }

    if (tbody) {
        if (!result.data || !Array.isArray(result.data) || !result.columns) {
            console.warn('[Results] Invalid or missing data structure');
            return;
        }
        
        result.data.forEach(function (row) {
            var tr = document.createElement('tr');
            result.columns.forEach(function (col) {
                var td = document.createElement('td');
                var val = row[col];
                td.textContent = (val !== null &&
                    val !== undefined)
                    ? val : '—';
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    }

    // Reset chart type selector
    var btns = document.querySelectorAll('.chart-type-btn');
    btns.forEach(function (b) {
        b.classList.remove('active');
        if (b.getAttribute('data-type') === 'bar') {
            b.classList.add('active');
        }
    });

    // Build chart after a short delay to ensure DOM is rendered
    setTimeout(function () {
        buildChart(result, 'bar');
    }, 100);
}

// ========================================
// MULTI-CHART ENGINE
// ========================================
var CHART_COLORS = [
    'rgba(99,102,241,0.8)',
    'rgba(6,182,212,0.8)',
    'rgba(244,63,94,0.8)',
    'rgba(16,185,129,0.8)',
    'rgba(245,158,11,0.8)',
    'rgba(139,92,246,0.8)',
    'rgba(236,72,153,0.8)',
    'rgba(14,165,233,0.8)',
    'rgba(251,191,36,0.8)',
    'rgba(52,211,153,0.8)',
    'rgba(248,113,113,0.8)',
    'rgba(167,139,250,0.8)'
];

function getChartData(result) {
    if (!result || !result.data || !Array.isArray(result.data) || !result.columns) {
        console.warn('[Chart] Invalid data structure for charting');
        return { labelCol: null, valueCols: [] };
    }
    
    var labelCol = null;
    var valueCols = [];
    result.columns.forEach(function (col) {
        var allNumeric = true;
        for (var i = 0; i < (result.data ? result.data.length : 0); i++) {
            var fv = result.data[i][col];
            if (fv === null || fv === undefined) continue;
            if (typeof fv !== 'number' &&
                (isNaN(parseFloat(fv)) || !isFinite(fv))) {
                allNumeric = false;
                break;
            }
        }
        if (allNumeric && (result.data ? result.data.length : 0) > 0
            && result.data[0][col] !== null
            && result.data[0][col] !== undefined) {
            valueCols.push(col);
        } else if (!labelCol) {
            labelCol = col;
        }
    });
    return { labelCol: labelCol, valueCols: valueCols };
}

function switchChart(type) {
    currentChartType = type;
    var btns = document.querySelectorAll('.chart-type-btn');
    btns.forEach(function (b) {
        b.classList.remove('active');
        if (b.getAttribute('data-type') === type) {
            b.classList.add('active');
        }
    });
    if (lastResult) buildChart(lastResult, type);
}

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

    if (!result.data || (result.data ? result.data.length : 0) === 0 ||
        result.columns.length < 2) {
        chartsGrid.style.display = 'none';
        return;
    }

    var info = getChartData(result);
    if (!info.labelCol || info.valueCols.length === 0) {
        // No numeric columns found. Try to find at least
        // one column that has any numeric value
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

    var isPolar = (type === 'pie' || type === 'doughnut' ||
        type === 'polarArea');

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
                backgroundColor:
                    CHART_COLORS[i % CHART_COLORS.length]
                        .replace('0.8', '0.2'),
                borderColor:
                    CHART_COLORS[i % CHART_COLORS.length],
                borderWidth: 2,
                pointBackgroundColor:
                    CHART_COLORS[i % CHART_COLORS.length]
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
                ds.borderColor =
                    CHART_COLORS[i % CHART_COLORS.length];
                ds.backgroundColor =
                    CHART_COLORS[i % CHART_COLORS.length]
                        .replace('0.8', '0.15');
                ds.fill = true;
                ds.tension = 0.4;
                ds.pointRadius = 4;
                ds.pointBackgroundColor =
                    CHART_COLORS[i % CHART_COLORS.length];
            } else {
                ds.backgroundColor = cData.map(function (_, j) {
                    return CHART_COLORS[
                        j % CHART_COLORS.length];
                });
                ds.borderColor = cData.map(function (_, j) {
                    return CHART_COLORS[
                        j % CHART_COLORS.length]
                        .replace('0.8', '1');
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

// ========================================
// HEATMAP (HTML table with color-coded cells)
// ========================================
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
        tdLabel.textContent =
            String(row[labelCol]).substring(0, 25);
        tr.appendChild(tdLabel);

        valueCols.forEach(function (col) {
            var td = document.createElement('td');
            var v = parseFloat(row[col]);
            td.textContent = isNaN(v) ? '—' : v;

            if (!isNaN(v)) {
                var norm = (v - minVal) / range;
                var level = Math.min(5,
                    Math.floor(norm * 5.99));
                td.className = 'heat-' + level;
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
}

// ===== HELPERS =====
function tryQuery(text) {
    var inp = getEl('queryInput');
    if (inp) inp.value = text;
    submitQuery();
}

function useHistory(el) {
    var text = el.textContent.trim().replace(/^↩\s*/, '');
    var inp = getEl('queryInput');
    if (inp) inp.value = text;
    submitQuery();
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ========================================
// INLINE CHATBOT
// ========================================
function toggleInlineChatbot() {
    var body = getEl('chatbotInlineBody');
    var btn = getEl('chatbotToggleBtn');
    if (body) body.classList.toggle('collapsed');
    if (btn) {
        btn.textContent = (body &&
            body.classList.contains('collapsed'))
            ? '▶' : '▼';
    }
}

function chatbotTry(text) {
    var chatInput = getEl('chatbotInput');
    if (chatInput) {
        chatInput.value = text;
        sendChatbotQuery();
    }
}

async function sendChatbotQuery() {
    var chatInput = getEl('chatbotInput');
    if (!chatInput) return;
    var query = chatInput.value.trim();
    if (!query) return;

    var msgArea = getEl('chatbotMessages');
    if (!msgArea) return;

    // User bubble
    var userBubble = document.createElement('div');
    userBubble.className = 'chatbot-bubble user-bubble';
    userBubble.innerHTML =
        '<span class="bubble-sender">👤 You</span>' +
        '<p>' + escapeHtml(query) + '</p>';
    msgArea.appendChild(userBubble);

    chatInput.value = '';
    msgArea.scrollTop = msgArea.scrollHeight;

    try {
        var response = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        });
        var result = await response.json();

        var botBubble = document.createElement('div');
        botBubble.className = 'chatbot-bubble bot-bubble';

        if (result.clarification) {
            var html =
                '<span class="bubble-sender">' +
                '🤖 Chatbot</span>';
            html += '<p>' +
                escapeHtml(result.message) + '</p>';
            html += '<div class="chatbot-examples" ' +
                'style="margin-top:8px;">';
            result.suggestions.forEach(function (s) {
                html += '<span class="chat-chip" ' +
                    'onclick="chatbotTry(\'' +
                    s.replace(/'/g, "\\'") +
                    '\')">' +
                    escapeHtml(s) + '</span>';
            });
            html += '</div>';
            botBubble.innerHTML = html;
        } else if (result.error) {
            botBubble.innerHTML =
                '<span class="bubble-sender">' +
                '🤖 Chatbot</span>' +
                '<p>❌ ' +
                escapeHtml(result.error) + '</p>';
        } else {
            botBubble.innerHTML =
                '<span class="bubble-sender">' +
                '🤖 Chatbot</span>' +
                '<p>✅ Query executed! <strong>' +
                (result.data ? result.data.length : 0) +
                '</strong> rows returned.</p>' +
                '<p style="font-size:0.72rem;' +
                'color:#fbbf24;margin-top:6px;">' +
                'SQL: ' +
                escapeHtml(result.sql) + '</p>';

            // Auto-display results in main area
            var inp = getEl('queryInput');
            if (inp) inp.value = query;
            displayResults(result);  // Auto-display results
        }

        msgArea.appendChild(botBubble);
        msgArea.scrollTop = msgArea.scrollHeight;
    } catch (err) {
        var errBubble = document.createElement('div');
        errBubble.className = 'chatbot-bubble bot-bubble';
        errBubble.innerHTML =
            '<span class="bubble-sender">' +
            '🤖 Chatbot</span>' +
            '<p>❌ Error: ' +
            escapeHtml(err.message) + '</p>';
        msgArea.appendChild(errBubble);
        msgArea.scrollTop = msgArea.scrollHeight;
    }
}

// ===== INIT =====
document.addEventListener('DOMContentLoaded', function () {
    initVoice();

    var micBtn = getEl('micBtn');  // Fixed: was voiceBtn
    if (micBtn) micBtn.addEventListener('click', toggleMic);

    var queryInput = getEl('queryInput');
    if (queryInput) {
        queryInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                submitQuery();
            }
        });
        queryInput.focus();
    }

    console.log("[Speak2DB] All features initialized ✅");
});
