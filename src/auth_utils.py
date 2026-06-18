from flask import redirect, render_template, session, url_for
import contextlib

def login_required(func):
    """Decorador para proteger rutas que requieren autenticación."""
    @contextlib.wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return render_template("login.html", error = "Debe iniciar sesión para acceder a esta página.")
        return func(*args, **kwargs)
    return wrapper