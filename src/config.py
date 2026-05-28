import json
from .logger import logger_instance
from .constants import CONFIG_FILE

class ConfigManager:
    def __init__(self, config_file):
        self.config_file = config_file
        self.config_data = {}

    def _default_config(self):
        return {
            "storage": {
                "videos_dir": "dahua_videos",
                "cache_dir": "cache",
                "allowed_extensions": [".dav", ".mp4", ".avi", ".mkv"],
                "device_dirs": "auto",
                "filename_pattern": "dahua_standard",
            },
            "devices": {},
            "filename_patterns": {
                "dahua_site_channel": (
                    r"^(?P<site>[^_]+)_(?P<channel>ch\d+)_(?P<stream>[^_]+)_"
                    r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_"
                    r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})_"
                    r"\d{8}_(?P<end_hour>\d{2})(?P<end_minute>\d{2})(?P<end_second>\d{2})"
                ),
                "dahua_standard": (
                    r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"
                    r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
                ),
                "dahua_alternate": (
                    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})_"
                    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})"
                ),
            },
            "hls": {
                "segment_duration": 3600,
            },
            "server": {
                "host": "0.0.0.0",
                "port": 5000,
                "debug": True,
                "max_upload_gb": 4,
            },
            "app": {
                "version": "1.0.0",
                "update_manifest_url": "",
            },
            "auth": {
                "users": [
                    { "username": "admin", "password": "1234" }
                ]
            },
            "security": {
                "max_login_attempts": 5
            }
        }

    def load_config(self):
        """Cargar configuración desde el archivo JSON"""
        try:
            with open(self.config_file, 'r') as f:
                self.config_data = json.load(f)
        except FileNotFoundError:
            logger_instance.warning(
                f"Archivo de configuración '{self.config_file}' no encontrado. Creando valores por defecto."
            )
            self.config_data = self._default_config()
            self.save_config()
        except json.JSONDecodeError as e:
            logger_instance.error(f"Error al parsear el archivo de configuración: {e}")
            self.config_data = {}
    
    def get(self, key, default=None):
        """Obtener un valor de configuración con un valor por defecto con acceso anidado"""
        keys = key.split('.')
        value = self.config_data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value
    
    def get_section(self, section):
        """Obtener una sección completa de la configuración"""
        return self.config_data.get(section, {})
    
    def set(self, key, value):
        """Establecer un valor de configuración con acceso anidado"""
        keys = key.split('.')
        d = self.config_data
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        self.save_config()

    def modify_value(self, key, value):
        """Modificar un valor de configuración y guardarlo en el archivo"""
        self.config_data[key] = value
        self.save_config()
    
    def modify_all(self, new_config):
        """Reemplazar toda la configuración y guardarla en el archivo"""
        self.config_data = new_config
        self.save_config()
        
    def save_config(self):
        """Guardar la configuración actual en el archivo JSON"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            logger_instance.error(f"Error al guardar la configuración: {e}")
        
config_instance = ConfigManager(CONFIG_FILE)