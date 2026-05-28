from .config import config_instance

config_instance.load_config()

VIDEOS_DIR = config_instance.get("storage.videos_dir", "dahua_videos")
CACHE_DIR  = config_instance.get("storage.cache_dir", "cache")
ALLOWED    = set(config_instance.get("storage.allowed_extensions", [".dav", ".mp4", ".avi", ".mkv"]))