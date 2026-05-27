from flask import redirect, request, session, url_for
import contextlib

def login_required(func):
    """Decorador para proteger rutas que requieren autenticación."""
    @contextlib.wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("auth.login", next=request.url))
        return func(*args, **kwargs)
    return wrapper