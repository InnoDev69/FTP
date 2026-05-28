from flask import redirect, session, url_for
import contextlib

def login_required(func):
    """Decorador para proteger rutas que requieren autenticación."""
    @contextlib.wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper