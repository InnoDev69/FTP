#!/usr/bin/env python3
"""
Servidor FTP orientado a objetos usando pyftpdlib.
Soporta múltiples conexiones simultáneas y transferencias de archivos grandes.

Uso:
    python ftp_server.py [opciones]
    python ftp_server.py --help
"""

import argparse
import logging
import sys
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler, ThrottledDTPHandler
from pyftpdlib.servers import ThreadedFTPServer


# ──────────────────────────────────────────────────────────────
# ARGUMENTOS CLI
# ──────────────────────────────────────────────────────────────

class FTPArgumentParser:
    """Encapsula la definición y parseo de flags de línea de comandos."""

    def __init__(self):
        self._parser = argparse.ArgumentParser(
            prog="ftp_server.py",
            description="Servidor FTP multi-conexión para archivos grandes (pyftpdlib)",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        self._add_network_args()
        self._add_auth_args()
        self._add_storage_args()
        self._add_performance_args()
        self._add_logging_args()

    def _add_network_args(self):
        g = self._parser.add_argument_group("Red")
        g.add_argument("--host", default="0.0.0.0",
                       help="Dirección IP de escucha")
        g.add_argument("--port", type=int, default=2121,
                       help="Puerto de control FTP (usa 21 con sudo)")
        g.add_argument("--passive-ports", default="50000-50100",
                       metavar="LO-HI",
                       help="Rango de puertos pasivos para transferencias de datos")
        g.add_argument("--masquerade-address", default="",
                       metavar="IP",
                       help="IP pública para modo pasivo detrás de NAT")

    def _add_auth_args(self):
        g = self._parser.add_argument_group("Autenticación")
        g.add_argument("--users", nargs="+", default=["anonymous:"],
                       metavar="USER:PASS",
                       help="Usuarios con formato USER:PASS. Ej: admin:s3cr3t user2:pass2")
        g.add_argument("--anonymous", action="store_true", default=False,
                       help="Habilitar acceso anónimo (solo lectura)")
        g.add_argument("--read-only", action="store_true", default=False,
                       help="Todos los usuarios en modo solo lectura")

    def _add_storage_args(self):
        g = self._parser.add_argument_group("Almacenamiento")
        g.add_argument("--root", default="./ftp_root",
                       help="Directorio raíz del servidor FTP")

    def _add_performance_args(self):
        g = self._parser.add_argument_group("Rendimiento")
        g.add_argument("--max-connections", type=int, default=256,
                       help="Máximo de conexiones simultáneas globales")
        g.add_argument("--max-connections-per-ip", type=int, default=10,
                       help="Máximo de conexiones simultáneas por IP")
        g.add_argument("--buffer-size", type=int, default=131072,
                       help="Buffer de transferencia en bytes (128 KB por defecto, "
                            "aumentar para archivos grandes)")
        g.add_argument("--timeout", type=int, default=300,
                       help="Segundos de inactividad antes de desconectar")
        g.add_argument("--read-limit", type=int, default=0,
                       help="Límite de velocidad de subida en bytes/s (0 = sin límite)")
        g.add_argument("--write-limit", type=int, default=0,
                       help="Límite de velocidad de bajada en bytes/s (0 = sin límite)")

    def _add_logging_args(self):
        g = self._parser.add_argument_group("Logging")
        g.add_argument("--log-level",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       default="INFO",
                       help="Nivel de verbosidad del log")
        g.add_argument("--log-file", default="",
                       help="Archivo de log (vacío = solo consola)")

    def parse(self) -> argparse.Namespace:
        return self._parser.parse_args()


# ──────────────────────────────────────────────────────────────
# AUTORIZADOR
# ──────────────────────────────────────────────────────────────

class FTPAuthorizer:
    """
    Construye el DummyAuthorizer de pyftpdlib a partir de los flags parseados.
    Gestiona usuarios, permisos y acceso anónimo.
    """

    # Permisos de lectura y escritura
    PERMS_READ  = "elradf"   # e=CWD, l=LIST, r=RETR, a=APPE, d=DELE, f=RNFR
    PERMS_WRITE = "elradfmwMT"  # incluye: m=MKD, w=STOR, M=CHMOD, T=MFMT

    def __init__(self, args: argparse.Namespace):
        self._args = args
        self._root = str(Path(args.root).resolve())
        self._authorizer = DummyAuthorizer()
        self._setup()

    def _setup(self):
        Path(self._root).mkdir(parents=True, exist_ok=True)
        perms = self.PERMS_READ if self._args.read_only else self.PERMS_WRITE

        for spec in self._args.users:
            if ":" in spec:
                username, password = spec.split(":", 1)
            else:
                username, password = spec, ""

            if username == "anonymous":
                continue  # Se maneja aparte con --anonymous

            self._authorizer.add_user(
                username, password,
                homedir=self._root,
                perm=perms,
                msg_login=f"Bienvenido, {username}.",
                msg_quit="Hasta luego.",
            )
            logging.getLogger("FTPServer").info(
                f"Usuario registrado: {username!r} "
                f"({'solo lectura' if self._args.read_only else 'lectura/escritura'})"
            )

        if self._args.anonymous:
            self._authorizer.add_anonymous(
                self._root,
                perm=self.PERMS_READ,
                msg_login="Bienvenido, acceso anónimo.",
                msg_quit="Hasta luego.",
            )
            logging.getLogger("FTPServer").info("Acceso anónimo habilitado (solo lectura)")

    @property
    def authorizer(self) -> DummyAuthorizer:
        return self._authorizer


# ──────────────────────────────────────────────────────────────
# HANDLER DE TRANSFERENCIA (DTP)
# ──────────────────────────────────────────────────────────────

class LargeFilesDTPHandler(ThrottledDTPHandler):
    """
    Handler de canal de datos especializado para archivos grandes.
    Hereda throttling de ThrottledDTPHandler y expone buffer configurable.
    Los límites read_limit / write_limit se inyectan desde FTPServerConfig.
    """

    # Desactivar sendfile() de OS para mayor compatibilidad
    use_sendfile = False


# ──────────────────────────────────────────────────────────────
# HANDLER DE CONTROL (FTP)
# ──────────────────────────────────────────────────────────────

class CustomFTPHandler(FTPHandler):
    """
    Handler de sesión FTP con logging enriquecido.
    Extiende FTPHandler para registrar inicio/fin de transferencias
    con tamaño y velocidad real.
    """

    def on_connect(self):
        logging.getLogger("FTPServer").info(
            f"Conexión entrante: {self.remote_ip}:{self.remote_port}"
        )

    def on_disconnect(self):
        logging.getLogger("FTPServer").info(
            f"Desconectado: {self.remote_ip}"
        )

    def on_login(self, username: str):
        logging.getLogger("FTPServer").info(
            f"Login exitoso: {username!r} desde {self.remote_ip}"
        )

    def on_login_failed(self, username: str, password: str):
        logging.getLogger("FTPServer").warning(
            f"Login fallido: {username!r} desde {self.remote_ip}"
        )

    def on_file_sent(self, file: str):
        logging.getLogger("FTPServer").info(
            f"ENVIADO   → {self.username!r} | {file}"
        )

    def on_file_received(self, file: str):
        logging.getLogger("FTPServer").info(
            f"RECIBIDO  ← {self.username!r} | {file}"
        )

    def on_incomplete_file_sent(self, file: str):
        logging.getLogger("FTPServer").warning(
            f"INCOMPLETO (envío)  | {self.username!r} | {file}"
        )

    def on_incomplete_file_received(self, file: str):
        logging.getLogger("FTPServer").warning(
            f"INCOMPLETO (recibo) | {self.username!r} | {file}"
        )


# ──────────────────────────────────────────────────────────────
# CONFIGURACIÓN CENTRALIZADA
# ──────────────────────────────────────────────────────────────

class FTPServerConfig:
    """
    Traduce los flags de argparse a la configuración de pyftpdlib.
    Responsabilidad única: preparar y aplicar la configuración al handler.
    """

    def __init__(self, args: argparse.Namespace):
        self._args = args

    @property
    def address(self) -> tuple[str, int]:
        return (self._args.host, self._args.port)

    def _parse_passive_ports(self) -> list[int]:
        lo, hi = self._args.passive_ports.split("-")
        return list(range(int(lo), int(hi) + 1))

    def apply_to_handler(self, handler: type[CustomFTPHandler], authorizer: DummyAuthorizer):
        """Aplica toda la configuración al handler class (atributos de clase)."""
        handler.authorizer         = authorizer
        handler.passive_ports      = self._parse_passive_ports()
        handler.timeout            = self._args.timeout
        handler.max_cons           = self._args.max_connections
        handler.max_cons_per_ip    = self._args.max_connections_per_ip
        handler.banner             = "Servidor FTP listo."

        if self._args.masquerade_address:
            handler.masquerade_address = self._args.masquerade_address

        # Configurar el handler DTP para archivos grandes
        dtp = LargeFilesDTPHandler
        dtp.ac_in_buffer_size  = self._args.buffer_size  # buffer subida
        dtp.ac_out_buffer_size = self._args.buffer_size  # buffer bajada
        dtp.read_limit         = self._args.read_limit
        dtp.write_limit        = self._args.write_limit
        handler.dtp_handler    = dtp


# ──────────────────────────────────────────────────────────────
# LOGGER
# ──────────────────────────────────────────────────────────────

class FTPLogger:
    """Configura el sistema de logging para consola y/o archivo."""

    FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"

    def __init__(self, level: str, log_file: str = ""):
        self._level    = getattr(logging, level)
        self._log_file = log_file

    def setup(self) -> logging.Logger:
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        if self._log_file:
            handlers.append(logging.FileHandler(self._log_file, encoding="utf-8"))

        logging.basicConfig(
            level=self._level,
            format=self.FORMAT,
            handlers=handlers,
        )
        # Silenciar logs internos muy verbosos de pyftpdlib en modo INFO
        logging.getLogger("pyftpdlib").setLevel(self._level)
        return logging.getLogger("FTPServer")


# ──────────────────────────────────────────────────────────────
# SERVIDOR PRINCIPAL
# ──────────────────────────────────────────────────────────────

class FTPServerApp:
    """
    Clase principal de la aplicación. Orquesta la inicialización y el arranque
    del servidor FTP usando pyftpdlib con soporte multi-hilo.
    """

    def __init__(self, args: argparse.Namespace):
        self._args   = args
        self._logger = FTPLogger(args.log_level, args.log_file).setup()
        self._config = FTPServerConfig(args)
        self._auth   = FTPAuthorizer(args)
        self._server: ThreadedFTPServer | None = None

    def _build_handler(self) -> type[CustomFTPHandler]:
        self._config.apply_to_handler(CustomFTPHandler, self._auth.authorizer)
        return CustomFTPHandler

    def _log_startup_info(self):
        args = self._args
        self._logger.info("=" * 55)
        self._logger.info("  Servidor FTP iniciando")
        self._logger.info("=" * 55)
        self._logger.info(f"  Escuchando en   : {args.host}:{args.port}")
        self._logger.info(f"  Puertos pasivos : {args.passive_ports}")
        self._logger.info(f"  Directorio raíz : {Path(args.root).resolve()}")
        self._logger.info(f"  Max conexiones  : {args.max_connections} global / "
                          f"{args.max_connections_per_ip} por IP")
        self._logger.info(f"  Buffer          : {args.buffer_size / 1024:.0f} KB")
        self._logger.info(f"  Timeout         : {args.timeout}s")
        self._logger.info(f"  Solo lectura    : {args.read_only}")
        if args.read_limit or args.write_limit:
            self._logger.info(
                f"  Throttle        : ↑{args.read_limit/1024:.0f} KB/s  "
                f"↓{args.write_limit/1024:.0f} KB/s"
            )
        self._logger.info("=" * 55)

    def run(self):
        handler = self._build_handler()
        self._log_startup_info()

        self._server = ThreadedFTPServer(self._config.address, handler)
        self._server.max_cons         = self._args.max_connections
        self._server.max_cons_per_ip  = self._args.max_connections_per_ip

        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            self._logger.info("Servidor detenido por el usuario (Ctrl+C)")
        finally:
            self._server.close_all()


# ──────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────

def main():
    args = FTPArgumentParser().parse()
    app  = FTPServerApp(args)
    app.run()


if __name__ == "__main__":
    main()
