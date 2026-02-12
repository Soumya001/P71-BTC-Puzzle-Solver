#!/usr/bin/env python3
"""
Bitcoin Puzzle Pool Worker v4.2.2 - AMOLED Hacker UI

- AMOLED true-black + neon accent theme (cyberpunk aesthetic)
- Ghost/outline control buttons with hover fill effects
- 3-section header: logo | status | settings
- Glow-bordered cards for key UI sections
- Two-column layout: stats left, live log stream right
- Animated progress bars with smooth easing
- ETA calculation for current scan chunk
- Live speed display (fixes stale speed between chunks)
- Single-address mode for maximum GPU speed
- Start / Stop / Pause controls, Normal & Eco modes
- Auto-installs to C:\\PuzzlePool (Windows) or ~/.puzzle-pool (Linux)
"""

import http.client
import json
import math
import os
import platform
import re
import shutil
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "4.2.2"
POOL_URL = "https://starnetlive.space"
APP_NAME = "PuzzlePool"

# ─── Platform paths ────────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_FROZEN = getattr(sys, 'frozen', False)
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

# Guard against None stdout/stderr in --windowed frozen apps
if IS_WIN and IS_FROZEN:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')

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

# ─── Windows setup ────────────────────────────────────────────────
if IS_WIN:
    try:
        import ctypes
        # Set AppUserModelID so Windows uses our icon on taskbar (not Python's)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PuzzlePool.Worker.v4")
    except Exception:
        pass
    try:
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
    from PIL import Image as PilImage, ImageDraw, ImageFont
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


THEMES = {
    "dark": {
        "bg": "#000000", "card": "#0a0a0f", "card_alt": "#0d0d14",
        "card_border": "#1a1a2e", "header": "#050510",
        "accent": "#f7931a", "gold": "#ffd700", "green": "#00ff88",
        "red": "#ff3355", "yellow": "#ffee00", "cyan": "#00ffff",
        "blue": "#448aff", "purple": "#cc66ff",
        "text": "#e0e0e8", "dim": "#555570", "vdim": "#2a2a3e",
        "input_bg": "#0a0a14", "log_bg": "#000000",
        "progress_bg": "#0f0f1a",
        "glow": "#00ffff", "btn_border": "#1a1a2e",
    },
    "light": {
        "bg": "#f2f4f8", "card": "#ffffff", "card_alt": "#f5f7fb",
        "card_border": "#d0d4e0", "header": "#eaecf2",
        "accent": "#e07a10", "gold": "#b8860b", "green": "#2e7d32",
        "red": "#c62828", "yellow": "#f57f17", "cyan": "#00838f",
        "blue": "#1565c0", "purple": "#6a1b9a",
        "text": "#1a1a2e", "dim": "#7a7a90", "vdim": "#b0b0c0",
        "input_bg": "#f0f2f8", "log_bg": "#fafcfe",
        "progress_bg": "#e0e2e8",
        "glow": "#00838f", "btn_border": "#c0c4d0",
    },
}


class CLR:
    """Compatibility shim — references dark theme defaults."""
    BG     = THEMES["dark"]["bg"]
    CARD   = THEMES["dark"]["card"]
    ACCENT = THEMES["dark"]["accent"]
    GOLD   = THEMES["dark"]["gold"]
    GREEN  = THEMES["dark"]["green"]
    RED    = THEMES["dark"]["red"]
    YELLOW = THEMES["dark"]["yellow"]
    CYAN   = THEMES["dark"]["cyan"]
    BLUE   = THEMES["dark"]["blue"]
    PURPLE = THEMES["dark"]["purple"]
    TEXT   = THEMES["dark"]["text"]
    DIM    = THEMES["dark"]["dim"]
    VDIM   = THEMES["dark"]["vdim"]
    GLOW   = THEMES["dark"]["glow"]


def _make_icon_image(size=256):
    """Generate a round Bitcoin icon with transparent background as PIL Image."""
    if not HAS_TRAY:
        return None
    img = PilImage.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx, cy = size / 2, size / 2
    r = size * 0.46

    # Draw round background
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill='#f7931a')

    # Subtle gradient overlay (shine)
    overlay = PilImage.new('RGBA', (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i in range(int(r)):
        alpha = int(35 * (1 - i / r))
        y = cy - r + i
        # Clip to circle
        dx = (r ** 2 - (i - r) ** 2) ** 0.5 if i < 2 * r else 0
        od.line([(cx - dx, y), (cx + dx, y)], fill=(255, 255, 255, alpha))
    img = PilImage.alpha_composite(img, overlay)
    d = ImageDraw.Draw(img)

    # Draw Bitcoin "B" symbol
    font_size = int(size * 0.52)
    font = None
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        for fp in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]:
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue

    if font:
        d.text((cx + 2, cy + 2), "B", fill=(0, 0, 0, 80), font=font, anchor='mm')
        d.text((cx, cy), "B", fill='white', font=font, anchor='mm')
    else:
        d.text((cx - size * 0.08, cy - size * 0.12), "B", fill='white')

    return img


def _get_icon_image():
    if not HAS_TRAY:
        return None
    # 1. Installed icon
    if ICON_PNG.exists():
        try:
            return PilImage.open(str(ICON_PNG))
        except Exception:
            pass
    # 2. Source dir (not frozen)
    if not IS_FROZEN:
        src_icon = Path(__file__).parent / "assets" / "icons" / "icon.png"
        if src_icon.exists():
            try:
                return PilImage.open(str(src_icon))
            except Exception:
                pass
    # 3. Frozen bundle
    if IS_FROZEN:
        bundled = Path(sys._MEIPASS) / "icon.png"
        if bundled.exists():
            try:
                return PilImage.open(str(bundled))
            except Exception:
                pass
    # 4. Generated fallback
    return _make_icon_image(64)


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
            bdir = Path(__file__).parent / "assets" / "icons"
        for name, dest in [("icon.ico", ICON_FILE), ("icon.png", ICON_PNG)]:
            src = bdir / name
            if src.exists():
                # Overwrite if destination is missing or is a small fallback (<5KB)
                need_copy = not dest.exists()
                if not need_copy:
                    try:
                        need_copy = dest.stat().st_size < 5000
                    except Exception:
                        need_copy = True
                if need_copy:
                    try:
                        shutil.copy2(str(src), str(dest))
                    except Exception:
                        pass
        if not ICON_PNG.exists() and HAS_TRAY:
            try:
                img = _make_icon_image(256)
                if img:
                    img.save(str(ICON_PNG), format='PNG')
            except Exception:
                pass

    @staticmethod
    def _is_valid_binary():
        """Check if existing KeyHunt binary is valid."""
        if not KEYHUNT_PATH.exists():
            return False
        size = KEYHUNT_PATH.stat().st_size
        if size < 500_000:
            return False
        try:
            with open(str(KEYHUNT_PATH), 'rb') as f:
                magic = f.read(4)
            if IS_WIN:
                return magic[:2] == b'MZ'
            else:
                return magic == b'\x7fELF'
        except Exception:
            return False

    @staticmethod
    def download_keyhunt(progress_cb=None):
        if KEYHUNT_PATH.exists() and Installer._is_valid_binary():
            return True
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
                           capture_output=True, startupinfo=si, timeout=10,
                           creationflags=CREATE_NO_WINDOW)
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
        cfg = {
            "worker_name": f"worker-{platform.node()}",
            "gpu_id": 0,
            "device": "gpu",
            "cpu_threads": 4,
            "mode": "normal",
            "eco_cooldown": 60,
        }
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ═══════════════════════════════════════════════════════════════════
# KEYHUNT RUNNER
# ═══════════════════════════════════════════════════════════════════

_RE_ADDR = re.compile(r"PubAddress:\s*(\S+)")
_RE_KEY = re.compile(r"Priv\s*\(HEX\):\s*([0-9a-fA-F]+)")
_RE_PROG = re.compile(r"\[C:\s*(\d+\.?\d*)\s*%\]")
_RE_SPEED = re.compile(r"\[(?:CPU\+GPU|GPU|CPU):\s*(\d+\.?\d*)\s*([KMGTPE])[Kk]/s\]")
_RE_BYE = re.compile(r"BYE")


class KeyHuntRunner:
    def __init__(self, path=None, gpu_id=0, device="gpu", cpu_threads=4):
        self.path = path or str(KEYHUNT_PATH)
        self.gpu_id = gpu_id
        self.device = device
        self.cpu_threads = cpu_threads
        self.proc = None
        self.pid = None

    def run(self, rs, re_, target, ui=None, timeout=1800):
        """Run KeyHunt in single-address mode. No canaries."""
        s = rs.replace("0x", "").lstrip("0") or "0"
        e = re_.replace("0x", "").lstrip("0") or "0"

        cmd = [self.path, "-m", "address"]
        if self.device in ("gpu", "cpu_gpu"):
            cmd += ["-g", "--gpui", str(self.gpu_id)]
        if self.device in ("cpu", "cpu_gpu"):
            cmd += ["-t", str(self.cpu_threads)]
        cmd += ["--range", f"{s}:{e}", target]

        result = {"status": "complete", "found_key": None,
                  "progress": 0.0, "speed": 0.0}
        si = None
        if IS_WIN:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        if ui:
            ui.log(f"CMD: {' '.join(cmd)}", GREY)

        try:
            # On Linux, use a PTY so KeyHunt CUDA sees a terminal and
            # flushes progress output in real-time (not 4-8KB buffered).
            _pty_stream = None
            if not IS_WIN:
                try:
                    import pty as _pty, tty as _tty
                    _mfd, _sfd = _pty.openpty()
                    _tty.setraw(_sfd)  # raw mode: no \n→\r\n, no echo
                    self.proc = subprocess.Popen(
                        cmd, stdout=_sfd, stderr=_sfd,
                        stdin=subprocess.DEVNULL, close_fds=True)
                    os.close(_sfd)
                    _pty_stream = os.fdopen(_mfd, 'rb', buffering=0)
                except Exception:
                    # PTY failed — will fall through to PIPE below
                    if self.proc is not None and self.proc.poll() is None:
                        self.proc.kill()
                    self.proc = None
                    _pty_stream = None

            if self.proc is None:
                self.proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    startupinfo=si, creationflags=CREATE_NO_WINDOW)

            _read_stream = _pty_stream or self.proc.stdout
            self.pid = self.proc.pid
            if ui:
                ui.keyhunt_pid = self.pid

            t0 = time.time()
            cur_addr = None
            output_lines = []
            line_buf = b""
            found = False

            # Read byte-by-byte: KeyHunt uses \r for progress, \n for
            # found-key output and BYE.  This handles both delimiters.
            while not found:
                try:
                    byte = _read_stream.read(1)
                except OSError:
                    byte = b""  # PTY slave closed (process exited)
                if not byte:  # EOF
                    if line_buf:
                        line = line_buf.decode('utf-8', errors='replace').strip()
                        line_buf = b""
                        if line:
                            output_lines.append(line)
                            if _RE_BYE.search(line):
                                result["status"] = "complete"
                                result["progress"] = 100.0
                                if ui:
                                    ui.chunk_progress = 100.0
                    break

                if byte in (b'\r', b'\n'):
                    if not line_buf:
                        continue
                    line = line_buf.decode('utf-8', errors='replace').strip()
                    line_buf = b""
                    if not line:
                        continue
                    output_lines.append(line)

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
                            found = True
                            break
                        cur_addr = None

                    m = _RE_PROG.search(line)
                    if m:
                        result["progress"] = float(m.group(1))
                        if ui:
                            ui.chunk_progress = result["progress"]

                    m = _RE_SPEED.search(line)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2)
                        multipliers = {"K": 1e3, "M": 1e6, "G": 1e9,
                                       "T": 1e12, "P": 1e15, "E": 1e18}
                        result["speed"] = val * multipliers.get(unit, 1e6)
                        if ui:
                            ui.current_speed = result["speed"]

                    if _RE_BYE.search(line):
                        result["status"] = "complete"
                        result["progress"] = 100.0
                        if ui:
                            ui.chunk_progress = 100.0

                    if time.time() - t0 > timeout:
                        result["status"] = "timeout"
                        self.kill()
                        break
                else:
                    line_buf += byte

            if self.proc.poll() is None:
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            if (self.proc.returncode and self.proc.returncode != 0
                    and result["status"] == "complete"):
                result["status"] = "error"
                last = " | ".join(output_lines[-5:]) if output_lines else "no output"
                result["error"] = f"exit code {self.proc.returncode}: {last}"
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            self.kill()
        finally:
            if _pty_stream is not None:
                try:
                    _pty_stream.close()
                except Exception:
                    pass
            self.proc = None
            self.pid = None
            if ui:
                ui.keyhunt_pid = None
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
                           timeout=5, startupinfo=si,
                           creationflags=CREATE_NO_WINDOW)
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
                               capture_output=True, text=True, timeout=5,
                               startupinfo=si, creationflags=CREATE_NO_WINDOW)
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
# SETTINGS DIALOG
# ═══════════════════════════════════════════════════════════════════

class SettingsDialog:
    def __init__(self, parent, current_config, on_save, theme=None):
        self._on_save = on_save
        self.t = theme or THEMES["dark"]
        self.win = ctk.CTkToplevel(parent)
        self.win.withdraw()
        self.win.title("Settings")
        self.win.geometry("440x500")
        self.win.transient(parent)
        self.win.resizable(False, False)
        self.win.configure(fg_color=self.t["bg"])
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        ctk.CTkLabel(self.win, text="Worker Settings", font=("", 20, "bold"),
                     text_color=self.t["accent"]).pack(pady=(20, 15))

        form = ctk.CTkFrame(self.win, fg_color=self.t["card"],
                            border_color=self.t["card_border"], border_width=1,
                            corner_radius=12)
        form.pack(fill="x", padx=20, pady=(0, 10))

        self._fields = {}
        self._add_field(form, "Worker Name", "worker_name",
                        current_config.get("worker_name", f"worker-{platform.node()}"), "entry")
        self._add_field(form, "GPU ID", "gpu_id",
                        str(current_config.get("gpu_id", 0)), "entry")
        self._add_field(form, "CPU Threads", "cpu_threads",
                        str(current_config.get("cpu_threads", 4)), "entry")
        device_map = {"gpu": "GPU", "cpu": "CPU", "cpu_gpu": "CPU+GPU"}
        self._add_field(form, "Device Mode", "device",
                        device_map.get(current_config.get("device", "gpu"), "GPU"),
                        "dropdown", options=["GPU", "CPU", "CPU+GPU"])
        mode_map = {"normal": "Normal", "eco": "Eco"}
        self._add_field(form, "Scan Mode", "mode",
                        mode_map.get(current_config.get("mode", "normal"), "Normal"),
                        "dropdown", options=["Normal", "Eco"])
        self._add_field(form, "Eco Cooldown (s)", "eco_cooldown",
                        str(current_config.get("eco_cooldown", 60)), "entry")

        btn_frame = ctk.CTkFrame(self.win, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(10, 20))
        ctk.CTkButton(btn_frame, text="Save", width=120, height=38,
                      fg_color=self.t["green"], hover_color="#00c853",
                      text_color="#000", font=("", 13, "bold"), corner_radius=10,
                      command=self._save).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Cancel", width=100, height=38,
                      fg_color=self.t["vdim"], hover_color=self.t["dim"],
                      text_color=self.t["text"], font=("", 13), corner_radius=10,
                      command=self._close).pack(side="right")

        self.win.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - 440) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - 500) // 2
        self.win.geometry(f"+{max(0,px)}+{max(0,py)}")
        self.win.deiconify()
        self.win.grab_set()
        self.win.lift()
        self.win.focus_force()

    def _add_field(self, parent, label, key, default, kind, options=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 2))
        ctk.CTkLabel(row, text=label, font=("", 12), text_color=self.t["dim"],
                     width=140, anchor="w").pack(side="left")
        if kind == "entry":
            var = ctk.StringVar(value=default)
            ctk.CTkEntry(row, textvariable=var, width=210, height=32,
                         fg_color=self.t["input_bg"], border_color=self.t["vdim"],
                         text_color=self.t["text"], corner_radius=8).pack(side="right")
            self._fields[key] = var
        elif kind == "dropdown":
            var = ctk.StringVar(value=default)
            ctk.CTkOptionMenu(row, variable=var, values=options, width=210, height=32,
                              fg_color=self.t["input_bg"], button_color=self.t["accent"],
                              button_hover_color="#e67e00",
                              dropdown_fg_color=self.t["card"],
                              text_color=self.t["text"],
                              corner_radius=8).pack(side="right")
            self._fields[key] = var

    def _close(self):
        self.win.grab_release()
        self.win.destroy()

    def _save(self):
        device_rmap = {"GPU": "gpu", "CPU": "cpu", "CPU+GPU": "cpu_gpu"}
        mode_rmap = {"Normal": "normal", "Eco": "eco"}
        new_cfg = {
            "worker_name": self._fields["worker_name"].get().strip()
                           or f"worker-{platform.node()}",
            "gpu_id": max(0, int(self._fields["gpu_id"].get() or 0)),
            "cpu_threads": max(1, min(64, int(self._fields["cpu_threads"].get() or 4))),
            "device": device_rmap.get(self._fields["device"].get(), "gpu"),
            "mode": mode_rmap.get(self._fields["mode"].get(), "normal"),
            "eco_cooldown": max(10, min(300, int(self._fields["eco_cooldown"].get() or 60))),
        }
        _save_config(new_cfg)
        if self._on_save:
            self._on_save(new_cfg)
        self._close()


# ═══════════════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════════════

class WorkerGUI:

    def __init__(self):
        self.running = True
        self._tick = 0
        self._tray = None
        self._worker_stop = None
        self._worker_ref = None

        # Theme
        cfg = _load_config()
        self.theme_name = cfg.get("theme", "dark")
        self.theme = THEMES.get(self.theme_name, THEMES["dark"])
        self.TAG_MAP = {
            "green": self.theme["green"], "red": self.theme["red"],
            "yellow": self.theme["yellow"], "gold": self.theme["gold"],
            "cyan": self.theme["cyan"], "blue": self.theme["blue"],
            "purple": self.theme["purple"], "dim": self.theme["dim"],
            "default": self.theme["text"],
        }

        # Shared state (worker writes, GUI reads)
        self.status = "STARTING"
        self.status_color = YELLOW
        self.worker_name = ""
        self.pool_url = POOL_URL
        self.gpu_name = "Detecting..."
        self.keyhunt_pid = None
        self.current_chunk = None
        self.assignment_id = None
        self.chunk_range_start = ""
        self.chunk_range_end = ""
        self.chunk_progress = 0.0
        self.current_speed = 0.0
        self.last_heartbeat_ago = 0.0
        self.heartbeat_ok = False
        self.chunks_done = 0
        self.chunks_accepted = 0
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

        # Animation state
        self._anim_scan = 0.0
        self._anim_pool = 0.0
        self._anim_id = None

        # Log flush state
        self._log_flushed_count = 0
        self._log_flush_pending = False

        # Change detection cache for _refresh
        self._prev = {}

        # Window
        self.root = ctk.CTk()
        self.root.title(f"Puzzle Pool Worker v{VERSION}")
        self.root.geometry("1200x900")
        self.root.minsize(1050, 750)
        self.root.configure(fg_color=self.theme["bg"])
        icon_path = None
        if ICON_FILE.exists():
            icon_path = str(ICON_FILE)
        elif IS_FROZEN:
            bundled = Path(sys._MEIPASS) / "icon.ico"
            if bundled.exists():
                icon_path = str(bundled)
        if icon_path:
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass
        # Cross-platform: use iconphoto with PNG (works on Linux where iconbitmap often fails)
        png_path = None
        if ICON_PNG.exists():
            png_path = str(ICON_PNG)
        elif IS_FROZEN:
            bundled_png = Path(sys._MEIPASS) / "icon.png"
            if bundled_png.exists():
                png_path = str(bundled_png)
        if png_path:
            try:
                import tkinter as tk
                icon_img = tk.PhotoImage(file=png_path)
                self.root.iconphoto(True, icon_img)
                self._icon_photo_ref = icon_img  # prevent GC
            except Exception:
                pass

        self._build_install_screen()
        self._build_main_screen()
        self._main_frame.pack_forget()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ────────── Install splash screen ──────────

    def _build_install_screen(self):
        t = self.theme
        self._inst = ctk.CTkFrame(self.root, fg_color="transparent")
        self._inst.pack(fill="both", expand=True)
        ctk.CTkFrame(self._inst, fg_color="transparent", height=180).pack()
        ctk.CTkLabel(self._inst, text="\u29c9", font=("", 72, "bold"),
                     text_color=t["accent"]).pack()
        ctk.CTkLabel(self._inst, text="Puzzle Pool Worker",
                     font=("", 28, "bold"), text_color=t["accent"]).pack(pady=(12, 5))
        ctk.CTkLabel(self._inst, text=f"v{VERSION}", font=("", 13),
                     text_color=t["dim"]).pack()
        self._lbl_inst = ctk.CTkLabel(self._inst, text="Initializing...",
                                       font=("", 14), text_color=t["text"])
        self._lbl_inst.pack(pady=(50, 12))
        self._pb_inst = ctk.CTkProgressBar(self._inst, width=440, height=20,
                                            progress_color=t["accent"],
                                            fg_color=t["progress_bg"], corner_radius=8)
        self._pb_inst.pack()
        self._pb_inst.set(0)
        self._lbl_inst2 = ctk.CTkLabel(self._inst, text="", font=("", 11),
                                        text_color=t["dim"])
        self._lbl_inst2.pack(pady=(12, 0))

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

    # ────────── Main screen (two-column layout) ──────────

    def _card(self, parent, alt=False, glow=False, **kw):
        """Create a card frame. glow=True uses neon border."""
        t = self.theme
        border_clr = t["glow"] if glow else t["card_border"]
        frame = ctk.CTkFrame(parent, fg_color=t["card_alt" if alt else "card"],
                             border_color=border_clr, border_width=1,
                             corner_radius=12, **kw)
        if glow:
            self._themed_glow_cards.append(frame)
        elif alt:
            self._themed_cards_alt.append(frame)
        else:
            self._themed_cards.append(frame)
        return frame

    def _build_main_screen(self):
        t = self.theme
        # Theme tracking lists
        self._themed_cards = []
        self._themed_cards_alt = []
        self._themed_glow_cards = []
        self._themed_dim_labels = []
        self._themed_gold_labels = []

        self._main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self._main_frame.pack(fill="both", expand=True)
        m = self._main_frame

        # ── Header (3-section) ──
        hdr = ctk.CTkFrame(m, fg_color=t["header"], corner_radius=12,
                           border_color=t["glow"], border_width=1, height=56)
        self._header_frame = hdr
        hdr.pack(fill="x", padx=10, pady=(8, 6))
        hdr.pack_propagate(False)

        # Left: logo + title
        hdr_left = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_left.pack(side="left", padx=(14, 0))
        self._lbl_btc = ctk.CTkLabel(hdr_left, text="\u29c9", font=("", 24, "bold"),
                                      text_color=t["accent"])
        self._lbl_btc.pack(side="left", padx=(0, 8))
        self._lbl_title = ctk.CTkLabel(hdr_left, text="PUZZLE POOL",
                     font=("", 17, "bold"), text_color=t["accent"])
        self._lbl_title.pack(side="left")

        # Center: version badge + status dot + status text
        hdr_center = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_center.pack(side="left", fill="x", expand=True, padx=16)
        self._vbadge = ctk.CTkFrame(hdr_center, fg_color=t["accent"], corner_radius=6,
                              width=56, height=22)
        self._vbadge.pack(side="left")
        self._vbadge.pack_propagate(False)
        ctk.CTkLabel(self._vbadge, text=f"v{VERSION}", font=("", 9, "bold"),
                     text_color="#000").pack(expand=True)
        self._lbl_hdr_dot = ctk.CTkLabel(hdr_center, text="\u25cf", font=("", 14),
                                          text_color=t["yellow"])
        self._lbl_hdr_dot.pack(side="left", padx=(12, 4))
        self._lbl_hdr_status = ctk.CTkLabel(hdr_center, text="STARTING",
                                             font=("", 13, "bold"), text_color=t["yellow"])
        self._lbl_hdr_status.pack(side="left")

        # Right: theme toggle + settings (ghost buttons)
        hdr_right = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_right.pack(side="right", padx=(0, 14))
        theme_icon = "\u263e" if self.theme_name == "dark" else "\u2600"
        self._btn_theme = ctk.CTkButton(
            hdr_right, text=theme_icon, width=36, height=36,
            fg_color="transparent", hover_color=t["card"],
            border_width=1, border_color=t["glow"],
            text_color=t["glow"], font=("", 18), corner_radius=10,
            command=self._toggle_theme)
        self._btn_theme.pack(side="left", padx=(0, 6))
        self._btn_settings = ctk.CTkButton(
            hdr_right, text="\u2699", width=36, height=36,
            fg_color="transparent", hover_color=t["card"],
            border_width=1, border_color=t["glow"],
            text_color=t["glow"], font=("", 18), corner_radius=10,
            command=self._on_settings)
        self._btn_settings.pack(side="left")

        # ── Controls Bar ──
        ctrl = self._card(m, glow=True)
        ctrl.pack(fill="x", padx=10, pady=(0, 5))
        ci = ctk.CTkFrame(ctrl, fg_color="transparent")
        ci.pack(fill="x", padx=14, pady=8)

        # Ghost button group with glow border
        self._btn_group = ctk.CTkFrame(ci, fg_color="transparent",
                                        border_color=t["glow"], border_width=1,
                                        corner_radius=10)
        self._btn_group.pack(side="left", padx=(0, 16))
        bg = self._btn_group

        self._btn_start = ctk.CTkButton(
            bg, text="\u25b8 START", width=105, height=36,
            fg_color="transparent", hover_color=t["green"],
            border_width=2, border_color=t["green"],
            text_color=t["green"], font=("", 13, "bold"), corner_radius=8,
            command=self._on_start)
        self._btn_start.pack(side="left", padx=(4, 2), pady=4)
        self._btn_start.bind("<Enter>", lambda e: self._ghost_hover(self._btn_start, t["green"], True))
        self._btn_start.bind("<Leave>", lambda e: self._ghost_hover(self._btn_start, t["green"], False))

        self._btn_pause = ctk.CTkButton(
            bg, text="\u23f8 PAUSE", width=105, height=36,
            fg_color="transparent", hover_color=t["yellow"],
            border_width=2, border_color=t["dim"],
            text_color=t["dim"], font=("", 13, "bold"), corner_radius=8,
            command=self._on_pause, state="disabled")
        self._btn_pause.pack(side="left", padx=2, pady=4)

        self._btn_stop = ctk.CTkButton(
            bg, text="\u25a0 STOP", width=105, height=36,
            fg_color="transparent", hover_color=t["red"],
            border_width=2, border_color=t["dim"],
            text_color=t["dim"], font=("", 13, "bold"), corner_radius=8,
            command=self._on_stop, state="disabled")
        self._btn_stop.pack(side="left", padx=(2, 4), pady=4)

        _lbl = ctk.CTkLabel(ci, text="Mode:", font=("", 11), text_color=t["dim"])
        _lbl.pack(side="left", padx=(0, 4))
        self._themed_dim_labels.append(_lbl)
        cfg = _load_config()
        mode_map = {"normal": "Normal", "eco": "Eco"}
        self._var_mode = ctk.StringVar(value=mode_map.get(cfg.get("mode", "normal"), "Normal"))
        self._dd_mode = ctk.CTkOptionMenu(
            ci, variable=self._var_mode, values=["Normal", "Eco"],
            width=95, height=30, fg_color=t["input_bg"],
            button_color=t["accent"], button_hover_color="#e67e00",
            dropdown_fg_color=t["card"], text_color=t["text"],
            corner_radius=8, command=self._on_mode_change)
        self._dd_mode.pack(side="left", padx=(0, 12))

        _lbl = ctk.CTkLabel(ci, text="Device:", font=("", 11), text_color=t["dim"])
        _lbl.pack(side="left", padx=(0, 4))
        self._themed_dim_labels.append(_lbl)
        device_map = {"gpu": "GPU", "cpu": "CPU", "cpu_gpu": "CPU+GPU"}
        self._var_device = ctk.StringVar(value=device_map.get(cfg.get("device", "gpu"), "GPU"))
        self._dd_device = ctk.CTkOptionMenu(
            ci, variable=self._var_device, values=["GPU", "CPU", "CPU+GPU"],
            width=105, height=30, fg_color=t["input_bg"],
            button_color=t["accent"], button_hover_color="#e67e00",
            dropdown_fg_color=t["card"], text_color=t["text"],
            corner_radius=8, command=self._on_device_change)
        self._dd_device.pack(side="left")

        # ── Two-column content ──
        content = ctk.CTkFrame(m, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=(0, 2))
        content.grid_columnconfigure(0, weight=58)
        content.grid_columnconfigure(1, weight=42)
        content.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right_col = ctk.CTkFrame(content, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        pad_card = {"padx": 0, "pady": (0, 5)}

        # ── LEFT: Status card ──
        sc = self._card(left)
        sc.pack(fill="x", **pad_card)
        si = ctk.CTkFrame(sc, fg_color="transparent")
        si.pack(fill="x", padx=14, pady=10)
        r1 = ctk.CTkFrame(si, fg_color="transparent")
        r1.pack(fill="x")
        _lbl = ctk.CTkLabel(r1, text="STATUS", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left")
        self._themed_dim_labels.append(_lbl)
        self._lbl_dot = ctk.CTkLabel(r1, text="\u25cf", font=("", 16), text_color=t["yellow"])
        self._lbl_dot.pack(side="left", padx=(10, 4))
        self._lbl_status = ctk.CTkLabel(r1, text="STARTING", font=("", 14, "bold"),
                                         text_color=t["yellow"])
        self._lbl_status.pack(side="left")
        _lbl = ctk.CTkLabel(r1, text="POOL", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left", padx=(32, 6))
        self._themed_dim_labels.append(_lbl)
        self._lbl_pool = ctk.CTkLabel(r1, text=POOL_URL.replace("https://", ""),
                                       font=("", 12, "bold"), text_color=t["cyan"])
        self._lbl_pool.pack(side="left")
        r2 = ctk.CTkFrame(si, fg_color="transparent")
        r2.pack(fill="x", pady=(5, 0))
        _lbl = ctk.CTkLabel(r2, text="WORKER", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left")
        self._themed_dim_labels.append(_lbl)
        self._lbl_worker = ctk.CTkLabel(r2, text="...", font=("", 12, "bold"), text_color=t["cyan"])
        self._lbl_worker.pack(side="left", padx=(6, 0))
        _lbl = ctk.CTkLabel(r2, text="GPU", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left", padx=(32, 6))
        self._themed_dim_labels.append(_lbl)
        self._lbl_gpu = ctk.CTkLabel(r2, text="Detecting...", font=("", 12, "bold"), text_color=t["green"])
        self._lbl_gpu.pack(side="left")

        # ── LEFT: Current Scan card ──
        scan = self._card(left, glow=True)
        scan.pack(fill="x", **pad_card)
        si2 = ctk.CTkFrame(scan, fg_color="transparent")
        si2.pack(fill="x", padx=14, pady=10)
        _lbl = ctk.CTkLabel(si2, text="CURRENT SCAN", font=("", 14, "bold"), text_color=t["gold"])
        _lbl.pack(anchor="w")
        self._themed_gold_labels.append(_lbl)
        self._lbl_chunk = ctk.CTkLabel(si2, text="Waiting for work...",
                                        font=("", 13, "bold"), text_color=t["dim"])
        self._lbl_chunk.pack(anchor="w", pady=(6, 0))
        self._lbl_range = ctk.CTkLabel(si2, text="", font=("", 11), text_color=t["dim"])
        self._lbl_range.pack(anchor="w", pady=(2, 0))

        pb = ctk.CTkFrame(si2, fg_color="transparent")
        pb.pack(fill="x", pady=(8, 0))
        self._pb_scan = ctk.CTkProgressBar(pb, height=22, progress_color=t["accent"],
                                            fg_color=t["progress_bg"], corner_radius=8)
        self._pb_scan.pack(side="left", fill="x", expand=True)
        self._pb_scan.set(0)
        self._lbl_pct = ctk.CTkLabel(pb, text="0.0%", font=("", 13, "bold"),
                                      text_color=t["accent"], width=70)
        self._lbl_pct.pack(side="right", padx=(10, 0))

        # Speed + heartbeat + ETA row
        info_row = ctk.CTkFrame(si2, fg_color="transparent")
        info_row.pack(fill="x", pady=(8, 0))
        _lbl = ctk.CTkLabel(info_row, text="\u2665", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left")
        self._themed_dim_labels.append(_lbl)
        self._lbl_hb_dot = ctk.CTkLabel(info_row, text="\u25cf", font=("", 10),
                                         text_color=t["vdim"])
        self._lbl_hb_dot.pack(side="left", padx=(2, 0))
        self._lbl_hb_text = ctk.CTkLabel(info_row, text="--", font=("", 12),
                                          text_color=t["dim"])
        self._lbl_hb_text.pack(side="left", padx=(4, 0))

        ctk.CTkLabel(info_row, text="\u26a1", font=("", 13), text_color=t["accent"]).pack(side="left", padx=(18, 0))
        self._lbl_cur_speed = ctk.CTkLabel(info_row, text="--", font=("", 15, "bold"),
                                            text_color=t["cyan"])
        self._lbl_cur_speed.pack(side="left", padx=(4, 0))

        _lbl = ctk.CTkLabel(info_row, text="ETA", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left", padx=(18, 4))
        self._themed_dim_labels.append(_lbl)
        self._lbl_eta = ctk.CTkLabel(info_row, text="--", font=("", 13, "bold"),
                                      text_color=t["purple"])
        self._lbl_eta.pack(side="left")

        # Keys scanned in chunk
        key_row = ctk.CTkFrame(si2, fg_color="transparent")
        key_row.pack(fill="x", pady=(4, 0))
        _lbl = ctk.CTkLabel(key_row, text="Keys in chunk:", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left")
        self._themed_dim_labels.append(_lbl)
        self._lbl_chunk_keys = ctk.CTkLabel(key_row, text="--", font=("", 13, "bold"),
                                             text_color=t["accent"])
        self._lbl_chunk_keys.pack(side="left", padx=(6, 0))

        # ── LEFT: Stats row (My Stats + System side by side) ──
        stats_row = ctk.CTkFrame(left, fg_color="transparent")
        stats_row.pack(fill="x", **pad_card)
        stats_row.grid_columnconfigure(0, weight=1)
        stats_row.grid_columnconfigure(1, weight=1)

        # My Stats card
        ms_card = self._card(stats_row)
        ms_card.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        msi = ctk.CTkFrame(ms_card, fg_color="transparent")
        msi.pack(fill="x", padx=12, pady=10)
        _lbl = ctk.CTkLabel(msi, text="MY STATS", font=("", 14, "bold"), text_color=t["gold"])
        _lbl.pack(anchor="w")
        self._themed_gold_labels.append(_lbl)
        self._sv = {}
        for k, lb in [("chunks", "Chunks"), ("keys", "Keys"), ("speed", "Speed"), ("uptime", "Uptime")]:
            row = ctk.CTkFrame(msi, fg_color="transparent")
            row.pack(anchor="w", fill="x", pady=2)
            _lbl = ctk.CTkLabel(row, text=lb, font=("", 12), text_color=t["dim"],
                                width=70, anchor="w")
            _lbl.pack(side="left")
            self._themed_dim_labels.append(_lbl)
            v = ctk.CTkLabel(row, text="--", font=("", 13, "bold"), text_color=t["text"])
            v.pack(side="left")
            self._sv[k] = v

        # System card
        sys_card = self._card(stats_row)
        sys_card.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        syi = ctk.CTkFrame(sys_card, fg_color="transparent")
        syi.pack(fill="x", padx=12, pady=10)
        _lbl = ctk.CTkLabel(syi, text="SYSTEM", font=("", 14, "bold"), text_color=t["gold"])
        _lbl.pack(anchor="w")
        self._themed_gold_labels.append(_lbl)
        for k, lb in [("gpu", "GPU"), ("vram", "VRAM"), ("cpu", "CPU"), ("ram", "RAM")]:
            row = ctk.CTkFrame(syi, fg_color="transparent")
            row.pack(anchor="w", fill="x", pady=2)
            _lbl = ctk.CTkLabel(row, text=lb, font=("", 12), text_color=t["dim"],
                                width=60, anchor="w")
            _lbl.pack(side="left")
            self._themed_dim_labels.append(_lbl)
            v = ctk.CTkLabel(row, text="--", font=("", 13, "bold"), text_color=t["text"])
            v.pack(side="left")
            self._sv[k] = v

        # ── LEFT: Pool Network card ──
        pf = self._card(left)
        pf.pack(fill="both", expand=True, **pad_card)
        si4 = ctk.CTkFrame(pf, fg_color="transparent")
        si4.pack(fill="x", padx=14, pady=10)
        _lbl = ctk.CTkLabel(si4, text="POOL NETWORK", font=("", 14, "bold"), text_color=t["gold"])
        _lbl.pack(anchor="w")
        self._themed_gold_labels.append(_lbl)
        pr = ctk.CTkFrame(si4, fg_color="transparent")
        pr.pack(fill="x", pady=(4, 0))
        for k, lb in [("p_workers", "Workers"), ("p_speed", "Speed"), ("p_eta", "ETA")]:
            _lbl = ctk.CTkLabel(pr, text=lb, font=("", 12), text_color=t["dim"])
            _lbl.pack(side="left")
            self._themed_dim_labels.append(_lbl)
            v = ctk.CTkLabel(pr, text="--", font=("", 13, "bold"), text_color=t["text"])
            v.pack(side="left", padx=(4, 20))
            self._sv[k] = v
        ppb = ctk.CTkFrame(si4, fg_color="transparent")
        ppb.pack(fill="x", pady=(6, 0))
        self._pb_pool = ctk.CTkProgressBar(ppb, height=18, progress_color=t["green"],
                                            fg_color=t["progress_bg"], corner_radius=6)
        self._pb_pool.pack(side="left", fill="x", expand=True)
        self._pb_pool.set(0)
        self._lbl_ppct = ctk.CTkLabel(ppb, text="0.000000%", font=("", 12, "bold"),
                                       text_color=t["green"], width=100)
        self._lbl_ppct.pack(side="right", padx=(8, 0))
        pr2 = ctk.CTkFrame(si4, fg_color="transparent")
        pr2.pack(fill="x", pady=(4, 0))
        _lbl = ctk.CTkLabel(pr2, text="Scanned", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left")
        self._themed_dim_labels.append(_lbl)
        self._sv["p_sc"] = ctk.CTkLabel(pr2, text="--", font=("", 13, "bold"), text_color=t["accent"])
        self._sv["p_sc"].pack(side="left", padx=(4, 20))
        _lbl = ctk.CTkLabel(pr2, text="Remaining", font=("", 12), text_color=t["dim"])
        _lbl.pack(side="left")
        self._themed_dim_labels.append(_lbl)
        self._sv["p_rm"] = ctk.CTkLabel(pr2, text="--", font=("", 13, "bold"), text_color=t["blue"])
        self._sv["p_rm"].pack(side="left", padx=(4, 0))
        self._lbl_found = ctk.CTkLabel(si4, text="", font=("", 14, "bold"), text_color=t["green"])
        self._lbl_found.pack(anchor="w")

        # ── RIGHT: Live Stream log ──
        log_card = self._card(right_col)
        log_card.pack(fill="both", expand=True, pady=(0, 5))
        _lbl = ctk.CTkLabel(log_card, text="LIVE STREAM", font=("", 14, "bold"),
                            text_color=t["gold"])
        _lbl.pack(anchor="w", padx=14, pady=(10, 0))
        self._themed_gold_labels.append(_lbl)
        mono = "Consolas" if IS_WIN else "monospace"
        self._lb = ctk.CTkTextbox(log_card, font=(mono, 11), fg_color=t["log_bg"],
                                   text_color=t["dim"], corner_radius=8, state="disabled")
        self._lb.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        tw = self._lb._textbox
        for tag, c in [("t_green", t["green"]), ("t_red", t["red"]),
                       ("t_yellow", t["yellow"]), ("t_cyan", t["cyan"]),
                       ("t_blue", t["blue"]), ("t_purple", t["purple"]),
                       ("t_dim", t["dim"]), ("t_default", t["text"]),
                       ("t_time", t["vdim"]), ("t_gold", t["gold"])]:
            tw.tag_config(tag, foreground=c)

        # Dashboard link under log
        self._lbl_dash = ctk.CTkLabel(right_col, text="Dashboard: https://starnetlive.space",
                                       font=("", 12), text_color=t["cyan"], cursor="hand2")
        self._lbl_dash.pack(anchor="w", padx=4, pady=(0, 2))
        self._lbl_dash.bind("<Button-1>", lambda e: __import__("webbrowser").open(POOL_URL))

        # ── Footer ──
        ft = ctk.CTkFrame(m, fg_color="transparent", height=28)
        ft.pack(fill="x", padx=10, pady=(0, 4))
        _lbl = ctk.CTkLabel(ft, text="Close = minimize to tray", font=("", 11),
                            text_color=t["dim"])
        _lbl.pack(side="right")
        self._themed_dim_labels.append(_lbl)

    # ────────── Theme toggle ──────────

    def _toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.theme = THEMES[self.theme_name]
        self.TAG_MAP = {
            "green": self.theme["green"], "red": self.theme["red"],
            "yellow": self.theme["yellow"], "gold": self.theme["gold"],
            "cyan": self.theme["cyan"], "blue": self.theme["blue"],
            "purple": self.theme["purple"], "dim": self.theme["dim"],
            "default": self.theme["text"],
        }
        _save_config({"theme": self.theme_name})
        ctk.set_appearance_mode("light" if self.theme_name == "light" else "dark")
        self._prev.clear()  # force _refresh to re-apply all values with new colors
        self._apply_theme()
        self.log(f"Theme: {self.theme_name}", CYAN)

    def _apply_theme(self):
        """Update all widget colors in-place — no destroy/rebuild."""
        t = self.theme
        self.root.configure(fg_color=t["bg"])

        # Update all tracked card frames
        for frame in self._themed_cards:
            try:
                frame.configure(fg_color=t["card"], border_color=t["card_border"])
            except Exception:
                pass
        for frame in self._themed_cards_alt:
            try:
                frame.configure(fg_color=t["card_alt"], border_color=t["card_border"])
            except Exception:
                pass
        for frame in self._themed_glow_cards:
            try:
                frame.configure(fg_color=t["card"], border_color=t["glow"])
            except Exception:
                pass

        # Header (glow border)
        try:
            self._header_frame.configure(fg_color=t["header"], border_color=t["glow"])
        except Exception:
            pass
        # Header title + status
        try:
            self._lbl_title.configure(text_color=t["accent"])
            self._lbl_btc.configure(text_color=t["accent"])
        except Exception:
            pass

        # Theme + settings ghost buttons
        self._btn_theme.configure(
            text="\u263e" if self.theme_name == "dark" else "\u2600",
            fg_color="transparent", hover_color=t["card"],
            border_color=t["glow"], text_color=t["glow"])
        self._btn_settings.configure(
            fg_color="transparent", hover_color=t["card"],
            border_color=t["glow"], text_color=t["glow"])

        # Button group glow border
        try:
            self._btn_group.configure(border_color=t["glow"])
        except Exception:
            pass

        # Ghost control buttons — re-apply current state colors
        # (actual state colors will be set by next _update_ctrl_buttons call via _refresh)
        for btn in (self._btn_start, self._btn_pause, self._btn_stop):
            try:
                btn.configure(fg_color="transparent")
            except Exception:
                pass

        # Control bar dropdowns
        try:
            self._dd_mode.configure(
                fg_color=t["input_bg"], button_color=t["accent"],
                dropdown_fg_color=t["card"], text_color=t["text"])
            self._dd_device.configure(
                fg_color=t["input_bg"], button_color=t["accent"],
                dropdown_fg_color=t["card"], text_color=t["text"])
        except Exception:
            pass

        # Progress bars
        self._pb_scan.configure(progress_color=t["accent"], fg_color=t["progress_bg"])
        self._pb_pool.configure(progress_color=t["green"], fg_color=t["progress_bg"])

        # Log textbox
        self._lb.configure(fg_color=t["log_bg"], text_color=t["dim"])
        tw = self._lb._textbox
        for tag, c in [("t_green", t["green"]), ("t_red", t["red"]),
                       ("t_yellow", t["yellow"]), ("t_cyan", t["cyan"]),
                       ("t_blue", t["blue"]), ("t_purple", t["purple"]),
                       ("t_dim", t["dim"]), ("t_default", t["text"]),
                       ("t_time", t["vdim"]), ("t_gold", t["gold"])]:
            tw.tag_config(tag, foreground=c)

        # Re-flush log to apply new tag colors
        self._log_flushed_count = 0
        self._flush_log()

        # Update all dim labels and themed labels
        for lbl in self._themed_dim_labels:
            try:
                lbl.configure(text_color=t["dim"])
            except Exception:
                pass
        for lbl in self._themed_gold_labels:
            try:
                lbl.configure(text_color=t["gold"])
            except Exception:
                pass

        # Dashboard link
        try:
            self._lbl_dash.configure(text_color=t["cyan"])
        except Exception:
            pass

    # ────────── Animated progress ──────────

    def _animate_tick(self):
        """Single animation loop for all progress bars — runs at ~60fps only when needed."""
        self._anim_id = None
        changed = False

        # Scan bar
        scan_target = max(0, min(1, self.chunk_progress / 100))
        if abs(scan_target - self._anim_scan) > 0.001:
            self._anim_scan += (scan_target - self._anim_scan) * 0.15
            self._pb_scan.set(max(0, min(1, self._anim_scan)))
            changed = True

        # Pool bar
        pool_target = max(0, min(1, self.pool_progress / 100))
        if abs(pool_target - self._anim_pool) > 0.001:
            self._anim_pool += (pool_target - self._anim_pool) * 0.15
            self._pb_pool.set(max(0, min(1, self._anim_pool)))
            changed = True

        if changed:
            self._anim_id = self.root.after(16, self._animate_tick)

    def _start_animation(self):
        """Start the animation loop if not already running."""
        if self._anim_id is None:
            self._anim_id = self.root.after(16, self._animate_tick)

    # ────────── Control handlers ──────────

    def _ghost_hover(self, btn, color, entering):
        """Swap text color on ghost button hover for contrast."""
        if str(btn.cget("state")) == "disabled":
            return
        if entering:
            btn.configure(text_color="#000000")
        else:
            btn.configure(text_color=color)

    def _on_start(self):
        if self._worker_ref:
            self._worker_ref._user_state = "running"
        self._update_ctrl_buttons("running")
        self.log("User: Start", GREEN)

    def _on_pause(self):
        if self._worker_ref:
            self._worker_ref._user_state = "paused"
        self._update_ctrl_buttons("paused")
        self.log("User: Pause (will pause after current assignment)", YELLOW)

    def _on_stop(self):
        if self._worker_ref:
            self._worker_ref._user_state = "stopped"
            self._worker_ref.runner.kill()
        self._update_ctrl_buttons("stopped")
        self.log("User: Stop", RED)

    def _update_ctrl_buttons(self, state):
        t = self.theme
        if state == "running":
            self._btn_start.configure(state="disabled",
                text_color=t["dim"], border_color=t["vdim"])
            self._btn_pause.configure(state="normal",
                text_color=t["yellow"], border_color=t["yellow"])
            self._btn_pause.bind("<Enter>", lambda e: self._ghost_hover(self._btn_pause, t["yellow"], True))
            self._btn_pause.bind("<Leave>", lambda e: self._ghost_hover(self._btn_pause, t["yellow"], False))
            self._btn_stop.configure(state="normal",
                text_color=t["red"], border_color=t["red"])
            self._btn_stop.bind("<Enter>", lambda e: self._ghost_hover(self._btn_stop, t["red"], True))
            self._btn_stop.bind("<Leave>", lambda e: self._ghost_hover(self._btn_stop, t["red"], False))
        elif state == "paused":
            self._btn_start.configure(state="normal", text="\u25b8 RESUME",
                text_color=t["green"], border_color=t["green"])
            self._btn_start.bind("<Enter>", lambda e: self._ghost_hover(self._btn_start, t["green"], True))
            self._btn_start.bind("<Leave>", lambda e: self._ghost_hover(self._btn_start, t["green"], False))
            self._btn_pause.configure(state="disabled",
                text_color=t["dim"], border_color=t["vdim"])
            self._btn_stop.configure(state="normal",
                text_color=t["red"], border_color=t["red"])
            self._btn_stop.bind("<Enter>", lambda e: self._ghost_hover(self._btn_stop, t["red"], True))
            self._btn_stop.bind("<Leave>", lambda e: self._ghost_hover(self._btn_stop, t["red"], False))
        elif state in ("stopped", "idle"):
            self._btn_start.configure(state="normal", text="\u25b8 START",
                text_color=t["green"], border_color=t["green"])
            self._btn_start.bind("<Enter>", lambda e: self._ghost_hover(self._btn_start, t["green"], True))
            self._btn_start.bind("<Leave>", lambda e: self._ghost_hover(self._btn_start, t["green"], False))
            self._btn_pause.configure(state="disabled",
                text_color=t["dim"], border_color=t["vdim"])
            self._btn_stop.configure(state="disabled",
                text_color=t["dim"], border_color=t["vdim"])

    def _on_mode_change(self, value):
        mode_rmap = {"Normal": "normal", "Eco": "eco"}
        new_mode = mode_rmap.get(value, "normal")
        _save_config({"mode": new_mode})
        if self._worker_ref:
            self._worker_ref.mode = new_mode
        self.log(f"Mode changed to: {value}", CYAN)

    def _on_device_change(self, value):
        device_rmap = {"GPU": "gpu", "CPU": "cpu", "CPU+GPU": "cpu_gpu"}
        new_device = device_rmap.get(value, "gpu")
        _save_config({"device": new_device})
        if self._worker_ref:
            self._worker_ref.device = new_device
            self._worker_ref.runner.device = new_device
        self.log(f"Device changed to: {value} (applies on next assignment)", CYAN)

    def _on_settings(self):
        cfg = _load_config()
        SettingsDialog(self.root, cfg, self._apply_settings, theme=self.theme)

    def _apply_settings(self, new_cfg):
        if self._worker_ref:
            w = self._worker_ref
            w.mode = new_cfg.get("mode", w.mode)
            w.eco_cooldown = new_cfg.get("eco_cooldown", w.eco_cooldown)
            w.device = new_cfg.get("device", w.device)
            w.runner.device = w.device
            w.runner.gpu_id = new_cfg.get("gpu_id", w.gpu_id)
            w.runner.cpu_threads = new_cfg.get("cpu_threads", w.runner.cpu_threads)
            w.gpu_id = new_cfg.get("gpu_id", w.gpu_id)
        self.worker_name = new_cfg.get("worker_name", self.worker_name)
        mode_map = {"normal": "Normal", "eco": "Eco"}
        device_map = {"gpu": "GPU", "cpu": "CPU", "cpu_gpu": "CPU+GPU"}
        self._var_mode.set(mode_map.get(new_cfg.get("mode", "normal"), "Normal"))
        self._var_device.set(device_map.get(new_cfg.get("device", "gpu"), "GPU"))
        self.log("Settings saved", GREEN)

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
        if v >= 1e18: return f"{v/1e18:.2f} EK/s"
        if v >= 1e15: return f"{v/1e15:.2f} PK/s"
        if v >= 1e12: return f"{v/1e12:.2f} TK/s"
        if v >= 1e9:  return f"{v/1e9:.2f} GK/s"
        if v >= 1e6:  return f"{v/1e6:.2f} MK/s"
        if v >= 1e3:  return f"{v/1e3:.2f} KK/s"
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
        tag = f"t_{color}" if color in ("green","red","yellow","cyan","blue","purple","dim","gold") else "t_default"
        with self._log_lock:
            self.log_lines.append((ts, msg, tag))
            if len(self.log_lines) > 200:
                self.log_lines.pop(0)
        if not self._log_flush_pending:
            self._log_flush_pending = True
            try:
                self.root.after(50, self._flush_log)
            except Exception:
                self._log_flush_pending = False

    def _flush_log(self):
        self._log_flush_pending = False
        with self._log_lock:
            lines = list(self.log_lines)
        total = len(lines)
        visible = lines[-50:]
        visible_start = max(0, total - 50)
        new_start = max(visible_start, self._log_flushed_count)
        new_lines = lines[new_start:]

        tw = self._lb._textbox
        self._lb.configure(state="normal")

        if new_start <= visible_start and self._log_flushed_count > 0:
            # Buffer scrolled — need to trim old lines from top
            tw.delete("1.0", "end")
            for ts, msg, tag in visible:
                tw.insert("end", f"[{ts}] ", "t_time")
                tw.insert("end", f"{msg}\n", tag)
        elif self._log_flushed_count == 0:
            # First flush — full write
            tw.delete("1.0", "end")
            for ts, msg, tag in visible:
                tw.insert("end", f"[{ts}] ", "t_time")
                tw.insert("end", f"{msg}\n", tag)
        else:
            # Incremental — only append new lines
            for ts, msg, tag in new_lines:
                tw.insert("end", f"[{ts}] ", "t_time")
                tw.insert("end", f"{msg}\n", tag)
            # Trim excess lines from top (keep 50)
            line_count = int(tw.index("end-1c").split(".")[0])
            if line_count > 51:
                tw.delete("1.0", f"{line_count - 50}.0")

        self._log_flushed_count = total
        tw.see("end")
        self._lb.configure(state="disabled")

    # ────────── Refresh loop ──────────

    def _chg(self, key, value):
        """Return True if value changed from last call, and cache it."""
        if self._prev.get(key) != value:
            self._prev[key] = value
            return True
        return False

    def _refresh(self):
        if not self.running:
            return
        self._tick += 1
        t = self.theme
        hx = self.TAG_MAP.get(self.status_color, t["text"])

        if self._chg("status", (self.status, hx)):
            self._lbl_status.configure(text=self.status, text_color=hx)
            self._lbl_hdr_status.configure(text=self.status, text_color=hx)
        show = self._tick % 4 < 3 or self.status != "SCANNING"
        dot_clr = hx if show else t["card"]
        if self._chg("dot", dot_clr):
            self._lbl_dot.configure(text_color=dot_clr)
            self._lbl_hdr_dot.configure(text_color=dot_clr)
        wn = self.worker_name or "..."
        if self._chg("worker", wn):
            self._lbl_worker.configure(text=wn)
        gn = self.gpu_name[:40]
        if self._chg("gpu", gn):
            self._lbl_gpu.configure(text=gn)

        cc = self.current_chunk
        if self._chg("chunk", cc):
            if cc is not None:
                self._lbl_chunk.configure(text=f"Chunk #{cc:,}", text_color=t["accent"])
            else:
                self._lbl_chunk.configure(text="Waiting for work...", text_color=t["dim"])

        rng = (self.chunk_range_start, self.chunk_range_end)
        if self._chg("range", rng):
            if cc is not None:
                self._lbl_range.configure(text=f"{rng[0]}  \u2192  {rng[1]}")
            else:
                self._lbl_range.configure(text="")

        # Kick animation loop (handles both scan + pool bars)
        self._start_animation()

        pct_txt = f"{self.chunk_progress:.1f}%"
        if self._chg("pct", pct_txt):
            self._lbl_pct.configure(text=pct_txt)

        # Heartbeat
        hb_key = (self.heartbeat_ok, int(self.last_heartbeat_ago))
        if self._chg("hb", hb_key):
            if self.heartbeat_ok:
                self._lbl_hb_dot.configure(text_color=t["green"])
                self._lbl_hb_text.configure(text=f"{self.last_heartbeat_ago:.0f}s ago", text_color=t["green"])
            else:
                self._lbl_hb_dot.configure(text_color=t["vdim"])
                self._lbl_hb_text.configure(text="--", text_color=t["dim"])

        # Speed
        spd_txt = self._fs(self.current_speed) if self.current_speed > 0 else "--"
        if self._chg("speed", spd_txt):
            self._lbl_cur_speed.configure(text=spd_txt)

        # ETA + keys in chunk
        if cc is not None and self.chunk_range_start and self.chunk_range_end:
            try:
                rs = int(self.chunk_range_start, 16)
                re_ = int(self.chunk_range_end, 16)
                chunk_size = re_ - rs + 1
                keys_done = int(chunk_size * self.chunk_progress / 100)
                keys_txt = self._fk(keys_done)
                if self.current_speed > 0:
                    remaining = chunk_size * (100 - self.chunk_progress) / 100
                    eta_txt = self._fd(remaining / self.current_speed)
                else:
                    eta_txt = "--"
            except (ValueError, ZeroDivisionError):
                eta_txt = "--"
                keys_txt = "--"
        else:
            eta_txt = "--"
            keys_txt = "--"
        if self._chg("eta", eta_txt):
            self._lbl_eta.configure(text=eta_txt)
        if self._chg("keys_c", keys_txt):
            self._lbl_chunk_keys.configure(text=keys_txt)

        # My Stats
        el = time.time() - self.session_start
        ct = f"{self.chunks_done} done"
        if self.chunks_accepted:
            ct += f"  {self.chunks_accepted} ok"
        if self._chg("s_chunks", ct):
            self._sv["chunks"].configure(text=ct, text_color=t["green"])
        keys_txt2 = self._fk(self.keys_scanned)
        if self._chg("s_keys", keys_txt2):
            self._sv["keys"].configure(text=keys_txt2, text_color=t["accent"])
        spd2 = self._fs(self.current_speed) if self.current_speed > 0 else "--"
        if self._chg("s_speed", spd2):
            self._sv["speed"].configure(text=spd2, text_color=t["cyan"])
        up_txt = self._fd(el)
        if self._chg("s_up", up_txt):
            self._sv["uptime"].configure(text=up_txt, text_color=t["blue"])

        # System
        gpu_txt = f"{self.gpu_usage}%  {self.gpu_temp}\u00b0C  {self.gpu_power}W"
        gpu_clr = t["green"] if self.gpu_usage > 0 else t["dim"]
        if self._chg("sys_gpu", (gpu_txt, gpu_clr)):
            self._sv["gpu"].configure(text=gpu_txt, text_color=gpu_clr)
        vram_txt = f"{self.gpu_mem_used}/{self.gpu_mem_total} MB"
        if self._chg("sys_vram", vram_txt):
            self._sv["vram"].configure(text=vram_txt, text_color=t["cyan"])
        cpu_txt = f"{self.cpu_usage}%"
        if self._chg("sys_cpu", cpu_txt):
            self._sv["cpu"].configure(text=cpu_txt, text_color=t["green"])
        ram_txt = f"{self.ram_used}/{self.ram_total} GB"
        if self._chg("sys_ram", ram_txt):
            self._sv["ram"].configure(text=ram_txt, text_color=t["cyan"])

        # Pool
        pw = str(self.pool_active)
        if self._chg("p_w", pw):
            self._sv["p_workers"].configure(text=pw, text_color=t["green"])
        ps = self._fs(self.pool_speed)
        if self._chg("p_s", ps):
            self._sv["p_speed"].configure(text=ps, text_color=t["cyan"])
        pe = self._fd(self.pool_eta)
        if self._chg("p_e", pe):
            self._sv["p_eta"].configure(text=pe, text_color=t["purple"])
        pp = f"{self.pool_progress:.6f}%"
        if self._chg("p_pct", pp):
            self._lbl_ppct.configure(text=pp)
        psc = self._fk(self.pool_total_keys)
        if self._chg("p_sc", psc):
            self._sv["p_sc"].configure(text=psc)
        prm = self._fk(self.pool_keys_remaining)
        if self._chg("p_rm", prm):
            self._sv["p_rm"].configure(text=prm)
        if self._chg("p_found", self.pool_found):
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
    def __init__(self, gpu_id=0, ui=None, device="gpu", cpu_threads=4,
                 mode="normal", eco_cooldown=60):
        self.gpu_id = gpu_id
        self.api = PoolAPI(POOL_URL)
        self.runner = KeyHuntRunner(str(KEYHUNT_PATH), gpu_id,
                                    device=device, cpu_threads=cpu_threads)
        self.ui = ui
        self.running = True
        self._last_heartbeat_time = 0.0
        self._user_state = "running"  # "running", "paused", "stopped"
        self.device = device
        self.mode = mode
        self.eco_cooldown = eco_cooldown

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
        max_retries = 5
        for attempt in range(max_retries):
            suffix = f" (attempt {attempt + 1}/{max_retries})" if attempt else ""
            self._log(f"Registering as '{name}'...{suffix}", YELLOW)
            try:
                resp = self.api.post("/api/register", {"name": name})
                if resp.get("status") != "ok":
                    raise RuntimeError(f"Registration failed: {resp}")
                self.api.api_key = resp["api_key"]
                _save_config({"api_key": resp["api_key"]})
                self._log(f"Registered as worker #{resp['worker_id']}", GREEN)
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 5 * (attempt + 1)
                    self._log(f"Registration error: {e}. Retrying in {wait}s...", RED)
                    if self.ui:
                        self.ui.status = "RECONNECTING"
                        self.ui.status_color = RED
                    time.sleep(wait)
                else:
                    raise

    def _heartbeat_loop(self, assignment_id, range_start, range_end, interval, stop_event):
        """Background thread: send heartbeats every `interval` seconds."""
        while not stop_event.is_set():
            stop_event.wait(interval)  # interruptible sleep
            if stop_event.is_set():
                break
            progress = self.ui.chunk_progress if self.ui else 0
            span = range_end - range_start
            scanned_up_to = range_start + int((progress / 100) * span)
            speed = self.ui.current_speed if self.ui else 0

            try:
                resp = self.api.post("/api/heartbeat", {
                    "assignment_id": assignment_id,
                    "scanned_up_to": hex(scanned_up_to),
                    "speed": speed,
                    "progress_pct": progress,
                })
                self._last_heartbeat_time = time.time()
                if self.ui:
                    self.ui.heartbeat_ok = True
                    self.ui.last_heartbeat_ago = 0.0

                if not resp.get("continue", True):
                    self._log("Server revoked assignment", RED)
                    self.runner.kill()
                    break
            except Exception as e:
                self._log(f"Heartbeat failed: {e}", YELLOW)

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
            time.sleep(30)

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

    def _heartbeat_age_loop(self):
        """Update heartbeat age display."""
        while self.running:
            if self.ui and self._last_heartbeat_time > 0:
                self.ui.last_heartbeat_ago = time.time() - self._last_heartbeat_time
            time.sleep(1)

    def run(self):
        cfg = _load_config()
        name = cfg.get("worker_name", f"worker-{platform.node()}")
        if self.ui:
            self.ui.worker_name = name
            self.ui.status = "CONNECTING"
            self.ui.status_color = YELLOW
        self.register()

        # Wait for user to press Start (initial state is idle)
        self._user_state = "stopped"
        if self.ui:
            self.ui.status = "IDLE"
            self.ui.status_color = YELLOW
            self.ui.root.after_idle(self.ui._update_ctrl_buttons, "idle")
        self._log("Ready. Press Start to begin scanning.", CYAN)

        threading.Thread(target=self._stats_loop, daemon=True).start()
        threading.Thread(target=self._sys_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_age_loop, daemon=True).start()
        self._fetch_pool_stats()

        while not (self.ui and not self.ui.running):
            # Wait for user to start
            while self._user_state != "running":
                if self.ui and not self.ui.running:
                    return
                time.sleep(0.5)
            # User pressed start — enter the work loop
            self._work_loop()
            # If we exited the work loop, go back to waiting
            if self._user_state == "stopped":
                if self.ui:
                    self.ui.status = "IDLE"
                    self.ui.status_color = YELLOW
                    self.ui.current_speed = 0.0
                    self.ui.chunk_progress = 0.0
                    self.ui.current_chunk = None
                    self.ui.heartbeat_ok = False
                    self.ui.root.after_idle(self.ui._update_ctrl_buttons, "idle")
                continue
            # If the GUI itself is shutting down, break out
            if self.ui and not self.ui.running:
                break

    def _work_loop(self):
        if self.ui:
            self.ui.status = "SCANNING"
            self.ui.status_color = GREEN
            self.ui.root.after_idle(self.ui._update_ctrl_buttons, "running")

        no_work = 0
        while self._user_state == "running":
            # Check pause state
            while self._user_state == "paused":
                if self.ui:
                    self.ui.status = "PAUSED"
                    self.ui.status_color = YELLOW
                time.sleep(1)
            if self._user_state == "stopped":
                break
            if self.ui and not self.ui.running:
                break

            # Sync device/mode from live settings
            self.runner.device = self.device
            cfg = _load_config()
            self.runner.cpu_threads = cfg.get("cpu_threads", self.runner.cpu_threads)
            self.runner.gpu_id = cfg.get("gpu_id", self.runner.gpu_id)

            # Get single assignment
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
                for _ in range(wait):
                    if self._user_state != "running":
                        return
                    time.sleep(1)
                continue

            # Validate response
            if work.get("status") != "ok":
                self._log(f"Unexpected response: {str(work)[:200]}", RED)
                time.sleep(5)
                continue

            # Normalize response — handle both old (chunks array) and new (flat) formats
            if "chunks" in work and isinstance(work["chunks"], list) and work["chunks"]:
                # Old format: {status, target_address, chunks: [{chunk_id, range_start, range_end, ...}]}
                chunk = work["chunks"][0]
                assignment_id = work.get("assignment_id", str(chunk["chunk_id"]))
                target = work["target_address"]
                rs = chunk["range_start"]
                re_ = chunk["range_end"]
                chunk_id = chunk["chunk_id"]
                heartbeat_interval = work.get("heartbeat_interval", 30)
            elif "assignment_id" in work:
                # New format: {status, assignment_id, chunk_id, target_address, range_start, range_end, ...}
                assignment_id = work["assignment_id"]
                target = work["target_address"]
                rs = work["range_start"]
                re_ = work["range_end"]
                chunk_id = work.get("chunk_id", 0)
                heartbeat_interval = work.get("heartbeat_interval", 30)
            else:
                self._log(f"Unknown work format: {str(work)[:200]}", RED)
                time.sleep(5)
                continue

            no_work = 0
            if self.ui:
                self.ui.status = "SCANNING"
                self.ui.status_color = GREEN

            # Parse range for heartbeat calculations
            range_start_int = int(rs, 16)
            range_end_int = int(re_, 16)
            chunk_size = range_end_int - range_start_int + 1

            if self.ui:
                self.ui.current_chunk = chunk_id
                self.ui.assignment_id = assignment_id
                self.ui.chunk_range_start = rs
                self.ui.chunk_range_end = re_
                self.ui.chunk_progress = 0.0
                self.ui.current_speed = 0.0
                self.ui.heartbeat_ok = False

            self._log(f"Assignment {assignment_id[:8]}... range {rs} -> {re_}", LBLUE)

            # Start heartbeat thread with per-assignment stop event
            hb_stop = threading.Event()
            hb_thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(assignment_id, range_start_int, range_end_int, heartbeat_interval, hb_stop),
                daemon=True,
            )
            hb_thread.start()

            # Run KeyHunt
            result = self.runner.run(rs, re_, target, self.ui)

            # Stop heartbeat — signal first, then join
            hb_stop.set()
            hb_thread.join(timeout=5)

            if result["status"] == "found":
                self._log("KEY FOUND! Reporting to pool...", GREEN)
                if self.ui:
                    self.ui.status = "KEY FOUND!"
                    self.ui.status_color = GREEN
                try:
                    self.api.post("/api/found", {
                        "chunk_id": chunk_id,
                        "private_key": result["found_key"]["privkey"],
                    })
                    self._log("Key reported to pool!", GREEN)
                except Exception as e:
                    self._log(f"FAILED to report key: {e}", RED)
                try:
                    self.api.post("/api/work/complete", {
                        "assignment_id": assignment_id,
                        "range_start": rs,
                        "range_end": re_,
                    })
                except Exception:
                    pass
                continue

            if result["status"] in ("complete", "timeout"):
                self._log(f"Assignment {assignment_id[:8]}... complete", GREEN)
                try:
                    rpt = self.api.post("/api/work/complete", {
                        "assignment_id": assignment_id,
                        "range_start": rs,
                        "range_end": re_,
                    })
                    if rpt.get("accepted"):
                        if self.ui:
                            self.ui.chunks_done += 1
                            self.ui.chunks_accepted += 1
                            self.ui.keys_scanned += chunk_size
                        self._log("Accepted by pool", GREEN)
                    else:
                        self._log(f"Rejected: {rpt.get('detail', 'unknown')}", YELLOW)
                except Exception as e:
                    self._log(f"Report error: {e}", RED)
            else:
                self._log(f"Assignment error: {result.get('error', result['status'])}", RED)
                if self.ui and self.ui.chunk_progress > 0:
                    self._log(f"Partial progress: {self.ui.chunk_progress:.1f}%", YELLOW)

            if self.ui:
                self.ui.current_chunk = None
                self.ui.current_speed = 0.0
                self.ui.chunk_progress = 0.0
                self.ui.heartbeat_ok = False

            # Eco mode cooldown
            if self.mode == "eco" and self._user_state == "running":
                self._log(f"Eco mode: cooling down {self.eco_cooldown}s...", CYAN)
                if self.ui:
                    self.ui.status = "ECO COOLDOWN"
                    self.ui.status_color = CYAN
                for i in range(self.eco_cooldown):
                    if self._user_state != "running":
                        break
                    time.sleep(1)

            # Check pause after assignment
            while self._user_state == "paused":
                if self.ui:
                    self.ui.status = "PAUSED"
                    self.ui.status_color = YELLOW
                time.sleep(1)
            if self._user_state == "stopped":
                break


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
        worker = PoolWorker(
            gpu_id=cfg.get("gpu_id", 0),
            ui=gui,
            device=cfg.get("device", "gpu"),
            cpu_threads=cfg.get("cpu_threads", 4),
            mode=cfg.get("mode", "normal"),
            eco_cooldown=cfg.get("eco_cooldown", 60),
        )
        gui._worker_ref = worker
        gui._worker_stop = lambda: (
            setattr(worker, '_user_state', 'stopped'),
            setattr(worker, 'running', False),
            worker.runner.kill(),
        )
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
