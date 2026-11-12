// Bloqueo de inspección
(function() {
    document.addEventListener('contextmenu', e => e.preventDefault());
    document.addEventListener('keydown', e => {
        if (e.key === 'F12' || e.keyCode === 123 || (e.ctrlKey && e.shiftKey && ['I','J','C'].includes(e.key.toUpperCase())) || (e.ctrlKey && e.key === 'U')) {
            e.preventDefault();
        }
    });
})();

// Mostrar campos de email
document.getElementById('send_test_email').addEventListener('change', function() {
    document.getElementById('email-config').style.display = this.checked ? 'block' : 'none';
});

let statusInterval = null;

function logMsg(msg, type = 'info') {
    const c = document.getElementById('log-console');
    const d = document.createElement('div');
    d.className = `log-entry ${type}`;
    d.textContent = msg;
    c.appendChild(d);
    c.scrollTop = c.scrollHeight;
}

function updateStats(d) {
    document.getElementById('stat-total').textContent = d.total_count;
    document.getElementById('stat-valid').textContent = d.valid_count;
    document.getElementById('stat-invalid').textContent = d.invalid_count;
    document.getElementById('stat-progress').textContent = `${d.checked_count}/${d.total_count}`;
    document.getElementById('stat-current').textContent = d.current_smtp || '-';
}

function updateLogs(logs) {
    const c = document.getElementById('log-console');
    if (logs.length > c.children.length) {
        c.innerHTML = '';
        logs.forEach(l => {
            const d = document.createElement('div');
            d.className = `log-entry ${l.type}`;
            d.textContent = `[${l.time}] ${l.message}`;
            c.appendChild(d);
        });
        c.scrollTop = c.scrollHeight;
    }
}

async function startCheck() {
    const list = document.getElementById('smtp-list').value;
    if (!list.trim()) return alert('Ingresa SMTPs');

    const config = {
        smtp_list: list,
        threads: document.getElementById('threads').value,
        send_test_email: document.getElementById('send_test_email').checked,
        recipients: document.getElementById('recipients').value,
        email_subject: document.getElementById('email_subject').value,
        sender_name: document.getElementById('sender_name').value,
        email_body: document.getElementById('email_body').value,
        enable_personalization: document.getElementById('enable_personalization').checked,
        telegram_token: document.getElementById('telegram_token').value,
        telegram_chat_id: document.getElementById('telegram_chat_id').value
    };

    document.getElementById('start-btn').disabled = true;
    document.getElementById('stop-btn').disabled = false;
    document.getElementById('log-console').innerHTML = '';
    document.getElementById('valid-results').value = '';

    try {
        const res = await fetch('/start-check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        const data = await res.json();
        if (res.ok) {
            logMsg(`🚀 Iniciado con ${data.total} SMTPs`, 'success');
            statusInterval = setInterval(fetchStatus, 1000);
        } else {
            alert(data.error);
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
        }
    } catch (e) {
        alert('Error al conectar con el servidor');
        document.getElementById('start-btn').disabled = false;
        document.getElementById('stop-btn').disabled = true;
    }
}

async function fetchStatus() {
    try {
        const res = await fetch('/status');
        const data = await res.json();
        updateStats(data);
        updateLogs(data.logs);

        if (!data.is_checking && data.checked_count > 0) {
            clearInterval(statusInterval);
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
            document.getElementById('valid-results').value = data.valid_smtps.join('\n');
            logMsg('✅ Finalizado', 'success');
        }
    } catch (e) { console.error(e); }
}

async function stopCheck() {
    await fetch('/stop-check', { method: 'POST' });
    logMsg('⛔ Detenido por el usuario', 'warning');
    clearInterval(statusInterval);
    document.getElementById('start-btn').disabled = false;
    document.getElementById('stop-btn').disabled = true;
}
