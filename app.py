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
from datetime import datetime
from pathlib import Path
from flask import (
    Flask, render_template, request, Response,
    jsonify, abort
)
from src import logger_instance, config_instance
from routes import all_blueprints

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — cargada desde config.json
# ─────────────────────────────────────────────────────────────────────────────

config_instance.load_config()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config_instance.get("server.max_upload_gb", 4) * 1024 ** 3

for bp in all_blueprints:
    app.register_blueprint(bp)

_VIDEOS_DIR = config_instance.get("storage.videos_dir", "dahua_videos")
_CACHE_DIR  = config_instance.get("storage.cache_dir", "cache")
_ALLOWED    = set(config_instance.get("storage.allowed_extensions", [".dav", ".mp4", ".avi", ".mkv"]))

os.makedirs(_VIDEOS_DIR, exist_ok=True)
os.makedirs(_CACHE_DIR,  exist_ok=True)


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
    mp4_path = os.path.join(_CACHE_DIR, f"{key}.mp4")

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

# ─────────────────────────────────────────────────────────────────────────────
# ESCANEO DE DISPOSITIVOS Y PARSEO DE NOMBRES DE ARCHIVO
# ─────────────────────────────────────────────────────────────────────────────

def _parse_filename_datetime(filename: str) -> dict | None:
    """
    Extrae fecha, hora y metadatos del nombre del archivo .dav.

    Formato real Dahua:
        COLONIAL_ch1_main_20260507_000000_20260507_010000
        → site=COLONIAL, channel=ch1, stream=main
        → start=2026-05-07 00:00  end=2026-05-07 01:00

    Retorna dict con claves datetime/date/hour/hour_label y opcionales
    site/channel/stream/end_label, o None si no matchea ningún patrón.
    """
    patterns = config_instance.get("filename_patterns", {})
    for pattern_name, pattern in patterns.items():
        m = re.search(pattern, filename)
        if m:
            g = m.groupdict()
            try:
                dt = datetime(
                    int(g["year"]), int(g["month"]), int(g["day"]),
                    int(g["hour"]),
                    int(g.get("minute", 0)),
                    int(g.get("second", 0)),
                )
                result = {
                    "datetime":     dt.isoformat(),
                    "date":         dt.strftime("%Y-%m-%d"),
                    "hour":         dt.hour,
                    "hour_label":   dt.strftime("%H:%M"),
                    "pattern_used": pattern_name,
                }
                # Campos opcionales presentes en dahua_site_channel
                if g.get("site"):
                    result["site"] = g["site"]
                if g.get("channel"):
                    result["channel"] = g["channel"]
                if g.get("stream"):
                    result["stream"] = g["stream"]
                # Hora de fin → label "00:00 – 01:00"
                if g.get("end_hour") is not None:
                    try:
                        end_dt = datetime(
                            int(g["year"]), int(g["month"]), int(g["day"]),
                            int(g["end_hour"]),
                            int(g.get("end_minute", 0)),
                            int(g.get("end_second", 0)),
                        )
                        result["end_label"]  = end_dt.strftime("%H:%M")
                        result["hour_label"] = f"{dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"
                    except ValueError:
                        pass
                return result
            except ValueError:
                continue
    return None

def _save_new_device(ip, alias="", location=""):
    """Guardar nuevo dispositivo en config.json si no existe"""
    devices = config_instance.get("devices", {})
    if ip not in devices:
        devices[ip] = {"alias": alias or ip, "location": location}
        config_instance.set("devices", devices)
        logger_instance.info("app",f"Nuevo dispositivo agregado: {ip} (alias: {alias}, location: {location})")

def _scan_devices() -> dict:
    """
    Escanea videos_dir buscando subcarpetas que representen dispositivos (IPs).
    Estructura de retorno:
    {
      "192.168.0.33": {
        "ip": "...", "alias": "...", "location": "...",
        "files": [ { path, name, size, datetime, date, hour, ... }, ... ],
        "total": N
      }, ...
    }
    """
    base    = Path(_VIDEOS_DIR)
    devices = config_instance.get("devices", {})
    result  = {}

    if not base.exists():
        return result

    for device_dir in sorted(base.iterdir()):
        if not device_dir.is_dir():
            continue

        ip          = device_dir.name
        
        if ip not in devices:
            _save_new_device(ip)
            devices = config_instance.get("devices", {})  # Recargar después de guardar
        
        device_info = devices.get(ip, {})
        files       = []

        for f in sorted(device_dir.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in _ALLOWED:
                continue

            rel  = str(f.relative_to(base))
            meta = _parse_filename_datetime(f.name) or {}

            files.append({
                "name":            f.name,
                "path":            rel,
                "size":            f.stat().st_size,
                "modified":        f.stat().st_mtime,
                "device_ip":       ip,
                "device_alias":    device_info.get("alias", ip),
                "device_location": device_info.get("location", ""),
                **meta,
            })

        result[ip] = {
            "ip":       ip,
            "alias":    device_info.get("alias", ip),
            "location": device_info.get("location", ""),
            "files":    files,
            "total":    len(files),
        }

    return result


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
    save_path = os.path.join(_VIDEOS_DIR, safe_name)
    f.save(save_path)

    return jsonify({
        "success":      True,
        "filename":     safe_name,
        "size":         os.path.getsize(save_path),
        "stream_url":   f"/stream/{safe_name}",
        "download_url": f"/download/{safe_name}",
    })


@app.route("/stream/<path:filepath>")
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
    
    dav_path = os.path.join(_VIDEOS_DIR, filepath)
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
def download_mp4(filepath):
    """Descarga directa del MP4 convertido."""
    dav_path = os.path.join(_VIDEOS_DIR, filepath)
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
def file_status(filepath):
    """Info del archivo: codec, resolución, duración, FPS."""
    dav_path = os.path.join(_VIDEOS_DIR, filepath)
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
def list_files():
    """
    Lista archivos planos en el directorio raíz de videos (compatibilidad).
    Para la vista por dispositivo usa /api/devices.
    """
    files  = []
    base   = Path(_VIDEOS_DIR)
    for f in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in _ALLOWED:
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
def api_devices():
    """
    Lista todos los dispositivos con sus archivos y metadatos de fecha/hora.
    Cada subcarpeta de videos_dir se trata como un dispositivo.
    """
    return jsonify(_scan_devices())


@app.route("/api/files/by-date")
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
def api_config():
    """Expone la configuración pública (sin datos sensibles) al frontend."""
    return jsonify({
        "devices":           config_instance.get("devices", {}),
        "filename_patterns": list(config_instance.get("filename_patterns", {}).keys()),
        "storage": {
            "allowed_extensions": list(_ALLOWED),
        },
    })


@app.route("/player")
def player():
    """
    Renderiza la página del reproductor con lista de videos disponibles.
    Los videos se obtienen recursivamente desde el directorio de videos.
    """
    videos = []
    
    def scan_dir(directory, prefix=""):
        """Escanea recursivamente buscando archivos de video."""
        try:
            for item in sorted(Path(directory).iterdir(), reverse=True):
                if item.is_file() and item.suffix.lower() in _ALLOWED:
                    rel_path = str(item.relative_to(_VIDEOS_DIR)) if prefix == "" else f"{prefix}/{item.name}"
                    
                    videos.append({
                        "id":              len(videos),
                        "filename":        item.name,
                        "path":            rel_path,
                        "device_id":       prefix if prefix else "local",
                        "channel_id":      "1",
                        "recording_date":  item.stat().st_mtime,
                        "resolution":      "1920x1080",
                        "file_size":       item.stat().st_size,
                        "conv_status":     "done",
                    })
                elif item.is_dir() and prefix == "":
                    scan_dir(item, prefix=item.name)
        except Exception as e:
            logger_instance.error("app", f"Error escaneando {directory}: {e}")

    scan_dir(_VIDEOS_DIR)
    
    return render_template("player.html", 
                          videos=videos, 
                          video_count=len(videos))


# ─────────────────────────────────────────────────────────────────────────────
# RUTAS AJAX — Configuración (Settings)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/config/current")
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
            config_instance.set(data["key"], data["value"])
            logger_instance.info("app", f"Config actualizada: {data['key']} = {data['value']}")
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
def check_video(filepath):
    """
    Verifica que un archivo existe y es accesible.
    Útil para debugging de problemas de streaming.
    """
    from urllib.parse import unquote
    filepath = unquote(filepath)
    dav_path = os.path.join(_VIDEOS_DIR, filepath)
    
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
def settings_page():
    """
    Renderiza la página de configuración con formularios AJAX.
    """
    return render_template("settings.html")

# ─────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    srv = config_instance.get("server", {})
    logger_instance.info("app", "Iniciando servidor...")
    logger_instance.info("app", f"  http://{srv.get('host','0.0.0.0')}:{srv.get('port',5000)}")
    logger_instance.info("app", f"  Videos : {_VIDEOS_DIR}/")
    logger_instance.info("app", f"  Caché  : {_CACHE_DIR}/")
    app.run(
        debug=srv.get("debug", True),
        threaded=True,
        host=srv.get("host", "0.0.0.0"),
        port=srv.get("port", 5000),
    )