#!/usr/bin/env python3
"""
Servidor FTP personalizado para recibir videos de DVR Dahua
Incluye funcionalidades de administración y organización automática
Con sistema de bloqueo de IPs por intentos fallidos
"""

import os
import sys
import time
import threading
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import shutil
import re
import argparse
from collections import defaultdict, deque

class SecurityManager:
    """Gestor de seguridad para el servidor FTP"""
    
    def __init__(self, max_attempts=3, block_duration=300, cleanup_interval=600):
        self.max_attempts = max_attempts  # Máximo intentos antes de bloquear
        self.block_duration = block_duration  # Duración del bloqueo en segundos
        self.cleanup_interval = cleanup_interval  # Intervalo de limpieza en segundos
        
        # Diccionarios para tracking
        self.failed_attempts = defaultdict(deque)  # IP -> deque de timestamps
        self.blocked_ips = {}  # IP -> timestamp de bloqueo
        self.success_logins = defaultdict(int)  # IP -> contador de logins exitosos
        
        self.logger = logging.getLogger("SecurityManager")
        self.lock = threading.Lock()
        
        # Archivo para persistir datos de seguridad
        self.security_file = Path("security_data.json")
        self.load_security_data()
        
        # Iniciar hilo de limpieza
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
    
    def load_security_data(self):
        """Cargar datos de seguridad desde archivo"""
        try:
            if self.security_file.exists():
                with open(self.security_file, 'r') as f:
                    data = json.load(f)
                    # Convertir timestamps string a datetime
                    for ip, timestamp_str in data.get('blocked_ips', {}).items():
                        timestamp = datetime.fromisoformat(timestamp_str)
                        if datetime.now() < timestamp + timedelta(seconds=self.block_duration):
                            self.blocked_ips[ip] = timestamp
                    self.logger.info(f"Datos de seguridad cargados: {len(self.blocked_ips)} IPs bloqueadas")
        except Exception as e:
            self.logger.error(f"Error cargando datos de seguridad: {e}")
    
    def save_security_data(self):
        """Guardar datos de seguridad en archivo"""
        try:
            data = {
                'blocked_ips': {ip: timestamp.isoformat() for ip, timestamp in self.blocked_ips.items()},
                'last_update': datetime.now().isoformat()
            }
            with open(self.security_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error guardando datos de seguridad: {e}")
    
    def is_ip_blocked(self, ip):
        """Verificar si una IP está bloqueada"""
        with self.lock:
            if ip in self.blocked_ips:
                block_time = self.blocked_ips[ip]
                if datetime.now() < block_time + timedelta(seconds=self.block_duration):
                    return True
                # El bloqueo ha expirado
                del self.blocked_ips[ip]
                self.save_security_data()
            return False
    
    def record_failed_attempt(self, ip):
        """Registrar un intento fallido de login"""
        with self.lock:
            now = datetime.now()
            
            # Limpiar intentos antiguos (más de 1 hora)
            cutoff_time = now - timedelta(hours=1)
            while self.failed_attempts[ip] and self.failed_attempts[ip][0] < cutoff_time:
                self.failed_attempts[ip].popleft()
            
            # Agregar el nuevo intento fallido
            self.failed_attempts[ip].append(now)
            
            # Verificar si debe ser bloqueada
            if len(self.failed_attempts[ip]) >= self.max_attempts:
                self.blocked_ips[ip] = now
                self.logger.warning(f"IP {ip} BLOQUEADA por {self.max_attempts} intentos fallidos")
                self.save_security_data()
                return True
            else:
                attempts_left = self.max_attempts - len(self.failed_attempts[ip])
                self.logger.warning(f"Intento fallido desde {ip}. Intentos restantes: {attempts_left}")
                return False
    
    def record_successful_login(self, ip, username):
        """Registrar un login exitoso"""
        with self.lock:
            # Limpiar intentos fallidos previos
            if ip in self.failed_attempts:
                del self.failed_attempts[ip]
            
            self.success_logins[ip] += 1
            self.logger.info(f"Login exitoso desde {ip} (usuario: {username})")
    
    def get_blocked_ips_info(self):
        """Obtener información de IPs bloqueadas"""
        with self.lock:
            info = []
            for ip, block_time in self.blocked_ips.items():
                remaining = self.block_duration - (datetime.now() - block_time).total_seconds()
                if remaining > 0:
                    info.append({
                        'ip': ip,
                        'blocked_at': block_time.isoformat(),
                        'remaining_seconds': int(remaining)
                    })
            return info
    
    def unblock_ip(self, ip):
        """Desbloquear una IP manualmente"""
        with self.lock:
            if ip in self.blocked_ips:
                del self.blocked_ips[ip]
                self.logger.info(f"IP {ip} desbloqueada manualmente")
                self.save_security_data()
                return True
            return False
    
    def _cleanup_loop(self):
        """Hilo de limpieza de datos antiguos"""
        while True:
            try:
                time.sleep(self.cleanup_interval)
                self._cleanup_old_data()
            except Exception as e:
                self.logger.error(f"Error en limpieza de seguridad: {e}")
    
    def _cleanup_old_data(self):
        """Limpiar datos antiguos"""
        with self.lock:
            now = datetime.now()

            # Limpiar IPs bloqueadas expiradas
            expired_ips = []
            expired_ips.extend(
                ip
                for ip, block_time in self.blocked_ips.items()
                if now > block_time + timedelta(seconds=self.block_duration)
            )
            for ip in expired_ips:
                del self.blocked_ips[ip]
                self.logger.info(f"IP {ip} desbloqueada automáticamente")

            if expired_ips:
                self.save_security_data()

            # Limpiar intentos fallidos antiguos
            cutoff_time = now - timedelta(hours=24)
            for ip in list(self.failed_attempts.keys()):
                while self.failed_attempts[ip] and self.failed_attempts[ip][0] < cutoff_time:
                    self.failed_attempts[ip].popleft()
                if not self.failed_attempts[ip]:
                    del self.failed_attempts[ip]

class SecureAuthorizer(DummyAuthorizer):
    """Autorizador con sistema de seguridad"""
    
    def __init__(self, security_manager):
        super().__init__()
        self.security_manager = security_manager
        self.logger = logging.getLogger("SecureAuthorizer")
    
    def validate_authentication(self, username, password, handler):
        """Validar autenticación con control de intentos fallidos"""
        client_ip = handler.remote_ip

        # Verificar si la IP está bloqueada
        if self.security_manager.is_ip_blocked(client_ip):
            self.logger.warning(f"Intento de conexión desde IP bloqueada: {client_ip}")
            raise AuthenticationFailed("IP temporalmente bloqueada por intentos fallidos")

        try:
            # Llamar al método original de validación
            result = super().validate_authentication(username, password, handler)

            # Si llegamos aquí, la autenticación fue exitosa
            self.security_manager.record_successful_login(client_ip, username)
            return result

        except AuthenticationFailed as e:
            if was_blocked := self.security_manager.record_failed_attempt(
                client_ip
            ):
                raise AuthenticationFailed(
                    "IP bloqueada por múltiples intentos fallidos"
                ) from e
            raise e

class DahuaFTPHandler(FTPHandler):
    """Handler personalizado para manejar uploads de DVR Dahua"""

    def on_file_received(self, file):
        logger = logging.getLogger("DahuaFTPServer")
        try:
            file_path = Path(file)
            file_size = file_path.stat().st_size
            logger.info(f"Archivo recibido: {file} ({file_size} bytes)")
            if self.is_video_file(file):
                self.organize_video_file(file)
        except Exception as e:
            logger.error(f"Error procesando archivo {file}: {e}")
    
    def is_video_file(self, file_path):
        video_extensions = ['.avi', '.mp4', '.mkv', '.mov', '.wmv', '.flv', '.dav']
        return Path(file_path).suffix.lower() in video_extensions
    
    def organize_video_file(self, file_path):
        logger = logging.getLogger("DahuaFTPServer")
        try:
            file_path = Path(file_path)
            if date_match := self.extract_date_from_filename(file_path.name):
                self._extracted_from_organize_video_file_6(date_match, file_path, logger)
        except Exception as e:
            logger.error(f"Error organizando video {file_path}: {e}")

    # TODO Rename this here and in `organize_video_file`
    def _extracted_from_organize_video_file_6(self, date_match, file_path, logger):
        date_folder = date_match.strftime("%Y/%m/%d")
        organized_path = file_path.parent / "organized" / date_folder
        organized_path.mkdir(parents=True, exist_ok=True)
        new_path = organized_path / file_path.name
        shutil.move(str(file_path), str(new_path))
        logger.info(f"Video organizado: {new_path}")
        self.update_video_database(new_path, date_match)

    def update_video_database(self, file_path, date_time):
        logger = logging.getLogger("DahuaFTPServer")
        try:
            db_file = Path(file_path).parents[3] / "video_database.txt"
            with open(db_file, "a", encoding="utf-8") as f:
                f.write(f"{date_time.isoformat()},{file_path},{file_path.stat().st_size}\n")
        except Exception as e:
            logger.error(f"Error actualizando base de datos: {e}")

    def extract_date_from_filename(self, filename):
        if match := re.search(r'(\d{8})(\d{6})', filename):
            date_str = match[1] + match[2]
            try:
                return datetime.strptime(date_str, "%Y%m%d%H%M%S")
            except Exception:
                return None
        return None

class DahuaFTPServer:
    """Servidor FTP especializado para DVR Dahua con seguridad mejorada"""
    
    def __init__(self, host="0.0.0.0", port=21, max_cons=256, max_cons_per_ip=5, 
                 video_dir="dahua_videos", log_dir="logs", keep_days=3, 
                 user="dahua", password="dahua123", max_attempts=3, block_duration=300):
        self.host = host
        self.port = port
        self.max_cons = max_cons
        self.max_cons_per_ip = max_cons_per_ip
        self.keep_days = keep_days
        self.user = user
        self.password = password
        self.max_attempts = max_attempts
        self.block_duration = block_duration
        self.video_dir = Path(video_dir)
        self.log_dir = Path(log_dir)
        
        # Inicializar gestor de seguridad
        self.security_manager = SecurityManager(max_attempts, block_duration)
        
        self.setup_logging()
        self.video_dir.mkdir(exist_ok=True)
        self.setup_server()
    
    def setup_logging(self):
        self.log_dir.mkdir(exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_dir / "ftp_server.log"),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger("DahuaFTPServer")
    
    def setup_server(self):
        # Usar el autorizador seguro
        authorizer = SecureAuthorizer(self.security_manager)
        authorizer.add_user(self.user, self.password, str(self.video_dir), perm="elradfmwMT")
        authorizer.add_anonymous(str(self.video_dir), perm="elr")
        
        handler = DahuaFTPHandler
        handler.authorizer = authorizer
        handler.passive_ports = range(60000, 65535)
        
        self.server = FTPServer((self.host, self.port), handler)
        self.server.max_cons = self.max_cons
        self.server.max_cons_per_ip = self.max_cons_per_ip
        
        self.logger.info(f"Servidor FTP configurado en {self.host}:{self.port}")
        self.logger.info(f"Seguridad: máximo {self.max_attempts} intentos, bloqueo por {self.block_duration}s")
    
    def start(self):
        try:
            self._extracted_from_start_3()
        except KeyboardInterrupt:
            self.logger.info("Deteniendo servidor...")
            self.server.close_all()
        except Exception as e:
            self.logger.error(f"Error en servidor: {e}")

    # TODO Rename this here and in `start`
    def _extracted_from_start_3(self):
        self.logger.info("Iniciando servidor FTP para DVR Dahua...")
        self.logger.info(f"Directorio de videos: {self.video_dir.absolute()}")
        self.logger.info(f"Usuario: {self.user}, Contraseña: {self.password}")
        self.logger.info(f"Días de retención de archivos: {self.keep_days}")

        # Iniciar hilo de monitoreo
        monitor_thread = threading.Thread(target=self.monitor_system, daemon=True)
        monitor_thread.start()

        # Iniciar hilo de reporte de seguridad
        security_thread = threading.Thread(target=self.security_report_loop, daemon=True)
        security_thread.start()

        self.server.serve_forever()
    
    def monitor_system(self):
        while True:
            try:
                video_count = sum(bool(f.is_file())
                              for f in self.video_dir.rglob("*"))
                total_size = sum(f.stat().st_size for f in self.video_dir.rglob("*") if f.is_file())
                self.logger.info(f"Estadísticas: {video_count} archivos, {total_size / (1024**3):.2f} GB")
                self.cleanup_old_files(self.keep_days)
                time.sleep(300)
            except Exception as e:
                self.logger.error(f"Error en monitoreo: {e}")
                time.sleep(60)
    
    def security_report_loop(self):
        """Hilo para reportar estadísticas de seguridad"""
        while True:
            try:
                time.sleep(900)  # Cada 15 minutos
                if blocked_ips := self.security_manager.get_blocked_ips_info():
                    self.logger.warning(f"IPs bloqueadas actualmente: {len(blocked_ips)}")
                    for ip_info in blocked_ips:
                        remaining_min = ip_info['remaining_seconds'] // 60
                        self.logger.warning(f"  - {ip_info['ip']}: {remaining_min} minutos restantes")
            except Exception as e:
                self.logger.error(f"Error en reporte de seguridad: {e}")
    
    def cleanup_old_files(self, days_to_keep=3):
        try:
            cutoff_time = time.time() - (days_to_keep * 24 * 3600)
            removed_count = 0
            removed_size = 0
            for file_path in self.video_dir.rglob("*"):
                if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    removed_count += 1
                    removed_size += file_size
            if removed_count > 0:
                self.logger.info(f"Limpieza: {removed_count} archivos eliminados, {removed_size / (1024**2):.2f} MB liberados")
        except Exception as e:
            self.logger.error(f"Error en limpieza: {e}")
    
    def unblock_ip(self, ip):
        """Desbloquear una IP específica"""
        return self.security_manager.unblock_ip(ip)
    
    def get_security_status(self):
        """Obtener estado de seguridad"""
        return self.security_manager.get_blocked_ips_info()

def main():
    parser = argparse.ArgumentParser(description="Servidor FTP Dahua configurable con seguridad")
    parser.add_argument('--host', default="0.0.0.0", help="Host/IP para escuchar (default: 0.0.0.0)")
    parser.add_argument('--port', type=int, default=60000, help="Puerto FTP (default: 60000)")
    parser.add_argument('--video-dir', default="dahua_videos", help="Directorio de videos (default: dahua_videos)")
    parser.add_argument('--log-dir', default="logs", help="Directorio de logs (default: logs)")
    parser.add_argument('--keep-days', type=int, default=3, help="Días para mantener archivos de video (default: 3)")
    parser.add_argument('--max-cons', type=int, default=256, help="Conexiones máximas (default: 256)")
    parser.add_argument('--max-cons-per-ip', type=int, default=5, help="Conexiones máximas por IP (default: 5)")
    parser.add_argument('--user', default="dahua", help="Usuario FTP (default: dahua)")
    parser.add_argument('--password', default="dahua123", help="Contraseña FTP (default: dahua123)")
    parser.add_argument('--max-attempts', type=int, default=3, help="Máximo intentos fallidos antes de bloquear (default: 3)")
    parser.add_argument('--block-duration', type=int, default=300, help="Duración del bloqueo en segundos (default: 300)")
    parser.add_argument('--unblock-ip', help="Desbloquear una IP específica")
    parser.add_argument('--status', action='store_true', help="Mostrar estado de seguridad")

    args = parser.parse_args()

    # Funciones de administración
    if args.unblock_ip or args.status:
        security_manager = SecurityManager(args.max_attempts, args.block_duration)

    if args.unblock_ip:
        if security_manager.unblock_ip(args.unblock_ip):
            print(f"IP {args.unblock_ip} desbloqueada exitosamente")
        else:
            print(f"IP {args.unblock_ip} no estaba bloqueada")
        return 0

    if args.status:
        if blocked_ips := security_manager.get_blocked_ips_info():
            print("IPs bloqueadas:")
            for ip_info in blocked_ips:
                remaining_min = ip_info['remaining_seconds'] // 60
                print(f"  - {ip_info['ip']}: {remaining_min} minutos restantes")
        else:
            print("No hay IPs bloqueadas actualmente")
        return 0

    print("=== Servidor FTP para DVR Dahua (Seguro) ===")
    print("Configuración:")
    print(f"- Host: {args.host}")
    print(f"- Puerto: {args.port}")
    print(f"- Usuario: {args.user}")
    print(f"- Contraseña: {args.password}")
    print(f"- Directorio de videos: {args.video_dir}")
    print(f"- Directorio de logs: {args.log_dir}")
    print(f"- Días de retención: {args.keep_days}")
    print(f"- Máximo intentos fallidos: {args.max_attempts}")
    print(f"- Duración de bloqueo: {args.block_duration} segundos")
    print("===========================================")

    try:
        server = DahuaFTPServer(
            host=args.host,
            port=args.port,
            max_cons=args.max_cons,
            max_cons_per_ip=args.max_cons_per_ip,
            video_dir=args.video_dir,
            log_dir=args.log_dir,
            keep_days=args.keep_days,
            user=args.user,
            password=args.password,
            max_attempts=args.max_attempts,
            block_duration=args.block_duration
        )
        server.start()
    except Exception as e:
        print(f"Error iniciando servidor: {e}")
        return 1
    return 0

if __name__ == "__main__":
    try:
        from pyftpdlib.authorizers import DummyAuthorizer
    except ImportError:
        print("Instalando dependencias...")
        os.system("pip install pyftpdlib")
        from pyftpdlib.authorizers import DummyAuthorizer
    sys.exit(main())