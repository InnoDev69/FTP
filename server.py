#!/usr/bin/env python3
"""
Servidor FTP personalizado para recibir videos de DVR Dahua
Incluye funcionalidades de administración y organización automática
"""

import os
import sys
import time
import threading
import logging
from datetime import datetime
from pathlib import Path
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import shutil
import re
import argparse

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
            date_match = self.extract_date_from_filename(file_path.name)
            if date_match:
                date_folder = date_match.strftime("%Y/%m/%d")
                organized_path = file_path.parent / "organized" / date_folder
                organized_path.mkdir(parents=True, exist_ok=True)
                new_path = organized_path / file_path.name
                shutil.move(str(file_path), str(new_path))
                logger.info(f"Video organizado: {new_path}")
                self.update_video_database(new_path, date_match)
        except Exception as e:
            logger.error(f"Error organizando video {file_path}: {e}")

    def update_video_database(self, file_path, date_time):
        logger = logging.getLogger("DahuaFTPServer")
        try:
            db_file = Path(file_path).parents[3] / "video_database.txt"
            with open(db_file, "a", encoding="utf-8") as f:
                f.write(f"{date_time.isoformat()},{file_path},{file_path.stat().st_size}\n")
        except Exception as e:
            logger.error(f"Error actualizando base de datos: {e}")

    def extract_date_from_filename(self, filename):
        # Ejemplo: Casa_ch1_main_20250624000000_20250624010000.dav
        match = re.search(r'(\d{8})(\d{6})', filename)
        if match:
            date_str = match.group(1) + match.group(2)
            try:
                return datetime.strptime(date_str, "%Y%m%d%H%M%S")
            except Exception:
                return None
        return None

class DahuaFTPServer:
    """Servidor FTP especializado para DVR Dahua"""
    
    def __init__(self, host="0.0.0.0", port=21, max_cons=256, max_cons_per_ip=5, video_dir="dahua_videos", log_dir="logs", keep_days=3, user="dahua", password="dahua123"):
        self.host = host
        self.port = port
        self.max_cons = max_cons
        self.max_cons_per_ip = max_cons_per_ip
        self.keep_days = keep_days
        self.user = user
        self.password = password
        self.video_dir = Path(video_dir)
        self.log_dir = Path(log_dir)
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
        authorizer = DummyAuthorizer()
        authorizer.add_user(self.user, self.password, str(self.video_dir), perm="elradfmwMT")
        authorizer.add_anonymous(str(self.video_dir), perm="elr")
        handler = DahuaFTPHandler
        handler.authorizer = authorizer
        handler.passive_ports = range(60000, 65535)
        self.server = FTPServer((self.host, self.port), handler)
        self.server.max_cons = self.max_cons
        self.server.max_cons_per_ip = self.max_cons_per_ip
        self.logger.info(f"Servidor FTP configurado en {self.host}:{self.port}")
    
    def start(self):
        try:
            self.logger.info("Iniciando servidor FTP para DVR Dahua...")
            self.logger.info(f"Directorio de videos: {self.video_dir.absolute()}")
            self.logger.info(f"Usuario: {self.user}, Contraseña: {self.password}")
            self.logger.info(f"Días de retención de archivos: {self.keep_days}")
            monitor_thread = threading.Thread(target=self.monitor_system, daemon=True)
            monitor_thread.start()
            self.server.serve_forever()
        except KeyboardInterrupt:
            self.logger.info("Deteniendo servidor...")
            self.server.close_all()
        except Exception as e:
            self.logger.error(f"Error en servidor: {e}")
    
    def monitor_system(self):
        while True:
            try:
                video_count = sum(1 for f in self.video_dir.rglob("*") if f.is_file())
                total_size = sum(f.stat().st_size for f in self.video_dir.rglob("*") if f.is_file())
                self.logger.info(f"Estadísticas: {video_count} archivos, {total_size / (1024**3):.2f} GB")
                self.cleanup_old_files(self.keep_days)
                time.sleep(300)
            except Exception as e:
                self.logger.error(f"Error en monitoreo: {e}")
                time.sleep(60)
    
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

def main():
    parser = argparse.ArgumentParser(description="Servidor FTP Dahua configurable")
    parser.add_argument('--host', default="0.0.0.0", help="Host/IP para escuchar (default: 0.0.0.0)")
    parser.add_argument('--port', type=int, default=60000, help="Puerto FTP (default: 60000)")
    parser.add_argument('--video-dir', default="dahua_videos", help="Directorio de videos (default: dahua_videos)")
    parser.add_argument('--log-dir', default="logs", help="Directorio de logs (default: logs)")
    parser.add_argument('--keep-days', type=int, default=3, help="Días para mantener archivos de video (default: 3)")
    parser.add_argument('--max-cons', type=int, default=256, help="Conexiones máximas (default: 256)")
    parser.add_argument('--max-cons-per-ip', type=int, default=5, help="Conexiones máximas por IP (default: 5)")
    parser.add_argument('--user', default="dahua", help="Usuario FTP (default: dahua)")
    parser.add_argument('--password', default="dahua123", help="Contraseña FTP (default: dahua123)")
    args = parser.parse_args()

    print("=== Servidor FTP para DVR Dahua ===")
    print("Configuración:")
    print(f"- Host: {args.host}")
    print(f"- Puerto: {args.port}")
    print(f"- Usuario: {args.user}")
    print(f"- Contraseña: {args.password}")
    print(f"- Directorio de videos: {args.video_dir}")
    print(f"- Directorio de logs: {args.log_dir}")
    print(f"- Días de retención: {args.keep_days}")
    print("=====================================")
    
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
            password=args.password
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
