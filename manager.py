#!/usr/bin/env python3
"""
Service Manager — GUI para administrar app.py (Flask DAV Server) y ftp_server.py
Requiere: Python 3.10+, customtkinter
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import subprocess
import threading
import sys
import os
import json
if os.name == "nt":
    import winreg
import shlex
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# CONSTANTES Y CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

APP_TITLE    = "Service Manager | DAV + FTP"
CONFIG_FILE  = Path(__file__).parent / "manager_config.json"
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

SERVICES = {
    "flask": {
        "id":          "flask",
        "label":       "Servidor DAV a MP4",
        "script":      "app.py",
        "description": "Convierte archivos DAV a MP4 y los sirve a través de HTTP.",
        "color":       "#007ACC",
        "options": {},
    },
    "ftp": {
        "id":          "ftp",
        "label":       "Servidor FTP Dahua",
        "script":      "ftp_server.py",
        "description": "Recibe y almacena grabaciones provenientes de DVRs.",
        "color":       "#4CAF50",
        "options": {
            "--host":                    {"type": "str",  "default": "0.0.0.0",       "help": "IP de escucha"},
            "--port":                    {"type": "int",  "default": 2121,            "help": "Puerto de control FTP"},
            "--passive-ports":           {"type": "str",  "default": "50000-50500",   "help": "Rango de puertos pasivos (ej: 50000-50500)"},
            "--masquerade-address":      {"type": "str",  "default": "",              "help": "IP pública para NAT (opcional)"},
            "--users":                   {"type": "str",  "default": "",              "help": "Usuarios USER:PASS separados por espacio"},
            "--anonymous":               {"type": "bool", "default": False,           "help": "Habilitar acceso anónimo"},
            "--read-only":               {"type": "bool", "default": False,           "help": "Modo solo lectura"},
            "--per-user-home":           {"type": "bool", "default": True,            "help": "Home separado por usuario"},
            "--root":                    {"type": "path", "default": "./ftp_root",    "help": "Directorio raíz FTP"},
            "--max-connections":         {"type": "int",  "default": 512,             "help": "Máx. conexiones globales"},
            "--max-connections-per-ip":  {"type": "int",  "default": 64,              "help": "Máx. conexiones por IP"},
            "--buffer-size":             {"type": "int",  "default": 524288,          "help": "Buffer transferencia (bytes)"},
            "--timeout":                 {"type": "int",  "default": 60,              "help": "Timeout inactividad (seg)"},
            "--read-limit":              {"type": "int",  "default": 0,               "help": "Límite subida bytes/s (0=sin límite)"},
            "--write-limit":             {"type": "int",  "default": 0,               "help": "Límite bajada bytes/s (0=sin límite)"},
            "--log-level":               {"type": "choice","default": "INFO",         "help": "Nivel de log",
                                          "choices": ["DEBUG", "INFO", "WARNING", "ERROR"]},
            "--log-file":                {"type": "str",  "default": "",              "help": "Archivo de log (vacío=consola)"},
        },
    },
}

COLOR_RUNNING = "#2E7D32"
COLOR_RUNNING_HOVER = "#1B5E20"
COLOR_STOPPED = "#C62828"
COLOR_STOPPED_HOVER = "#8E0000"
COLOR_RESTART = "#F57C00"
COLOR_RESTART_HOVER = "#E65100"

# ─────────────────────────────────────────────────────────────
# CONFIG PERSISTENTE
# ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    defaults = {
        "python_path": sys.executable,
        "work_dir":    str(Path(__file__).parent),
        "ftp_options": {k: v["default"] for k, v in SERVICES["ftp"]["options"].items()},
    }
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in defaults["ftp_options"].items():
                saved.setdefault("ftp_options", {}).setdefault(k, v)
            defaults.update(saved)
        except Exception:
            pass
    return defaults

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

# ─────────────────────────────────────────────────────────────
# AUTOSTART WINDOWS
# ─────────────────────────────────────────────────────────────

def _reg_name(service_id: str) -> str:
    return f"ServiceManager_{service_id}"

def get_autostart(service_id: str) -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, _reg_name(service_id))
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False

def set_autostart(service_id: str, enable: bool, cmd: str):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, _reg_name(service_id), 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, _reg_name(service_id))
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo modificar el registro:\n{e}")
        return False

# ─────────────────────────────────────────────────────────────
# PROCESO DE SERVICIO
# ─────────────────────────────────────────────────────────────

class ServiceProcess:
    def __init__(self, service_id: str, on_output, on_status_change):
        self.service_id       = service_id
        self._on_output       = on_output
        self._on_status       = on_status_change
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, python: str, work_dir: str, script: str, extra_args: list[str]):
        if self.running:
            return
        cmd = [python, script] + extra_args
        self._on_output(f"[{_ts()}] INICIANDO PROCESO: {' '.join(shlex.quote(a) for a in cmd)}\n")
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._reader = threading.Thread(target=self._read_output, daemon=True)
            self._reader.start()
            self._on_status(True)
        except Exception as e:
            self._on_output(f"[{_ts()}] ERROR AL INICIAR: {e}\n")
            self._on_status(False)

    def stop(self):
        if not self.running:
            return
        self._on_output(f"[{_ts()}] DETENIENDO PROCESO (PID {self._proc.pid})...\n")
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        except Exception:
            pass
        self._on_status(False)

    def _read_output(self):
        try:
            for line in self._proc.stdout:
                self._on_output(line)
        except Exception:
            pass
        ret = self._proc.wait()
        self._on_output(f"[{_ts()}] PROCESO FINALIZADO (CODIGO {ret})\n")
        self._on_status(False)

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

# ─────────────────────────────────────────────────────────────
# WIDGET: PANEL DE SERVICIO
# ─────────────────────────────────────────────────────────────

class ServicePanel(ctk.CTkFrame):
    def __init__(self, parent, service_def: dict, cfg: dict, cfg_save_cb):
        super().__init__(parent)
        self._svc      = service_def
        self._cfg      = cfg
        self._save_cfg = cfg_save_cb
        self._running  = False
        self._proc     = ServiceProcess(
            service_def["id"],
            on_output=self._append_output,
            on_status_change=self._on_status_change,
        )
        self._autostart_var = ctk.BooleanVar(value=get_autostart(service_def["id"]))
        self._option_vars: dict[str, ctk.Variable] = {}
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        header.columnconfigure(0, weight=1)

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(title_frame, text=self._svc["label"],
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=self._svc["color"]).pack(anchor="w")
        ctk.CTkLabel(title_frame, text=self._svc["description"],
                     font=ctk.CTkFont(size=12),
                     text_color="gray60", justify="left").pack(anchor="w", pady=(2, 0))

        self._status_lbl = ctk.CTkLabel(header, text=" DETENIDO ",
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        fg_color=COLOR_STOPPED, text_color="white",
                                        corner_radius=6, padx=10, pady=4)
        self._status_lbl.grid(row=0, column=1, padx=(10, 0))

        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 15))

        self._btn_start = ctk.CTkButton(ctrl, text="INICIAR", command=self._start,
                                        font=ctk.CTkFont(weight="bold"),
                                        fg_color=COLOR_RUNNING, hover_color=COLOR_RUNNING_HOVER,
                                        width=100)
        self._btn_start.grid(row=0, column=0, padx=(0, 10))

        self._btn_stop = ctk.CTkButton(ctrl, text="DETENER", command=self._stop,
                                       font=ctk.CTkFont(weight="bold"),
                                       fg_color=COLOR_STOPPED, hover_color=COLOR_STOPPED_HOVER,
                                       state="disabled", width=100)
        self._btn_stop.grid(row=0, column=1, padx=(0, 10))

        self._btn_restart = ctk.CTkButton(ctrl, text="REINICIAR", command=self._restart,
                                          font=ctk.CTkFont(weight="bold"),
                                          fg_color=COLOR_RESTART, hover_color=COLOR_RESTART_HOVER,
                                          state="disabled", width=100)
        self._btn_restart.grid(row=0, column=2, padx=(0, 20))

        auto_cb = ctk.CTkCheckBox(ctrl, text="Arrancar con el sistema",
                                  variable=self._autostart_var,
                                  command=self._toggle_autostart,
                                  font=ctk.CTkFont(size=12))
        auto_cb.grid(row=0, column=3)

        self._tabview = ctk.CTkTabview(self)
        self._tabview.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.rowconfigure(2, weight=1)

        tab_out = self._tabview.add("Registro del Sistema")
        tab_out.columnconfigure(0, weight=1)
        tab_out.rowconfigure(0, weight=1)

        self._output = ctk.CTkTextbox(tab_out, font=ctk.CTkFont(family="Consolas", size=12),
                                      text_color="#CCCCCC", state="disabled")
        self._output.grid(row=0, column=0, sticky="nsew", pady=(5, 10))

        ctk.CTkButton(tab_out, text="Limpiar registro", command=self._clear_output,
                      fg_color="transparent", border_width=1, text_color=("gray10", "gray90"),
                      hover_color=("gray70", "gray30"), width=120).grid(row=1, column=0, sticky="w")

        if self._svc["options"]:
            tab_opts = self._tabview.add("Configuracion de Red")
            self._build_options_tab(tab_opts)

    def _build_options_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        scroll_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll_frame.grid(row=0, column=0, sticky="nsew")

        ftp_opts = self._cfg.get("ftp_options", {})
        row = 0
        for flag, meta in self._svc["options"].items():
            saved = ftp_opts.get(flag, meta["default"])
            
            lbl_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
            lbl_frame.grid(row=row, column=0, sticky="w", padx=(0, 20), pady=(15, 0))
            
            ctk.CTkLabel(lbl_frame, text=flag, font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
                         text_color="#007ACC").pack(anchor="w")
            ctk.CTkLabel(lbl_frame, text=meta["help"], font=ctk.CTkFont(size=11),
                         text_color="gray60").pack(anchor="w", pady=(0, 5))

            t = meta["type"]
            if t == "bool":
                var = ctk.BooleanVar(value=bool(saved))
                cb = ctk.CTkCheckBox(scroll_frame, text="", variable=var)
                cb.grid(row=row, column=1, padx=10, pady=(15, 0), sticky="w")
            elif t == "choice":
                var = ctk.StringVar(value=str(saved))
                om = ctk.CTkComboBox(scroll_frame, variable=var, values=meta["choices"], state="readonly", width=160)
                om.grid(row=row, column=1, padx=10, pady=(15, 0), sticky="w")
            elif t == "path":
                var = ctk.StringVar(value=str(saved))
                row_f = ctk.CTkFrame(scroll_frame, fg_color="transparent")
                row_f.grid(row=row, column=1, padx=10, pady=(15, 0), sticky="ew")
                
                entry = ctk.CTkEntry(row_f, textvariable=var, font=ctk.CTkFont(family="Consolas", size=12), width=250)
                entry.pack(side="left")
                
                browse = ctk.CTkButton(row_f, text="Explorar", command=lambda v=var: self._browse_dir(v), width=80)
                browse.pack(side="left", padx=(10, 0))
            else:
                var = ctk.StringVar(value=str(saved))
                entry = ctk.CTkEntry(scroll_frame, textvariable=var, font=ctk.CTkFont(family="Consolas", size=12), width=340)
                entry.grid(row=row, column=1, padx=10, pady=(15, 0), sticky="w")

            self._option_vars[flag] = var
            row += 1

        save_btn = ctk.CTkButton(scroll_frame, text="GUARDAR CONFIGURACION", command=self._save_options,
                                 font=ctk.CTkFont(weight="bold"))
        save_btn.grid(row=row, column=0, columnspan=2, pady=(30, 10), sticky="w")

    def _build_args(self) -> list[str]:
        args = []
        for flag, meta in self._svc["options"].items():
            var = self._option_vars.get(flag)
            if var is None:
                continue
            val = var.get()
            t = meta["type"]
            if t == "bool":
                if val:
                    args.append(flag)
            elif t in ["str", "path", "choice"]:
                if str(val).strip():
                    if flag == "--users" and val.strip():
                        args.append(flag)
                        args.extend(val.strip().split())
                    else:
                        args += [flag, str(val)]
            elif t == "int":
                args += [flag, str(val)]
        return args

    def _start(self):
        self._save_options(silent=True)
        python   = self._cfg.get("python_path", sys.executable)
        work_dir = self._cfg.get("work_dir", str(Path(__file__).parent))
        script   = self._svc["script"]
        extra    = self._build_args()
        threading.Thread(
            target=self._proc.start,
            args=(python, work_dir, script, extra),
            daemon=True,
        ).start()

    def _stop(self):
        threading.Thread(target=self._proc.stop, daemon=True).start()

    def _restart(self):
        def _do():
            self._proc.stop()
            import time; time.sleep(1)
            self._start()
        threading.Thread(target=_do, daemon=True).start()

    def _toggle_autostart(self):
        enabled = self._autostart_var.get()
        python   = self._cfg.get("python_path", sys.executable)
        work_dir = self._cfg.get("work_dir", str(Path(__file__).parent))
        script   = self._svc["script"]
        extra    = self._build_args()
        full_script = str(Path(work_dir) / script)
        cmd = f'"{python}" "{full_script}"'
        if extra:
            cmd += " " + " ".join(shlex.quote(a) for a in extra)
        ok = set_autostart(self._svc["id"], enabled, cmd)
        if not ok:
            self._autostart_var.set(not enabled)

    def _save_options(self, silent=False):
        ftp_opts = {}
        for flag, var in self._option_vars.items():
            ftp_opts[flag] = var.get()
        self._cfg["ftp_options"] = ftp_opts
        self._save_cfg(self._cfg)
        if not silent:
            self._append_output(f"[{_ts()}] OPCIONES GUARDADAS CORRECTAMENTE.\n")

    def _browse_dir(self, var: ctk.StringVar):
        d = filedialog.askdirectory(initialdir=var.get() or ".")
        if d:
            var.set(d)

    def _clear_output(self):
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.configure(state="disabled")

    def _append_output(self, text: str):
        def _do():
            self._output.configure(state="normal")
            self._output.insert("end", text)
            self._output.see("end")
            self._output.configure(state="disabled")
        self._output.after(0, _do)

    def _on_status_change(self, running: bool):
        self._running = running
        def _do():
            bg_color = COLOR_RUNNING if running else COLOR_STOPPED
            label_text = " EN EJECUCION " if running else " DETENIDO "
            self._status_lbl.configure(text=label_text, fg_color=bg_color)
            
            st_start   = "disabled" if running else "normal"
            st_stop    = "normal"   if running else "disabled"
            self._btn_start.configure(state=st_start)
            self._btn_stop.configure(state=st_stop)
            self._btn_restart.configure(state=st_stop)
        self._output.after(0, _do)

# ─────────────────────────────────────────────────────────────
# VENTANA DE CONFIGURACIÓN GLOBAL
# ─────────────────────────────────────────────────────────────

class GlobalConfigDialog(ctk.CTkToplevel):
    def __init__(self, parent, cfg: dict, save_cb):
        super().__init__(parent)
        self.title("Configuración Global")
        self.geometry("600x250")
        self.resizable(False, False)
        
        self.transient(parent)
        self.grab_set()

        self._cfg     = cfg
        self._save_cb = save_cb
        self._build()

    def _build(self):
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=25, pady=25)

        ctk.CTkLabel(main_frame, text="Ejecutable Python", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self._py_var = ctk.StringVar(value=self._cfg.get("python_path", sys.executable))
        
        py_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        py_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        
        ctk.CTkEntry(py_frame, textvariable=self._py_var, font=ctk.CTkFont(family="Consolas"), width=400).pack(side="left")
        ctk.CTkButton(py_frame, text="Explorar", command=self._browse_python, width=80).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(main_frame, text="Directorio Base", font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, sticky="w", pady=(0, 5))
        self._wd_var = ctk.StringVar(value=self._cfg.get("work_dir", str(Path(__file__).parent)))
        
        wd_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        wd_frame.grid(row=3, column=0, sticky="ew", pady=(0, 25))
        
        ctk.CTkEntry(wd_frame, textvariable=self._wd_var, font=ctk.CTkFont(family="Consolas"), width=400).pack(side="left")
        ctk.CTkButton(wd_frame, text="Explorar", command=self._browse_wd, width=80).pack(side="left", padx=(10, 0))

        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.grid(row=4, column=0, sticky="w")
        
        ctk.CTkButton(btn_frame, text="GUARDAR CAMBIOS", command=self._save, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="CANCELAR", command=self.destroy, fg_color="transparent", border_width=1, 
                      text_color=("gray10", "gray90")).pack(side="left")

    def _browse_python(self):
        path = filedialog.askopenfilename(
            title="Seleccionar Python",
            filetypes=[("Python", "python*.exe python3*"), ("Todos", "*")],
            initialdir=str(Path(self._py_var.get()).parent),
        )
        if path:
            self._py_var.set(path)

    def _browse_wd(self):
        d = filedialog.askdirectory(initialdir=self._wd_var.get())
        if d:
            self._wd_var.set(d)

    def _save(self):
        self._cfg["python_path"] = self._py_var.get()
        self._cfg["work_dir"]    = self._wd_var.get()
        self._save_cb(self._cfg)
        self.destroy()

# ─────────────────────────────────────────────────────────────
# VENTANA PRINCIPAL
# ─────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(APP_TITLE)
        self.geometry("950x850")
        self.minsize(850, 750)
        
        self._cfg = load_config()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        topbar = ctk.CTkFrame(self, height=60, corner_radius=0)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        ctk.CTkLabel(topbar, text="PANEL DE CONTROL",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", padx=25, pady=15)

        ctk.CTkButton(topbar, text="CONFIGURACION GLOBAL",
                      command=self._open_global_config,
                      font=ctk.CTkFont(weight="bold"),
                      fg_color="transparent", border_width=1, text_color=("gray10", "gray90"),
                      hover_color=("gray70", "gray30")).pack(side="right", padx=25, pady=15)

        main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        main_scroll.pack(fill="both", expand=True, padx=15, pady=15)
        main_scroll.columnconfigure(0, weight=1)

        for i, (svc_id, svc_def) in enumerate(SERVICES.items()):
            panel = ServicePanel(main_scroll, svc_def, self._cfg, save_config)
            panel.grid(row=i, column=0, sticky="nsew", pady=(0, 20))
            main_scroll.rowconfigure(i, weight=1)

        statusbar = ctk.CTkFrame(self, height=30, corner_radius=0)
        statusbar.pack(fill="x", side="bottom")
        
        ctk.CTkLabel(statusbar, text=f"  Entorno Python: {self._cfg.get('python_path', sys.executable)}",
                     font=ctk.CTkFont(family="Consolas", size=11), text_color="gray50").pack(side="left", pady=4, padx=10)
        ctk.CTkLabel(statusbar, text=f"Directorio de Trabajo: {self._cfg.get('work_dir', '.')}  ",
                     font=ctk.CTkFont(family="Consolas", size=11), text_color="gray50").pack(side="right", pady=4, padx=10)

    def _open_global_config(self):
        GlobalConfigDialog(self, self._cfg, save_config)

    def _on_close(self):
        if messagebox.askokcancel("Cerrar Panel",
                "¿Desea cerrar el administrador?\n\nLos servicios en ejecución continuarán corriendo en segundo plano."):
            self.destroy()

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()