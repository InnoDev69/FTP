#!/usr/bin/env python3
"""
Cliente web para administrar el servidor FTP Dahua
Aplicación Flask separada del servidor FTP
"""

from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash
from flask import send_from_directory
from pathlib import PurePosixPath
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import psutil
import ftplib
from functools import wraps
import subprocess
import threading
import tempfile
import signal
import atexit
import glob

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'  # Cambiar en producción

# Configuración por defecto
DEFAULT_CONFIG = {
    "FTP_HOST": "localhost",
    "FTP_PORT": 60000,
    "VIDEO_DIR": "dahua_videos",
    "LOG_DIR": "logs",
    "ALIAS_FILE": "dahua_videos/folder_aliases.json",
    "ATTEMPS_LOGGING": 0,
    "ATTEMPS_MAX": 5,
    "CHANGELOG_FILE": "changelog.json",
    "LAST_COMMIT_FILE": "last_commit.txt"
}

CONFIG_FILE = Path("config.json")

def load_config():
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        config = DEFAULT_CONFIG.copy()
    else:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    return config

config = load_config()

# Usar la configuración cargada
FTP_HOST = config["FTP_HOST"]
FTP_PORT = config["FTP_PORT"]
VIDEO_DIR = Path(config["VIDEO_DIR"])
LOG_DIR = Path(config["LOG_DIR"])
ALIAS_FILE = Path(config["ALIAS_FILE"])
ATTEMPS_LOGGING = config["ATTEMPS_LOGGING"]
ATTEMPS_MAX = config["ATTEMPS_MAX"]
CHANGELOG_FILE = Path(config["CHANGELOG_FILE"])
LAST_COMMIT_FILE = Path(config["LAST_COMMIT_FILE"])

SERVER_START_TIME = time.time()

def format_uptime(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def login_required(f):
    """Decorador para requerir login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_project_stats():
    """Estadísticas solo del proceso Flask y sus hijos"""
    try:
        proc = psutil.Process(os.getpid())
        # Incluye hijos (por ejemplo, ffmpeg)
        children = proc.children(recursive=True)
        procs = [proc] + children

        # CPU y memoria
        cpu = sum(p.cpu_percent(interval=0.1) for p in procs)
        mem = sum(p.memory_info().rss for p in procs) / (1024 * 1024)  # MB

        # Disco (bytes leídos/escritos)
        disk_read = sum(getattr(p.io_counters(), 'read_bytes', 0) for p in procs)
        disk_write = sum(getattr(p.io_counters(), 'write_bytes', 0) for p in procs)

        # Red (bytes enviados/recibidos)
        net_sent = sum(getattr(p, 'net_io_counters', lambda: None)() and getattr(p.net_io_counters(), 'bytes_sent', 0) or 0 for p in procs)
        net_recv = sum(getattr(p, 'net_io_counters', lambda: None)() and getattr(p.net_io_counters(), 'bytes_recv', 0) or 0 for p in procs)

        return {
            'cpu_usage': round(cpu, 2),  # %
            'mem_usage': round(mem, 2),  # MB
            'disk_read_mb': round(disk_read / (1024 * 1024), 2),
            'disk_write_mb': round(disk_write / (1024 * 1024), 2),
            'net_sent_mb': round(net_sent / (1024 * 1024), 2),
            'net_recv_mb': round(net_recv / (1024 * 1024), 2),
        }
    except Exception as e:
        print(f"Error obteniendo estadísticas del proyecto: {e}")
        return {
            'cpu_usage': 0,
            'mem_usage': 0,
            'disk_read_mb': 0,
            'disk_write_mb': 0,
            'net_sent_mb': 0,
            'net_recv_mb': 0,
        }

def get_server_stats():
    """Obtiene estadísticas del servidor"""
    try:
        stats = {
            'status': 'offline',
            'video_count': 0,
            'total_size_gb': 0,
            'disk_usage': 0,
            'uptime': format_uptime(time.time() - SERVER_START_TIME),
            'connections': 0,
            'last_upload': 'N/A',
            'cpu_usage': psutil.cpu_percent(interval=0.2),
            'mem_usage': psutil.virtual_memory().percent,
            'disk_usage_sys': psutil.disk_usage('/').percent,
            'net_usage': 0  # Se calcula abajo
        }
        
        # Verificar si el directorio de videos existe
        if VIDEO_DIR.exists():
            # Contar archivos de video
            video_files = list(VIDEO_DIR.rglob("*.avi")) + list(VIDEO_DIR.rglob("*.mp4")) + list(VIDEO_DIR.rglob("*.dav"))
            stats['video_count'] = len(video_files)
            
            # Calcular tamaño total
            total_size = sum(f.stat().st_size for f in video_files if f.exists())
            stats['total_size_gb'] = round(total_size / (1024**3), 2)
            
            # Último archivo subido
            if video_files:
                latest_file = max(video_files, key=lambda f: f.stat().st_mtime)
                stats['last_upload'] = datetime.fromtimestamp(latest_file.stat().st_mtime).strftime('%Y/%m/%d %H:%M:%S')
        
        # Verificar estado del servidor FTP
        try:
            ftp = ftplib.FTP()
            ftp.connect(FTP_HOST, FTP_PORT, timeout=5)
            ftp.login(session['ftp_user'], session['ftp_pass'])
            stats['status'] = 'online'
            ftp.quit()
        except:
            stats['status'] = 'offline'
        
        # Uso del disco
        if VIDEO_DIR.exists():
            disk_usage = psutil.disk_usage(str(VIDEO_DIR))
            stats['disk_usage'] = round((disk_usage.used / disk_usage.total) * 100, 1)
        
        # Uso de red (bytes enviados+recibidos desde arranque)
        net = psutil.net_io_counters()
        stats['net_usage'] = round((net.bytes_sent + net.bytes_recv) / (1024*1024), 2)  # MB

        return stats
    except Exception as e:
        print(f"Error obteniendo estadísticas: {e}")
        return stats

def get_recent_logs(lines=100):
    """Obtiene los logs recientes del servidor"""
    try:
        log_file = LOG_DIR / 'ftp_server.log'
        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
            except UnicodeDecodeError:
                with open(log_file, 'r', encoding='latin1') as f:
                    all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
        return []
    except Exception as e:
        print(f"Error leyendo logs: {e}")
        return []

def get_video_database():
    """Lee la base de datos de videos o lista los archivos si no hay base"""
    try:
        db_file = VIDEO_DIR / 'video_database.txt'
        videos = []
        if db_file.exists() and db_file.stat().st_size > 0:
            with open(db_file, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split(',')
                    if len(parts) >= 3:
                        # Convertir a ruta relativa si es absoluta
                        rel_path = PurePosixPath(f.relative_to(VIDEO_DIR))
                        videos.append({
                            'datetime': parts[0],
                            'path': rel_path,
                            'size': int(parts[2]) if parts[2].isdigit() else 0
                        })
        else:
            for ext in ('*.avi', '*.mp4', '*.dav'):
                for f in VIDEO_DIR.rglob(ext):
                    rel_path = f.relative_to(VIDEO_DIR)
                    videos.append({
                        'datetime': datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                        'path': str(rel_path),
                        'size': f.stat().st_size
                    })
        return sorted(videos, key=lambda x: x['datetime'], reverse=True)
    except Exception as e:
        print(f"Error leyendo base de datos: {e}")
        return []
    
@app.route('/videos/<folder>')
@login_required
def videos_in_folder(folder):
    aliases = load_folder_aliases()
    folder_path = VIDEO_DIR / folder
    if not folder_path.exists() or not folder_path.is_dir():
        flash("Carpeta no encontrada", "error")
        return redirect(url_for('videos'))
    # Buscar archivos de video en la carpeta y subcarpetas (recursivo, case-insensitive)
    videos = []
    for f in folder_path.rglob('*'):
        if f.is_file() and f.suffix.lower() in ('.mp4', '.avi', '.dav'):
            videos.append(f)
    videos_info = [{
        "name": v.name,
        "size": v.stat().st_size,
        "mtime": datetime.fromtimestamp(v.stat().st_mtime),
        "path": str(v.relative_to(VIDEO_DIR))
    } for v in videos]
    # Ordenar por fecha descendente
    videos_info.sort(key=lambda x: x["mtime"], reverse=True)
    return render_template('videos_in_folder.html',
                           folder=folder,
                           alias=aliases.get(folder, ""),
                           videos=videos_info)  

@app.route('/download/<path:filename>')
@login_required
def download_video(filename):
    """Descargar un archivo de video"""
    # Asegura que la ruta sea relativa al directorio de videos
    return send_from_directory(VIDEO_DIR, filename, as_attachment=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Intentar login FTP con las credenciales ingresadas
        try:
            ftp = ftplib.FTP()
            ftp.connect(FTP_HOST, FTP_PORT, timeout=5)
            ftp.login(username, password)
            ftp.quit()
            # Si el login es exitoso, guardar en sesión
            session['logged_in'] = True
            session['username'] = username
            session['ftp_user'] = username
            session['ftp_pass'] = password
            flash('Login exitoso', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            print(e)
            if "503" in str(e):
                flash("Maximo de intentos alcanzado. Intenta más tarde.", "error")
            if "530" in str(e):
                flash('Credenciales incorrectas', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Cerrar sesión"""
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    """Dashboard principal"""
    stats = get_server_stats()
    recent_videos = get_video_database()[:10]  # Últimos 10 videos
    return render_template('dashboard.html', stats=stats, recent_videos=recent_videos)

@app.route('/logs')
@login_required
def logs():
    """Página de logs"""
    log_lines = get_recent_logs(200)
    return render_template('logs.html', logs=log_lines)

@app.route('/videos')
@login_required
def videos():
    aliases = load_folder_aliases()
    # Listar carpetas de primer nivel en VIDEO_DIR
    folders = [f for f in VIDEO_DIR.iterdir() if f.is_dir()]
    folders_info = []
    for folder in folders:
        folders_info.append({
            "real_name": folder.name,
            "alias": aliases.get(folder.name, ""),
            "video_count": len(list(folder.rglob("*.mp4"))) + len(list(folder.rglob("*.avi"))) + len(list(folder.rglob("*.dav")))
        })
    return render_template('videos.html', folders=folders_info)

@app.route('/api/stats')
@login_required
def api_stats():
    """API para obtener estadísticas en tiempo real"""
    stats = get_server_stats()
    project_stats = get_project_stats()
    stats.update(project_stats)
    return jsonify(stats)

@app.route('/api/logs')
@login_required
def api_logs():
    """API para obtener logs recientes"""
    lines = request.args.get('lines', 50, type=int)
    return jsonify({'logs': get_recent_logs(lines)})

def check_git_update():
    """Verifica si hay actualizaciones en el repositorio git"""
    try:
        # Buscar cambios remotos
        subprocess.run(['git', 'fetch'], check=True, capture_output=True)
        local = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
        remote = subprocess.check_output(['git', 'rev-parse', '@{u}']).decode().strip()
        
        if local != remote:
            # Obtener información del commit remoto
            commit_info = get_remote_commit_info()
            return True, commit_info
        return False, None
    except Exception as e:
        print(f"Error comprobando actualizaciones git: {e}")
        return False, None

def get_remote_commit_info():
    """Obtiene información del commit remoto más reciente"""
    try:
        # Obtener hash del commit remoto
        remote_hash = subprocess.check_output(['git', 'rev-parse', '@{u}']).decode().strip()
        
        # Obtener información del commit
        commit_message = subprocess.check_output([
            'git', 'log', '-1', '--pretty=format:%s', remote_hash
        ]).decode().strip()
        
        commit_author = subprocess.check_output([
            'git', 'log', '-1', '--pretty=format:%an', remote_hash
        ]).decode().strip()
        
        commit_date = subprocess.check_output([
            'git', 'log', '-1', '--pretty=format:%ci', remote_hash
        ]).decode().strip()
        
        return {
            'hash': remote_hash[:8],  # Solo los primeros 8 caracteres
            'message': commit_message,
            'author': commit_author,
            'date': commit_date
        }
    except Exception as e:
        print(f"Error obteniendo información del commit: {e}")
        return {
            'hash': 'unknown',
            'message': 'Actualización disponible',
            'author': 'unknown',
            'date': datetime.now().isoformat()
        }
        
def save_changelog_entry(commit_info):
    """Guarda una entrada del changelog"""
    try:
        changelog = []
        if CHANGELOG_FILE.exists():
            with open(CHANGELOG_FILE, 'r', encoding='utf-8') as f:
                changelog = json.load(f)
        
        # Agregar nueva entrada al inicio
        new_entry = {
            'timestamp': datetime.now().isoformat(),
            'commit_hash': commit_info['hash'],
            'commit_message': commit_info['message'],
            'commit_author': commit_info['author'],
            'commit_date': commit_info['date'],
            'applied': True
        }
        
        changelog.insert(0, new_entry)
        
        # Mantener solo las últimas 20 entradas
        changelog = changelog[:20]
        
        with open(CHANGELOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(changelog, f, indent=2, ensure_ascii=False)
            
        return True
    except Exception as e:
        print(f"Error guardando changelog: {e}")
        return False        

def do_git_pull_and_restart():
    """Ejecuta git pull y reinicia el servidor Flask"""
    try:
        # Obtener información del commit antes del pull
        commit_info = get_remote_commit_info()
        
        # Ejecutar git pull
        result = subprocess.run(['git', 'pull', '--no-rebase'], 
                              check=True, capture_output=True, text=True)
        
        # Guardar entrada del changelog
        save_changelog_entry(commit_info)
        
        print(f"Actualización exitosa: {commit_info['message']}")
        
        # Reiniciar el servidor Flask
        os._exit(3)  # Código especial para reinicio supervisado
        
    except subprocess.CalledProcessError as e:
        print(f"Error en git pull: {e}")
        flash('Error al actualizar el proyecto', 'error')
    except Exception as e:
        print(f"Error actualizando el proyecto: {e}")
        flash('Error inesperado al actualizar', 'error')

def get_changelog():
    """Obtiene el changelog completo"""
    try:
        if CHANGELOG_FILE.exists():
            with open(CHANGELOG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"Error leyendo changelog: {e}")
        return []

@app.context_processor
def inject_update_flag():
    """Inyecta variables globales en todas las plantillas"""
    has_update, commit_info = check_git_update()
    changelog = get_changelog()
    
    return dict(
        update_available=has_update,
        pending_commit=commit_info,
        changelog=changelog
    )
    
@app.route('/changelog')
@login_required
def changelog():
    """Página del changelog"""
    changelog_entries = get_changelog()
    return render_template('changelog.html', changelog=changelog_entries)

@app.route('/api/changelog')
@login_required
def api_changelog():
    """API para obtener changelog"""
    return jsonify({'changelog': get_changelog()})

@app.route('/update', methods=['POST'])
@login_required
def update():
    """Endpoint para actualizar el proyecto"""
    has_update, commit_info = check_git_update()
    
    if not has_update:
        flash('No hay actualizaciones disponibles', 'info')
        return redirect(url_for('dashboard'))
    
    # Mostrar información del commit que se va a aplicar
    if commit_info:
        flash(f'Aplicando actualización: {commit_info["message"]} por {commit_info["author"]}', 'info')
    
    threading.Thread(target=do_git_pull_and_restart).start()
    flash('Actualizando proyecto... El servidor se reiniciará.', 'info')
    return redirect(url_for('dashboard'))

def convert_dav_to_mp4(dav_path, mp4_path):
    """Convierte un archivo .dav a .mp4 compatible con navegadores usando ffmpeg"""
    tmp_path = str(mp4_path).replace('.mp4', '.tmp.mp4')
    lock_path = str(mp4_path) + '.lock'
    # Crea un archivo lock para indicar conversión en curso
    with open(lock_path, 'w') as lock:
        lock.write(str(os.getpid()))
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", str(dav_path),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart",
            tmp_path
        ], check=True)
        os.rename(tmp_path, mp4_path)
        return True
    except Exception as e:
        print(f"Error convirtiendo {dav_path} a mp4: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False
    finally:
        if os.path.exists(lock_path):
            os.remove(lock_path)

@app.route('/play/<path:filename>')
@login_required
def play_video(filename):
    """Convierte y reproduce un video .dav temporalmente"""
    video_path = VIDEO_DIR / filename
    if not video_path.exists():
        flash("Archivo no encontrado", "error")
        return redirect(url_for('videos'))

    if video_path.suffix.lower() == ".dav":
        temp_name = f"{session['username']}_{video_path.stem}.mp4"
        temp_path = Path(tempfile.gettempdir()) / temp_name

        # Si el archivo no existe o está vacío, inicia conversión
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            lock_path = str(temp_path) + '.lock'
            if not os.path.exists(lock_path):
                if temp_path.exists():
                    temp_path.unlink()
                threading.Thread(target=convert_dav_to_mp4, args=(video_path, temp_path)).start()
            return render_template('preparing.html', temp_filename=temp_name)
        else:
            return redirect(url_for('player_temp', temp_filename=temp_name))
    else:
        return render_template('player.html', video_file=url_for('download_video', filename=filename))

@app.route('/temp_video/<temp_filename>')
@login_required
def temp_video(temp_filename):
    """Sirve el archivo mp4 temporal"""
    temp_path = Path(tempfile.gettempdir()) / temp_filename
    if not temp_path.exists():
        flash("El video temporal expiró. Intenta de nuevo.", "error")
        return redirect(url_for('videos'))
    return send_from_directory(tempfile.gettempdir(), temp_filename, as_attachment=False)

@app.route('/check_temp_video/<temp_filename>')
@login_required
def check_temp_video(temp_filename):
    """API para saber si el video temporal ya está listo y estable"""
    temp_path = Path(tempfile.gettempdir()) / temp_filename
    if not temp_path.exists():
        return jsonify({'ready': False})
    # Comprobar que el archivo no esté creciendo (esperar 1 segundo y comparar tamaño)
    size1 = temp_path.stat().st_size
    time.sleep(1)
    if not temp_path.exists():
        return jsonify({'ready': False})
    size2 = temp_path.stat().st_size
    ready = size1 == size2 and size1 > 0
    return jsonify({'ready': ready})

@app.route('/player_temp/<temp_filename>')
@login_required
def player_temp(temp_filename):
    """Muestra el reproductor para el video temporal"""
    temp_path = Path(tempfile.gettempdir()) / temp_filename
    if not temp_path.exists():
        flash("El video temporal expiró. Intenta de nuevo.", "error")
        return redirect(url_for('videos'))
    return render_template('player.html', video_file=url_for('temp_video', temp_filename=temp_filename))

def load_folder_aliases():
    if ALIAS_FILE.exists():
        with open(ALIAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_folder_aliases(aliases):
    with open(ALIAS_FILE, "w", encoding="utf-8") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)

@app.route('/set_folder_alias', methods=['POST'])
@login_required
def set_folder_alias():
    folder = request.form['folder']
    alias = request.form['alias']
    aliases = load_folder_aliases()
    aliases[folder] = alias
    save_folder_aliases(aliases)
    return jsonify({"success": True})

def clean_all_temp_videos():
    """Elimina TODOS los archivos temporales de video al cerrar el servidor"""
    temp_dir = Path(tempfile.gettempdir())
    patterns = ["*_*.mp4", "*_*.tmp.mp4", "*_*.mp4.lock"]
    for pattern in patterns:
        for f in temp_dir.glob(pattern):
            try:
                f.unlink()
            except Exception:
                pass

# Limpieza al cerrar el servidor (funciona en la mayoría de los casos)
atexit.register(clean_all_temp_videos)

# Opcional: también puedes limpiar con señales (Ctrl+C, kill)
def handle_exit(signum, frame):
    clean_all_temp_videos()
    os._exit(0)
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

if __name__ == '__main__':
    # Crear directorios necesarios
    VIDEO_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    
    print("=== Cliente Web FTP Dahua ===")
    print("Accede a: http://localhost:5000")
    print("=============================")
    
    app.run(debug=True, host='0.0.0.0', port=5000)

