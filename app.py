from flask import Flask, render_template, request, jsonify
import smtplib
import ssl
import socket
import threading
import time
import json
import re
from queue import Queue

app = Flask(__name__)

# Variables globales para mantener el estado del checkeo
checking_state = {
    'is_checking': False,
    'valid_count': 0,
    'invalid_count': 0,
    'total_count': 0,
    'checked_count': 0,
    'logs': [],
    'valid_smtps': []
}

def log_message(message, type='info'):
    """Agregar mensaje al log global"""
    timestamp = time.strftime("%H:%M:%S")
    checking_state['logs'].append({'time': timestamp, 'message': message, 'type': type})

def parse_smtp_line(line):
    """Parsear línea SMTP (versión simplificada para web)"""
    line = line.strip()
    if not line:
        return None
    
    try:
        # Formato simple: host:port:user:pass
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 4:
                return f"{parts[0].strip()}|{parts[1].strip()}|{parts[2].strip()}|{parts[3].strip()}"
        
        # Formato con @
        if '@' in line and ':' in line:
            match = re.match(r'([^:]+):([^@]+)@([^:]+):(\d+)', line)
            if match:
                user, password, host, port = match.groups()
                return f"{host.strip()}|{port.strip()}|{user.strip()}|{password.strip()}"
        
        # Formato con dos puntos
        if line.count(':') >= 3:
            parts = line.split(':')
            if len(parts) >= 4:
                return f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}"
                
    except Exception as e:
        return None
    
    return None

def test_smtp_connection(host, port, user, password):
    """Probar conexión SMTP"""
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
        try:
            server = None
            if method_name == 'SSL':
                server = smtplib.SMTP_SSL(host=host, port=test_port, timeout=10, context=context)
            else:
                server = smtplib.SMTP(host=host, port=test_port, timeout=10)
                server.starttls(context=context)
            
            server.login(user, password)
            server.noop()
            server.quit()
            return True, f"{method_name}:{test_port} - Conexión exitosa"
            
        except smtplib.SMTPAuthenticationError:
            return False, "Autenticación fallida"
        except Exception as e:
            continue
    
    return False, "No se pudo conectar"

def worker(queue, results):
    """Worker para procesar SMTPs en hilos"""
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
                    
                    is_valid, message = test_smtp_connection(host, int(port), user, password)
                    
                    if is_valid:
                        checking_state['valid_count'] += 1
                        checking_state['valid_smtps'].append(smtp_standard)
                        log_message(f"[{line_num}] ✅ VÁLIDO: {host}:{port} | {user}", 'success')
                    else:
                        checking_state['invalid_count'] += 1
                        log_message(f"[{line_num}] ❌ INVÁLIDO: {host}:{port} | {message}", 'error')
                    
                    checking_state['checked_count'] += 1
            else:
                checking_state['invalid_count'] += 1
                log_message(f"[{line_num}] ⚠️ No se pudo parsear: {original_line[:50]}...", 'warning')
            
            queue.task_done()
            
        except Exception as e:
            log_message(f"[ERROR Worker] {str(e)[:50]}", 'error')
            queue.task_done()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start-check', methods=['POST'])
def start_check():
    """Iniciar el checkeo de SMTPs"""
    data = request.json
    smtp_list = data.get('smtp_list', '')
    threads_count = int(data.get('threads', 10))
    
    if not smtp_list.strip():
        return jsonify({'error': 'La lista de SMTPs está vacía'}), 400
    
    # Reiniciar estado
    checking_state.update({
        'is_checking': True,
        'valid_count': 0,
        'invalid_count': 0,
        'total_count': 0,
        'checked_count': 0,
        'logs': [],
        'valid_smtps': []
    })
    
    lines = [line.strip() for line in smtp_list.split('\n') if line.strip()]
    checking_state['total_count'] = len(lines)
    
    queue = Queue()
    for i, line in enumerate(lines, 1):
        queue.put((i, line))
    
    # Iniciar hilos en segundo plano
    def run_check():
        threads = []
        num_threads = min(threads_count, queue.qsize())
        for _ in range(num_threads):
            t = threading.Thread(target=worker, args=(queue, []))
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
    """Obtener el estado actual del checkeo"""
    return jsonify(checking_state)

@app.route('/stop-check', methods=['POST'])
def stop_check():
    checking_state['is_checking'] = False
    return jsonify({'message': 'Checkeo detenido'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)