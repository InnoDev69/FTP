"""
tools/dvr_simulator.py — Simulador de DVR Dahua.

Genera archivos .dav falsos con nombres realistas y los sube al servidor
FTP exactamente como lo haría un DVR real.

Uso rápido:
    python tools/dvr_simulator.py                   # 5 videos, config por defecto
    python tools/dvr_simulator.py --count 20        # 20 videos
    python tools/dvr_simulator.py --host 192.168.1.10 --port 21
    python tools/dvr_simulator.py --device DVR_02 --channels 4

Opciones:
    --host      IP del servidor FTP       (default: 127.0.0.1)
    --port      Puerto FTP                (default: 21)
    --user      Usuario FTP               (default: dahua)
    --password  Contraseña FTP            (default: dahua123)
    --device    ID del dispositivo        (default: DVR_01)
    --channels  Número de canales         (default: 2)
    --count     Cantidad de videos a subir (default: 5)
    --size-kb   Tamaño de cada archivo KB (default: 512)
    --delay     Segundos entre uploads    (default: 0.5)
    --date      Fecha base YYYYMMDD       (default: hoy)
"""

import argparse
import ftplib
import io
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


# ── Generador de archivos falsos ──────────────────────────────────────────

def make_fake_dav(size_kb: int = 512) -> bytes:
    """
    Genera un archivo .dav con una imagen blanca de 1 hora usando GPU NVIDIA (si está disponible).
    """
    import subprocess
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix='.dav', delete=False) as tmp:
        tmp_path = tmp.name
    
    # Intentar primero con h264_nvenc (GPU NVIDIA)
    cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        '-i', 'color=white:s=1920x1080:d=3600',
        '-f', 'lavfi',
        '-i', 'anullsrc=r=44100:cl=mono:d=3600',
        '-c:v', 'h264_nvenc',
        '-preset', 'fast',
        '-c:a', 'aac',
        '-shortest',
        '-y',
        tmp_path
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"\n  ⚠ h264_nvenc no disponible: {e.stderr[:200]}")
        print(f"  Usando libx264 en su lugar...\n")
        
        # Fallback a libx264 (CPU)
        cmd[cmd.index('h264_nvenc')] = 'libx264'
        if 'fast' in cmd:
            cmd.remove('-preset')
            cmd.remove('fast')
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e2:
            print(f"  ✗ Error con libx264: {e2.stderr}")
            raise
    
    with open(tmp_path, 'rb') as f:
        data = f.read()
    
    Path(tmp_path).unlink()
    return data

def make_filename(device: str, channel: int, dt: datetime, duration_secs: int = 60) -> str:
    """
    Genera nombre de archivo al estilo Dahua.
    Ejemplo: DVR_01_ch02_20260523_143000_143100.dav
    """
    end_dt = dt + timedelta(seconds=duration_secs)
    return (
        f"{device}_ch{channel:02d}_"
        f"{dt.strftime('%Y%m%d')}_{dt.strftime('%H%M%S')}_"
        f"{end_dt.strftime('%H%M%S')}.dav"
    )


# ── Upload FTP ────────────────────────────────────────────────────────────

def upload_file(ftp: ftplib.FTP, filename: str, data: bytes) -> bool:
    """Sube un archivo al servidor FTP. Retorna True si tuvo éxito."""
    try:
        buf = io.BytesIO(data)
        ftp.storbinary(f"STOR {filename}", buf)
        return True
    except ftplib.all_errors as e:
        print(f"  ✗ Error subiendo {filename}: {e}")
        return False


# ── Simulación principal ──────────────────────────────────────────────────

def run_simulation(args):
    base_date = datetime.strptime(args.date, "%Y%m%d") if args.date else datetime.now()
    base_date = base_date.replace(hour=8, minute=0, second=0, microsecond=0)

    print(f"\n{'═'*55}")
    print(f"  Simulador DVR Dahua")
    print(f"{'═'*55}")
    print(f"  Servidor : {args.host}:{args.port}")
    print(f"  Usuario  : {args.user}")
    print(f"  Device   : {args.device}  |  Canales: {args.channels}")
    print(f"  Videos   : {args.count}   |  Tamaño: {args.size_kb} KB c/u")
    print(f"  Fecha    : {base_date.strftime('%Y-%m-%d')}")
    print(f"{'═'*55}\n")

    # Conectar al FTP
    print(f"Conectando a {args.host}:{args.port}…")
    try:
        ftp = ftplib.FTP()
        ftp.connect(args.host, args.port, timeout=10)
        ftp.login(args.user, args.password)
        ftp.set_pasv(True)
        print(f"  ✓ Conectado. Banner: {ftp.getwelcome()}\n")
    except Exception as e:
        print(f"  ✗ No se pudo conectar: {e}")
        print(f"\n  ¿Está corriendo el servidor? → python server.py\n")
        sys.exit(1)

    # Generar y subir videos
    ok = 0
    current_dt = base_date
    channels = list(range(1, args.channels + 1))

    for i in range(args.count):
        channel = channels[i % len(channels)]
        # Avanzar el tiempo simulado entre grabaciones
        current_dt += timedelta(minutes=random.randint(1, 5))

        filename = make_filename(args.device, channel, current_dt)
        data     = make_fake_dav(args.size_kb)

        print(f"  [{i+1:03d}/{args.count}] {filename}  ({len(data):,} bytes) … ", end="", flush=True)
        if upload_file(ftp, filename, data):
            print("✓")
            ok += 1
        else:
            print("✗")

        if args.delay > 0 and i < args.count - 1:
            time.sleep(args.delay)

    ftp.quit()

    print(f"\n{'─'*55}")
    print(f"  Resultado: {ok}/{args.count} archivos subidos correctamente")
    if ok < args.count:
        print(f"  Fallidos : {args.count - ok}")
    print(f"{'─'*55}\n")


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Simulador de DVR Dahua — sube archivos .dav de prueba al servidor FTP"
    )
    p.add_argument("--host",      default="127.0.0.1", help="IP del servidor FTP")
    p.add_argument("--port",      type=int, default=21, help="Puerto FTP")
    p.add_argument("--user",      default="dahua",     help="Usuario FTP")
    p.add_argument("--password",  default="dahua123",  help="Contraseña FTP")
    p.add_argument("--device",    default="DVR_01",    help="ID del dispositivo")
    p.add_argument("--channels",  type=int, default=2, help="Número de canales a simular")
    p.add_argument("--count",     type=int, default=5, help="Cantidad de videos a subir")
    p.add_argument("--size-kb",   type=int, default=512, dest="size_kb",
                                  help="Tamaño de cada archivo en KB")
    p.add_argument("--delay",     type=float, default=0.5,
                                  help="Segundos entre uploads (0 = sin delay)")
    p.add_argument("--date",      default=None,
                                  help="Fecha base YYYYMMDD (default: hoy)")
    args = p.parse_args()
    run_simulation(args)


if __name__ == "__main__":
    main()
