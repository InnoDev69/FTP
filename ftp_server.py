#!/usr/bin/env python3
"""
Servidor FTP orientado a objetos usando pyftpdlib.
Soporta múltiples conexiones simultáneas y transferencias de archivos grandes.
Optimizado para múltiples DVRs Dahua enviando grabaciones simultáneamente.

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
            description="Servidor FTP multi-conexión para DVRs Dahua (pyftpdlib)",
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
        g.add_argument("--passive-ports", default="50000-50500",
                       metavar="LO-HI",
                       help="Rango de puertos pasivos. Con muchos DVRs usar rango amplio (ej: 50000-51000)")
        g.add_argument("--masquerade-address", default="",
                       metavar="IP",
                       help="IP pública para modo pasivo detrás de NAT")

    def _add_auth_args(self):
        g = self._parser.add_argument_group("Autenticación")
        g.add_argument("--users", nargs="+", default=[],
                       metavar="USER:PASS",
                       help="Usuarios con formato USER:PASS. Ej: dvr1:pass1 dvr2:pass2")
        g.add_argument("--anonymous", action="store_true", default=False,
                       help="Habilitar acceso anónimo (solo lectura)")
        g.add_argument("--read-only", action="store_true", default=False,
                       help="Todos los usuarios en modo solo lectura")
        g.add_argument("--per-user-home", action="store_true", default=True,
                       help="Cada usuario tiene su propio subdirectorio (evita conflictos entre DVRs)")

    def _add_storage_args(self):
        g = self._parser.add_argument_group("Almacenamiento")
        g.add_argument("--root", default="./ftp_root",
                       help="Directorio raíz del servidor FTP")

    def _add_performance_args(self):
        g = self._parser.add_argument_group("Rendimiento")
        g.add_argument("--max-connections", type=int, default=512,
                       help="Máximo de conexiones simultáneas globales")
        g.add_argument("--max-connections-per-ip", type=int, default=64,
                       help="Máximo de conexiones por IP (un DVR puede abrir muchas a la vez)")
        g.add_argument("--buffer-size", type=int, default=524288,
                       help="Buffer de transferencia en bytes (512 KB por defecto)")
        g.add_argument("--timeout", type=int, default=60,
                       help="Segundos de inactividad antes de desconectar (bajo para liberar slots rápido)")
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
    Con --per-user-home cada usuario escribe en su propio subdirectorio,
    eliminando conflictos de nombres de archivo entre DVRs.
    """

    PERMS_READ  = "elradf"
    PERMS_WRITE = "elradfmwT"

    def __init__(self, args: argparse.Namespace):
        self._args        = args
        self._root        = Path(args.root).resolve()
        self._authorizer  = DummyAuthorizer()
        self._log         = logging.getLogger("FTPServer")
        self._setup()

    def _user_home(self, username: str) -> str:
        if self._args.per_user_home:
            home = self._root / username
        else:
            home = self._root
        home.mkdir(parents=True, exist_ok=True)
        return str(home)

    def _setup(self):
        self._root.mkdir(parents=True, exist_ok=True)
        perms = self.PERMS_READ if self._args.read_only else self.PERMS_WRITE

        if not self._args.users and not self._args.anonymous:
            self._log.warning(
                "No hay usuarios configurados. "
                "Usá --users dvr1:pass1 dvr2:pass2 o --anonymous"
            )

        for spec in self._args.users:
            if ":" in spec:
                username, password = spec.split(":", 1)
            else:
                username, password = spec, ""

            if username == "anonymous":
                continue

            home = self._user_home(username)
            self._authorizer.add_user(
                username, password,
                homedir=home,
                perm=perms,
                msg_login=f"Bienvenido, {username}. Directorio: {home}",
                msg_quit="Hasta luego.",
            )
            self._log.info(
                f"Usuario registrado: {username!r} → {home} "
                f"({'solo lectura' if self._args.read_only else 'lectura/escritura'})"
            )

        if self._args.anonymous:
            anon_home = self._user_home("anonymous")
            self._authorizer.add_anonymous(
                anon_home,
                perm=self.PERMS_READ,
                msg_login="Bienvenido, acceso anónimo.",
                msg_quit="Hasta luego.",
            )
            self._log.info(f"Acceso anónimo habilitado (solo lectura) → {anon_home}")

    @property
    def authorizer(self) -> DummyAuthorizer:
        return self._authorizer


# ──────────────────────────────────────────────────────────────
# HANDLER DE TRANSFERENCIA (DTP)
# ──────────────────────────────────────────────────────────────

class LargeFilesDTPHandler(ThrottledDTPHandler):
    """
    Handler de canal de datos optimizado para archivos grandes de DVR.
    use_sendfile debe ser un método callable (pyftpdlib 2.2.0 lo invoca
    como dc.use_sendfile() en get_repr_info — si es un bool estático
    lanza TypeError: 'bool' object is not callable).
    """

    def use_sendfile(self) -> bool:
        return False


# ──────────────────────────────────────────────────────────────
# HANDLER DE CONTROL (FTP)
# ──────────────────────────────────────────────────────────────

class CustomFTPHandler(FTPHandler):
    """
    Handler de sesión FTP con logging enriquecido.
    Registra conexiones, logins, y transferencias completas/incompletas.
    """

    def on_connect(self):
        logging.getLogger("FTPServer").info(
            f"[CONNECT]   {self.remote_ip}:{self.remote_port}"
        )

    def on_disconnect(self):
        logging.getLogger("FTPServer").info(
            f"[DISCONNECT] {self.remote_ip}"
        )

    def on_login(self, username: str):
        logging.getLogger("FTPServer").info(
            f"[LOGIN OK]  {username!r} desde {self.remote_ip}"
        )

    def on_login_failed(self, username: str, password: str):
        logging.getLogger("FTPServer").warning(
            f"[LOGIN FAIL] {username!r} desde {self.remote_ip}"
        )

    def on_file_sent(self, file: str):
        logging.getLogger("FTPServer").info(
            f"[SENT]      {self.username!r} ← {file}"
        )

    def on_file_received(self, file: str):
        logging.getLogger("FTPServer").info(
            f"[RECEIVED]  {self.username!r} → {file}"
        )

    def on_incomplete_file_sent(self, file: str):
        logging.getLogger("FTPServer").warning(
            f"[INCOMPLETE SEND]  {self.username!r} | {file}"
        )

    def on_incomplete_file_received(self, file: str):
        logging.getLogger("FTPServer").warning(
            f"[INCOMPLETE RECV]  {self.username!r} | {file}"
        )


# ──────────────────────────────────────────────────────────────
# CONFIGURACIÓN CENTRALIZADA
# ──────────────────────────────────────────────────────────────

class FTPServerConfig:
    """
    Traduce los flags de argparse a la configuración de pyftpdlib.
    """

    def __init__(self, args: argparse.Namespace):
        self._args = args

    @property
    def address(self) -> tuple[str, int]:
        return (self._args.host, self._args.port)

    def _parse_passive_ports(self) -> list[int]:
        lo, hi = self._args.passive_ports.split("-")
        ports = list(range(int(lo), int(hi) + 1))
        if len(ports) < 100:
            logging.getLogger("FTPServer").warning(
                f"Rango de puertos pasivos muy pequeño ({len(ports)} puertos). "
                "Con múltiples DVRs se puede agotar. Recomendado: al menos 500."
            )
        return ports

    def apply_to_handler(self, handler: type[CustomFTPHandler], authorizer: DummyAuthorizer):
        """Aplica toda la configuración al handler class (atributos de clase)."""

        # ── DTP handler (canal de datos) ──────────────────────────────────
        # IMPORTANTE: sin esta línea pyftpdlib usa el DTPHandler base, que
        # tiene use_sendfile=False como bool → TypeError en pyftpdlib 2.2.0
        LargeFilesDTPHandler.read_limit        = self._args.read_limit
        LargeFilesDTPHandler.write_limit       = self._args.write_limit
        LargeFilesDTPHandler.ac_in_buffer_size  = self._args.buffer_size
        LargeFilesDTPHandler.ac_out_buffer_size = self._args.buffer_size
        handler.dtp_handler = LargeFilesDTPHandler

        # ── Control handler ───────────────────────────────────────────────
        handler.authorizer         = authorizer
        handler.passive_ports      = self._parse_passive_ports()
        handler.timeout            = self._args.timeout
        handler.max_cons           = self._args.max_connections
        handler.max_cons_per_ip    = self._args.max_connections_per_ip
        handler.banner             = "Servidor FTP Dahua listo."
        handler.permit_foreign_addresses = False

        if self._args.masquerade_address:
            handler.masquerade_address = self._args.masquerade_address


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
        logging.getLogger("pyftpdlib").setLevel(self._level)
        return logging.getLogger("FTPServer")


# ──────────────────────────────────────────────────────────────
# SERVIDOR PRINCIPAL
# ──────────────────────────────────────────────────────────────

class FTPServerApp:
    """
    Clase principal. Orquesta la inicialización y el arranque del servidor.
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
        passive_lo, passive_hi = args.passive_ports.split("-")
        n_passive = int(passive_hi) - int(passive_lo) + 1
        self._logger.info("=" * 60)
        self._logger.info("  Servidor FTP para DVRs Dahua — iniciando")
        self._logger.info("=" * 60)
        self._logger.info(f"  Escuchando en      : {args.host}:{args.port}")
        self._logger.info(f"  Puertos pasivos    : {args.passive_ports} ({n_passive} puertos)")
        self._logger.info(f"  Directorio raíz    : {Path(args.root).resolve()}")
        self._logger.info(f"  Home por usuario   : {args.per_user_home}")
        self._logger.info(f"  Max conexiones     : {args.max_connections} global / "
                          f"{args.max_connections_per_ip} por IP")
        self._logger.info(f"  Buffer             : {args.buffer_size / 1024:.0f} KB")
        self._logger.info(f"  Timeout inactividad: {args.timeout}s")
        self._logger.info(f"  Solo lectura       : {args.read_only}")
        if args.read_limit or args.write_limit:
            self._logger.info(
                f"  Throttle           : ↑{args.read_limit/1024:.0f} KB/s  "
                f"↓{args.write_limit/1024:.0f} KB/s"
            )
        self._logger.info("=" * 60)

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