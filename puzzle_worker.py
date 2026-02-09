#!/usr/bin/env python3
"""
Bitcoin Puzzle Pool Worker v2.0 - Modern GUI
Uses CustomTkinter for a sleek dark-themed interface.
Standalone single file. Connects to starnetlive.space pool.
"""

import argparse
import http.client
import json
import os
import platform
import re
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

VERSION = "2.0.0"
DEFAULT_POOL = "https://starnetlive.space"
CONFIG_DIR = Path.home() / ".puzzle-worker"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Windows High-DPI awareness (must be set before any GUI)
if platform.system() == "Windows":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# Try importing CustomTkinter for modern GUI
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

# ─── Color identifiers (used as log color tags) ────────────────────
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


class _Clr:
    """Hex color palette for GUI."""
    BG       = "#080812"
    CARD     = "#12122a"
    ACCENT   = "#f7931a"
    GOLD     = "#ffd700"
    GREEN    = "#00e676"
    DGREEN   = "#00aa55"
    RED      = "#ff5252"
    YELLOW   = "#ffd740"
    CYAN     = "#00e5ff"
    BLUE     = "#448aff"
    PURPLE   = "#b388ff"
    TEXT     = "#e0e0e8"
    DIM      = "#666680"
    VDIM     = "#3a3a50"
    BORDER   = "#252540"

CLR = _Clr


# ═══════════════════════════════════════════════════════════════════
# HTTP CLIENT (zero external deps)
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
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _hdrs(self):
        h = {"Content-Type": "application/json", "User-Agent": f"PuzzleWorker/{VERSION}"}
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
            c.request("POST", self.base + path, json.dumps(data).encode(), self._hdrs())
            r = c.getresponse()
            body = r.read().decode()
            if r.status >= 400:
                raise Exception(f"HTTP {r.status}: {body[:200]}")
            return json.loads(body)
        finally:
            c.close()


# ═══════════════════════════════════════════════════════════════════
# KEYHUNT-CUDA SUBPROCESS RUNNER
# ═══════════════════════════════════════════════════════════════════

_RE_ADDR = re.compile(r"PubAddress:\s*(\S+)")
_RE_KEY = re.compile(r"Priv\s*\(HEX\):\s*([0-9a-fA-F]+)")
_RE_PROG = re.compile(r"\[.*?(\d+\.?\d*)%\]")
_RE_BYE = re.compile(r"BYE")


class KeyHuntRunner:
    def __init__(self, path, gpu_id=0):
        self.path = path
        self.gpu_id = gpu_id
        self.proc = None
        self.pid = None

    def run(self, rs, re_, target, canaries, ui=None, timeout=600):
        addrs = [target] + canaries
        tmp = Path(os.environ.get("TEMP", "/tmp")) / f"_pa_{os.getpid()}.txt"
        tmp.write_text("\n".join(addrs) + "\n")

        s = rs.replace("0x", "").lstrip("0") or "0"
        e = re_.replace("0x", "").lstrip("0") or "0"
        cmd = [self.path, "-m", "address", "-f", str(tmp),
               "-r", f"{s}:{e}", "-t", "0", "-b", "0",
               "-g", str(self.gpu_id), "-q"]

        result = {"status": "complete", "found_key": None, "canary_keys": {}, "progress": 0.0}
        si = None
        if platform.system() == "Windows":
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
                        result["found_key"] = {"address": cur_addr, "privkey": pk}
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
            if self.proc.returncode and self.proc.returncode != 0 and result["status"] == "complete":
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
               "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,name",
               "--format=csv,noheader,nounits"]
        si = None
        if platform.system() == "Windows":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, startupinfo=si)
        if r.returncode == 0:
            p = [x.strip() for x in r.stdout.strip().split(",")]
            if len(p) >= 6:
                return {"usage": int(float(p[0])), "temp": int(float(p[1])),
                        "power": int(float(p[2])), "mem_used": int(float(p[3])),
                        "mem_total": int(float(p[4])),
                        "name": p[5].replace("NVIDIA ", "").replace("GeForce ", "")}
    except Exception:
        pass
    return None


def _cpu_ram():
    cpu, ru, rt = 0, 0.0, 0.0
    if platform.system() == "Linux":
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
    elif platform.system() == "Windows":
        try:
            import ctypes

            class MEMSTAT(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
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
            r = subprocess.run(
                ["wmic", "cpu", "get", "loadpercentage"],
                capture_output=True, text=True, timeout=5, startupinfo=si)
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if line.isdigit():
                    cpu = int(line)
                    break
        except Exception:
            pass
    return {"cpu": cpu, "ram_used": round(ru, 1), "ram_total": round(rt, 1)}


# ═══════════════════════════════════════════════════════════════════
# CONFIG MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

def _load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return None
    return None


def _save_config(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def _find_keyhunt():
    if platform.system() == "Windows":
        candidates = ["KeyHunt.exe", ".\\KeyHunt.exe",
                       str(Path.home() / "keyhunt" / "KeyHunt.exe"),
                       str(Path.home() / "Desktop" / "KeyHunt.exe")]
    else:
        candidates = ["./KeyHunt", "KeyHunt",
                       str(Path.home() / "keyhunt" / "KeyHunt"),
                       "/usr/local/bin/KeyHunt"]
    for c in candidates:
        if Path(c).exists():
            return str(Path(c).resolve())
    return None


# ═══════════════════════════════════════════════════════════════════
# GUI - SETUP WINDOW
# ═══════════════════════════════════════════════════════════════════

class SetupApp(ctk.CTk):
    """Modern setup dialog using CustomTkinter."""

    def __init__(self, saved_config=None):
        super().__init__()
        self.result = None

        self.title("Puzzle Pool Worker - Setup")
        self.geometry("520x520")
        self.resizable(False, False)

        # ── Header ──
        hdr = ctk.CTkFrame(self, fg_color="#14142a", corner_radius=0, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="  ", font=("", 26, "bold"),
                     text_color="#f7931a").pack(side="left", padx=(16, 0))
        ctk.CTkLabel(hdr, text="Puzzle Pool Worker", font=("", 18, "bold"),
                     text_color="#f7931a").pack(side="left", padx=(4, 0))
        ctk.CTkLabel(hdr, text="Setup", font=("", 13),
                     text_color="#666").pack(side="left", padx=(8, 0), pady=(2, 0))

        # ── Form ──
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=32, pady=20)

        # Pool URL
        ctk.CTkLabel(form, text="Pool URL", font=("", 12, "bold"),
                     text_color="#888").pack(anchor="w")
        self.e_url = ctk.CTkEntry(form, placeholder_text=DEFAULT_POOL, height=38)
        self.e_url.pack(fill="x", pady=(4, 14))

        # Worker Name
        ctk.CTkLabel(form, text="Worker Name", font=("", 12, "bold"),
                     text_color="#888").pack(anchor="w")
        self.e_name = ctk.CTkEntry(form, placeholder_text=f"worker-{platform.node()}", height=38)
        self.e_name.pack(fill="x", pady=(4, 14))

        # KeyHunt Path
        ctk.CTkLabel(form, text="KeyHunt Binary Path", font=("", 12, "bold"),
                     text_color="#888").pack(anchor="w")
        kh_row = ctk.CTkFrame(form, fg_color="transparent")
        kh_row.pack(fill="x", pady=(4, 14))
        self.e_kh = ctk.CTkEntry(kh_row, placeholder_text="Path to KeyHunt-Cuda executable", height=38)
        self.e_kh.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(kh_row, text="Browse", width=80, height=38,
                       fg_color="#333355", hover_color="#444477",
                       command=self._browse).pack(side="right", padx=(8, 0))

        # GPU ID
        ctk.CTkLabel(form, text="GPU Device ID", font=("", 12, "bold"),
                     text_color="#888").pack(anchor="w")
        self.e_gpu = ctk.CTkEntry(form, placeholder_text="0", width=100, height=38)
        self.e_gpu.pack(anchor="w", pady=(4, 20))

        # Pre-fill saved config
        if saved_config:
            if saved_config.get("pool_url"):
                self.e_url.insert(0, saved_config["pool_url"])
            if saved_config.get("worker_name"):
                self.e_name.insert(0, saved_config["worker_name"])
            if saved_config.get("keyhunt_path"):
                self.e_kh.insert(0, saved_config["keyhunt_path"])
            if saved_config.get("gpu_id") is not None:
                self.e_gpu.insert(0, str(saved_config["gpu_id"]))
        else:
            auto = _find_keyhunt()
            if auto:
                self.e_kh.insert(0, auto)

        # Start button
        ctk.CTkButton(form, text="START MINING", height=46,
                       font=("", 15, "bold"),
                       fg_color="#f7931a", hover_color="#e08517",
                       text_color="#000",
                       command=self._start).pack(fill="x", pady=(4, 0))

        # Error label
        self.lbl_err = ctk.CTkLabel(form, text="", text_color="#ff5252", font=("", 11))
        self.lbl_err.pack(pady=(8, 0))

        self.protocol("WM_DELETE_WINDOW", self._close)

    def _browse(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select KeyHunt-Cuda Binary",
            filetypes=[("Executable", "*.exe *.bin *"), ("All", "*.*")])
        if path:
            self.e_kh.delete(0, "end")
            self.e_kh.insert(0, path)

    def _start(self):
        url = self.e_url.get().strip() or DEFAULT_POOL
        name = self.e_name.get().strip() or f"worker-{platform.node()}"
        kh = self.e_kh.get().strip()
        gpu_s = self.e_gpu.get().strip()
        gpu_id = int(gpu_s) if gpu_s.isdigit() else 0

        if not kh:
            self.lbl_err.configure(text="Please specify the KeyHunt binary path")
            return
        if not Path(kh).exists():
            self.lbl_err.configure(text=f"File not found: {kh}")
            return

        self.result = {
            "pool_url": url,
            "worker_name": name,
            "keyhunt_path": kh,
            "gpu_id": gpu_id,
        }
        _save_config(self.result)
        self.destroy()

    def _close(self):
        self.result = None
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
# GUI - MAIN WORKER WINDOW
# ═══════════════════════════════════════════════════════════════════

class WorkerGUI:
    """Modern worker GUI using CustomTkinter. Same state interface as old TUI."""

    TAG_MAP = {
        "green": CLR.GREEN, "red": CLR.RED, "yellow": CLR.YELLOW,
        "gold": CLR.GOLD, "cyan": CLR.CYAN, "blue": CLR.BLUE,
        "purple": CLR.PURPLE, "dim": CLR.DIM, "default": CLR.TEXT,
    }

    def __init__(self):
        self.running = True
        self._tick = 0

        # ── State (worker writes to these from bg thread) ──
        self.status = "CONNECTING"
        self.status_color = YELLOW
        self.worker_name = ""
        self.pool_url = ""
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

        # ── Build window ──
        self.root = ctk.CTk()
        self.root.title(f"Puzzle Pool Worker v{VERSION}")
        self.root.geometry("800x780")
        self.root.minsize(740, 700)

        self._build()
        self._schedule_refresh()

    # ────────────────────── BUILD UI ──────────────────────

    def _build(self):
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=8)

        # ── HEADER ──
        hdr = ctk.CTkFrame(main, fg_color="#14142a", corner_radius=10, height=52)
        hdr.pack(fill="x", pady=(0, 6))
        hdr.pack_propagate(False)

        self._lbl_btc = ctk.CTkLabel(hdr, text="BTC", font=("", 20, "bold"),
                                      text_color=CLR.ACCENT)
        self._lbl_btc.pack(side="left", padx=(16, 8))
        ctk.CTkLabel(hdr, text="PUZZLE POOL WORKER", font=("", 15, "bold"),
                     text_color=CLR.ACCENT).pack(side="left")
        ctk.CTkLabel(hdr, text=f"v{VERSION}", font=("", 10),
                     text_color=CLR.DIM).pack(side="right", padx=16)

        # ── STATUS CARD ──
        sc = ctk.CTkFrame(main, fg_color=CLR.CARD, corner_radius=10)
        sc.pack(fill="x", pady=(0, 5))
        si = ctk.CTkFrame(sc, fg_color="transparent")
        si.pack(fill="x", padx=14, pady=10)

        row1 = ctk.CTkFrame(si, fg_color="transparent")
        row1.pack(fill="x")
        ctk.CTkLabel(row1, text="STATUS", font=("", 10),
                     text_color=CLR.DIM).pack(side="left")
        self._lbl_dot = ctk.CTkLabel(row1, text="\u25cf", font=("", 14),
                                      text_color=CLR.YELLOW)
        self._lbl_dot.pack(side="left", padx=(8, 3))
        self._lbl_status = ctk.CTkLabel(row1, text="CONNECTING",
                                         font=("", 12, "bold"), text_color=CLR.YELLOW)
        self._lbl_status.pack(side="left")

        ctk.CTkLabel(row1, text="POOL", font=("", 10),
                     text_color=CLR.DIM).pack(side="left", padx=(32, 6))
        self._lbl_pool = ctk.CTkLabel(row1, text="...", font=("", 11, "bold"),
                                       text_color=CLR.CYAN)
        self._lbl_pool.pack(side="left")

        row2 = ctk.CTkFrame(si, fg_color="transparent")
        row2.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(row2, text="WORKER", font=("", 10),
                     text_color=CLR.DIM).pack(side="left")
        self._lbl_worker = ctk.CTkLabel(row2, text="...", font=("", 11, "bold"),
                                         text_color=CLR.CYAN)
        self._lbl_worker.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(row2, text="GPU", font=("", 10),
                     text_color=CLR.DIM).pack(side="left", padx=(32, 6))
        self._lbl_gpu = ctk.CTkLabel(row2, text="Detecting...", font=("", 11, "bold"),
                                      text_color=CLR.GREEN)
        self._lbl_gpu.pack(side="left")

        # ── CURRENT SCAN CARD ──
        scan = ctk.CTkFrame(main, fg_color=CLR.CARD, corner_radius=10)
        scan.pack(fill="x", pady=(0, 5))
        si2 = ctk.CTkFrame(scan, fg_color="transparent")
        si2.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(si2, text="CURRENT SCAN", font=("", 12, "bold"),
                     text_color=CLR.GOLD).pack(anchor="w")

        self._lbl_chunk = ctk.CTkLabel(si2, text="Waiting for work...",
                                        font=("", 11, "bold"), text_color=CLR.DIM)
        self._lbl_chunk.pack(anchor="w", pady=(6, 0))
        self._lbl_range = ctk.CTkLabel(si2, text="", font=("", 10),
                                        text_color=CLR.DIM)
        self._lbl_range.pack(anchor="w", pady=(2, 0))

        # Progress bar row
        pb_row = ctk.CTkFrame(si2, fg_color="transparent")
        pb_row.pack(fill="x", pady=(8, 0))
        self._pb_scan = ctk.CTkProgressBar(pb_row, height=20,
                                            progress_color=CLR.ACCENT,
                                            fg_color="#1a1a30",
                                            corner_radius=6)
        self._pb_scan.pack(side="left", fill="x", expand=True)
        self._pb_scan.set(0)
        self._lbl_pct = ctk.CTkLabel(pb_row, text="0.0%", font=("", 12, "bold"),
                                      text_color=CLR.ACCENT, width=65)
        self._lbl_pct.pack(side="right", padx=(10, 0))

        # Canary indicators
        can_row = ctk.CTkFrame(si2, fg_color="transparent")
        can_row.pack(anchor="w", pady=(8, 0))
        ctk.CTkLabel(can_row, text="CANARIES", font=("", 10),
                     text_color=CLR.DIM).pack(side="left", padx=(0, 8))
        self._can_lbls = []
        for _ in range(5):
            lbl = ctk.CTkLabel(can_row, text="\u25cb", font=("", 12),
                               text_color=CLR.VDIM)
            lbl.pack(side="left", padx=3)
            self._can_lbls.append(lbl)

        # ── STATS CARD (two columns) ──
        stats = ctk.CTkFrame(main, fg_color=CLR.CARD, corner_radius=10)
        stats.pack(fill="x", pady=(0, 5))
        si3 = ctk.CTkFrame(stats, fg_color="transparent")
        si3.pack(fill="x", padx=14, pady=10)

        cols = ctk.CTkFrame(si3, fg_color="transparent")
        cols.pack(fill="x")

        # Left: Worker Stats
        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(left, text="MY STATS", font=("", 12, "bold"),
                     text_color=CLR.GOLD).pack(anchor="w")

        self._sv = {}
        for key, lbl in [("chunks", "Chunks"), ("keys", "Keys"),
                         ("speed", "Speed"), ("uptime", "Uptime")]:
            r = ctk.CTkFrame(left, fg_color="transparent")
            r.pack(anchor="w", fill="x", pady=1)
            ctk.CTkLabel(r, text=f"  {lbl}", font=("", 10),
                         text_color=CLR.DIM, width=65, anchor="w").pack(side="left")
            v = ctk.CTkLabel(r, text="--", font=("", 10, "bold"), text_color=CLR.TEXT)
            v.pack(side="left")
            self._sv[key] = v

        # Right: System Stats
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.pack(side="right", fill="both", expand=True)
        ctk.CTkLabel(right, text="SYSTEM", font=("", 12, "bold"),
                     text_color=CLR.GOLD).pack(anchor="w")

        for key, lbl in [("gpu", "GPU"), ("vram", "VRAM"),
                         ("cpu", "CPU"), ("ram", "RAM")]:
            r = ctk.CTkFrame(right, fg_color="transparent")
            r.pack(anchor="w", fill="x", pady=1)
            ctk.CTkLabel(r, text=f"  {lbl}", font=("", 10),
                         text_color=CLR.DIM, width=55, anchor="w").pack(side="left")
            v = ctk.CTkLabel(r, text="--", font=("", 10, "bold"), text_color=CLR.TEXT)
            v.pack(side="left")
            self._sv[key] = v

        # ── POOL NETWORK CARD ──
        pool = ctk.CTkFrame(main, fg_color=CLR.CARD, corner_radius=10)
        pool.pack(fill="x", pady=(0, 5))
        si4 = ctk.CTkFrame(pool, fg_color="transparent")
        si4.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(si4, text="POOL NETWORK", font=("", 12, "bold"),
                     text_color=CLR.GOLD).pack(anchor="w")

        pr1 = ctk.CTkFrame(si4, fg_color="transparent")
        pr1.pack(fill="x", pady=(4, 0))
        for key, lbl in [("p_workers", "Workers"), ("p_speed", "Speed"),
                         ("p_eta", "ETA")]:
            ctk.CTkLabel(pr1, text=lbl, font=("", 10),
                         text_color=CLR.DIM).pack(side="left")
            v = ctk.CTkLabel(pr1, text="--", font=("", 10, "bold"), text_color=CLR.TEXT)
            v.pack(side="left", padx=(4, 18))
            self._sv[key] = v

        ppb_row = ctk.CTkFrame(si4, fg_color="transparent")
        ppb_row.pack(fill="x", pady=(6, 0))
        self._pb_pool = ctk.CTkProgressBar(ppb_row, height=16,
                                            progress_color=CLR.GREEN,
                                            fg_color="#1a1a30",
                                            corner_radius=5)
        self._pb_pool.pack(side="left", fill="x", expand=True)
        self._pb_pool.set(0)
        self._lbl_ppct = ctk.CTkLabel(ppb_row, text="0.000000%", font=("", 10, "bold"),
                                       text_color=CLR.GREEN, width=90)
        self._lbl_ppct.pack(side="right", padx=(8, 0))

        pr2 = ctk.CTkFrame(si4, fg_color="transparent")
        pr2.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(pr2, text="Scanned", font=("", 10),
                     text_color=CLR.DIM).pack(side="left")
        self._sv["p_scanned"] = ctk.CTkLabel(pr2, text="--", font=("", 10, "bold"),
                                              text_color=CLR.ACCENT)
        self._sv["p_scanned"].pack(side="left", padx=(4, 18))
        ctk.CTkLabel(pr2, text="Remaining", font=("", 10),
                     text_color=CLR.DIM).pack(side="left")
        self._sv["p_remain"] = ctk.CTkLabel(pr2, text="--", font=("", 10, "bold"),
                                             text_color=CLR.BLUE)
        self._sv["p_remain"].pack(side="left", padx=(4, 0))

        self._lbl_found = ctk.CTkLabel(si4, text="", font=("", 13, "bold"),
                                        text_color=CLR.GREEN)
        self._lbl_found.pack(anchor="w")

        # ── LOG CARD ──
        log_card = ctk.CTkFrame(main, fg_color=CLR.CARD, corner_radius=10)
        log_card.pack(fill="both", expand=True, pady=(0, 5))

        mono = "Consolas" if platform.system() == "Windows" else "monospace"
        self._log_box = ctk.CTkTextbox(log_card, font=(mono, 10),
                                        fg_color="#06060e",
                                        text_color=CLR.DIM,
                                        corner_radius=8,
                                        state="disabled")
        self._log_box.pack(fill="both", expand=True, padx=8, pady=8)

        # Configure text tags on the underlying tk text widget
        tw = self._log_box._textbox
        tw.tag_config("t_green", foreground=CLR.GREEN)
        tw.tag_config("t_red", foreground=CLR.RED)
        tw.tag_config("t_yellow", foreground=CLR.YELLOW)
        tw.tag_config("t_cyan", foreground=CLR.CYAN)
        tw.tag_config("t_blue", foreground=CLR.BLUE)
        tw.tag_config("t_purple", foreground=CLR.PURPLE)
        tw.tag_config("t_dim", foreground=CLR.DIM)
        tw.tag_config("t_default", foreground=CLR.TEXT)
        tw.tag_config("t_time", foreground=CLR.VDIM)

        # ── FOOTER ──
        footer = ctk.CTkFrame(main, fg_color="transparent", height=28)
        footer.pack(fill="x")
        link = ctk.CTkLabel(footer, text="Dashboard: https://starnetlive.space",
                            font=("", 11), text_color=CLR.CYAN, cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: __import__("webbrowser").open(
            "https://starnetlive.space"))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ────────────────────── FORMATTING ──────────────────────

    @staticmethod
    def _fk(n):
        if n >= 1e18: return f"{n / 1e18:.2f} Exa"
        if n >= 1e15: return f"{n / 1e15:.2f} P"
        if n >= 1e12: return f"{n / 1e12:.2f} T"
        if n >= 1e9:  return f"{n / 1e9:.2f} B"
        if n >= 1e6:  return f"{n / 1e6:.2f} M"
        if n >= 1e3:  return f"{n:,.0f}"
        return str(int(n))

    @staticmethod
    def _fs(v):
        if v >= 1e12: return f"{v / 1e12:.2f} TK/s"
        if v >= 1e9:  return f"{v / 1e9:.2f} GK/s"
        if v >= 1e6:  return f"{v / 1e6:.2f} MK/s"
        return f"{v:.0f} K/s"

    @staticmethod
    def _fd(s):
        if s <= 0 or s > 1e15:
            return "--"
        y = int(s / 31557600)
        d = int(s % 31557600 / 86400)
        h = int(s % 86400 / 3600)
        m = int(s % 3600 / 60)
        if y > 0: return f"{y}y {d}d"
        if d > 0: return f"{d}d {h}h"
        if h > 0: return f"{h}h {m}m"
        return f"{m}m"

    # ────────────────────── LOGGING ──────────────────────

    def log(self, msg, color=LGREY):
        ts = time.strftime("%H:%M:%S")
        tag = f"t_{color}" if color in (
            "green", "red", "yellow", "cyan", "blue", "purple", "dim"
        ) else "t_default"
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
        tw = self._log_box._textbox
        self._log_box.configure(state="normal")
        tw.delete("1.0", "end")
        for ts, msg, tag in lines[-30:]:
            tw.insert("end", f"[{ts}] ", "t_time")
            tw.insert("end", f"{msg}\n", tag)
        tw.see("end")
        self._log_box.configure(state="disabled")

    # ────────────────────── REFRESH LOOP ──────────────────────

    def _schedule_refresh(self):
        self.root.after(250, self._refresh)

    def _refresh(self):
        if not self.running:
            return
        self._tick += 1

        # Status
        hex_clr = self.TAG_MAP.get(self.status_color, CLR.TEXT)
        self._lbl_status.configure(text=self.status, text_color=hex_clr)
        # Blink dot
        show = self._tick % 4 < 3 or self.status != "SCANNING"
        self._lbl_dot.configure(text_color=hex_clr if show else CLR.CARD)

        # BTC animation
        symbols = ["BTC", "BTC", "BTC", "BTC"]
        self._lbl_btc.configure(text=symbols[self._tick % len(symbols)])

        # Info
        pool_d = self.pool_url.replace("https://", "").replace("http://", "")
        self._lbl_pool.configure(text=pool_d or "...")
        self._lbl_worker.configure(text=self.worker_name or "...")
        self._lbl_gpu.configure(text=self.gpu_name[:40])

        # Current scan
        if self.current_chunk is not None:
            self._lbl_chunk.configure(
                text=f"Chunk #{self.current_chunk:,}", text_color=CLR.ACCENT)
            self._lbl_range.configure(
                text=f"{self.chunk_range_start}  \u2192  {self.chunk_range_end}",
                text_color=CLR.DIM)
        else:
            self._lbl_chunk.configure(text="Waiting for work...", text_color=CLR.DIM)
            self._lbl_range.configure(text="")

        # Scan progress
        self._pb_scan.set(max(0, min(1, self.chunk_progress / 100)))
        self._lbl_pct.configure(text=f"{self.chunk_progress:.1f}%")

        # Canaries
        for i in range(5):
            if i < len(self.canary_addresses):
                addr = self.canary_addresses[i]
                short = addr[:5] + ".." + addr[-3:]
                if addr in self.canary_found_set:
                    self._can_lbls[i].configure(
                        text=f"\u2713 {short}", text_color=CLR.GREEN)
                else:
                    self._can_lbls[i].configure(
                        text=f"\u25cb {short}", text_color=CLR.VDIM)
            else:
                self._can_lbls[i].configure(text="\u25cb", text_color=CLR.VDIM)

        # Worker stats
        el = time.time() - self.session_start
        spd = self.keys_scanned / el if el > 0 and self.keys_scanned > 0 else 0

        ct = f"{self.chunks_done} done"
        if self.chunks_accepted:
            ct += f"  {self.chunks_accepted} ok"
        if self.chunks_rejected:
            ct += f"  {self.chunks_rejected} rej"
        self._sv["chunks"].configure(text=ct,
                                      text_color=CLR.RED if self.chunks_rejected else CLR.GREEN)
        self._sv["keys"].configure(text=self._fk(self.keys_scanned), text_color=CLR.ACCENT)
        self._sv["speed"].configure(text=self._fs(spd), text_color=CLR.CYAN)
        self._sv["uptime"].configure(text=self._fd(el), text_color=CLR.BLUE)

        # System stats
        gt = f"{self.gpu_usage}%  {self.gpu_temp}\u00b0C  {self.gpu_power}W"
        self._sv["gpu"].configure(text=gt,
                                   text_color=CLR.GREEN if self.gpu_usage > 0 else CLR.DIM)
        self._sv["vram"].configure(
            text=f"{self.gpu_mem_used}/{self.gpu_mem_total} MB", text_color=CLR.CYAN)
        self._sv["cpu"].configure(text=f"{self.cpu_usage}%", text_color=CLR.GREEN)
        self._sv["ram"].configure(
            text=f"{self.ram_used}/{self.ram_total} GB", text_color=CLR.CYAN)

        # Pool stats
        self._sv["p_workers"].configure(text=str(self.pool_active), text_color=CLR.GREEN)
        self._sv["p_speed"].configure(text=self._fs(self.pool_speed), text_color=CLR.CYAN)
        self._sv["p_eta"].configure(text=self._fd(self.pool_eta), text_color=CLR.PURPLE)

        self._pb_pool.set(max(0, min(1, self.pool_progress / 100)))
        self._lbl_ppct.configure(text=f"{self.pool_progress:.6f}%")

        self._sv["p_scanned"].configure(text=self._fk(self.pool_total_keys))
        self._sv["p_remain"].configure(text=self._fk(self.pool_keys_remaining))

        if self.pool_found > 0:
            stars = "\u2605 " * min(self.pool_found, 5)
            self._lbl_found.configure(
                text=f"{stars}{self.pool_found} KEY(S) FOUND! {stars}")
        else:
            self._lbl_found.configure(text="")

        self.root.after(250, self._refresh)

    # ────────────────────── INTERFACE ──────────────────────

    def render_loop(self):
        """No-op for GUI - refresh handled by after()."""
        pass

    def stop(self):
        self.running = False
        try:
            self.root.after(100, self.root.destroy)
        except Exception:
            pass

    def _on_close(self):
        self.running = False
        self.root.after(200, self.root.destroy)

    def mainloop(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════
# PLAIN TEXT UI (--no-gui fallback)
# ═══════════════════════════════════════════════════════════════════

class PlainUI:
    """Minimal UI that prints to stdout. Same state interface as WorkerGUI."""

    ANSI = {
        "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m",
        "cyan": "\033[36m", "blue": "\033[34m", "purple": "\033[35m",
        "gold": "\033[33m", "dim": "\033[90m", "default": "\033[37m",
    }
    RESET = "\033[0m"

    def __init__(self):
        self.running = True
        self.status = "CONNECTING"
        self.status_color = YELLOW
        self.worker_name = ""
        self.pool_url = ""
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

    def log(self, msg, color="dim"):
        ts = time.strftime("%H:%M:%S")
        clr = self.ANSI.get(color, "")
        print(f"\033[90m[{ts}]{self.RESET} {clr}{msg}{self.RESET}", flush=True)

    def render_loop(self):
        pass

    def stop(self):
        self.running = False


# ═══════════════════════════════════════════════════════════════════
# WORKER LOGIC
# ═══════════════════════════════════════════════════════════════════

class PoolWorker:
    def __init__(self, pool_url, name, keyhunt_path, gpu_id=0, ui=None):
        self.pool_url = pool_url
        self.name = name
        self.keyhunt_path = keyhunt_path
        self.gpu_id = gpu_id
        self.api = PoolAPI(pool_url)
        self.runner = KeyHuntRunner(keyhunt_path, gpu_id)
        self.ui = ui
        self.running = True
        self.chunk_size = 2 ** 36

    def _log(self, msg, color=LGREY):
        if self.ui:
            self.ui.log(msg, color)

    def register(self):
        cfg = _load_config()
        if cfg and cfg.get("api_key"):
            self.api.api_key = cfg["api_key"]
            self._log("Loaded saved credentials", GREEN)
            return

        self._log(f"Registering as '{self.name}'...", YELLOW)
        resp = self.api.post("/api/register", {"name": self.name})
        if resp.get("status") != "ok":
            raise RuntimeError(f"Registration failed: {resp}")
        self.api.api_key = resp["api_key"]

        old_cfg = _load_config() or {}
        old_cfg.update({
            "api_key": resp["api_key"],
            "worker_name": self.name,
            "pool_url": self.pool_url,
            "keyhunt_path": self.keyhunt_path,
            "gpu_id": self.gpu_id,
        })
        _save_config(old_cfg)
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
        if self.ui:
            self.ui.worker_name = self.name
            self.ui.pool_url = self.pool_url
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
                        self._log("Key reported to pool successfully!", GREEN)
                    except Exception as e:
                        self._log(f"FAILED to report key: {e}", RED)
                    completed.append({"chunk_id": cid, "canary_keys": result["canary_keys"]})
                    break

                if result["status"] in ("complete", "timeout"):
                    nc = len(result["canary_keys"])
                    c_clr = GREEN if nc == len(canaries) else YELLOW
                    self._log(f"Chunk #{cid:,} done. Canaries: {nc}/{len(canaries)}", c_clr)
                    completed.append({"chunk_id": cid, "canary_keys": result["canary_keys"]})
                    if self.ui:
                        self.ui.chunks_done += 1
                        self.ui.keys_scanned += self.chunk_size
                else:
                    err = result.get("error", result["status"])
                    self._log(f"Chunk #{cid:,} error: {err}", RED)

            if completed:
                try:
                    rpt = self.api.post("/api/work", {"results": completed})
                    ac = rpt.get("accepted", 0)
                    rj = rpt.get("rejected", 0)
                    if self.ui:
                        self.ui.chunks_accepted += ac
                        self.ui.chunks_rejected += rj
                    self._log(f"Reported: {ac} accepted, {rj} rejected",
                              GREEN if rj == 0 else YELLOW)
                except Exception as e:
                    self._log(f"Report error: {e}", RED)


# ═══════════════════════════════════════════════════════════════════
# TERMINAL SETUP (for --no-gui mode)
# ═══════════════════════════════════════════════════════════════════

def _terminal_setup():
    print(f"\n  PUZZLE POOL WORKER SETUP\n")

    print(f"  Pool URL [{DEFAULT_POOL}]:")
    url = input("  > ").strip() or DEFAULT_POOL

    default_name = f"worker-{platform.node()}"
    print(f"\n  Worker name [{default_name}]:")
    name = input("  > ").strip() or default_name

    auto = _find_keyhunt()
    if auto:
        print(f"\n  Found KeyHunt: {auto}")
        print(f"  KeyHunt path [{auto}]:")
    else:
        print(f"\n  Path to KeyHunt binary:")
    kh = input("  > ").strip() or (auto or "")

    if not kh or not Path(kh).exists():
        print(f"\n  KeyHunt not found at '{kh}'")
        sys.exit(1)

    print(f"\n  GPU device ID [0]:")
    gid = input("  > ").strip()
    gpu_id = int(gid) if gid.isdigit() else 0

    cfg = {"pool_url": url, "worker_name": name, "keyhunt_path": kh, "gpu_id": gpu_id}
    _save_config(cfg)
    print(f"\n  Config saved! Launching...\n")
    time.sleep(0.5)
    return cfg


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Bitcoin Puzzle Pool Worker")
    parser.add_argument("--pool-url", help=f"Pool URL (default: {DEFAULT_POOL})")
    parser.add_argument("--name", help="Worker name")
    parser.add_argument("--keyhunt-path", help="Path to KeyHunt-Cuda binary")
    parser.add_argument("--gpu-id", type=int, default=0, help="GPU device ID (default: 0)")
    parser.add_argument("--auto", action="store_true", help="Use saved config without prompts")
    parser.add_argument("--no-gui", action="store_true", help="Plain text mode (no GUI)")
    parser.add_argument("--version", action="version", version=f"puzzle-worker {VERSION}")
    args = parser.parse_args()

    use_gui = HAS_GUI and not args.no_gui

    if not use_gui and not HAS_GUI and not args.no_gui:
        print("\nCustomTkinter not found. Install with: pip install customtkinter")
        print("Or run with --no-gui for plain text mode.\n")
        sys.exit(1)

    # ── Resolve config ──
    cfg = None

    if args.pool_url and args.keyhunt_path:
        cfg = {
            "pool_url": args.pool_url,
            "worker_name": args.name or f"worker-{platform.node()}",
            "keyhunt_path": args.keyhunt_path,
            "gpu_id": args.gpu_id,
        }
    elif args.auto:
        cfg = _load_config()
        if not cfg or "keyhunt_path" not in cfg:
            print("No saved config found. Run without --auto first.")
            sys.exit(1)

    if cfg is None:
        if use_gui:
            saved = _load_config()
            setup = SetupApp(saved_config=saved)
            setup.mainloop()
            cfg = setup.result
            if cfg is None:
                sys.exit(0)
        else:
            saved = _load_config()
            if saved and saved.get("keyhunt_path") and Path(saved["keyhunt_path"]).exists():
                print(f"\n  Saved config: {saved.get('worker_name')} @ {saved.get('pool_url', DEFAULT_POOL)}")
                print(f"  Use this config? [Y/n]:")
                ch = input("  > ").strip().lower()
                cfg = saved if ch in ("", "y", "yes") else _terminal_setup()
            else:
                cfg = _terminal_setup()

    # Apply CLI overrides
    if args.pool_url:
        cfg["pool_url"] = args.pool_url
    if args.name:
        cfg["worker_name"] = args.name
    if args.keyhunt_path:
        cfg["keyhunt_path"] = args.keyhunt_path
    if args.gpu_id != 0:
        cfg["gpu_id"] = args.gpu_id

    # ── Create UI ──
    if use_gui:
        ui = WorkerGUI()
    else:
        ui = PlainUI()

    # ── Create Worker ──
    worker = PoolWorker(
        cfg.get("pool_url", DEFAULT_POOL),
        cfg.get("worker_name", f"worker-{platform.node()}"),
        cfg["keyhunt_path"],
        cfg.get("gpu_id", 0),
        ui,
    )

    # ── Signal handling ──
    def on_signal(sig, frame):
        worker.running = False
        worker.runner.kill()
        ui.stop()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    if use_gui:
        # GUI on main thread, worker on background thread
        def _worker_thread():
            try:
                worker.run()
            except Exception as e:
                ui.log(f"Fatal error: {e}", RED)
                ui.status = "ERROR"
                ui.status_color = RED

        t = threading.Thread(target=_worker_thread, daemon=True)
        t.start()
        ui.mainloop()

        # Cleanup after GUI closes
        worker.running = False
        worker.runner.kill()
    else:
        # No GUI: worker on main thread
        try:
            worker.run()
        except KeyboardInterrupt:
            worker.running = False
            worker.runner.kill()
        except Exception as e:
            print(f"\nFatal: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
