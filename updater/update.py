from flask import Blueprint, render_template, flash, redirect, url_for, jsonify
from src.auth_utils import login_required
from updater.functions import check_git_update, get_changelog, do_git_pull_and_restart, get_remote_commit_info
import threading

update_api_bp = Blueprint('update_api', __name__)
    
@update_api_bp.route('/update/check')
@login_required
def api_check_update():
    """API para verificar si hay actualizaciones disponibles"""
    has_update, commit_info = check_git_update()
    result = {
        "update_available": has_update,
        "message": list(get_remote_commit_info().get("message").splitlines())
    }
    return jsonify(result)  
 
@update_api_bp.route('/update/info')
@login_required
def api_update_info():
    """API para obtener información de actualización"""
    return jsonify({'commit_info': get_remote_commit_info()})

@update_api_bp.route('/changelog')
@login_required
def api_changelog():
    """API para obtener changelog"""
    return jsonify({'changelog': get_changelog()})

@update_api_bp.route('/update', methods=['POST'])
@login_required
def update():
    has_update, commit_info = check_git_update()
    
    if not has_update:
        return jsonify({
            "status": "error",
            "message": "No updates available at this moment."
        }), 400
    
    threading.Thread(target=do_git_pull_and_restart).start()
    
    return jsonify({
        "status": "success",
        "message": "Update started. The server will restart shortly.",
        "commit": commit_info
    }), 200