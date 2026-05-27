#!/usr/bin/env python3
"""
Simple updater for the project.
- Downloads update manifest.
- Verifies sha256.
- Creates backup.
- Extracts package over APP_ROOT.
"""

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_URL = ""


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url) as resp, dest.open("wb") as f:
        f.write(resp.read())


def load_manifest(manifest_path: Path) -> dict:
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def backup_app(backup_dir: Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    backup_path = backup_dir / f"backup_{ts}"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP_ROOT, backup_path, dirs_exist_ok=True)
    return backup_path


def extract_package(pkg_path: Path) -> None:
    with tarfile.open(pkg_path, "r:gz") as tar:
        tar.extractall(APP_ROOT)


def run_update(manifest_url: str) -> str:
    tmp_dir = Path(tempfile.mkdtemp(prefix="update_"))
    manifest_path = tmp_dir / "update.json"
    download(manifest_url, manifest_path)

    manifest = load_manifest(manifest_path)
    pkg_url = manifest.get("url", "")
    expected_sha = manifest.get("sha256", "")
    if not pkg_url or not expected_sha:
        raise RuntimeError("Manifest incompleto: falta url o sha256")

    pkg_path = tmp_dir / "package.tar.gz"
    download(pkg_url, pkg_path)

    actual_sha = sha256sum(pkg_path)
    if actual_sha != expected_sha:
        raise RuntimeError("Checksum invalido")

    backup_app(APP_ROOT / "backups")
    extract_package(pkg_path)

    return manifest.get("latest", "unknown")


def main() -> int:
    parser = argparse.ArgumentParser(description="Project updater")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST_URL)
    args = parser.parse_args()

    if not args.manifest:
        raise SystemExit("Falta --manifest")

    latest = run_update(args.manifest)
    print(f"Actualizado a {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
