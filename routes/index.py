from flask import Blueprint, render_template, request, redirect, url_for, session
from src.auth_utils import login_required

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    stats = {
        "total": 0,
        "new_count": 0,
        "converted_count": 0,
        "devices": 0,
        "channels": 0,
        "total_size": 0,
    }
    return render_template('dashboard.html', stats=stats)