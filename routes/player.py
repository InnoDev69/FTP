import re
from flask import Blueprint, render_template
from src.auth_utils import login_required  
from src.scanner import _scan_devices

player_bp = Blueprint('player', __name__)

@player_bp.route('/player')
@login_required
def player():
    """
    Renderiza la página del reproductor con lista de videos disponibles.
    Los videos se obtienen recursivamente desde el directorio de videos.
    """
    videos = []
    devices_data = _scan_devices()

    for device in devices_data.values():
        for f in device.get("files", []):
            channel = f.get("channel")
            if not channel:
                name = f.get("name") or ""
                ch_match = re.search(r"_ch(\d+)_", name)
                if ch_match:
                    channel = f"ch{ch_match.group(1)}"
            channel = channel or "ch1"
            videos.append({
                "id":              len(videos),
                "filename":        f.get("name"),
                "path":            f.get("path"),
                "device_id":       device.get("ip", "local"),
                "device_alias":    device.get("alias", "local"),
                "channel_id":      channel,
                "recording_date":  f.get("datetime"),
                "resolution":      "1920x1080",
                "file_size":       f.get("size"),
                "conv_status":     "done",
            })
    
    return render_template("player.html", 
                          videos=videos, 
                          video_count=len(videos))