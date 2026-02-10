#!/usr/bin/env python3
"""
Bitcoin Puzzle Pool Worker v3.0 - Fully Standalone App

- Auto-installs to C:\\PuzzlePool (Windows) or ~/.puzzle-pool (Linux)
- Auto-downloads KeyHunt-Cuda scanning engine
- Creates desktop shortcut with icon
- System tray for background mining
- Modern GUI with live stats
- Zero setup required — just run and go
"""

import base64
import http.client
import json
import os
import platform
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "3.0.3"
POOL_URL = "https://starnetlive.space"
APP_NAME = "PuzzlePool"

# ─── Platform paths ────────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_FROZEN = getattr(sys, 'frozen', False)

if IS_WIN:
    INSTALL_DIR = Path("C:/PuzzlePool")
    KEYHUNT_NAME = "KeyHunt.exe"
    KEYHUNT_DL = f"{POOL_URL}/download/keyhunt-windows"
else:
    INSTALL_DIR = Path.home() / ".puzzle-pool"
    KEYHUNT_NAME = "KeyHunt"
    KEYHUNT_DL = f"{POOL_URL}/download/keyhunt-linux"

BIN_DIR = INSTALL_DIR / "bin"
KEYHUNT_PATH = BIN_DIR / KEYHUNT_NAME
CONFIG_FILE = INSTALL_DIR / "config.json"
LOG_DIR = INSTALL_DIR / "logs"
ICON_FILE = INSTALL_DIR / "icon.ico"
ICON_PNG = INSTALL_DIR / "icon.png"

# ─── Windows High-DPI ─────────────────────────────────────────────
if IS_WIN:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ─── Optional imports ──────────────────────────────────────────────
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

try:
    import pystray
    from PIL import Image as PilImage, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ─── Color IDs (used by worker code for log colors) ───────────────
GREEN = "green"
LGREEN = "green"
RED = "red"
YELLOW = "yellow"
GOLD = "gold"
CYAN = "cyan"
LBLUE = "cyan"
BLUE = "blue"
LGREY = "dim"
GREY = "dim"
DGREY = "dim"
PURPLE = "purple"


class CLR:
    BG     = "#080812"
    CARD   = "#12122a"
    ACCENT = "#f7931a"
    GOLD   = "#ffd700"
    GREEN  = "#00e676"
    RED    = "#ff5252"
    YELLOW = "#ffd740"
    CYAN   = "#00e5ff"
    BLUE   = "#448aff"
    PURPLE = "#b388ff"
    TEXT   = "#e0e0e8"
    DIM    = "#666680"
    VDIM   = "#3a3a50"


def _make_icon_image():
    """Generate a 64x64 Bitcoin icon as PIL Image."""
    if not HAS_TRAY:
        return None
    img = PilImage.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, 61, 61], fill='#f7931a')
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except Exception:
            font = None
    if font:
        d.text((32, 32), "B", fill='white', font=font, anchor='mm')
    else:
        d.text((22, 14), "B", fill='white')
    return img


def _get_icon_image():
    if HAS_TRAY and ICON_PNG.exists():
        try:
            return PilImage.open(str(ICON_PNG))
        except Exception:
            pass
    return _make_icon_image()


# ═══════════════════════════════════════════════════════════════════
# HTTP CLIENT
# ═══════════════════════════════════════════════════════════════════

class PoolAPI:
    def __init__(self, base_url, api_key=None):
        p = urllib.parse.urlparse(base_url)
        self.https = p.scheme == "https"
        self.host = p.hostname
        self.port = p.port or (443 if self.https else 80)
        self.base = p.path.rstrip("/")
        self.api_key = api_key
        self.timeout = 30

    def _conn(self):
        if self.https:
            return http.client.HTTPSConnection(
                self.host, self.port, timeout=self.timeout,
                context=ssl.create_default_context())
        return http.client.HTTPConnection(self.host, self.port,
                                           timeout=self.timeout)

    def _hdrs(self):
        h = {"Content-Type": "application/json",
             "User-Agent": f"PuzzleWorker/{VERSION}"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def get(self, path):
        c = self._conn()
        try:
            c.request("GET", self.base + path, headers=self._hdrs())
            r = c.getresponse()
            body = r.read().decode()
            if r.status >= 400:
                raise Exception(f"HTTP {r.status}: {body[:200]}")
            return json.loads(body)
        finally:
            c.close()

    def post(self, path, data):
        c = self._conn()
        try:
            c.request("POST", self.base + path,
                       json.dumps(data).encode(), self._hdrs())
            r = c.getresponse()
            body = r.read().decode()
            if r.status >= 400:
                raise Exception(f"HTTP {r.status}: {body[:200]}")
            return json.loads(body)
        finally:
            c.close()


# ═══════════════════════════════════════════════════════════════════
# INSTALLER
# ═══════════════════════════════════════════════════════════════════

class Installer:

    @staticmethod
    def is_ready():
        return KEYHUNT_PATH.exists()

    @staticmethod
    def setup_dirs():
        for d in [INSTALL_DIR, BIN_DIR, LOG_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def copy_self():
        if not IS_FROZEN:
            return
        src = Path(sys.executable)
        name = "puzzle-worker.exe" if IS_WIN else "puzzle-worker"
        dst = INSTALL_DIR / name
        if src.resolve() != dst.resolve():
            try:
                shutil.copy2(str(src), str(dst))
                if not IS_WIN:
                    dst.chmod(0o755)
            except Exception:
                pass

    @staticmethod
    def copy_icons():
        if IS_FROZEN:
            bdir = Path(sys._MEIPASS)
        else:
            bdir = Path(__file__).parent
        for name, dest in [("icon.ico", ICON_FILE), ("icon.png", ICON_PNG)]:
            src = bdir / name
            if src.exists() and not dest.exists():
                try:
                    shutil.copy2(str(src), str(dest))
                except Exception:
                    pass
        if not ICON_PNG.exists() and HAS_TRAY:
            try:
                img = _make_icon_image()
                if img:
                    img.save(str(ICON_PNG), format='PNG')
            except Exception:
                pass

    @staticmethod
    def _is_valid_binary():
        """Check if existing KeyHunt binary is valid (not a corrupt/wrong-platform file)."""
        if not KEYHUNT_PATH.exists():
            return False
        size = KEYHUNT_PATH.stat().st_size
        if size < 500_000:  # valid binary is >10MB, reject tiny files
            return False
        # Check PE header on Windows, ELF on Linux
        try:
            with open(str(KEYHUNT_PATH), 'rb') as f:
                magic = f.read(4)
            if IS_WIN:
                return magic[:2] == b'MZ'  # PE executable
            else:
                return magic == b'\x7fELF'  # ELF executable
        except Exception:
            return False

    @staticmethod
    def download_keyhunt(progress_cb=None):
        if KEYHUNT_PATH.exists() and Installer._is_valid_binary():
            return True
        # Remove invalid file if present
        if KEYHUNT_PATH.exists():
            try:
                KEYHUNT_PATH.unlink()
            except Exception:
                pass
        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                KEYHUNT_DL,
                headers={"User-Agent": f"PuzzleWorker/{VERSION}"})
            resp = urllib.request.urlopen(req, context=ctx, timeout=120)
            total = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            tmp = KEYHUNT_PATH.with_suffix('.tmp')
            with open(str(tmp), 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total > 0:
                        progress_cb(downloaded / total)
            tmp.rename(KEYHUNT_PATH)
            if not IS_WIN:
                KEYHUNT_PATH.chmod(0o755)
            return True
        except Exception as e:
            if progress_cb:
                progress_cb(-1, str(e))
            return False

    @staticmethod
    def create_shortcut():
        if IS_WIN:
            Installer._win_shortcut()
        else:
            Installer._linux_shortcut()

    @staticmethod
    def _win_shortcut():
        try:
            exe = str(INSTALL_DIR / "puzzle-worker.exe") if IS_FROZEN \
                else sys.executable
            desktop = Path.home() / "Desktop"
            lnk = desktop / "Puzzle Pool Worker.lnk"
            if lnk.exists():
                return
            ico = str(ICON_FILE) if ICON_FILE.exists() else exe
            ps = (
                '$ws = New-Object -ComObject WScript.Shell; '
                f'$sc = $ws.CreateShortcut("{lnk}"); '
                f'$sc.TargetPath = "{exe}"; '
                f'$sc.WorkingDirectory = "{INSTALL_DIR}"; '
                f'$sc.IconLocation = "{ico}"; '
                '$sc.Description = "Bitcoin Puzzle Pool Worker"; '
                '$sc.Save()'
            )
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(["powershell", "-Command", ps],
                           capture_output=True, startupinfo=si, timeout=10)
        except Exception:
            pass

    @staticmethod
    def _linux_shortcut():
        try:
            apps = Path.home() / ".local" / "share" / "applications"
            apps.mkdir(parents=True, exist_ok=True)
            exe = str(INSTALL_DIR / "puzzle-worker") if IS_FROZEN \
                else f"{sys.executable} {__file__}"
            ico = str(ICON_PNG) if ICON_PNG.exists() else ""
            content = (
                "[Desktop Entry]\nType=Application\n"
                "Name=Puzzle Pool Worker\n"
                "Comment=Bitcoin Puzzle Pool Miner\n"
                f"Exec={exe}\nIcon={ico}\n"
                "Terminal=false\nCategories=Utility;\n"
            )
            (apps / "puzzle-worker.desktop").write_text(content)
            dt = Path.home() / "Desktop"
            if dt.exists():
                dst = dt / "puzzle-worker.desktop"
                if not dst.exists():
                    dst.write_text(content)
                    dst.chmod(0o755)
        except Exception:
            pass

    @staticmethod
    def ensure_config():
        if CONFIG_FILE.exists():
            return
        cfg = {"worker_name": f"worker-{platform.node()}", "gpu_id": 0}
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ═══════════════════════════════════════════════════════════════════
# KEYHUNT RUNNER
# ═══════════════════════════════════════════════════════════════════

_RE_ADDR = re.compile(r"PubAddress:\s*(\S+)")
_RE_KEY = re.compile(r"Priv\s*\(HEX\):\s*([0-9a-fA-F]+)")
_RE_PROG = re.compile(r"\[.*?(\d+\.?\d*)%\]")
_RE_BYE = re.compile(r"BYE")


class KeyHuntRunner:
    def __init__(self, path=None, gpu_id=0):
        self.path = path or str(KEYHUNT_PATH)
        self.gpu_id = gpu_id
        self.proc = None
        self.pid = None

    def run(self, rs, re_, target, canaries, ui=None, timeout=600):
        addrs = [target] + canaries
        tmp = Path(tempfile.gettempdir()) / f"_pa_{os.getpid()}.txt"
        tmp.write_text("\n".join(addrs) + "\n")

        s = rs.replace("0x", "").lstrip("0") or "0"
        e = re_.replace("0x", "").lstrip("0") or "0"
        cmd = [self.path, "-m", "address", "-f", str(tmp),
               "-r", f"{s}:{e}", "-t", "0", "-b", "0",
               "-g", str(self.gpu_id), "-q"]

        result = {"status": "complete", "found_key": None,
                  "canary_keys": {}, "progress": 0.0}
        si = None
        if IS_WIN:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, startupinfo=si)
            self.pid = self.proc.pid
            if ui:
                ui.keyhunt_pid = self.pid

            t0 = time.time()
            cur_addr = None
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                m = _RE_ADDR.search(line)
                if m:
                    cur_addr = m.group(1)
                m = _RE_KEY.search(line)
                if m and cur_addr:
                    pk = m.group(1)
                    if cur_addr == target:
                        result["found_key"] = {"address": cur_addr,
                                               "privkey": pk}
                        result["status"] = "found"
                        self.kill()
                        break
                    elif cur_addr in canaries:
                        result["canary_keys"][cur_addr] = "0x" + pk
                        if ui:
                            ui.canary_found_set.add(cur_addr)
                            ui.canaries_found = len(result["canary_keys"])
                    cur_addr = None
                m = _RE_PROG.search(line)
                if m:
                    result["progress"] = float(m.group(1))
                    if ui:
                        ui.chunk_progress = result["progress"]
                if _RE_BYE.search(line):
                    result["status"] = "complete"
                    result["progress"] = 100.0
                    if ui:
                        ui.chunk_progress = 100.0
                if time.time() - t0 > timeout:
                    result["status"] = "timeout"
                    self.kill()
                    break

            if self.proc.poll() is None:
                self.proc.wait(timeout=10)
            if (self.proc.returncode and self.proc.returncode != 0
                    and result["status"] == "complete"):
                result["status"] = "error"
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            self.kill()
        finally:
            self.proc = None
            self.pid = None
            if ui:
                ui.keyhunt_pid = None
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        return result

    def kill(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════
# SYSTEM STATS
# ═══════════════════════════════════════════════════════════════════

def _gpu_stats(gpu_id=0):
    try:
        cmd = ["nvidia-smi", f"--id={gpu_id}",
               "--query-gpu=utilization.gpu,temperature.gpu,power.draw,"
               "memory.used,memory.total,name",
               "--format=csv,noheader,nounits"]
        si = None
        if IS_WIN:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=5, startupinfo=si)
        if r.returncode == 0:
            p = [x.strip() for x in r.stdout.strip().split(",")]
            if len(p) >= 6:
                return {
                    "usage": int(float(p[0])), "temp": int(float(p[1])),
                    "power": int(float(p[2])), "mem_used": int(float(p[3])),
                    "mem_total": int(float(p[4])),
                    "name": p[5].replace("NVIDIA ", "").replace("GeForce ", ""),
                }
    except Exception:
        pass
    return None


def _cpu_ram():
    cpu, ru, rt = 0, 0.0, 0.0
    if not IS_WIN:
        try:
            with open("/proc/stat") as f:
                p = f.readline().split()
                idle = int(p[4])
                total = sum(int(x) for x in p[1:])
                cpu = max(0, min(100, 100 - idle * 100 // total))
        except Exception:
            pass
        try:
            with open("/proc/meminfo") as f:
                m = {}
                for ln in f:
                    pp = ln.split()
                    m[pp[0].rstrip(":")] = int(pp[1])
                rt = m.get("MemTotal", 0) / 1048576
                ru = rt - m.get("MemAvailable", m.get("MemFree", 0)) / 1048576
        except Exception:
            pass
    else:
        try:
            import ctypes
            class MEMSTAT(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            ms = MEMSTAT()
            ms.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            rt = ms.ullTotalPhys / (1024 ** 3)
            ru = rt - ms.ullAvailPhys / (1024 ** 3)
        except Exception:
            pass
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            r = subprocess.run(["wmic", "cpu", "get", "loadpercentage"],
                               capture_output=True, text=True, timeout=5, startupinfo=si)
            for line in r.stdout.strip().split("\n"):
                if line.strip().isdigit():
                    cpu = int(line.strip())
                    break
        except Exception:
            pass
    return {"cpu": cpu, "ram_used": round(ru, 1), "ram_total": round(rt, 1)}


# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

def _load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_config(data):
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    old = _load_config()
    old.update(data)
    CONFIG_FILE.write_text(json.dumps(old, indent=2))


# ═══════════════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════════════

class WorkerGUI:
    TAG_MAP = {
        "green": CLR.GREEN, "red": CLR.RED, "yellow": CLR.YELLOW,
        "gold": CLR.GOLD, "cyan": CLR.CYAN, "blue": CLR.BLUE,
        "purple": CLR.PURPLE, "dim": CLR.DIM, "default": CLR.TEXT,
    }

    def __init__(self):
        self.running = True
        self._tick = 0
        self._tray = None
        self._worker_stop = None

        # ── Shared state (worker writes, GUI reads) ──
        self.status = "STARTING"
        self.status_color = YELLOW
        self.worker_name = ""
        self.pool_url = POOL_URL
        self.gpu_name = "Detecting..."
        self.keyhunt_pid = None
        self.current_chunk = None
        self.chunk_range_start = ""
        self.chunk_range_end = ""
        self.chunk_progress = 0.0
        self.canaries_total = 5
        self.canaries_found = 0
        self.canary_addresses = []
        self.canary_found_set = set()
        self.chunks_done = 0
        self.chunks_accepted = 0
        self.chunks_rejected = 0
        self.keys_scanned = 0
        self.session_start = time.time()
        self.gpu_usage = 0
        self.gpu_temp = 0
        self.gpu_power = 0
        self.gpu_mem_used = 0
        self.gpu_mem_total = 0
        self.cpu_usage = 0
        self.ram_used = 0.0
        self.ram_total = 0.0
        self.pool_active = 0
        self.pool_progress = 0.0
        self.pool_speed = 0
        self.pool_eta = 0
        self.pool_total_keys = 0
        self.pool_keys_remaining = 0
        self.pool_found = 0
        self._log_lock = threading.Lock()
        self.log_lines = []
        self.install_done = False

        # ── Window ──
        self.root = ctk.CTk()
        self.root.title(f"Puzzle Pool Worker v{VERSION}")
        self.root.geometry("800x780")
        self.root.minsize(740, 700)
        if ICON_FILE.exists():
            try:
                self.root.iconbitmap(str(ICON_FILE))
            except Exception:
                pass

        self._build_install_screen()
        self._build_main_screen()
        self._main_frame.pack_forget()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ────────── Install splash screen ──────────

    def _build_install_screen(self):
        self._inst = ctk.CTkFrame(self.root, fg_color="transparent")
        self._inst.pack(fill="both", expand=True)
        ctk.CTkFrame(self._inst, fg_color="transparent", height=150).pack()
        ctk.CTkLabel(self._inst, text="B", font=("", 60, "bold"),
                     text_color=CLR.ACCENT).pack()
        ctk.CTkLabel(self._inst, text="Puzzle Pool Worker",
                     font=("", 24, "bold"), text_color=CLR.ACCENT).pack(pady=(10, 5))
        ctk.CTkLabel(self._inst, text=f"v{VERSION}", font=("", 12),
                     text_color=CLR.DIM).pack()
        self._lbl_inst = ctk.CTkLabel(self._inst, text="Initializing...",
                                       font=("", 13), text_color=CLR.TEXT)
        self._lbl_inst.pack(pady=(40, 10))
        self._pb_inst = ctk.CTkProgressBar(self._inst, width=400, height=18,
                                            progress_color=CLR.ACCENT,
                                            fg_color="#1a1a30", corner_radius=6)
        self._pb_inst.pack()
        self._pb_inst.set(0)
        self._lbl_inst2 = ctk.CTkLabel(self._inst, text="", font=("", 10),
                                        text_color=CLR.DIM)
        self._lbl_inst2.pack(pady=(10, 0))

    def show_install_progress(self, msg, pct=None, detail=""):
        try:
            self.root.after_idle(lambda: self._upd_inst(msg, pct, detail))
        except Exception:
            pass

    def _upd_inst(self, msg, pct, detail):
        self._lbl_inst.configure(text=msg)
        if pct is not None:
            self._pb_inst.set(max(0, min(1, pct)))
        if detail:
            self._lbl_inst2.configure(text=detail)

    def switch_to_main(self):
        try:
            self.root.after_idle(self._do_switch)
        except Exception:
            pass

    def _do_switch(self):
        self._inst.pack_forget()
        self._main_frame.pack(fill="both", expand=True)
        self.install_done = True
        self._refresh()

    # ────────── Main screen ──────────

    def _build_main_screen(self):
        self._main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self._main_frame.pack(fill="both", expand=True)
        m = self._main_frame
        pad = {"padx": 10, "pady": (0, 5)}

        # Header
        hdr = ctk.CTkFrame(m, fg_color="#14142a", corner_radius=10, height=52)
        hdr.pack(fill="x", padx=10, pady=(8, 6))
        hdr.pack_propagate(False)
        self._lbl_btc = ctk.CTkLabel(hdr, text="BTC", font=("", 20, "bold"),
                                      text_color=CLR.ACCENT)
        self._lbl_btc.pack(side="left", padx=(16, 8))
        ctk.CTkLabel(hdr, text="PUZZLE POOL WORKER", font=("", 15, "bold"),
                     text_color=CLR.ACCENT).pack(side="left")
        ctk.CTkLabel(hdr, text=f"v{VERSION}", font=("", 10),
                     text_color=CLR.DIM).pack(side="right", padx=16)

        # Status
        sc = ctk.CTkFrame(m, fg_color=CLR.CARD, corner_radius=10)
        sc.pack(fill="x", **pad)
        si = ctk.CTkFrame(sc, fg_color="transparent")
        si.pack(fill="x", padx=14, pady=10)
        r1 = ctk.CTkFrame(si, fg_color="transparent")
        r1.pack(fill="x")
        ctk.CTkLabel(r1, text="STATUS", font=("", 10), text_color=CLR.DIM).pack(side="left")
        self._lbl_dot = ctk.CTkLabel(r1, text="\u25cf", font=("", 14), text_color=CLR.YELLOW)
        self._lbl_dot.pack(side="left", padx=(8, 3))
        self._lbl_status = ctk.CTkLabel(r1, text="STARTING", font=("", 12, "bold"),
                                         text_color=CLR.YELLOW)
        self._lbl_status.pack(side="left")
        ctk.CTkLabel(r1, text="POOL", font=("", 10), text_color=CLR.DIM).pack(side="left", padx=(32, 6))
        self._lbl_pool = ctk.CTkLabel(r1, text=POOL_URL.replace("https://", ""),
                                       font=("", 11, "bold"), text_color=CLR.CYAN)
        self._lbl_pool.pack(side="left")
        r2 = ctk.CTkFrame(si, fg_color="transparent")
        r2.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(r2, text="WORKER", font=("", 10), text_color=CLR.DIM).pack(side="left")
        self._lbl_worker = ctk.CTkLabel(r2, text="...", font=("", 11, "bold"), text_color=CLR.CYAN)
        self._lbl_worker.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(r2, text="GPU", font=("", 10), text_color=CLR.DIM).pack(side="left", padx=(32, 6))
        self._lbl_gpu = ctk.CTkLabel(r2, text="Detecting...", font=("", 11, "bold"), text_color=CLR.GREEN)
        self._lbl_gpu.pack(side="left")

        # Current scan
        scan = ctk.CTkFrame(m, fg_color=CLR.CARD, corner_radius=10)
        scan.pack(fill="x", **pad)
        si2 = ctk.CTkFrame(scan, fg_color="transparent")
        si2.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(si2, text="CURRENT SCAN", font=("", 12, "bold"), text_color=CLR.GOLD).pack(anchor="w")
        self._lbl_chunk = ctk.CTkLabel(si2, text="Waiting for work...", font=("", 11, "bold"), text_color=CLR.DIM)
        self._lbl_chunk.pack(anchor="w", pady=(6, 0))
        self._lbl_range = ctk.CTkLabel(si2, text="", font=("", 10), text_color=CLR.DIM)
        self._lbl_range.pack(anchor="w", pady=(2, 0))
        pb = ctk.CTkFrame(si2, fg_color="transparent")
        pb.pack(fill="x", pady=(8, 0))
        self._pb_scan = ctk.CTkProgressBar(pb, height=20, progress_color=CLR.ACCENT,
                                            fg_color="#1a1a30", corner_radius=6)
        self._pb_scan.pack(side="left", fill="x", expand=True)
        self._pb_scan.set(0)
        self._lbl_pct = ctk.CTkLabel(pb, text="0.0%", font=("", 12, "bold"),
                                      text_color=CLR.ACCENT, width=65)
        self._lbl_pct.pack(side="right", padx=(10, 0))
        cr = ctk.CTkFrame(si2, fg_color="transparent")
        cr.pack(anchor="w", pady=(8, 0))
        ctk.CTkLabel(cr, text="CANARIES", font=("", 10), text_color=CLR.DIM).pack(side="left", padx=(0, 8))
        self._can = []
        for _ in range(5):
            l = ctk.CTkLabel(cr, text="\u25cb", font=("", 12), text_color=CLR.VDIM)
            l.pack(side="left", padx=3)
            self._can.append(l)

        # Stats
        st = ctk.CTkFrame(m, fg_color=CLR.CARD, corner_radius=10)
        st.pack(fill="x", **pad)
        si3 = ctk.CTkFrame(st, fg_color="transparent")
        si3.pack(fill="x", padx=14, pady=10)
        cols = ctk.CTkFrame(si3, fg_color="transparent")
        cols.pack(fill="x")
        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(left, text="MY STATS", font=("", 12, "bold"), text_color=CLR.GOLD).pack(anchor="w")
        self._sv = {}
        for k, lb in [("chunks", "Chunks"), ("keys", "Keys"), ("speed", "Speed"), ("uptime", "Uptime")]:
            row = ctk.CTkFrame(left, fg_color="transparent")
            row.pack(anchor="w", fill="x", pady=1)
            ctk.CTkLabel(row, text=f"  {lb}", font=("", 10), text_color=CLR.DIM, width=65, anchor="w").pack(side="left")
            v = ctk.CTkLabel(row, text="--", font=("", 10, "bold"), text_color=CLR.TEXT)
            v.pack(side="left")
            self._sv[k] = v
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.pack(side="right", fill="both", expand=True)
        ctk.CTkLabel(right, text="SYSTEM", font=("", 12, "bold"), text_color=CLR.GOLD).pack(anchor="w")
        for k, lb in [("gpu", "GPU"), ("vram", "VRAM"), ("cpu", "CPU"), ("ram", "RAM")]:
            row = ctk.CTkFrame(right, fg_color="transparent")
            row.pack(anchor="w", fill="x", pady=1)
            ctk.CTkLabel(row, text=f"  {lb}", font=("", 10), text_color=CLR.DIM, width=55, anchor="w").pack(side="left")
            v = ctk.CTkLabel(row, text="--", font=("", 10, "bold"), text_color=CLR.TEXT)
            v.pack(side="left")
            self._sv[k] = v

        # Pool network
        pf = ctk.CTkFrame(m, fg_color=CLR.CARD, corner_radius=10)
        pf.pack(fill="x", **pad)
        si4 = ctk.CTkFrame(pf, fg_color="transparent")
        si4.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(si4, text="POOL NETWORK", font=("", 12, "bold"), text_color=CLR.GOLD).pack(anchor="w")
        pr = ctk.CTkFrame(si4, fg_color="transparent")
        pr.pack(fill="x", pady=(4, 0))
        for k, lb in [("p_workers", "Workers"), ("p_speed", "Speed"), ("p_eta", "ETA")]:
            ctk.CTkLabel(pr, text=lb, font=("", 10), text_color=CLR.DIM).pack(side="left")
            v = ctk.CTkLabel(pr, text="--", font=("", 10, "bold"), text_color=CLR.TEXT)
            v.pack(side="left", padx=(4, 18))
            self._sv[k] = v
        ppb = ctk.CTkFrame(si4, fg_color="transparent")
        ppb.pack(fill="x", pady=(6, 0))
        self._pb_pool = ctk.CTkProgressBar(ppb, height=16, progress_color=CLR.GREEN,
                                            fg_color="#1a1a30", corner_radius=5)
        self._pb_pool.pack(side="left", fill="x", expand=True)
        self._pb_pool.set(0)
        self._lbl_ppct = ctk.CTkLabel(ppb, text="0.000000%", font=("", 10, "bold"),
                                       text_color=CLR.GREEN, width=90)
        self._lbl_ppct.pack(side="right", padx=(8, 0))
        pr2 = ctk.CTkFrame(si4, fg_color="transparent")
        pr2.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(pr2, text="Scanned", font=("", 10), text_color=CLR.DIM).pack(side="left")
        self._sv["p_sc"] = ctk.CTkLabel(pr2, text="--", font=("", 10, "bold"), text_color=CLR.ACCENT)
        self._sv["p_sc"].pack(side="left", padx=(4, 18))
        ctk.CTkLabel(pr2, text="Remaining", font=("", 10), text_color=CLR.DIM).pack(side="left")
        self._sv["p_rm"] = ctk.CTkLabel(pr2, text="--", font=("", 10, "bold"), text_color=CLR.BLUE)
        self._sv["p_rm"].pack(side="left", padx=(4, 0))
        self._lbl_found = ctk.CTkLabel(si4, text="", font=("", 13, "bold"), text_color=CLR.GREEN)
        self._lbl_found.pack(anchor="w")

        # Log
        lc = ctk.CTkFrame(m, fg_color=CLR.CARD, corner_radius=10)
        lc.pack(fill="both", expand=True, **pad)
        mono = "Consolas" if IS_WIN else "monospace"
        self._lb = ctk.CTkTextbox(lc, font=(mono, 10), fg_color="#06060e",
                                   text_color=CLR.DIM, corner_radius=8, state="disabled")
        self._lb.pack(fill="both", expand=True, padx=8, pady=8)
        tw = self._lb._textbox
        for t, c in [("t_green", CLR.GREEN), ("t_red", CLR.RED), ("t_yellow", CLR.YELLOW),
                     ("t_cyan", CLR.CYAN), ("t_blue", CLR.BLUE), ("t_purple", CLR.PURPLE),
                     ("t_dim", CLR.DIM), ("t_default", CLR.TEXT), ("t_time", CLR.VDIM)]:
            tw.tag_config(t, foreground=c)

        # Footer
        ft = ctk.CTkFrame(m, fg_color="transparent", height=28)
        ft.pack(fill="x", padx=10)
        lk = ctk.CTkLabel(ft, text="Dashboard: https://starnetlive.space",
                           font=("", 11), text_color=CLR.CYAN, cursor="hand2")
        lk.pack(side="left")
        lk.bind("<Button-1>", lambda e: __import__("webbrowser").open(POOL_URL))
        ctk.CTkLabel(ft, text="Close = minimize to tray", font=("", 10),
                     text_color=CLR.DIM).pack(side="right")

    # ────────── Formatting ──────────

    @staticmethod
    def _fk(n):
        if n >= 1e18: return f"{n/1e18:.2f} Exa"
        if n >= 1e15: return f"{n/1e15:.2f} P"
        if n >= 1e12: return f"{n/1e12:.2f} T"
        if n >= 1e9:  return f"{n/1e9:.2f} B"
        if n >= 1e6:  return f"{n/1e6:.2f} M"
        if n >= 1e3:  return f"{n:,.0f}"
        return str(int(n))

    @staticmethod
    def _fs(v):
        if v >= 1e12: return f"{v/1e12:.2f} TK/s"
        if v >= 1e9:  return f"{v/1e9:.2f} GK/s"
        if v >= 1e6:  return f"{v/1e6:.2f} MK/s"
        return f"{v:.0f} K/s"

    @staticmethod
    def _fd(s):
        if s <= 0 or s > 1e15: return "--"
        y, s = divmod(int(s), 31557600)
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        mi = s // 60
        if y > 0: return f"{y}y {d}d"
        if d > 0: return f"{d}d {h}h"
        if h > 0: return f"{h}h {mi}m"
        return f"{mi}m"

    # ────────── Logging ──────────

    def log(self, msg, color=LGREY):
        ts = time.strftime("%H:%M:%S")
        tag = f"t_{color}" if color in ("green","red","yellow","cyan","blue","purple","dim") else "t_default"
        with self._log_lock:
            self.log_lines.append((ts, msg, tag))
            if len(self.log_lines) > 100:
                self.log_lines.pop(0)
        try:
            self.root.after_idle(self._flush_log)
        except Exception:
            pass

    def _flush_log(self):
        with self._log_lock:
            lines = list(self.log_lines)
        tw = self._lb._textbox
        self._lb.configure(state="normal")
        tw.delete("1.0", "end")
        for ts, msg, tag in lines[-30:]:
            tw.insert("end", f"[{ts}] ", "t_time")
            tw.insert("end", f"{msg}\n", tag)
        tw.see("end")
        self._lb.configure(state="disabled")

    # ────────── Refresh loop ──────────

    def _refresh(self):
        if not self.running:
            return
        self._tick += 1
        hx = self.TAG_MAP.get(self.status_color, CLR.TEXT)
        self._lbl_status.configure(text=self.status, text_color=hx)
        show = self._tick % 4 < 3 or self.status != "SCANNING"
        self._lbl_dot.configure(text_color=hx if show else CLR.CARD)
        self._lbl_worker.configure(text=self.worker_name or "...")
        self._lbl_gpu.configure(text=self.gpu_name[:40])

        if self.current_chunk is not None:
            self._lbl_chunk.configure(text=f"Chunk #{self.current_chunk:,}", text_color=CLR.ACCENT)
            self._lbl_range.configure(text=f"{self.chunk_range_start}  \u2192  {self.chunk_range_end}")
        else:
            self._lbl_chunk.configure(text="Waiting for work...", text_color=CLR.DIM)
            self._lbl_range.configure(text="")

        self._pb_scan.set(max(0, min(1, self.chunk_progress / 100)))
        self._lbl_pct.configure(text=f"{self.chunk_progress:.1f}%")

        for i in range(5):
            if i < len(self.canary_addresses):
                a = self.canary_addresses[i]
                sh = a[:5] + ".." + a[-3:]
                if a in self.canary_found_set:
                    self._can[i].configure(text=f"\u2713 {sh}", text_color=CLR.GREEN)
                else:
                    self._can[i].configure(text=f"\u25cb {sh}", text_color=CLR.VDIM)
            else:
                self._can[i].configure(text="\u25cb", text_color=CLR.VDIM)

        el = time.time() - self.session_start
        spd = self.keys_scanned / el if el > 0 and self.keys_scanned > 0 else 0
        ct = f"{self.chunks_done} done"
        if self.chunks_accepted: ct += f"  {self.chunks_accepted} ok"
        if self.chunks_rejected: ct += f"  {self.chunks_rejected} rej"
        self._sv["chunks"].configure(text=ct, text_color=CLR.RED if self.chunks_rejected else CLR.GREEN)
        self._sv["keys"].configure(text=self._fk(self.keys_scanned), text_color=CLR.ACCENT)
        self._sv["speed"].configure(text=self._fs(spd), text_color=CLR.CYAN)
        self._sv["uptime"].configure(text=self._fd(el), text_color=CLR.BLUE)

        self._sv["gpu"].configure(
            text=f"{self.gpu_usage}%  {self.gpu_temp}\u00b0C  {self.gpu_power}W",
            text_color=CLR.GREEN if self.gpu_usage > 0 else CLR.DIM)
        self._sv["vram"].configure(text=f"{self.gpu_mem_used}/{self.gpu_mem_total} MB", text_color=CLR.CYAN)
        self._sv["cpu"].configure(text=f"{self.cpu_usage}%", text_color=CLR.GREEN)
        self._sv["ram"].configure(text=f"{self.ram_used}/{self.ram_total} GB", text_color=CLR.CYAN)

        self._sv["p_workers"].configure(text=str(self.pool_active), text_color=CLR.GREEN)
        self._sv["p_speed"].configure(text=self._fs(self.pool_speed), text_color=CLR.CYAN)
        self._sv["p_eta"].configure(text=self._fd(self.pool_eta), text_color=CLR.PURPLE)
        self._pb_pool.set(max(0, min(1, self.pool_progress / 100)))
        self._lbl_ppct.configure(text=f"{self.pool_progress:.6f}%")
        self._sv["p_sc"].configure(text=self._fk(self.pool_total_keys))
        self._sv["p_rm"].configure(text=self._fk(self.pool_keys_remaining))

        if self.pool_found > 0:
            self._lbl_found.configure(text=f"\u2605 {self.pool_found} KEY(S) FOUND! \u2605")
        else:
            self._lbl_found.configure(text="")

        self.root.after(250, self._refresh)

    # ────────── System tray ──────────

    def setup_tray(self):
        if not HAS_TRAY:
            return
        icon_img = _get_icon_image()
        if not icon_img:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._tray_show, default=True),
            pystray.MenuItem("Quit", self._tray_quit),
        )
        self._tray = pystray.Icon("PuzzleWorker", icon_img,
                                   "Puzzle Pool Worker", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _tray_show(self, *_):
        try:
            self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))
        except Exception:
            pass

    def _tray_quit(self, *_):
        self.running = False
        if self._tray:
            self._tray.stop()
        try:
            self.root.after(100, self.root.destroy)
        except Exception:
            pass

    def _on_close(self):
        if HAS_TRAY and self._tray:
            self.root.withdraw()
        else:
            self.running = False
            self.root.after(200, self.root.destroy)

    def render_loop(self):
        pass

    def stop(self):
        self.running = False
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        try:
            self.root.after(100, self.root.destroy)
        except Exception:
            pass

    def mainloop(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════
# WORKER LOGIC
# ═══════════════════════════════════════════════════════════════════

class PoolWorker:
    def __init__(self, gpu_id=0, ui=None):
        self.gpu_id = gpu_id
        self.api = PoolAPI(POOL_URL)
        self.runner = KeyHuntRunner(str(KEYHUNT_PATH), gpu_id)
        self.ui = ui
        self.running = True
        self.chunk_size = 2 ** 36

    def _log(self, msg, color=LGREY):
        if self.ui:
            self.ui.log(msg, color)

    def register(self):
        cfg = _load_config()
        if cfg.get("api_key"):
            self.api.api_key = cfg["api_key"]
            self._log("Loaded saved credentials", GREEN)
            return
        name = cfg.get("worker_name", f"worker-{platform.node()}")
        self._log(f"Registering as '{name}'...", YELLOW)
        resp = self.api.post("/api/register", {"name": name})
        if resp.get("status") != "ok":
            raise RuntimeError(f"Registration failed: {resp}")
        self.api.api_key = resp["api_key"]
        _save_config({"api_key": resp["api_key"]})
        self._log(f"Registered as worker #{resp['worker_id']}", GREEN)

    def _fetch_pool_stats(self):
        try:
            d = self.api.get("/api/stats")
            if self.ui:
                self.ui.pool_active = d["pool"]["active_workers"]
                self.ui.pool_progress = d["progress"]["percentage"]
                self.ui.pool_speed = d["pool"]["est_keys_per_sec"]
                self.ui.pool_eta = d["pool"]["est_eta_seconds"]
                self.ui.pool_total_keys = d["progress"]["total_keys_scanned"]
                self.ui.pool_keys_remaining = d["progress"]["keys_remaining"]
                self.ui.pool_found = d["pool"]["keys_found"]
        except Exception:
            pass

    def _stats_loop(self):
        while self.running:
            self._fetch_pool_stats()
            time.sleep(10)

    def _sys_loop(self):
        while self.running:
            g = _gpu_stats(self.gpu_id)
            if g and self.ui:
                self.ui.gpu_usage = g["usage"]
                self.ui.gpu_temp = g["temp"]
                self.ui.gpu_power = g["power"]
                self.ui.gpu_mem_used = g["mem_used"]
                self.ui.gpu_mem_total = g["mem_total"]
                if g["name"]:
                    self.ui.gpu_name = g["name"]
            cr = _cpu_ram()
            if self.ui:
                self.ui.cpu_usage = cr["cpu"]
                self.ui.ram_used = cr["ram_used"]
                self.ui.ram_total = cr["ram_total"]
            time.sleep(2)

    def run(self):
        cfg = _load_config()
        name = cfg.get("worker_name", f"worker-{platform.node()}")
        if self.ui:
            self.ui.worker_name = name
            self.ui.status = "CONNECTING"
            self.ui.status_color = YELLOW
        self.register()
        if self.ui:
            self.ui.status = "SCANNING"
            self.ui.status_color = GREEN
        threading.Thread(target=self._stats_loop, daemon=True).start()
        threading.Thread(target=self._sys_loop, daemon=True).start()
        self._fetch_pool_stats()
        no_work = 0
        while self.running:
            try:
                work = self.api.get("/api/work")
            except Exception as e:
                self._log(f"Connection error: {e}", RED)
                if self.ui:
                    self.ui.status = "RECONNECTING"
                    self.ui.status_color = RED
                time.sleep(10)
                continue
            if work.get("status") == "no_work":
                no_work += 1
                wait = min(30 * no_work, 300)
                self._log(f"No work available. Retry in {wait}s...", YELLOW)
                if self.ui:
                    self.ui.status = "WAITING"
                    self.ui.status_color = YELLOW
                time.sleep(wait)
                continue
            no_work = 0
            if self.ui:
                self.ui.status = "SCANNING"
                self.ui.status_color = GREEN
            target = work["target_address"]
            chunks = work["chunks"]
            self._log(f"Got {len(chunks)} chunks from pool", CYAN)
            completed = []
            for chunk in chunks:
                if not self.running:
                    break
                cid = chunk["chunk_id"]
                rs = chunk["range_start"]
                re_ = chunk["range_end"]
                canaries = chunk["canary_addresses"]
                if self.ui:
                    self.ui.current_chunk = cid
                    self.ui.chunk_range_start = rs
                    self.ui.chunk_range_end = re_
                    self.ui.chunk_progress = 0.0
                    self.ui.canary_addresses = canaries
                    self.ui.canary_found_set = set()
                    self.ui.canaries_found = 0
                self._log(f"Scanning chunk #{cid:,}...", LBLUE)
                result = self.runner.run(rs, re_, target, canaries, self.ui)
                if result["status"] == "found":
                    self._log("KEY FOUND! Reporting to pool...", GREEN)
                    if self.ui:
                        self.ui.status = "KEY FOUND!"
                        self.ui.status_color = GREEN
                    try:
                        self.api.post("/api/found", {
                            "chunk_id": cid,
                            "private_key": result["found_key"]["privkey"],
                        })
                        self._log("Key reported to pool!", GREEN)
                    except Exception as e:
                        self._log(f"FAILED to report key: {e}", RED)
                    completed.append({"chunk_id": cid, "canary_keys": result["canary_keys"]})
                    break
                if result["status"] in ("complete", "timeout"):
                    nc = len(result["canary_keys"])
                    self._log(f"Chunk #{cid:,} done. Canaries: {nc}/{len(canaries)}",
                              GREEN if nc == len(canaries) else YELLOW)
                    completed.append({"chunk_id": cid, "canary_keys": result["canary_keys"]})
                    if self.ui:
                        self.ui.chunks_done += 1
                        self.ui.keys_scanned += self.chunk_size
                else:
                    self._log(f"Chunk #{cid:,} error: {result.get('error', result['status'])}", RED)
            if completed:
                try:
                    rpt = self.api.post("/api/work", {"results": completed})
                    ac, rj = rpt.get("accepted", 0), rpt.get("rejected", 0)
                    if self.ui:
                        self.ui.chunks_accepted += ac
                        self.ui.chunks_rejected += rj
                    self._log(f"Reported: {ac} accepted, {rj} rejected",
                              GREEN if rj == 0 else YELLOW)
                except Exception as e:
                    self._log(f"Report error: {e}", RED)


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def _bg_thread(gui):
    """Background: install then run worker."""
    try:
        gui.show_install_progress("Creating folders...", 0.1)
        Installer.setup_dirs()
        Installer.ensure_config()
        Installer.copy_icons()
        time.sleep(0.3)

        gui.show_install_progress("Setting up...", 0.2)
        Installer.copy_self()
        time.sleep(0.3)

        if not Installer.is_ready():
            gui.show_install_progress("Downloading scanning engine...", 0.3,
                                       "One-time download")

            def on_dl(pct, err=None):
                if err:
                    gui.show_install_progress(f"Error: {err}", 0.3)
                elif pct >= 0:
                    gui.show_install_progress("Downloading scanning engine...",
                                               0.3 + pct * 0.5,
                                               f"{int(pct * 100)}%")

            if not Installer.download_keyhunt(on_dl):
                gui.show_install_progress(
                    "Download failed — check internet and restart", 0)
                return
        else:
            gui.show_install_progress("Engine ready", 0.8)

        gui.show_install_progress("Creating shortcut...", 0.9)
        Installer.create_shortcut()
        time.sleep(0.3)

        gui.show_install_progress("Ready!", 1.0)
        time.sleep(0.5)
        gui.switch_to_main()

        cfg = _load_config()
        worker = PoolWorker(cfg.get("gpu_id", 0), gui)
        gui._worker_stop = lambda: (setattr(worker, 'running', False), worker.runner.kill())
        worker.run()
    except Exception as e:
        gui.log(f"Fatal: {e}", RED)
        gui.show_install_progress(f"Error: {e}", 0)


def main():
    if not HAS_GUI:
        print(f"\nPuzzle Pool Worker v{VERSION}")
        print("GUI libraries missing. Download the standalone EXE:")
        print("  https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases\n")
        sys.exit(1)

    gui = WorkerGUI()
    gui.setup_tray()

    t = threading.Thread(target=_bg_thread, args=(gui,), daemon=True)
    t.start()

    signal.signal(signal.SIGINT, lambda *_: gui.stop())
    signal.signal(signal.SIGTERM, lambda *_: gui.stop())

    gui.mainloop()

    if gui._worker_stop:
        gui._worker_stop()


if __name__ == "__main__":
    main()
