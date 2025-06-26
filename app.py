#!/usr/bin/env python3
"""
Cliente web para administrar el servidor FTP Dahua
Aplicación Flask separada del servidor FTP
"""

from flask import Flask, render_template, jsonify, request, redirect, url_for, session, flash
from flask import send_from_directory
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import psutil
import ftplib
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'  # Cambiar en producción

# Configuración
FTP_HOST = 'localhost'
FTP_PORT = 60000
VIDEO_DIR = Path('dahua_videos')
LOG_DIR = Path('logs')

def login_required(f):
    """Decorador para requerir login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_server_stats():
    """Obtiene estadísticas del servidor"""
    try:
        stats = {
            'status': 'offline',
            'video_count': 0,
            'total_size_gb': 0,
            'disk_usage': 0,
            'uptime': 0,
            'connections': 0,
            'last_upload': 'N/A'
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
                stats['last_upload'] = datetime.fromtimestamp(latest_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
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
        
        return stats
    except Exception as e:
        print(f"Error obteniendo estadísticas: {e}")
        return stats

def get_recent_logs(lines=100):
    """Obtiene los logs recientes del servidor"""
    try:
        log_file = LOG_DIR / 'ftp_server.log'
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
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
                        rel_path = os.path.relpath(parts[1], VIDEO_DIR)
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
            flash('Credenciales incorrectas o servidor FTP no disponible', 'error')
    
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
    """Página de videos"""
    all_videos = get_video_database()
    return render_template('videos.html', videos=all_videos)

@app.route('/api/stats')
@login_required
def api_stats():
    """API para obtener estadísticas en tiempo real"""
    return jsonify(get_server_stats())

@app.route('/api/logs')
@login_required
def api_logs():
    """API para obtener logs recientes"""
    lines = request.args.get('lines', 50, type=int)
    return jsonify({'logs': get_recent_logs(lines)})

if __name__ == '__main__':
    # Crear directorios necesarios
    VIDEO_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    
    print("=== Cliente Web FTP Dahua ===")
    print("Accede a: http://localhost:5000")
    print("=============================")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
