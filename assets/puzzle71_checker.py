import hashlib, time, random, requests, base58, tkinter as tk, socket, os
from coincurve import PrivateKey   # ⚡ faster than ecdsa
from multiprocessing import Process, Value, cpu_count, freeze_support

# ================= CONFIG =================
TARGET_ADDR   = "1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU"
BOT_TOKEN     = "***"   #TG
CHAT_ID       = "***"   #TG
BASE_BATCH    = 50000   # ⚡ start higher for fewer Python loops
TUNE_INTERVAL = 5       # seconds between auto-tune checks
# ==========================================

RANGE_START = int("400000000000000000", 16)
RANGE_END   = int("7FFFFFFFFFFFFFFFFF", 16)
KEYSPACE    = RANGE_END - RANGE_START + 1

# --- Internet check ---
def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False

# --- Crypto helpers ---
def b58decode_check(b58str):
    data = base58.b58decode(b58str)
    return data[:-4]

target_payload   = b58decode_check(TARGET_ADDR)
TARGET_HASH160   = target_payload[1:]

def priv_to_hash160(priv_int):
    priv_bytes = priv_int.to_bytes(32, 'big')
    pk = PrivateKey(priv_bytes)
    pubkey = pk.public_key.format(compressed=True)  # already compressed
    sha = hashlib.sha256(pubkey).digest()
    return hashlib.new('ripemd160', sha).digest()

def priv_to_wif(priv_int):
    priv_bytes = priv_int.to_bytes(32, 'big')
    payload    = b'\x80' + priv_bytes + b'\x01'
    checksum   = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return base58.b58encode(payload + checksum).decode()

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=5)
    except Exception:
        pass

# --- Worker (hybrid batching) ---
def worker(total_tries, found_flag, batch_size, stop_flag):
    rng = random.Random()
    step = max(20000, batch_size // 20)  # bigger mini-steps
    while not found_flag.value and not stop_flag.value:
        done = 0
        while done < batch_size:
            keys = [(RANGE_START + (rng.getrandbits(128) % KEYSPACE)) for _ in range(step)]
            for key in keys:
                if found_flag.value or stop_flag.value:
                    return
                h160 = priv_to_hash160(key)
                if h160 == TARGET_HASH160:
                    wif = priv_to_wif(key)
                    with open("found.txt", "a") as f:
                        f.write(f"TARGET,{hex(key)},{wif},{TARGET_ADDR}\n")
                    found_flag.value = 1
                    msg = f"🎯 Puzzle #71 HIT!\nKey: {hex(key)}\nWIF: {wif}\nAddr: {TARGET_ADDR}"
                    send_telegram(msg)
                    return
            with total_tries.get_lock():
                total_tries.value += step
            done += step

# --- Formatting ---
def format_number(n):
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n/1_000:.2f}K"
    return str(n)

# --- CMD Style GUI with custom title bar ---
class CheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.overrideredirect(True)
        self.root.geometry("640x380")
        self.root.configure(bg="black")

        self.console_font = ("Consolas", 12)
        self.color        = "#00FF41"

        # --- Custom Title Bar ---
        self.title_bar = tk.Frame(root, bg="black", relief="raised", bd=0,
                                  highlightthickness=1, highlightbackground=self.color)
        self.title_bar.pack(fill="x")

        self.title_label = tk.Label(self.title_bar, text="Puzzle71.exe | Status: Idle",
                                    fg=self.color, bg="black", font=("Consolas", 13, "bold"))
        self.title_label.pack(side="left", padx=8)

        # Minimize button
        self.min_btn = tk.Label(self.title_bar, text="–", bg="black", fg=self.color,
                                width=3, font=("Consolas", 12, "bold"))
        self.min_btn.pack(side="right")
        self.min_btn.bind("<Button-1>", lambda e: self.minimize())
        self.min_btn.bind("<Enter>", lambda e: self.min_btn.config(bg=self.color, fg="black"))
        self.min_btn.bind("<Leave>", lambda e: self.min_btn.config(bg="black", fg=self.color))

        # Close button
        self.close_btn = tk.Label(self.title_bar, text="X", bg="black", fg="red",
                                  width=3, font=("Consolas", 12, "bold"))
        self.close_btn.pack(side="right")
        self.close_btn.bind("<Button-1>", lambda e: self.close())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.config(bg="red", fg="black"))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.config(bg="black", fg="red"))

        # Dragging
        for widget in (self.title_bar, self.title_label):
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)

        # --- Target ---
        tk.Label(root, text=f"Target: {TARGET_ADDR}",
                 fg=self.color, bg="black", font=self.console_font).pack(pady=5)

        # --- Thread selection ---
        max_threads = cpu_count()
        self.thread_var  = tk.StringVar(value=str(max_threads))
        thread_frame     = tk.Frame(root, bg="black")
        thread_frame.pack(pady=5)
        tk.Label(thread_frame, text="Select CPU cores:",
                 fg=self.color, bg="black", font=self.console_font).pack(side="left", padx=5)
        self.thread_menu = tk.OptionMenu(thread_frame, self.thread_var,
                                         *[str(i) for i in range(1, max_threads+1)])
        self.thread_menu.config(bg="black", fg=self.color, font=self.console_font, width=6,
                                highlightbackground=self.color, highlightthickness=1,
                                activebackground="black", activeforeground="white", bd=1)
        self.thread_menu["menu"].config(bg="black", fg=self.color,
                                        activebackground="black", activeforeground="white",
                                        font=self.console_font)
        self.thread_menu.pack(side="left")

        # --- Stats ---
        self.stats_label = tk.Label(root, text="Idle...",
                                    fg=self.color, bg="black",
                                    font=self.console_font, justify="left")
        self.stats_label.pack(pady=15)

        # --- Buttons ---
        btn_frame = tk.Frame(root, bg="black")
        btn_frame.pack(pady=10)
        self.start_btn = tk.Button(btn_frame, text="> START", command=self.start_checker,
                                   bg="black", fg=self.color, font=self.console_font,
                                   activebackground="black", activeforeground="white",
                                   width=12, relief="ridge")
        self.start_btn.grid(row=0, column=0, padx=10)
        self.stop_btn = tk.Button(btn_frame, text="> STOP", command=self.stop_checker,
                                  bg="black", fg="red", font=self.console_font,
                                  activebackground="black", activeforeground="white",
                                  width=12, relief="ridge", state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=10)

        # Vars
        self.procs       = []
        self.start_time  = None
        self.total_tries = None
        self.found_flag  = None
        self.stop_flag   = None
        self.batch_size  = BASE_BATCH
        self.last_check  = None
        self.last_tries  = 0

        # Internet check at startup
        if not check_internet():
            self.start_btn.config(state="disabled")
            self.stats_label.config(text="⚠️ Please connect to the internet")
        else:
            self.stats_label.config(text="✅ Internet connected. Ready to start.")

        self.root.after(2000, self.check_connection_loop)

    # --- Internet re-check ---
    def check_connection_loop(self):
        if check_internet():
            if not self.procs:  # idle
                self.start_btn.config(state="normal")
                self.stats_label.config(text="✅ Internet connected. Ready to start.")
        else:
            self.start_btn.config(state="disabled")
            if self.procs:  # scanning in progress
                self.stop_checker()
                self.stats_label.config(text="⚠ Lost internet connection. Scanning stopped.")
                self.title_label.config(text="Puzzle71.exe | Status: No Internet")
            else:
                self.stats_label.config(text="⚠ Please connect to the internet")
        self.root.after(5000, self.check_connection_loop)

    # --- Title bar drag ---
    def start_move(self, event): self.x, self.y = event.x, event.y
    def do_move(self, event):
        x, y = event.x_root - self.x, event.y_root - self.y
        self.root.geometry(f"+{x}+{y}")

    # --- Title bar buttons ---
    def minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        def check_restore():
            if self.root.state() == "normal":
                self.root.overrideredirect(True)
            else:
                self.root.after(200, check_restore)
        self.root.after(200, check_restore)
    def close(self):
        self.root.overrideredirect(False)
        self.root.quit()
        self.root.destroy()

    # --- Checker controls ---
    def start_checker(self):
        if self.procs: return
        threads = int(self.thread_var.get())
        self.batch_size = BASE_BATCH * threads
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.title_label.config(text="Puzzle71.exe | Status: Scanning…")
        self.start_time  = time.time()
        self.total_tries = Value("L", 0)
        self.found_flag  = Value("i", 0)
        self.stop_flag   = Value("i", 0)
        for i in range(threads):
            p = Process(target=worker, args=(self.total_tries, self.found_flag,
                                             self.batch_size, self.stop_flag))
            p.start()
            self.procs.append(p)
        send_telegram(f"✅ Puzzle71 checker started with {threads} threads, batch={self.batch_size}")
        self.last_check = time.time()
        self.update_stats()

    def stop_checker(self):
        if not self.procs: return
        self.stop_flag.value = 1
        for p in self.procs:
            p.terminate(); p.join()
        self.procs.clear()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.stats_label.config(text="⏹ Stopped by user")
        self.title_label.config(text="Puzzle71.exe | Status: Stopped")

    def update_stats(self):
        if not self.start_time: return
        with self.total_tries.get_lock():
            tried = self.total_tries.value
        elapsed   = time.time() - self.start_time
        speed     = tried / elapsed if elapsed > 0 else 0
        coverage  = (tried / KEYSPACE) * 100
        h, m      = divmod(int(elapsed), 3600)
        m, s      = divmod(m, 60)

        # Auto-tune batch size
        if time.time() - self.last_check >= TUNE_INTERVAL and not self.found_flag.value:
            recent_tries = tried - self.last_tries
            recent_speed = recent_tries / TUNE_INTERVAL
            if recent_speed < speed * 0.9:
                self.batch_size = max(BASE_BATCH, self.batch_size // 2)
            else:
                self.batch_size = min(self.batch_size * 2, 1_000_000)
            self.last_check = time.time()
            self.last_tries = tried

        if not self.found_flag.value and not self.stop_flag.value:
            self.stats_label.config(
                text=f"Keys tried: {format_number(tried)}\n"
                     f"Speed: {format_number(int(speed))}/sec\n"
                     f"Time: {h:02d}:{m:02d}:{s:02d}\n"
                     f"Coverage: {coverage:.12f}%\n"
                     f"Batch size: {self.batch_size}"
            )
            self.root.after(2000, self.update_stats)  # update every 2 sec
        elif self.found_flag.value:
            self.stats_label.config(text="🎯 TARGET FOUND!\nDetails sent securely.")
            self.title_label.config(text="Puzzle71.exe | Status: FOUND")

# --- Main ---
def main():
    root = tk.Tk()
    root.title("Puzzle71.exe")
    try:
        root.iconbitmap("icon.ico")
        icon_img = tk.PhotoImage(file="icon.png")
        root.call('wm', 'iconphoto', root._w, icon_img)
    except Exception as e:
        print("Could not load icon:", e)
    app = CheckerApp(root)
    root.mainloop()

if __name__ == "__main__":
    freeze_support()  # ✅ prevents multiple instances spawning
    main()
