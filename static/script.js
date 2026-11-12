// --- BLOQUEO DE INSPECCIÓN ---
(function() {
    document.addEventListener('contextmenu', function(e) { e.preventDefault(); return false; });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F12' || e.keyCode === 123) { e.preventDefault(); return false; }
        if (e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'i')) { e.preventDefault(); return false; }
        if (e.ctrlKey && e.shiftKey && (e.key === 'J' || e.key === 'j')) { e.preventDefault(); return false; }
        if (e.ctrlKey && e.shiftKey && (e.key === 'C' || e.key === 'c')) { e.preventDefault(); return false; }
        if (e.ctrlKey && (e.key === 'U' || e.key === 'u')) { e.preventDefault(); return false; }
    });
    document.addEventListener('selectstart', function(e) { e.preventDefault(); return false; });
})();
// --- FIN BLOQUEO ---

let statusInterval = null;

function logToConsole(message, type = 'info') {
    const consoleDiv = document.getElementById('log-console');
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = message;
    consoleDiv.appendChild(entry);
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
}

function updateStats(data) {
    document.getElementById('stat-total').textContent = data.total_count;
    document.getElementById('stat-valid').textContent = data.valid_count;
    document.getElementById('stat-invalid').textContent = data.invalid_count;
    document.getElementById('stat-progress').textContent = `${data.checked_count}/${data.total_count}`;
}

function updateLogs(logs) {
    const consoleDiv = document.getElementById('log-console');
    consoleDiv.innerHTML = '';
    logs.forEach(log => {
        const entry = document.createElement('div');
        entry.className = `log-entry ${log.type}`;
        entry.textContent = `[${log.time}] ${log.message}`;
        consoleDiv.appendChild(entry);
    });
    consoleDiv.scrollTop = consoleDiv.scrollHeight;
}

async function startCheck() {
    const smtpList = document.getElementById('smtp-list').value;
    const threads = document.getElementById('threads').value;

    if (!smtpList.trim()) {
        alert('Por favor, ingresa al menos un SMTP.');
        return;
    }

    document.getElementById('start-btn').disabled = true;
    document.getElementById('stop-btn').disabled = false;
    document.getElementById('log-console').innerHTML = '';
    document.getElementById('valid-results').value = '';

    try {
        const response = await fetch('/start-check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ smtp_list: smtpList, threads: threads })
        });

        const data = await response.json();
        if (response.ok) {
            logToConsole(`🚀 Checkeo iniciado con ${data.total} SMTPs`, 'success');
            statusInterval = setInterval(fetchStatus, 1000);
        } else {
            alert(data.error);
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
        }
    } catch (error) {
        console.error(error);
        alert('Error al iniciar el checkeo.');
        document.getElementById('start-btn').disabled = false;
        document.getElementById('stop-btn').disabled = true;
    }
}

async function fetchStatus() {
    try {
        const response = await fetch('/status');
        const data = await response.json();

        updateStats(data);
        updateLogs(data.logs);

        if (!data.is_checking && data.checked_count > 0) {
            clearInterval(statusInterval);
            statusInterval = null;
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
            document.getElementById('valid-results').value = data.valid_smtps.join('\n');
            logToConsole('✅ Checkeo finalizado.', 'success');
        }
    } catch (error) {
        console.error('Error al obtener estado:', error);
    }
}

async function stopCheck() {
    try {
        await fetch('/stop-check', { method: 'POST' });
        logToConsole('⛔ Checkeo detenido por el usuario.', 'warning');
        clearInterval(statusInterval);
        statusInterval = null;
        document.getElementById('start-btn').disabled = false;
        document.getElementById('stop-btn').disabled = true;
    } catch (error) {
        console.error(error);
    }
}