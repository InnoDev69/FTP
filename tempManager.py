import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
import contextlib
import json
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TempFileManager:
    def __init__(self, config_loader=None):
        self.temp_files = {}  # {temp_path: last_access_time}
        self.config_loader = config_loader
        self.cleanup_thread = None
        self.stop_cleanup = threading.Event()
        self.lock = threading.Lock()
        self.last_cleanup = 0  # Forzar primera limpieza
        
        # Cargar configuración inicial
        self._load_config()
        
        # Iniciar limpieza automática
        self.start_cleanup_thread()
        logger.info("TempFileManager iniciado")

    def _load_config(self):
        """Carga la configuración actual"""
        try:
            if self.config_loader:
                config = self.config_loader()
            else:
                # Fallback a archivo local
                config_file = Path("config.json")
                if config_file.exists():
                    with open(config_file, "r", encoding="utf-8") as f:
                        config = json.load(f)
                else:
                    config = {}
            
            # Asegurar valores mínimos (en segundos)
            self.max_age = config.get("TEMP_FILE_MAX_AGE", 30) * 60  # Convertir minutos a segundos
            self.cleanup_interval = config.get("TEMP_CLEANUP_INTERVAL", 30) * 60
            
            logger.info(f"Configuración cargada: max_age={self.max_age}s, interval={self.cleanup_interval}s")
            return config
            
        except Exception as e:
            logger.error(f"Error cargando configuración: {e}")
            # Valores seguros por defecto (en segundos)
            self.max_age = 1800  # 30 minutos
            self.cleanup_interval = 1800
            return {}

    def register_file(self, temp_path):
        """Registra un archivo temporal y su tiempo de último acceso"""
        with self.lock:
            self.temp_files[str(temp_path)] = time.time()
            logger.info(f"Archivo temporal registrado: {temp_path}")

    def access_file(self, temp_path):
        """Actualiza el tiempo de último acceso de un archivo y verifica si existe"""
        temp_path_str = str(temp_path)
        path_obj = Path(temp_path)
        
        # Verificar si el archivo existe
        if not path_obj.exists():
            # Si no existe, eliminarlo del registro
            with self.lock:
                if temp_path_str in self.temp_files:
                    del self.temp_files[temp_path_str]
                    logger.info(f"Archivo temporal eliminado del registro (no existe): {temp_path}")
            return False
        
        # Si existe, actualizar tiempo de acceso
        with self.lock:
            self.temp_files[temp_path_str] = time.time()
            logger.info(f"Archivo temporal accedido: {temp_path}")
        
        return True

    def remove_file(self, temp_path):
        """Elimina un archivo temporal y su registro"""
        temp_path_str = str(temp_path)
        
        with self.lock:
            # Eliminar del registro
            if temp_path_str in self.temp_files:
                del self.temp_files[temp_path_str]
            
            # Eliminar archivo físico
            try:
                path_obj = Path(temp_path)
                if path_obj.exists():
                    path_obj.unlink()
                    logger.info(f"Archivo temporal eliminado: {temp_path}")
                    return True
            except Exception as e:
                logger.error(f"Error eliminando archivo temporal {temp_path}: {e}")
        
        return False

    def cleanup_old_files(self, max_age=None):
        """Limpia archivos antiguos"""
        if max_age is None:
            max_age = self.max_age

        current_time = time.time()
        removed_count = 0
        
        with self.lock:
            # Copiar lista para evitar modificar durante iteración
            temp_files = list(self.temp_files.items())
        
        logger.info(f"Iniciando limpieza. {len(temp_files)} archivos registrados")
        
        for temp_path_str, last_access in temp_files:
            try:
                path = Path(temp_path_str)
                age = current_time - last_access
                
                should_remove = False
                if not path.exists():
                    should_remove = True
                    reason = "no existe"
                elif age > max_age:
                    should_remove = True
                    reason = f"expirado ({age:.0f}s > {max_age}s)"
                
                if should_remove:
                    logger.info(f"Eliminando {temp_path_str}: {reason}")
                    if self.remove_file(temp_path_str):
                        removed_count += 1
                        
            except Exception as e:
                logger.error(f"Error procesando {temp_path_str}: {e}")
        
        self.last_cleanup = current_time
        logger.info(f"Limpieza completada. Eliminados: {removed_count}")
        return removed_count

    def start_cleanup_thread(self):
        """Inicia el hilo de limpieza automática"""
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.stop_cleanup.clear()
            self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
            self.cleanup_thread.start()
            logger.info("Hilo de limpieza automática iniciado")

    def stop_cleanup_thread(self):
        """Detiene el hilo de limpieza automática"""
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.stop_cleanup.set()
            self.cleanup_thread.join(timeout=5)
            logger.info("Hilo de limpieza automática detenido")

    def _cleanup_worker(self):
        """Worker thread para limpieza automática"""
        while not self.stop_cleanup.is_set():
            try:
                # Recargar configuración
                self._load_config()
                
                current_time = time.time()
                time_since_cleanup = current_time - self.last_cleanup
                
                # Ejecutar limpieza si:
                # 1. Es la primera vez (last_cleanup = 0)
                # 2. Ha pasado el intervalo configurado
                if self.last_cleanup == 0 or time_since_cleanup >= self.cleanup_interval:
                    logger.info("Iniciando limpieza programada")
                    self.cleanup_old_files()
                
                # Esperar hasta el próximo intervalo o señal de parada
                self.stop_cleanup.wait(min(60, self.cleanup_interval / 4))
                
            except Exception as e:
                logger.error(f"Error en hilo de limpieza: {e}")
                self.stop_cleanup.wait(60)  # Esperar 1 minuto antes de reintentar

    def get_status(self):
        """Obtiene el estado actual del gestor"""
        with self.lock:
            config = self._load_config()
            current_time = time.time()
            
            status = {
                "registered_files": len(self.temp_files),
                "cleanup_interval": config.get("TEMP_CLEANUP_INTERVAL", 1800),
                "max_age": config.get("TEMP_FILE_MAX_AGE", 1800),
                "last_cleanup": self.last_cleanup,
                "time_since_last_cleanup": current_time - self.last_cleanup,
                "cleanup_thread_active": self.cleanup_thread and self.cleanup_thread.is_alive(),
                "files": []
            }
            
            for temp_path, last_access in self.temp_files.items():
                path_obj = Path(temp_path)
                status["files"].append({
                    "path": temp_path,
                    "exists": path_obj.exists(),
                    "last_access": last_access,
                    "age": current_time - last_access,
                    "size": path_obj.stat().st_size if path_obj.exists() else 0
                })
            
            return status

    def force_cleanup(self):
        """Fuerza una limpieza inmediata"""
        logger.info("Forzando limpieza de archivos temporales...")
        return self.cleanup_old_files()

    def __del__(self):
        """Destructor: detiene el hilo de limpieza"""
        self.stop_cleanup_thread()