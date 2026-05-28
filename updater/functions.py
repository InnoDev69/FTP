from datetime import datetime
from src.constants import CHANGELOG_FILE
import subprocess
import json
from flask import flash
import os

def check_git_update():
    """Verifica si hay actualizaciones en el repositorio git"""
    try:
        subprocess.run(['git', 'fetch'], check=True, capture_output=True)
        local = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
        remote = subprocess.check_output(['git', 'rev-parse', '@{u}']).decode().strip()
        
        if local != remote:
            commit_info = get_remote_commit_info()
            return True, commit_info
        return False, None
    except Exception as e:
        print(f"Error comprobando actualizaciones git: {e}")
        return False, None

def get_remote_commit_info():
    """Obtiene información del commit remoto más reciente"""
    try:
        remote_hash = subprocess.check_output(['git', 'rev-parse', '@{u}']).decode().strip()
        
        commit_message = subprocess.check_output([
            'git', 'log', '-1', '--pretty=format:%B', remote_hash
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
    except Exception as e:
        print(f"Error actualizando el proyecto: {e}")

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