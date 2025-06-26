#!/usr/bin/env python3
"""
Script para instalar todas las dependencias del proyecto FTP Dahua
Compatible con Windows y Linux
"""

import sys
import subprocess

# Lista de dependencias principales
requirements = [
    "pyftpdlib",
    "flask",
    "psutil"
]

def install(package):
    """Instala un paquete usando pip"""
    print(f"Instalando {package}...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def main():
    print("=== Instalador de dependencias para FTP Dahua ===")
    for pkg in requirements:
        try:
            install(pkg)
        except Exception as e:
            print(f"Error instalando {pkg}: {e}")
    print("=== Instalación completada ===")

if __name__ == "__main__":
    main()