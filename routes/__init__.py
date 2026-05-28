from .index import main_bp
from .auth import auth_bp
from .player import player_bp
from updater.update import update_api_bp

all_blueprints = [
    main_bp,
    auth_bp,
    player_bp,
    update_api_bp,
]

