#!/usr/bin/env python3
"""
Cliente web para administrar el servidor FTP Dahua
Aplicación Flask separada del servidor FTP
"""


import contextlib
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
    "LAST_COMMIT_FILE": "last_commit.txt",

    # Configuración de conversión DAV a MP4
    "CONVERSION_ENABLED": True,
    "CONVERSION_METHOD": "software",  # software, nvidia, amd, intel, auto
    "CONVERSION_PRESET": "fast",      # ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
    "CONVERSION_CRF": 23,             # 18-28, menor = mejor calidad
    "CONVERSION_RESOLUTION": "original",  # original, 1080p, 720p, 480p
    "CONVERSION_THREADS": 0,          # 0 = auto, o número específico
    "CONVERSION_AUDIO_CODEC": "aac",  # aac, mp3, copy
    "CONVERSION_AUDIO_BITRATE": "128k",
    "CONVERSION_CLEANUP_TEMP": True,  # Limpiar archivos temporales
    "CONVERSION_TIMEOUT": 300,        # Timeout en segundos (5 minutos)
    "CONVERSION_CUSTOM_ARGS": "",     # Argumentos adicionales de FFmpeg
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
        except Exception:
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
    videos.extend(
        f
        for f in folder_path.rglob('*')
        if f.is_file() and f.suffix.lower() in ('.mp4', '.avi', '.dav')
    )
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
    folders_info.extend(
        {
            "real_name": folder.name,
            "alias": aliases.get(folder.name, ""),
            "video_count": len(list(folder.rglob("*.mp4")))
            + len(list(folder.rglob("*.avi")))
            + len(list(folder.rglob("*.dav"))),
        }
        for folder in folders
    )
    return render_template('videos.html', folders=folders_info)

@app.route('/api/cpu_usage')
def api_cpu_usage():
    """API para obtener uso de CPU"""
    try:
        cpu_usage = psutil.cpu_percent(interval=0.2)
        return jsonify({'cpu_usage': cpu_usage})
    except Exception as e:
        print(f"Error obteniendo uso de CPU: {e}")
        return jsonify({'cpu_usage': 0})
    
@app.route('/api/time')
def api_time():
    """API para obtener el tiempo de uso del servidor"""
    return jsonify({'uptime': format_uptime(time.time() - SERVER_START_TIME)})

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

def get_conversion_command(dav_path, mp4_path, config):
    """
    Genera el comando FFmpeg basado en la configuración
    """
    cmd = ["ffmpeg", "-y"]

    # Configurar método de conversión (aceleración por hardware)
    method = config.get("CONVERSION_METHOD", "software")

    # Opciones de hwaccel SOLO para la entrada
    hwaccel_args = []
    if method == "nvidia":
        hwaccel_args = [
            "-hwaccel", "cuda",
            "-hwaccel_output_format", "cuda"
        ]
    elif method == "amd":
        hwaccel_args = [
            "-hwaccel", "d3d11va"
        ]
    elif method == "intel":
        hwaccel_args = [
            "-hwaccel", "qsv"
        ]
    elif method == "auto":
        hwaccel_args = get_auto_acceleration_args(config)[:4]  # Solo hwaccel args

    # Agrega las opciones de hwaccel ANTES del input
    cmd.extend(hwaccel_args)
    cmd.extend(["-i", str(dav_path)])

    # Opciones de codificación de video
    if method == "nvidia":
        # Mapear presets a los válidos de h264_nvenc
        user_preset = config.get("CONVERSION_PRESET", "fast")
        nvenc_preset_map = {
            "ultrafast": "fast",
            "superfast": "fast",
            "veryfast": "fast",
            "faster": "fast",
            "fast": "medium",
            "medium": "medium",
            "slow": "slow",
            "slower": "slow",
            "veryslow": "slow"
        }
        nvenc_preset = nvenc_preset_map.get(user_preset, "medium")
        cmd.extend([
            "-c:v", "h264_nvenc",
            "-preset", nvenc_preset,
            "-cq", str(config.get("CONVERSION_CRF", 23))
        ])
    elif method == "amd":
        cmd.extend([
            "-c:v", "h264_amf",
            "-quality", "speed" if config.get("CONVERSION_PRESET", "fast") in ["ultrafast", "superfast", "veryfast", "faster", "fast"] else "quality",
            "-crf", str(config.get("CONVERSION_CRF", 23))
        ])
    elif method == "intel":
        cmd.extend([
            "-c:v", "h264_qsv",
            "-preset", config.get("CONVERSION_PRESET", "fast"),
            "-crf", str(config.get("CONVERSION_CRF", 23))
        ])
    elif method == "auto":
        # El resto de args de auto
        cmd.extend(get_auto_acceleration_args(config)[4:])
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-preset", config.get("CONVERSION_PRESET", "fast"),
            "-crf", str(config.get("CONVERSION_CRF", 23))
        ])

    # Configurar resolución
    resolution = config.get("CONVERSION_RESOLUTION", "original")
    if resolution == "1080p":
        cmd.extend(["-vf", "scale=1920:1080"])
    elif resolution == "480p":
        cmd.extend(["-vf", "scale=854:480"])

    elif resolution == "720p":
        cmd.extend(["-vf", "scale=1280:720"])
    # Configurar audio
    audio_codec = config.get("CONVERSION_AUDIO_CODEC", "aac")
    audio_bitrate = config.get("CONVERSION_AUDIO_BITRATE", "128k") or "128k"
    if audio_codec == "copy":
        cmd.extend(["-c:a", "copy"])
    elif audio_codec == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", audio_bitrate])
    else:  # aac
        cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])

    # Configurar threads
    threads = config.get("CONVERSION_THREADS", 0)
    if threads > 0:
        cmd.extend(["-threads", str(threads)])

    # Optimizaciones adicionales
    cmd.extend([
        "-movflags", "+faststart",  # Optimización para streaming
        "-avoid_negative_ts", "make_zero"  # Evitar timestamps negativos
    ])

    if custom_args := config.get("CONVERSION_CUSTOM_ARGS", ""):
        cmd.extend(custom_args.split())

    # Archivo de salida
    cmd.append(str(mp4_path))

    return cmd

def get_auto_acceleration_args(config):
    """
    Detecta automáticamente la mejor aceleración disponible
    """
    import subprocess
    
    # Probar NVIDIA
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        if result.returncode == 0:
            return [
                "-hwaccel", "cuda",
                "-hwaccel_output_format", "cuda",
                "-c:v", "h264_nvenc",
                "-preset", config.get("CONVERSION_PRESET", "fast"),
                "-cq", str(config.get("CONVERSION_CRF", 23))
            ]
    except:
        pass
    
    # Probar Intel QSV
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
        if "h264_qsv" in result.stdout:
            return [
                "-hwaccel", "qsv",
                "-c:v", "h264_qsv",
                "-preset", config.get("CONVERSION_PRESET", "fast"),
                "-crf", str(config.get("CONVERSION_CRF", 23))
            ]
    except:
        pass
    
    # Fallback a software
    return [
        "-c:v", "libx264",
        "-preset", config.get("CONVERSION_PRESET", "fast"),
        "-crf", str(config.get("CONVERSION_CRF", 23))
    ]

def convert_dav_to_mp4_advanced(dav_path, mp4_path, config):
    """
    Versión mejorada de conversión con configuración avanzada
    """
    import subprocess
    import os
    import time

    if not config.get("CONVERSION_ENABLED", True):
        print("Conversión deshabilitada en la configuración")
        return False

    tmp_path = str(mp4_path).replace('.mp4', '.tmp.mp4')
    lock_path = f'{str(mp4_path)}.lock'

    # Crear archivo lock
    with open(lock_path, 'w') as lock:
        lock.write(str(os.getpid()))

    try:
        # Generar comando de conversión
        cmd = get_conversion_command(dav_path, tmp_path, config)

        print(f"Iniciando conversión: {' '.join(cmd)}")

        # Ejecutar conversión con timeout
        timeout = config.get("CONVERSION_TIMEOUT", 300)
        start_time = time.time()

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout)

            if process.returncode == 0:
                # Conversión exitosa
                os.rename(tmp_path, mp4_path)

                # Limpiar archivos temporales si está habilitado
                if config.get("CONVERSION_CLEANUP_TEMP", True):
                    cleanup_temp_files(dav_path, mp4_path)

                elapsed_time = time.time() - start_time
                print(f"Conversión completada en {elapsed_time:.2f} segundos")
                return True
            else:
                print(f"Error en conversión: {stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"Conversión cancelada por timeout ({timeout}s)")
            process.kill()
            return False

    except Exception as e:
        print(f"Error en conversión: {e}")
        return False
    finally:
        # Limpiar archivos temporales
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(lock_path):
            os.remove(lock_path)

def cleanup_temp_files(dav_path, mp4_path):
    """
    Limpia archivos temporales relacionados con la conversión
    """
    import os
    import glob
    
    try:
        # Limpiar archivos temporales de FFmpeg
        base_name = os.path.splitext(mp4_path)[0]
        temp_patterns = [
            f"{base_name}*.tmp",
            f"{base_name}*.temp",
            f"{base_name}*.log"
        ]
        
        for pattern in temp_patterns:
            for temp_file in glob.glob(pattern):
                try:
                    os.remove(temp_file)
                except:
                    pass
                    
    except Exception as e:
        print(f"Error limpiando archivos temporales: {e}")

def validate_conversion_config(config):
    """
    Valida la configuración de conversión
    """
    errors = []
    
    # Validar método de conversión
    valid_methods = ["software", "nvidia", "amd", "intel", "auto"]
    if config.get("CONVERSION_METHOD") not in valid_methods:
        errors.append(f"Método de conversión inválido. Opciones: {', '.join(valid_methods)}")
    
    # Validar preset
    valid_presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
    if config.get("CONVERSION_PRESET") not in valid_presets:
        errors.append(f"Preset inválido. Opciones: {', '.join(valid_presets)}")
    
    # Validar CRF
    crf = config.get("CONVERSION_CRF", 23)
    if not (0 <= crf <= 51):
        errors.append("CRF debe estar entre 0 y 51")
    
    # Validar resolución
    valid_resolutions = ["original", "1080p", "720p", "480p"]
    if config.get("CONVERSION_RESOLUTION") not in valid_resolutions:
        errors.append(f"Resolución inválida. Opciones: {', '.join(valid_resolutions)}")
    
    # Validar threads
    threads = config.get("CONVERSION_THREADS", 0)
    if threads < 0:
        errors.append("Número de threads no puede ser negativo")
    
    # Validar timeout
    timeout = config.get("CONVERSION_TIMEOUT", 300)
    if timeout < 30:
        errors.append("Timeout mínimo es 30 segundos")
    
    return errors

def test_conversion_capabilities():
    """
    Prueba las capacidades de conversión disponibles
    """
    
    capabilities = {
        "ffmpeg_available": False,
        "nvidia_available": False,
        "amd_available": False,
        "intel_available": False,
        "supported_encoders": []
    }
    
    # Verificar FFmpeg
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        capabilities["ffmpeg_available"] = result.returncode == 0
    except:
        return capabilities
    
    # Verificar encoders disponibles
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
        if result.returncode == 0:
            encoders = result.stdout
            
            # Verificar NVIDIA
            if "h264_nvenc" in encoders:
                capabilities["nvidia_available"] = True
                capabilities["supported_encoders"].append("h264_nvenc")
            
            # Verificar AMD
            if "h264_amf" in encoders:
                capabilities["amd_available"] = True
                capabilities["supported_encoders"].append("h264_amf")
            
            # Verificar Intel
            if "h264_qsv" in encoders:
                capabilities["intel_available"] = True
                capabilities["supported_encoders"].append("h264_qsv")
            
            # Software encoder
            if "libx264" in encoders:
                capabilities["supported_encoders"].append("libx264")
                
    except:
        pass
    
    return capabilities

# Ejemplo de uso en la función convert_dav_to_mp4 existente
def convert_dav_to_mp4(dav_path, mp4_path):
    """
    Función de conversión actualizada que usa la configuración avanzada
    """
    # Cargar configuración actual
    config = load_config()
    
    # Usar la conversión avanzada
    return convert_dav_to_mp4_advanced(dav_path, mp4_path, config)
            
@app.route('/configuration')
@login_required
def configuration():
    """Página de configuración"""
    current_config = load_config()
    return render_template('configuration.html', config=current_config)

def get_int_form(name, default):
    try:
        value = request.form.get(name, str(default))
        return int(value) if value.strip() != '' else default
    except Exception:
        return default

@app.route('/save_configuration', methods=['POST'])
@login_required
def save_configuration():
    """Guardar configuración"""
    try:
        new_config = {
            'FTP_HOST': request.form.get('ftp_host', 'localhost'),
            'FTP_PORT': get_int_form('ftp_port', 60000),
            'VIDEO_DIR': request.form.get('video_dir', 'dahua_videos'),
            'LOG_DIR': request.form.get('log_dir', 'logs'),
            'ALIAS_FILE': request.form.get('alias_file', 'dahua_videos/folder_aliases.json'),
            'ATTEMPS_LOGGING': get_int_form('attemps_logging', 0),
            'ATTEMPS_MAX': get_int_form('attemps_max', 5),
            'CHANGELOG_FILE': request.form.get('changelog_file', 'changelog.json'),
            'LAST_COMMIT_FILE': request.form.get('last_commit_file', 'last_commit.txt'),
            'KEEP_DAYS': get_int_form('keep_days', 7),
            'MAX_CONNECTIONS': get_int_form('max_connections', 256),
            'MAX_CONNECTIONS_PER_IP': get_int_form('max_connections_per_ip', 5),
            'BLOCK_DURATION': get_int_form('block_duration', 300),
            'WEB_PORT': get_int_form('web_port', 5000),
            'WEB_HOST': request.form.get('web_host', '0.0.0.0'),
            'CONVERSION_ENABLED': request.form.get('conversion_enabled', '1') == '1',
            'CONVERSION_METHOD': request.form.get('conversion_method', 'software'),
            'CONVERSION_PRESET': request.form.get('conversion_preset', 'fast'),
            'CONVERSION_CRF': get_int_form('conversion_crf', 23),
            'CONVERSION_RESOLUTION': request.form.get('conversion_resolution', 'original'),
            'CONVERSION_THREADS': get_int_form('conversion_threads', 0),
            'CONVERSION_TIMEOUT': get_int_form('conversion_timeout', 300),
            'CONVERSION_AUDIO_CODEC': request.form.get('conversion_audio_codec', 'aac'),
            'CONVERSION_AUDIO_BITRATE': request.form.get('conversion_audio_bitrate', '128k'),
            'CONVERSION_CLEANUP_TEMP': request.form.get('conversion_cleanup_temp', '1') == '1',
            'CONVERSION_CUSTOM_ARGS': request.form.get('conversion_custom_args', ''),
        }
        
        # Guardar configuración
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        flash('Configuración guardada correctamente. Reinicia el servidor para aplicar los cambios.', 'success')
    except Exception as e:
        flash(f'Error al guardar la configuración: {str(e)}', 'error')
    return redirect(url_for('configuration'))

@app.route('/reset_configuration', methods=['POST'])
@login_required
def reset_configuration():
    """Resetear configuración a valores por defecto"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        flash('Configuración restablecida a valores por defecto', 'success')
    except Exception as e:
        flash(f'Error al restablecer la configuración: {str(e)}', 'error')
    
    return redirect(url_for('configuration'))

@app.route('/play/<path:filename>')
@login_required
def play_video(filename):
    """Convierte y reproduce un video .dav temporalmente"""
    video_path = VIDEO_DIR / filename
    if not video_path.exists():
        flash("Archivo no encontrado", "error")
        return redirect(url_for('videos'))

    if video_path.suffix.lower() != ".dav":
        return render_template('player.html', video_file=url_for('download_video', filename=filename))
    temp_name = f"{session['username']}_{video_path.stem}.mp4"
    temp_path = Path(tempfile.gettempdir()) / temp_name

    if temp_path.exists() and temp_path.stat().st_size != 0:
        return redirect(url_for('player_temp', temp_filename=temp_name))
    lock_path = f'{str(temp_path)}.lock'
    if not os.path.exists(lock_path):
        if temp_path.exists():
            temp_path.unlink()
        threading.Thread(target=convert_dav_to_mp4, args=(video_path, temp_path)).start()
    return render_template('preparing.html', temp_filename=temp_name)

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
            with contextlib.suppress(Exception):
                f.unlink()

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

