"""
DAV → MP4 Streaming Server
===========================
Estrategia: REMUX (sin recodificar) usando PyAV.
- Copia streams de video/audio bit a bit al contenedor MP4.
- No hay transcodificación: es ~100x más rápido que recodificar.
- Soporta HTTP Range Requests para seeking en el navegador.
- Soporta estructura de carpetas por dispositivo/IP (Dahua DVR).
"""

import os
import io
import re
import json
import threading
import tempfile
import hashlib
import time
import hmac
from datetime import datetime
from pathlib import Path
from flask import (
    Flask, render_template, request, Response,
    jsonify, abort, redirect, url_for, flash, session
)
from werkzeug.security import check_password_hash
from src import logger_instance, config_instance
from routes import all_blueprints
from src import login_required
from src import VIDEOS_DIR, CACHE_DIR, ALLOWED
from src.scanner import _scan_devices

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — cargada desde config.json
# ─────────────────────────────────────────────────────────────────────────────

config_instance.load_config()

app = Flask(__name__)
app.secret_key = (
    os.environ.get("SECRET_KEY")
    or config_instance.get("server.secret_key")
    or "dev-secret"
)
app.config["MAX_CONTENT_LENGTH"] = config_instance.get("server.max_upload_gb", 4) * 1024 ** 3


@app.context_processor
def _inject_user_context():
    return {"username": session.get("username")}

for bp in all_blueprints:
    app.register_blueprint(bp)

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR,  exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# CORE: Remux DAV → MP4 usando PyAV (sin recodificación)
# ─────────────────────────────────────────────────────────────────────────────

def _add_output_stream(output_container, input_stream):
    """
    Copia parámetros del input al output.
    Ignora audio incompatible (pcm_alaw causa Error 22 en MP4).
    """
    s   = input_stream
    ctx = s.codec_context

    if s.type != "video":
        return None

    out_s        = output_container.add_stream(ctx.name)
    out_s.width  = s.width
    out_s.height = s.height

    if s.pix_fmt:        out_s.pix_fmt   = s.pix_fmt
    if s.time_base:      out_s.time_base = s.time_base
    if s.average_rate:   out_s.rate      = s.average_rate

    if ctx.extradata:
        out_s.codec_context.extradata = ctx.extradata

    return out_s


def _remux(input_path: str, output_path: str) -> None:
    """
    Remuxea input → output MP4.
    Maneja timestamps rotos (dts/pts) nativos de los DVRs Dahua.
    """
    import av
    with av.open(input_path) as inp:
        with av.open(output_path, "w", format="mp4",
                     options={"movflags": "faststart"}) as out:

            stream_map: dict[int, object] = {}
            for s in inp.streams:
                out_s = _add_output_stream(out, s)
                if out_s:
                    stream_map[s.index] = out_s

            if not stream_map:
                raise ValueError(
                    "No se encontraron streams de video compatibles en el archivo"
                )

            streams_to_demux = [s for s in inp.streams if s.index in stream_map]
            last_dts = -1

            for packet in inp.demux(*streams_to_demux):
                if packet.dts is None:
                    continue

                if packet.dts < 0:
                    packet.dts = 0
                if packet.dts <= last_dts:
                    packet.dts = last_dts + 1
                if packet.pts is None or packet.pts < packet.dts:
                    packet.pts = packet.dts

                last_dts = packet.dts

                out_s = stream_map.get(packet.stream_index)
                if out_s is None:
                    continue
                packet.stream = out_s
                try:
                    out.mux(packet)
                except Exception:
                    pass

def _remux_streaming(input_path: str):
    """
    Generador que remuxea mientras envía chunks al cliente.
    Escribe a un archivo temporal y lee en paralelo.
    """
    tmp      = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = tmp.name
    tmp.close()

    done_event   = threading.Event()
    error_holder: list = []

    def _worker():
        try:
            _remux(input_path, tmp_path)
        except Exception as e:
            error_holder.append(e)
        finally:
            done_event.set()

    threading.Thread(target=_worker, daemon=True).start()

    CHUNK = 65536
    with open(tmp_path, "rb") as f:
        while not done_event.is_set():
            chunk = f.read(CHUNK)
            if chunk:
                yield chunk
            else:
                time.sleep(0.01)
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            yield chunk

    try:
        os.unlink(tmp_path)
    except Exception:
        pass

    if error_holder:
        raise error_holder[0]

def get_or_create_mp4(dav_path: str) -> str:
    """
    Retorna la ruta a un MP4 cacheado. Si no existe, lo crea.
    La clave de caché incluye path + mtime + size.
    """
    stat = os.stat(dav_path)
    key  = hashlib.md5(
        f"{dav_path}:{stat.st_mtime}:{stat.st_size}".encode()
    ).hexdigest()
    mp4_path = os.path.join(CACHE_DIR, f"{key}.mp4")

    if not os.path.exists(mp4_path):
        tmp_path = mp4_path + ".tmp"
        try:
            _remux(dav_path, tmp_path)
            os.rename(tmp_path, mp4_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    return mp4_path

def cleanup_old_videos(days: int = 7) -> dict:
    """
    Borra archivos en VIDEOS_DIR con antiguedad mayor a X dias.
    Retorna conteos de eliminados y errores.
    """
    cutoff = time.time() - (days * 86400)
    deleted = 0
    errors = 0

    base = Path(VIDEOS_DIR)
    if not base.exists():
        return {"deleted": 0, "errors": 0}

    for f in base.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in ALLOWED:
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except Exception as e:
            errors += 1
            logger_instance.error("app", f"No se pudo borrar {f}: {e}")

    logger_instance.info("app", f"Limpieza videos >{days} dias: {deleted} borrados, {errors} errores")
    return {"deleted": deleted, "errors": errors}


_cleanup_stop_event = threading.Event()
_cleanup_thread = None


def start_cleanup_scheduler(interval_minutes: int = 60, days: int = 7) -> None:
    """
    Inicia un hilo en segundo plano que limpia videos cada cierto tiempo.
    """
    global _cleanup_thread

    if interval_minutes <= 0:
        logger_instance.info("app", "Limpieza programada deshabilitada (intervalo <= 0)")
        return

    if _cleanup_thread and _cleanup_thread.is_alive():
        return

    def _loop():
        logger_instance.info(
            "app",
            f"Limpieza programada cada {interval_minutes} min (retencion {days} dias)",
        )
        while not _cleanup_stop_event.wait(interval_minutes * 60):
            try:
                cleanup_old_videos(days=days)
            except Exception as e:
                logger_instance.error("app", f"Error limpieza programada: {e}")

    _cleanup_thread = threading.Thread(target=_loop, daemon=True)
    _cleanup_thread.start()


_login_attempts: dict[str, list[float]] = {}


def _get_client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _get_auth_users() -> list[dict]:
    users = config_instance.get("auth.users", [])
    return users if isinstance(users, list) else []


def _find_auth_user(username: str) -> dict | None:
    for user in _get_auth_users():
        if user.get("username") == username:
            return user
    return None


def _verify_password(user: dict, password: str) -> bool:
    password_hash = user.get("password_hash")
    if password_hash:
        return check_password_hash(password_hash, password)
    stored = user.get("password", "")
    return hmac.compare_digest(stored, password)


def _record_failed_attempt(ip: str) -> None:
    now = time.time()
    attempts = _login_attempts.setdefault(ip, [])
    attempts.append(now)
    cutoff = now - 900
    _login_attempts[ip] = [t for t in attempts if t > cutoff]


def _is_blocked(ip: str) -> bool:
    max_attempts = int(config_instance.get("security.max_login_attempts", 5))
    now = time.time()
    cutoff = now - 900
    recent = [t for t in _login_attempts.get(ip, []) if t > cutoff]
    return len(recent) >= max_attempts


def _clear_attempts(ip: str) -> None:
    _login_attempts.pop(ip, None)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Range Request support
# ─────────────────────────────────────────────────────────────────────────────

def stream_file_with_ranges(file_path: str, mimetype: str = "video/mp4") -> Response:
    """
    Sirve un archivo con soporte completo de HTTP Range Requests.
    Necesario para que el <video> del navegador pueda hacer seeking.
    """
    file_size    = os.path.getsize(file_path)
    range_header = request.headers.get("Range")

    if range_header:
        byte_range = range_header.replace("bytes=", "").split("-")
        start  = int(byte_range[0]) if byte_range[0] else 0
        end    = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1
        end    = min(end, file_size - 1)
        length = end - start + 1

        def _gen_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return Response(
            _gen_range(),
            status=206,
            headers={
                "Content-Range":  f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges":  "bytes",
                "Content-Length": str(length),
                "Content-Type":   mimetype,
            },
        )

    def _gen_full():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                yield chunk

    return Response(
        _gen_full(),
        status=200,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges":  "bytes",
            "Content-Type":   mimetype,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# RUTAS FLASK — existentes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    """Recibe un .dav (o cualquier video) y lo guarda en disco."""
    if "file" not in request.files:
        return jsonify({"error": "No se envió archivo"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    ext     = Path(f.filename).suffix.lower()
    allowed = {".dav", ".mp4", ".avi", ".mkv", ".ts", ".mov"}
    if ext not in allowed:
        return jsonify({
            "error": f"Extensión '{ext}' no soportada. Use: {', '.join(allowed)}"
        }), 400

    safe_name = f"{int(time.time())}_{Path(f.filename).stem}{ext}"
    save_path = os.path.join(VIDEOS_DIR, safe_name)
    f.save(save_path)

    return jsonify({
        "success":      True,
        "filename":     safe_name,
        "size":         os.path.getsize(save_path),
        "stream_url":   f"/stream/{safe_name}",
        "download_url": f"/download/{safe_name}",
    })


@app.route("/stream/<path:filepath>")
@login_required
def stream_video(filepath):
    """
    Stream del video convertido a MP4.
    Acepta tanto nombres planos ('video.dav') como rutas con subcarpeta
    ('192.168.0.33/20250125_120000.dav').

    Query params:
      ?mode=cache  (default) — convierte completo, sirve con Range Requests.
      ?mode=live             — stream durante la conversión.
    """
    from urllib.parse import unquote
    
    # Decodificar URL encoding si lo hay
    filepath = unquote(filepath)
    
    dav_path = os.path.join(VIDEOS_DIR, filepath)
    logger_instance.info("app", f"Stream request: {filepath} -> {dav_path}")
    
    if not os.path.exists(dav_path):
        logger_instance.error("app", f"Archivo no encontrado: {dav_path}")
        return jsonify({
            "error": f"Archivo no encontrado: {filepath}",
            "requested_path": filepath,
            "resolved_path": dav_path
        }), 404

    mode = request.args.get("mode", "cache")

    if mode == "live":
        return Response(
            _remux_streaming(dav_path),
            mimetype="video/mp4",
            headers={
                "Content-Disposition": (
                    f'inline; filename="{Path(filepath).stem}.mp4"'
                ),
                "Cache-Control": "no-cache",
            },
        )

    try:
        logger_instance.info("app", f"Convirtiendo a MP4: {dav_path}")
        mp4_path = get_or_create_mp4(dav_path)
        logger_instance.info("app", f"MP4 listo: {mp4_path}")
        return stream_file_with_ranges(mp4_path)
    except Exception as e:
        logger_instance.error("app", f"Error convirtiendo {dav_path}: {str(e)}")
        return jsonify({
            "error": f"Error convirtiendo: {str(e)}",
            "file": filepath
        }), 500


@app.route("/download/<path:filepath>")
@login_required
def download_mp4(filepath):
    """Descarga directa del MP4 convertido."""
    dav_path = os.path.join(VIDEOS_DIR, filepath)
    if not os.path.exists(dav_path):
        abort(404)

    try:
        mp4_path = get_or_create_mp4(dav_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    stem = Path(filepath).stem

    def _gen():
        with open(mp4_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                yield chunk

    return Response(
        _gen(),
        mimetype="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.mp4"',
            "Content-Length":      str(os.path.getsize(mp4_path)),
        },
    )


@app.route("/status/<path:filepath>")
@login_required
def file_status(filepath):
    """Info del archivo: codec, resolución, duración, FPS."""
    dav_path = os.path.join(VIDEOS_DIR, filepath)
    if not os.path.exists(dav_path):
        return jsonify({"error": "Archivo no encontrado"}), 404

    try:
        import av
        info: dict = {
            "filename":   filepath,
            "size_bytes": os.path.getsize(dav_path),
            "streams":    [],
        }
        with av.open(dav_path) as c:
            info["duration_sec"] = float(c.duration / 1e6) if c.duration else None
            for s in c.streams:
                if s.type == "video":
                    info["streams"].append({
                        "type":   "video",
                        "codec":  s.codec_context.name,
                        "width":  s.width,
                        "height": s.height,
                        "fps":    float(s.average_rate) if s.average_rate else None,
                    })
                elif s.type == "audio":
                    info["streams"].append({
                        "type":        "audio",
                        "codec":       s.codec_context.name,
                        "sample_rate": s.sample_rate,
                        "channels":    s.channels,
                    })
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/files")
@login_required
def list_files():
    """
    Lista archivos planos en el directorio raíz de videos (compatibilidad).
    Para la vista por dispositivo usa /api/devices.
    """
    files  = []
    base   = Path(VIDEOS_DIR)
    for f in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in ALLOWED:
            files.append({
                "name":         f.name,
                "size":         f.stat().st_size,
                "stream_url":   f"/stream/{f.name}",
                "download_url": f"/download/{f.name}",
            })
    return jsonify(files)


# ─────────────────────────────────────────────────────────────────────────────
# RUTAS FLASK — nuevas (dispositivos, fecha, playlist)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/devices")
@login_required
def api_devices():
    """
    Lista todos los dispositivos con sus archivos y metadatos de fecha/hora.
    Cada subcarpeta de videos_dir se trata como un dispositivo.
    """
    return jsonify(_scan_devices())


@app.route("/api/files/by-date")
@login_required
def api_files_by_date():
    """
    Retorna archivos de todos los dispositivos agrupados por fecha.

    Query params opcionales:
      ?date=2025-01-25   → filtra por fecha
      ?ip=192.168.0.33   → filtra por dispositivo
    """
    date_filter = request.args.get("date")
    ip_filter   = request.args.get("ip")

    devices = _scan_devices()
    # { "2025-01-25": { "192.168.0.33": [files...] } }
    result: dict = {}

    for ip, dev in devices.items():
        if ip_filter and ip != ip_filter:
            continue
        for f in dev["files"]:
            date = f.get("date", "unknown")
            if date_filter and date != date_filter:
                continue
            result.setdefault(date, {}).setdefault(ip, []).append(f)

    return jsonify(result)


@app.route("/api/playlist/day")
@login_required
def api_playlist_day():
    """
    Genera una playlist M3U8 para todas las horas de un dispositivo en un día.
    Parámetros requeridos: ?ip=192.168.0.33&date=2025-01-25
    """
    ip   = request.args.get("ip")
    date = request.args.get("date")

    if not ip or not date:
        return jsonify({"error": "Parámetros requeridos: ip y date"}), 400

    devices = _scan_devices()
    dev     = devices.get(ip)
    if not dev:
        return jsonify({"error": f"Dispositivo '{ip}' no encontrado"}), 404

    day_files = sorted(
        [f for f in dev["files"] if f.get("date") == date],
        key=lambda f: f.get("hour", 0),
    )
    if not day_files:
        return jsonify({
            "error": f"Sin archivos para {ip} en {date}"
        }), 404

    seg_dur = config_instance.get("hls.segment_duration", 6)
    lines   = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{seg_dur}",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    for f in day_files:
        lines.append(f"#EXTINF:{float(seg_dur):.6f},")
        lines.append(f"/stream/{f['path']}")
    lines.append("#EXT-X-ENDLIST")

    return Response(
        "\n".join(lines),
        mimetype="application/vnd.apple.mpegurl",
        headers={
            "Content-Disposition": (
                f'inline; filename="{ip.replace(".", "_")}_{date}.m3u8"'
            )
        },
    )


@app.route("/api/config")
@login_required
def api_config():
    """Expone la configuración pública (sin datos sensibles) al frontend."""
    return jsonify({
        "devices":           config_instance.get("devices", {}),
        "filename_patterns": list(config_instance.get("filename_patterns", {}).keys()),
        "storage": {
            "allowed_extensions": list(ALLOWED),
        },
    })


@app.route("/api/version")
def api_version():
    return jsonify({
        "version": config_instance.get("app.version", "0.0.0"),
        "update_manifest_url": config_instance.get("app.update_manifest_url", ""),
    })


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"ok": False, "error": "Credenciales incompletas"}), 400

    if not _get_auth_users():
        return jsonify({"ok": False, "error": "Sin usuarios configurados"}), 503

    ip = _get_client_ip()
    if _is_blocked(ip):
        return jsonify({"ok": False, "error": "Demasiados intentos"}), 429

    user = _find_auth_user(username)
    if not user or not _verify_password(user, password):
        _record_failed_attempt(ip)
        return jsonify({"ok": False, "error": "Usuario o contraseña inválidos"}), 401

    _clear_attempts(ip)
    session["logged_in"] = True
    session["username"] = username

    return jsonify({"ok": True, "user": {"username": username}})


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────────────────────
# RUTAS AJAX — Configuración (Settings)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/config/current")
@login_required
def api_config_current():
    """
    Retorna la configuración actual completa.
    Usado por la página de settings para rellenar formularios.
    """
    return jsonify({
        "ok": True,
        "config": {
            "storage": config_instance.get("storage", {}),
            "server": config_instance.get("server", {}),
            "devices": config_instance.get("devices", {}),
            "hls": config_instance.get("hls", {}),
        }
    })


@app.route("/api/config/update", methods=["POST"])
@login_required
def api_config_update():
    """
    Actualiza valores de configuración.
    Body esperado: { "key": "server.port", "value": 5000 }
    o { "section": "server", "data": { "port": 5000, ... } }
    """
    try:
        data = request.get_json() or {}
        
        # Actualizar campo individual
        if "key" in data and "value" in data:
            key = data["key"]
            value = data["value"]
            if key.startswith("devices.") and key.endswith(".alias"):
                ip = key[len("devices."):-len(".alias")]
                devices = config_instance.get("devices", {})
                devices.setdefault(ip, {})["alias"] = value
                config_instance.modify_value("devices", devices)
            else:
                config_instance.set(key, value)
            logger_instance.info("app", f"Config actualizada: {key} = {value}")
            return jsonify({"ok": True, "message": "Configuración actualizada"})
        
        # Actualizar sección completa
        if "section" in data and "data" in data:
            for key, value in data["data"].items():
                config_instance.set(f"{data['section']}.{key}", value)
            logger_instance.info("app", f"Sección '{data['section']}' actualizada")
            return jsonify({"ok": True, "message": f"Sección {data['section']} actualizada"})
        
        return jsonify({"ok": False, "error": "Parámetros inválidos"}), 400
    
    except Exception as e:
        logger_instance.error("app", f"Error actualizando config: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/video-check/<path:filepath>")
@login_required
def check_video(filepath):
    """
    Verifica que un archivo existe y es accesible.
    Útil para debugging de problemas de streaming.
    """
    from urllib.parse import unquote
    filepath = unquote(filepath)
    dav_path = os.path.join(VIDEOS_DIR, filepath)
    
    exists = os.path.exists(dav_path)
    is_file = os.path.isfile(dav_path) if exists else False
    file_size = os.path.getsize(dav_path) if is_file else None
    readable = os.access(dav_path, os.R_OK) if exists else False
    
    logger_instance.info("app", f"Check: {filepath} -> exists={exists}, is_file={is_file}, size={file_size}, readable={readable}")
    
    return jsonify({
        "filepath": filepath,
        "full_path": dav_path,
        "exists": exists,
        "is_file": is_file,
        "file_size": file_size,
        "readable": readable,
        "stream_url": f"/stream/{filepath}" if is_file else None
    })


@app.route("/settings")
@login_required
def settings_page():
    """
    Renderiza la página de configuración con formularios AJAX.
    """
    return render_template(
        "settings.html",
        server=config_instance.get("server", {}),
        storage=config_instance.get("storage", {}),
        hls=config_instance.get("hls", {}),
        devices=config_instance.get("devices", {}),
    )


@app.post("/settings/update/<section>")
@login_required
def settings_update(section):
    """
    Actualiza secciones de configuración desde formularios HTML.
    """
    try:
        if section == "server":
            host = request.form.get("host", "0.0.0.0")
            port = int(request.form.get("port", 5000))
            debug = request.form.get("debug") == "on"
            max_upload_gb = int(request.form.get("max_upload_gb", 4))
            config_instance.set("server.host", host)
            config_instance.set("server.port", port)
            config_instance.set("server.debug", debug)
            config_instance.set("server.max_upload_gb", max_upload_gb)
        elif section == "storage":
            videos_dir = request.form.get("videos_dir", "dahua_videos")
            cache_dir = request.form.get("cache_dir", "cache")
            ext_raw = request.form.get("allowed_extensions", ".dav, .mp4, .avi, .mkv")
            exts = [e.strip() for e in ext_raw.split(",") if e.strip()]
            config_instance.set("storage.videos_dir", videos_dir)
            config_instance.set("storage.cache_dir", cache_dir)
            config_instance.set("storage.allowed_extensions", exts)
        elif section == "hls":
            segment_duration = int(request.form.get("segment_duration", 3600))
            config_instance.set("hls.segment_duration", segment_duration)
        else:
            flash("Sección inválida", "error")
            return redirect(url_for("settings_page"))

        flash("Configuración actualizada", "success")
    except Exception as e:
        logger_instance.error("app", f"Error actualizando {section}: {e}")
        flash(f"Error actualizando {section}", "error")

    return redirect(url_for("settings_page"))


@app.post("/settings/device-alias")
@login_required
def settings_device_alias():
    """
    Actualiza el alias de un dispositivo desde settings.
    """
    try:
        ip = request.form.get("ip", "").strip()
        alias = request.form.get("alias", "").strip()
        if not ip:
            flash("IP inválida", "error")
            return redirect(url_for("settings_page"))

        if not alias:
            alias = ip

        devices = config_instance.get("devices", {})
        devices.setdefault(ip, {})["alias"] = alias
        config_instance.modify_value("devices", devices)
        flash("Alias actualizado", "success")
    except Exception as e:
        logger_instance.error("app", f"Error actualizando alias: {e}")
        flash("Error actualizando alias", "error")

    return redirect(url_for("settings_page"))

# ─────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    srv = config_instance.get("server", {})
    maint_enabled = config_instance.get("maintenance.cleanup_enabled", True)
    maint_days = int(config_instance.get("maintenance.cleanup_days", 7))
    maint_interval = int(config_instance.get("maintenance.cleanup_interval_minutes", 60))

    if maint_enabled:
        if not srv.get("debug", True) or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            start_cleanup_scheduler(interval_minutes=maint_interval, days=maint_days)

    logger_instance.info("app", "Iniciando servidor...")
    logger_instance.info("app", f"  http://{srv.get('host','0.0.0.0')}:{srv.get('port',5000)}")
    logger_instance.info("app", f"  Videos : {VIDEOS_DIR}/")
    logger_instance.info("app", f"  Caché  : {CACHE_DIR}/")
    app.run(
        debug=srv.get("debug", True),
        threaded=True,
        host=srv.get("host", "0.0.0.0"),
        port=srv.get("port", 5000),
    )