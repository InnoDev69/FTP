import re
from datetime import datetime
from pathlib import Path
from .config import config_instance
from .logger import logger_instance
from .globals import ALLOWED, VIDEOS_DIR

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

def _is_ip_folder(name: str) -> bool:
    parts = name.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        value = int(part)
        if value < 0 or value > 255:
            return False
    return True

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
    base    = Path(VIDEOS_DIR)
    devices = config_instance.get("devices", {})
    result  = {}

    if not base.exists():
        return result

    ip_dirs = [d for d in sorted(base.iterdir()) if d.is_dir() and _is_ip_folder(d.name)]

    if ip_dirs:
        scan_targets = [(d.name, d) for d in ip_dirs]
    else:
        scan_targets = [("local", base)]

    for ip, device_dir in scan_targets:
        if ip not in devices:
            _save_new_device(ip)
            devices = config_instance.get("devices", {})

        device_info = devices.get(ip, {})
        files = []

        for f in sorted(device_dir.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in ALLOWED:
                continue

            rel  = f.relative_to(base).as_posix()
            meta = _parse_filename_datetime(f.name) or {}
            if "channel" not in meta:
                ch_match = re.search(r"_ch(\d+)_", f.name)
                if ch_match:
                    meta["channel"] = f"ch{ch_match.group(1)}"

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