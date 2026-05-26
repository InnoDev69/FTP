import json
from .logger import logger_instance

class ConfigManager:
    def __init__(self, config_file):
        self.config_file = config_file
        self.config_data = {}

    def load_config(self):
        """Cargar configuración desde el archivo JSON"""
        try:
            with open(self.config_file, 'r') as f:
                self.config_data = json.load(f)
        except FileNotFoundError:
            logger_instance.warning(f"Archivo de configuración '{self.config_file}' no encontrado. Usando valores por defecto.")
            self.config_data = {}
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