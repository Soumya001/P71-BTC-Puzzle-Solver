"""
Retro Space-themed Terminal UI for Puzzle Pool Worker.
Zero external dependencies - pure ANSI escape codes.
"""

import os
import platform
import random
import shutil
import subprocess
import sys
import threading
import time

# ─── ANSI Colors ───
ESC = "\033["
RESET = f"{ESC}0m"
BOLD = f"{ESC}1m"
DIM = f"{ESC}2m"

# Foreground
BLACK = f"{ESC}30m"
RED = f"{ESC}31m"
GREEN = f"{ESC}32m"
YELLOW = f"{ESC}33m"
BLUE = f"{ESC}34m"
MAGENTA = f"{ESC}35m"
CYAN = f"{ESC}36m"
WHITE = f"{ESC}37m"
ORANGE = f"{ESC}38;5;208m"
GOLD = f"{ESC}38;5;220m"
GREY = f"{ESC}38;5;240m"
LGREY = f"{ESC}38;5;245m"
DGREY = f"{ESC}38;5;236m"
PINK = f"{ESC}38;5;205m"
LGREEN = f"{ESC}38;5;82m"
LBLUE = f"{ESC}38;5;75m"
PURPLE = f"{ESC}38;5;141m"
DBLUE = f"{ESC}38;5;24m"

# Background
BG_BLACK = f"{ESC}40m"
BG_DGREY = f"{ESC}48;5;233m"
BG_VDGREY = f"{ESC}48;5;232m"
BG_BLUE = f"{ESC}48;5;17m"
BG_DBLUE = f"{ESC}48;5;16m"

HIDE_CURSOR = f"{ESC}?25l"
SHOW_CURSOR = f"{ESC}?25h"
CLEAR = f"{ESC}2J{ESC}H"
HOME = f"{ESC}H"


def enable_ansi_windows():
    """Enable ANSI escape codes on Windows 10+."""
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def goto(row, col):
    return f"{ESC}{row};{col}H"


class StarField:
    """Animated starfield background effect."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.stars = []
        for _ in range(max(20, width * height // 80)):
            self.stars.append({
                "x": random.randint(0, width - 1),
                "y": random.randint(0, height - 1),
                "char": random.choice([".", "·", "∙", "*", "✦"]),
                "bright": random.random(),
                "speed": random.uniform(0.02, 0.08),
            })

    def render(self, frame: int) -> list[tuple[int, int, str]]:
        result = []
        for s in self.stars:
            brightness = (1 + abs(((frame * s["speed"]) % 2) - 1)) / 2
            if brightness > 0.7:
                color = WHITE
            elif brightness > 0.4:
                color = LGREY
            else:
                color = DGREY
            result.append((s["y"], s["x"], f"{color}{s['char']}{RESET}"))
        return result


class WorkerTUI:
    """Main TUI renderer."""

    def __init__(self):
        self.running = True
        self.frame = 0
        self.width = 80
        self.height = 40
        self._lock = threading.Lock()

        # Worker state
        self.status = "CONNECTING"
        self.status_color = YELLOW
        self.worker_name = ""
        self.pool_url = ""
        self.gpu_name = "Detecting..."
        self.keyhunt_pid = None

        # Current scan
        self.current_chunk = None
        self.chunk_range_start = ""
        self.chunk_range_end = ""
        self.chunk_progress = 0.0
        self.canaries_total = 5
        self.canaries_found = 0
        self.canary_addresses = []
        self.canary_found_set = set()

        # Worker stats
        self.chunks_done = 0
        self.chunks_accepted = 0
        self.chunks_rejected = 0
        self.keys_scanned = 0
        self.session_start = time.time()
        self.batch_times = []

        # System stats
        self.gpu_usage = 0
        self.gpu_temp = 0
        self.gpu_power = 0
        self.gpu_mem_used = 0
        self.gpu_mem_total = 0
        self.cpu_usage = 0
        self.ram_used = 0
        self.ram_total = 0

        # Pool stats
        self.pool_workers = 0
        self.pool_active = 0
        self.pool_progress = 0.0
        self.pool_speed = 0
        self.pool_eta = 0
        self.pool_total_keys = 0
        self.pool_keys_remaining = 0
        self.pool_chunks_done = 0
        self.pool_total_chunks = 0
        self.pool_found = 0

        # Log buffer
        self.log_lines = []
        self.max_log = 6

        # Star field
        self.stars = None

    def log(self, msg: str, color: str = LGREY):
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self.log_lines.append((ts, msg, color))
            if len(self.log_lines) > self.max_log:
                self.log_lines.pop(0)

    def _get_size(self):
        try:
            sz = shutil.get_terminal_size((80, 40))
            self.width = max(sz.columns, 70)
            self.height = max(sz.lines, 30)
        except Exception:
            pass

    def _box_top(self, w):
        return f"{DBLUE}╔{'═' * (w - 2)}╗{RESET}"

    def _box_mid(self, w):
        return f"{DBLUE}╠{'═' * (w - 2)}╣{RESET}"

    def _box_bot(self, w):
        return f"{DBLUE}╚{'═' * (w - 2)}╝{RESET}"

    def _box_side(self):
        return f"{DBLUE}║{RESET}"

    def _pad(self, text: str, w: int) -> str:
        """Pad text to width, accounting for ANSI codes."""
        visible = 0
        i = 0
        while i < len(text):
            if text[i] == '\033':
                while i < len(text) and text[i] != 'm':
                    i += 1
                i += 1
            else:
                visible += 1
                i += 1
        padding = max(0, w - visible)
        return text + " " * padding

    def _line(self, content: str, w: int) -> str:
        return f"{self._box_side()} {self._pad(content, w - 4)} {self._box_side()}"

    def _progress_bar(self, pct: float, width: int, filled_color: str = ORANGE,
                      empty_color: str = DGREY, char_filled: str = "█",
                      char_empty: str = "░", animate: bool = True) -> str:
        filled = int(pct / 100 * width)
        empty = width - filled

        # Animated leading edge
        lead = ""
        if animate and filled < width and pct > 0:
            pulse = ["▓", "▒", "░"][self.frame % 3]
            if filled > 0:
                bar = f"{filled_color}{char_filled * (filled - 1)}{GOLD}{pulse}{RESET}"
            else:
                bar = f"{GOLD}{pulse}{RESET}"
            bar += f"{empty_color}{char_empty * (empty)}{RESET}"
        else:
            bar = f"{filled_color}{char_filled * filled}{RESET}{empty_color}{char_empty * empty}{RESET}"

        return bar

    def _format_keys(self, n):
        if n >= 1e18:
            return f"{n / 1e18:.2f} Exa"
        if n >= 1e15:
            return f"{n / 1e15:.2f} Peta"
        if n >= 1e12:
            return f"{n / 1e12:.2f} T"
        if n >= 1e9:
            return f"{n / 1e9:.2f} B"
        if n >= 1e6:
            return f"{n / 1e6:.2f} M"
        if n >= 1e3:
            return f"{n:,.0f}"
        return str(int(n))

    def _format_speed(self, kps):
        if kps >= 1e12:
            return f"{kps / 1e12:.2f} TK/s"
        if kps >= 1e9:
            return f"{kps / 1e9:.2f} GK/s"
        if kps >= 1e6:
            return f"{kps / 1e6:.2f} MK/s"
        return f"{kps:.0f} K/s"

    def _format_duration(self, sec):
        if sec <= 0 or sec > 1e15:
            return "--"
        y = int(sec / (365.25 * 86400))
        d = int((sec % (365.25 * 86400)) / 86400)
        h = int((sec % 86400) / 3600)
        m = int((sec % 3600) / 60)
        s = int(sec % 60)
        if y > 0:
            return f"{y}y {d}d"
        if d > 0:
            return f"{d}d {h}h"
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    def _format_uptime(self):
        return self._format_duration(time.time() - self.session_start)

    def render(self):
        """Render one frame of the TUI."""
        self._get_size()
        w = min(self.width, 82)
        inner = w - 4

        if self.stars is None or self.stars.width != w:
            self.stars = StarField(w, 38)

        lines = []

        # ─── HEADER ───
        lines.append(self._box_top(w))

        # Title with animated bitcoin symbol
        btc_frames = ["₿", "฿", "₿", "Ƀ"]
        btc = f"{ORANGE}{BOLD}{btc_frames[self.frame % 4]}{RESET}"
        title = f"  {btc} {ORANGE}{BOLD}PUZZLE POOL WORKER{RESET}                              {DGREY}v1.0.0{RESET}"
        lines.append(self._line(title, w))

        # Animated subtitle dots
        dots = "·" * ((self.frame % 4) + 1)
        sub = f"  {DGREY}{'▀' * 20}{RESET}   {GREY}{dots}{RESET}"
        lines.append(self._line(sub, w))

        lines.append(self._box_mid(w))

        # ─── STATUS BAR ───
        status_icon = "●" if self.status == "SCANNING" else "◌" if self.status == "CONNECTING" else "■"
        if self.status == "SCANNING":
            spin = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"][self.frame % 10]
            status_display = f"{self.status_color}{BOLD}{spin} {self.status}{RESET}"
        else:
            status_display = f"{self.status_color}{BOLD}{status_icon} {self.status}{RESET}"

        status_line = f"  STATUS: {status_display}"
        pool_display = f"{LBLUE}{self.pool_url.replace('https://', '')}{RESET}"
        pad1 = " " * max(1, 34 - len(self.status) - 10)
        lines.append(self._line(f"{status_line}{pad1}POOL: {pool_display}", w))

        worker_display = f"{CYAN}{self.worker_name}{RESET}"
        gpu_short = self.gpu_name[:30] if self.gpu_name else "N/A"
        gpu_display = f"{GREEN}{gpu_short}{RESET}"
        lines.append(self._line(f"  WORKER: {worker_display}              GPU: {gpu_display}", w))

        lines.append(self._box_mid(w))

        # ─── CURRENT SCAN ───
        lines.append(self._line(f"  {GOLD}{BOLD}◆ CURRENT SCAN{RESET}", w))
        lines.append(self._line("", w))

        if self.current_chunk is not None:
            chunk_display = f"{ORANGE}{BOLD}#{self.current_chunk:,}{RESET}"
            lines.append(self._line(f"    CHUNK {chunk_display}    {GREY}RANGE:{RESET} {CYAN}{self.chunk_range_start}{RESET}", w))
            lines.append(self._line(f"                         {GREY}  TO:{RESET} {CYAN}{self.chunk_range_end}{RESET}", w))
        else:
            lines.append(self._line(f"    {GREY}Waiting for work assignment...{RESET}", w))
            lines.append(self._line("", w))

        # Progress bar
        bar_w = inner - 22
        bar = self._progress_bar(self.chunk_progress, bar_w)
        pct_str = f"{self.chunk_progress:5.1f}%"
        scan_label = "scanning" if self.chunk_progress < 100 else "done"
        lines.append(self._line(f"    {bar} {ORANGE}{pct_str}{RESET} {GREY}[{scan_label}]{RESET}", w))
        lines.append(self._line("", w))

        # Canaries
        canary_str = "    "
        for i in range(self.canaries_total):
            if i < len(self.canary_addresses):
                addr = self.canary_addresses[i]
                short = addr[:8] + "..." + addr[-4:] if len(addr) > 14 else addr
                if addr in self.canary_found_set:
                    canary_str += f"{GREEN}✓{RESET} {GREY}{short}{RESET} "
                else:
                    canary_str += f"{DGREY}○{RESET} {DGREY}{short}{RESET} "
            else:
                canary_str += f"{DGREY}○ waiting{RESET}  "
        lines.append(self._line(f"  {GREY}CANARIES:{RESET} {canary_str}", w))

        lines.append(self._box_mid(w))

        # ─── STATS SPLIT ───
        half = inner // 2 - 1

        lines.append(self._line(
            f"  {GOLD}{BOLD}◆ MY STATS{RESET}" + " " * (half - 11) +
            f"{GREY}│{RESET}  {GOLD}{BOLD}◆ SYSTEM{RESET}", w))
        lines.append(self._line(f"  {'─' * (half - 2)}{GREY}│{RESET}  {'─' * (half - 2)}", w))

        # Left: worker stats | Right: system stats
        avg_speed = 0
        if self.chunks_done > 0:
            elapsed = time.time() - self.session_start
            avg_speed = self.keys_scanned / elapsed if elapsed > 0 else 0

        stat_pairs = [
            (f"  Chunks done:   {LGREEN}{self.chunks_done}{RESET}",
             f"  GPU: {GREEN}{self.gpu_usage}%{RESET} │ {ORANGE}{self.gpu_temp}°C{RESET} │ {YELLOW}{self.gpu_power}W{RESET}"),
            (f"  Keys scanned:  {ORANGE}{self._format_keys(self.keys_scanned)}{RESET}",
             f"  MEM: {CYAN}{self.gpu_mem_used}MB{RESET}/{self.gpu_mem_total}MB"),
            (f"  Session time:  {LBLUE}{self._format_uptime()}{RESET}",
             f"  CPU: {GREEN}{self.cpu_usage}%{RESET}  RAM: {CYAN}{self.ram_used:.1f}{RESET}/{self.ram_total:.1f}GB"),
            (f"  Avg speed:     {CYAN}{self._format_speed(avg_speed)}{RESET}",
             f"  KeyHunt PID: {GREY}{self.keyhunt_pid or '--'}{RESET}"),
            (f"  Accepted:      {GREEN}{self.chunks_accepted}{RESET}  {RED}Rej: {self.chunks_rejected}{RESET}",
             f""),
        ]

        for left, right in stat_pairs:
            left_padded = self._pad(left, half)
            lines.append(self._line(f"{left_padded}{GREY}│{RESET}{right}", w))

        lines.append(self._box_mid(w))

        # ─── POOL NETWORK ───
        lines.append(self._line(f"  {GOLD}{BOLD}◆ POOL NETWORK{RESET}", w))

        net_line1_l = f"  Workers: {GREEN}{self.pool_active}{RESET} online"
        net_line1_r = f"Progress: {ORANGE}{self.pool_progress:.8f}%{RESET}"
        pad2 = " " * max(1, half - 20)
        lines.append(self._line(f"{net_line1_l}{pad2}{net_line1_r}", w))

        net_line2_l = f"  Speed: {CYAN}{self._format_speed(self.pool_speed)}{RESET}"
        net_line2_r = f"ETA: {PURPLE}{self._format_duration(self.pool_eta)}{RESET}"
        pad3 = " " * max(1, half - 14)
        lines.append(self._line(f"{net_line2_l}{pad3}{net_line2_r}", w))

        # Pool progress bar
        pool_bar_w = inner - 18
        pool_bar = self._progress_bar(self.pool_progress, pool_bar_w, LGREEN, DGREY, "█", "░", False)
        lines.append(self._line(f"  {pool_bar} {LGREEN}{self.pool_progress:.4f}%{RESET}", w))

        scanned_str = self._format_keys(self.pool_total_keys)
        remain_str = self._format_keys(self.pool_keys_remaining)
        lines.append(self._line(
            f"  {GREY}Scanned:{RESET} {ORANGE}{scanned_str}{RESET} keys"
            f"    {GREY}Remaining:{RESET} {LBLUE}{remain_str}{RESET} keys", w))

        if self.pool_found > 0:
            lines.append(self._line(
                f"  {GREEN}{BOLD}★ {self.pool_found} KEY(S) FOUND! ★{RESET}", w))

        lines.append(self._box_mid(w))

        # ─── LOG ───
        lines.append(self._line(f"  {GREY}LOG{RESET}", w))
        with self._lock:
            display_logs = list(self.log_lines)

        for i in range(self.max_log):
            if i < len(display_logs):
                ts, msg, color = display_logs[i]
                log_text = f"  {DGREY}{ts}{RESET} {color}{msg[:inner - 14]}{RESET}"
            else:
                log_text = ""
            lines.append(self._line(log_text, w))

        lines.append(self._box_mid(w))

        # ─── FOOTER ───
        footer = (
            f"  {LBLUE}Dashboard:{RESET} {CYAN}https://starnetlive.space{RESET}"
            f"          {GREY}Ctrl+C to quit{RESET}"
        )
        lines.append(self._line(footer, w))
        lines.append(self._box_bot(w))

        return "\n".join(lines)

    def draw(self):
        """Draw the TUI to terminal."""
        output = HOME + self.render()
        sys.stdout.write(output)
        sys.stdout.flush()
        self.frame += 1

    def start_render_loop(self):
        """Background thread that redraws the TUI."""
        enable_ansi_windows()
        sys.stdout.write(HIDE_CURSOR + CLEAR)
        sys.stdout.flush()

        while self.running:
            try:
                self.draw()
            except Exception:
                pass
            time.sleep(0.25)

        sys.stdout.write(SHOW_CURSOR + CLEAR)
        sys.stdout.flush()

    def stop(self):
        self.running = False
        time.sleep(0.3)
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


def get_gpu_stats(gpu_id: int = 0) -> dict:
    """Get GPU stats from nvidia-smi."""
    try:
        cmd = [
            "nvidia-smi",
            f"--id={gpu_id}",
            "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,name",
            "--format=csv,noheader,nounits",
        ]
        if platform.system() == "Windows":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, startupinfo=si)
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 6:
                return {
                    "usage": int(float(parts[0])),
                    "temp": int(float(parts[1])),
                    "power": int(float(parts[2])),
                    "mem_used": int(float(parts[3])),
                    "mem_total": int(float(parts[4])),
                    "name": parts[5].replace("NVIDIA ", "").replace("GeForce ", ""),
                }
    except Exception:
        pass
    return None


def get_cpu_ram_stats() -> dict:
    """Get CPU and RAM usage."""
    cpu = 0
    ram_used = 0.0
    ram_total = 0.0

    if platform.system() == "Linux":
        try:
            with open("/proc/stat") as f:
                line = f.readline()
                parts = line.split()
                idle = int(parts[4])
                total = sum(int(x) for x in parts[1:])
                cpu = max(0, min(100, 100 - (idle * 100 // total)))
        except Exception:
            pass
        try:
            with open("/proc/meminfo") as f:
                mem = {}
                for line in f:
                    parts = line.split()
                    mem[parts[0].rstrip(":")] = int(parts[1])
                ram_total = mem.get("MemTotal", 0) / 1024 / 1024
                ram_free = mem.get("MemAvailable", mem.get("MemFree", 0)) / 1024 / 1024
                ram_used = ram_total - ram_free
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(
                ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/value"],
                capture_output=True, text=True, timeout=5, startupinfo=si,
            )
            for line in result.stdout.strip().split("\n"):
                if "FreePhysicalMemory=" in line:
                    ram_free_kb = int(line.split("=")[1])
                elif "TotalVisibleMemorySize=" in line:
                    ram_total = int(line.split("=")[1]) / 1024 / 1024
            ram_used = ram_total - (ram_free_kb / 1024 / 1024)
        except Exception:
            pass

    return {"cpu": cpu, "ram_used": round(ram_used, 1), "ram_total": round(ram_total, 1)}


def system_stats_loop(tui: WorkerTUI, gpu_id: int = 0):
    """Background thread to update system stats."""
    while tui.running:
        gpu = get_gpu_stats(gpu_id)
        if gpu:
            tui.gpu_usage = gpu["usage"]
            tui.gpu_temp = gpu["temp"]
            tui.gpu_power = gpu["power"]
            tui.gpu_mem_used = gpu["mem_used"]
            tui.gpu_mem_total = gpu["mem_total"]
            if gpu["name"]:
                tui.gpu_name = gpu["name"]

        cpu_ram = get_cpu_ram_stats()
        tui.cpu_usage = cpu_ram["cpu"]
        tui.ram_used = cpu_ram["ram_used"]
        tui.ram_total = cpu_ram["ram_total"]

        time.sleep(2)
