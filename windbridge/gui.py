from __future__ import annotations

import os
import socket
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Iterable
from tkinter import filedialog, messagebox, ttk

import qrcode
import pystray
from PIL import Image, ImageTk

try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    DND_FILES = None

from .discovery import DiscoveryResponder
from .network import get_local_ip
from .server import LocalServer, create_app
from .settings import Settings
from .state import BridgeState


THEME = {
    "deep": "#123F4A",
    "nav": "#155866",
    "wind": "#2B8492",
    "wind_hover": "#236F7C",
    "sky": "#DDF1EE",
    "pale": "#F2F8F5",
    "surface": "#FFFDF7",
    "gold": "#C9A85D",
    "gold_soft": "#EBDDAE",
    "line": "#CFE0DB",
    "text": "#244047",
    "muted": "#6B8185",
    "danger": "#B8625A",
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative


def human_size(size: int) -> str:
    value = float(max(0, size))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" or value >= 10 else f"{value:.1f} {unit}"
        value /= 1024
    return "0 B"


class WindBridgeApp:
    def __init__(
        self,
        root: tk.Tk,
        settings: Settings | None = None,
        initial_paths: Iterable[str | Path] = (),
    ) -> None:
        self.root = root
        self.settings = settings or Settings.load()
        self.settings.save()
        self.state = BridgeState(self.settings.incoming_dir)
        self.local_ip = get_local_ip()
        self.server: LocalServer | None = None
        self.discovery: DiscoveryResponder | None = None
        self.tray_icon: pystray.Icon | None = None
        self.last_revision = -1
        self.last_clipboard_stamp = ""
        self.qr_photo = None

        self.root.title("WindBridge 风桥 · 局域网传输")
        self.root.geometry("1280x820")
        self.root.minsize(1060, 700)
        self.root.configure(background=THEME["sky"])
        icon_path = resource_path("assets/app_icon.png")
        if icon_path.is_file():
            self.app_icon = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self.app_icon)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_style()
        self._build_ui()
        self._refresh_pairing()
        self._start_server()
        self.state.add_outbound(initial_paths)
        if os.environ.get("WINDBRIDGE_DISABLE_TRAY") != "1":
            self.root.after(500, self._start_tray)
        self._poll_state()

    @property
    def access_url(self) -> str:
        return f"http://{self.local_ip}:{self.settings.port}/?token={self.state.token}"

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 9), foreground=THEME["text"], background=THEME["surface"])
        style.configure("App.TFrame", background=THEME["sky"])
        style.configure("Page.TFrame", background=THEME["pale"])
        style.configure("Card.TFrame", background=THEME["surface"])
        style.configure("Hero.TFrame", background="#E8F5F0")
        style.configure("TLabel", background=THEME["surface"], foreground=THEME["text"])
        style.configure("Page.TLabel", background=THEME["pale"], foreground=THEME["text"])
        style.configure("Hero.TLabel", background="#E8F5F0", foreground=THEME["deep"])
        style.configure("Title.TLabel", background=THEME["pale"], foreground=THEME["deep"], font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("Eyebrow.TLabel", background=THEME["pale"], foreground=THEME["gold"], font=("Consolas", 8, "bold"))
        style.configure("Hint.TLabel", foreground=THEME["muted"])
        style.configure("PageHint.TLabel", background=THEME["pale"], foreground=THEME["muted"])
        style.configure("HeroHint.TLabel", background="#E8F5F0", foreground=THEME["muted"])
        style.configure("Metric.TLabel", background=THEME["surface"], foreground=THEME["deep"], font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("MetricHint.TLabel", background=THEME["surface"], foreground=THEME["muted"], font=("Microsoft YaHei UI", 8))
        style.configure("TLabelFrame", background=THEME["surface"], bordercolor=THEME["line"], lightcolor=THEME["line"], darkcolor=THEME["line"], borderwidth=1, relief="solid")
        style.configure("TLabelFrame.Label", background=THEME["surface"], foreground=THEME["nav"], font=("Microsoft YaHei UI", 10, "bold"), padding=(4, 0))
        style.layout("Page.TNotebook.Tab", [])
        style.configure("Page.TNotebook", background=THEME["sky"], borderwidth=0, tabmargins=0)
        style.configure("TButton", background="#EAF4F1", foreground=THEME["deep"], bordercolor=THEME["line"], lightcolor=THEME["line"], darkcolor=THEME["line"], padding=(13, 7), relief="flat")
        style.map("TButton", background=[("active", "#DCECE8"), ("pressed", "#CCE2DD"), ("disabled", "#EFF2F0")])
        style.configure("Accent.TButton", background=THEME["wind"], foreground="#FFFFFF", bordercolor=THEME["wind"], font=("Microsoft YaHei UI", 10, "bold"), padding=(16, 8))
        style.map("Accent.TButton", background=[("active", THEME["wind_hover"]), ("pressed", THEME["nav"])])
        style.configure("Gold.TButton", background=THEME["gold_soft"], foreground=THEME["deep"], bordercolor=THEME["gold"], font=("Microsoft YaHei UI", 10, "bold"), padding=(16, 8))
        style.map("Gold.TButton", background=[("active", "#E2CF8C"), ("pressed", "#D4BB69")])
        style.configure("Danger.TButton", background="#FAEAE6", foreground=THEME["danger"], bordercolor="#ECC7BF")
        style.map("Danger.TButton", background=[("active", "#F2D7D1")])
        style.configure("TEntry", fieldbackground="#FCFEFC", foreground=THEME["text"], bordercolor=THEME["line"], lightcolor=THEME["line"], darkcolor=THEME["line"], insertcolor=THEME["wind"], padding=(8, 7))
        style.configure("Treeview", rowheight=31, background=THEME["surface"], fieldbackground=THEME["surface"], foreground=THEME["text"], bordercolor=THEME["line"], borderwidth=1)
        style.map("Treeview", background=[("selected", "#D4EAE6")], foreground=[("selected", THEME["deep"])])
        style.configure("Treeview.Heading", background="#E3F0EC", foreground=THEME["nav"], bordercolor=THEME["line"], font=("Microsoft YaHei UI", 9, "bold"), padding=(6, 7), relief="flat")
        style.configure("Status.TLabel", background=THEME["deep"], foreground="#DCEFED", padding=(12, 6))
        style.configure("Horizontal.TProgressbar", background=THEME["wind"], troughcolor="#D5E8E3", bordercolor="#D5E8E3", thickness=9)
        style.configure("TCheckbutton", background=THEME["surface"], foreground=THEME["text"], padding=3)

    def _build_ui(self) -> None:
        sticker_path = resource_path("assets/venti_sticker.png")
        self.venti_sticker = tk.PhotoImage(file=str(sticker_path)) if sticker_path.is_file() else None
        shell = tk.Frame(self.root, background=THEME["sky"])
        shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(shell, width=220, background=THEME["deep"], highlightthickness=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        content = ttk.Frame(shell, style="App.TFrame")
        content.pack(side="right", fill="both", expand=True)
        self.header = tk.Canvas(content, height=145, highlightthickness=0, borderwidth=0, background=THEME["nav"])
        self.header.pack(fill="x")
        self.header.bind("<Configure>", self._draw_header)

        self.status_text = tk.StringVar(value="正在启动本地风桥…")
        ttk.Label(content, textvariable=self.status_text, style="Status.TLabel", anchor="w").pack(side="bottom", fill="x")

        self.notebook = ttk.Notebook(content, style="Page.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(12, 12))
        self.home_tab = ttk.Frame(self.notebook, padding=(18, 14), style="Page.TFrame")
        self.files_tab = ttk.Frame(self.notebook, padding=(18, 14), style="Page.TFrame")
        self.clipboard_tab = ttk.Frame(self.notebook, padding=(18, 14), style="Page.TFrame")
        self.settings_tab = ttk.Frame(self.notebook, padding=(18, 14), style="Page.TFrame")
        for page, title in ((self.home_tab, "首页"), (self.files_tab, "文件桥"), (self.clipboard_tab, "文本桥"), (self.settings_tab, "设置")):
            self.notebook.add(page, text=title)

        self._build_home()
        self._build_files()
        self._build_clipboard()
        self._build_settings()
        self._build_sidebar()
        self.notebook.bind("<<NotebookTabChanged>>", self._sync_nav)
        self._show_page(0)

    def _draw_header(self, _event: tk.Event | None = None) -> None:
        canvas = self.header
        width = max(820, canvas.winfo_width())
        height = 145
        canvas.delete("all")
        start, end = (18, 72, 84), (51, 139, 151)
        for index in range(36):
            ratio = index / 35
            color = "#%02x%02x%02x" % tuple(int(a + (b - a) * ratio) for a, b in zip(start, end, strict=True))
            left = int(width * index / 36)
            canvas.create_rectangle(left, 0, int(width * (index + 1) / 36) + 1, height, fill=color, outline="")
        for y in (27, 58, 91):
            canvas.create_arc(width - 470, y - 115, width + 90, y + 116, start=178, extent=92, style="arc", outline="#7EB9BD", width=1)
        canvas.create_arc(width - 230, -80, width + 70, 207, start=120, extent=165, style="arc", outline=THEME["gold_soft"], width=2)
        canvas.create_line(0, height - 3, width, height - 3, fill=THEME["gold_soft"], width=2)
        canvas.create_text(30, 38, anchor="w", text="MONDSTADT TRANSFER NODE  //  LOCAL", fill="#CFE7E3", font=("Consolas", 9, "bold"))
        canvas.create_text(30, 75, anchor="w", text="WindBridge 风桥", fill="#FFFDF0", font=("Microsoft YaHei UI", 22, "bold"))
        canvas.create_text(32, 111, anchor="w", text="FILES  ·  CLIPBOARD  ·  LAN  ·  FREEDOM", fill="#D4EBE7", font=("Consolas", 10))
        if width >= 1080:
            canvas.create_text(width - 380, 57, text="让文件随风抵达", fill="#FFF5D2", font=("Microsoft YaHei UI", 16, "bold"))
            canvas.create_text(width - 380, 88, text="THE WIND KNOWS THE WAY", fill="#CFE7E3", font=("Consolas", 8))
        if self.venti_sticker:
            canvas.create_image(width - 16, height + 31, image=self.venti_sticker, anchor="se")
        else:
            canvas.create_line(width - 68, 35, width - 92, 111, fill="#F7E9B8", width=3, smooth=True)
            for dx, dy in ((0, 0), (-13, 7), (13, 8), (-20, 21), (20, 22), (-10, 31), (10, 32)):
                canvas.create_oval(width - 71 + dx, 26 + dy, width - 64 + dx, 33 + dy, fill="#FFFDF0", outline="")

    def _build_sidebar(self) -> None:
        brand = tk.Canvas(self.sidebar, width=220, height=140, background=THEME["deep"], highlightthickness=0)
        brand.pack(fill="x")
        brand.create_oval(22, 20, 66, 64, fill=THEME["nav"], outline=THEME["gold"], width=1)
        brand.create_arc(31, 31, 58, 54, start=15, extent=155, style="arc", outline="#FFF4D5", width=3)
        brand.create_line(35, 49, 54, 32, fill="#FFF4D5", width=2, smooth=True)
        brand.create_text(78, 31, anchor="w", text="WindBridge", fill="#FFFDF2", font=("Georgia", 17, "bold"))
        brand.create_text(79, 57, anchor="w", text="风桥", fill="#D4E9E6", font=("Microsoft YaHei UI", 10))
        brand.create_line(23, 89, 197, 89, fill="#376B73")
        brand.create_text(110, 112, text="自由如风，传递无界", fill="#A6C6C7", font=("Microsoft YaHei UI", 9))

        tk.Label(self.sidebar, text="风之路径", anchor="w", padx=24, background=THEME["deep"], foreground="#72969B", font=("Microsoft YaHei UI", 8, "bold")).pack(fill="x", pady=(4, 8))
        self.nav_buttons: list[tk.Button] = []
        for index, (icon, title) in enumerate((("⌂", "首页"), ("⇄", "文件桥"), ("✎", "文本桥"), ("⚙", "连接设置"))):
            button = tk.Button(
                self.sidebar,
                text=f" {icon}    {title}",
                anchor="w",
                padx=20,
                pady=11,
                borderwidth=0,
                relief="flat",
                background=THEME["deep"],
                foreground="#D7E9E7",
                activebackground=THEME["nav"],
                activeforeground="#FFFDF2",
                font=("Microsoft YaHei UI", 10),
                cursor="hand2",
                command=lambda page=index: self._show_page(page),
            )
            button.pack(fill="x", padx=13, pady=3)
            self.nav_buttons.append(button)
        spacer = tk.Frame(self.sidebar, background=THEME["deep"])
        spacer.pack(fill="both", expand=True)
        tk.Label(self.sidebar, text="LOCAL FIRST\nNO CLOUD RELAY", justify="left", anchor="w", padx=24, pady=22, background=THEME["deep"], foreground="#73979C", font=("Consolas", 8)).pack(fill="x", side="bottom")

    def _show_page(self, index: int) -> None:
        self.notebook.select(index)
        self._sync_nav()

    def _sync_nav(self, _event: tk.Event | None = None) -> None:
        selected = self.notebook.index(self.notebook.select())
        for index, button in enumerate(self.nav_buttons):
            active = index == selected
            button.configure(background=THEME["wind"] if active else THEME["deep"], foreground="#FFFFFF" if active else "#D7E9E7")

    @staticmethod
    def _section_intro(parent: ttk.Frame, eyebrow: str, title: str, subtitle: str) -> None:
        ttk.Label(parent, text=eyebrow, style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w", pady=(3, 2))
        ttk.Label(parent, text=subtitle, style="PageHint.TLabel").pack(anchor="w", pady=(0, 13))

    def _build_home(self) -> None:
        hero = ttk.Frame(self.home_tab, style="Hero.TFrame", padding=(23, 18))
        hero.pack(fill="x")
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, text="LOCAL WIND NODE", style="HeroHint.TLabel", font=("Consolas", 8, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(hero, text="让文件随风抵达", style="Hero.TLabel", font=("Microsoft YaHei UI", 20, "bold")).grid(row=1, column=0, sticky="w", pady=(4, 3))
        ttk.Label(hero, text="电脑与手机之间的本地桥梁，不登录，不经过云端。", style="HeroHint.TLabel").grid(row=2, column=0, sticky="w")
        actions = ttk.Frame(hero, style="Hero.TFrame")
        actions.grid(row=3, column=0, sticky="w", pady=(15, 0))
        ttk.Button(actions, text="添加共享文件", style="Gold.TButton", command=self._share_files).pack(side="left")
        ttk.Button(actions, text="打开移动端", style="Accent.TButton", command=self._open_web).pack(side="left", padx=9)
        self.node_state = tk.StringVar(value="正在启动")
        ttk.Label(hero, textvariable=self.node_state, style="HeroHint.TLabel", font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=1, rowspan=4, sticky="e", padx=(25, 0))

        metrics = ttk.Frame(self.home_tab, style="Page.TFrame")
        metrics.pack(fill="x", pady=14)
        for col in range(3):
            metrics.columnconfigure(col, weight=1)
        self.outbound_count = tk.StringVar(value="0")
        self.inbound_count = tk.StringVar(value="0")
        self.transfer_size = tk.StringVar(value="0 B")
        for col, (label, variable, note) in enumerate((("正在共享", self.outbound_count, "移动端可下载"), ("已经接收", self.inbound_count, "保存在接收目录"), ("桥接数据", self.transfer_size, "本次运行累计"))):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=(18, 12))
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0 if col == 2 else 6))
            ttk.Label(card, text=label, style="MetricHint.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(3, 0))
            ttk.Label(card, text=note, style="MetricHint.TLabel").pack(anchor="w")

        lower = ttk.Frame(self.home_tab, style="Page.TFrame")
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=2)
        lower.columnconfigure(1, weight=3)
        lower.rowconfigure(0, weight=1)
        pair = ttk.LabelFrame(lower, text="扫码连接", padding=13)
        pair.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.qr_label = ttk.Label(pair)
        self.qr_label.pack(pady=(2, 7))
        self.url_text = tk.StringVar()
        ttk.Label(pair, textvariable=self.url_text, style="Hint.TLabel", wraplength=310, justify="center").pack(fill="x")
        row = ttk.Frame(pair)
        row.pack(pady=(10, 0))
        ttk.Button(row, text="复制地址", command=self._copy_url).pack(side="left")
        ttk.Button(row, text="更换配对码", command=self._rotate_pairing).pack(side="left", padx=7)

        activity = ttk.LabelFrame(lower, text="风中来信", padding=12)
        activity.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(0, weight=1)
        self.activity_tree = ttk.Treeview(activity, columns=("time", "event"), show="headings", height=7)
        self.activity_tree.heading("time", text="时间")
        self.activity_tree.heading("event", text="最近活动")
        self.activity_tree.column("time", width=135, stretch=False)
        self.activity_tree.column("event", width=380, stretch=True)
        self.activity_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(activity, orient="vertical", command=self.activity_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.activity_tree.configure(yscrollcommand=scroll.set)

    def _build_files(self) -> None:
        self._section_intro(self.files_tab, "FILE CURRENT", "文件桥", "从电脑分享文件，也接收手机、平板和另一台电脑发送的文件。")
        shared = ttk.LabelFrame(self.files_tab, text="电脑 → 其他设备", padding=12)
        shared.pack(fill="both", expand=True, pady=(0, 8))
        self.desktop_drop = tk.Label(
            shared,
            text="⇧  把文件拖到这里，或点击选择",
            background="#E9F5F1",
            foreground=THEME["nav"],
            activebackground="#D9ECE7",
            activeforeground=THEME["deep"],
            highlightthickness=1,
            highlightbackground="#A9CEC7",
            padx=12,
            pady=10,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.desktop_drop.pack(fill="x", pady=(0, 8))
        self.desktop_drop.bind("<Button-1>", lambda _event: self._share_files())
        if DND_FILES and getattr(self.root, "TkdndVersion", None) and hasattr(self.desktop_drop, "drop_target_register"):
            self.desktop_drop.drop_target_register(DND_FILES)
            self.desktop_drop.dnd_bind("<<Drop>>", self._on_desktop_drop)
        actions = ttk.Frame(shared)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="添加文件", style="Accent.TButton", command=self._share_files).pack(side="left")
        ttk.Button(actions, text="取消共享", style="Danger.TButton", command=self._remove_shared).pack(side="left", padx=8)
        ttk.Button(actions, text="复制连接地址", command=self._copy_url).pack(side="left")
        self.outbound_tree = self._file_tree(shared)

        received = ttk.LabelFrame(self.files_tab, text="其他设备 → 电脑", padding=12)
        received.pack(fill="both", expand=True, pady=(8, 0))
        actions = ttk.Frame(received)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="打开选中文件", style="Accent.TButton", command=self._open_received).pack(side="left")
        ttk.Button(actions, text="打开接收目录", command=self._open_incoming_folder).pack(side="left", padx=8)
        self.inbound_tree = self._file_tree(received)

    @staticmethod
    def _file_tree(parent: ttk.Frame) -> ttk.Treeview:
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        columns = ("name", "size", "time")
        tree = ttk.Treeview(holder, columns=columns, show="headings", height=5, selectmode="browse")
        for key, title, width in (("name", "文件名", 500), ("size", "大小", 100), ("time", "时间", 160)):
            tree.heading(key, text=title)
            tree.column(key, width=width, stretch=key == "name")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _build_clipboard(self) -> None:
        self._section_intro(self.clipboard_tab, "CLIPBOARD BREEZE", "文本桥", "快速传递链接、地址、验证码之外的普通文本或一小段笔记。")
        card = ttk.LabelFrame(self.clipboard_tab, text="当前桥接文本", padding=14)
        card.pack(fill="both", expand=True)
        self.clipboard_meta = tk.StringVar(value="尚未同步文本")
        ttk.Label(card, textvariable=self.clipboard_meta, style="Hint.TLabel").pack(anchor="w", pady=(0, 8))
        self.clipboard_editor = tk.Text(card, wrap="word", height=20, font=("Microsoft YaHei UI", 10), background="#FCFEFC", foreground=THEME["text"], insertbackground=THEME["wind"], selectbackground="#B9DCD7", relief="solid", borderwidth=1, padx=13, pady=11)
        self.clipboard_editor.pack(fill="both", expand=True)
        actions = ttk.Frame(card)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="发送到风桥", style="Accent.TButton", command=self._publish_text).pack(side="left")
        ttk.Button(actions, text="粘贴系统剪贴板", command=self._paste_system_clipboard).pack(side="left", padx=8)
        ttk.Button(actions, text="复制当前文本", command=self._copy_current_text).pack(side="left")
        ttk.Button(actions, text="清空", command=lambda: self.clipboard_editor.delete("1.0", "end")).pack(side="right")

    def _build_settings(self) -> None:
        self._section_intro(self.settings_tab, "CONNECTION SETTINGS", "连接设置", "调整监听端口、文件接收位置和文本同步方式。")
        card = ttk.LabelFrame(self.settings_tab, text="本地节点", padding=16)
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)
        self.port_var = tk.IntVar(value=self.settings.port)
        self.incoming_var = tk.StringVar(value=self.settings.incoming_dir)
        self.auto_copy_var = tk.BooleanVar(value=self.settings.auto_copy_received_text)
        self.minimize_tray_var = tk.BooleanVar(value=self.settings.minimize_to_tray)
        ttk.Label(card, text="局域网地址").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=7)
        ttk.Entry(card, textvariable=self.url_text, state="readonly").grid(row=0, column=1, sticky="ew", pady=7)
        ttk.Label(card, text="监听端口").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=7)
        ttk.Spinbox(card, from_=1024, to=65535, textvariable=self.port_var, width=12).grid(row=1, column=1, sticky="w", pady=7)
        ttk.Label(card, text="文件接收目录").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=7)
        directory_row = ttk.Frame(card)
        directory_row.grid(row=2, column=1, sticky="ew", pady=7)
        directory_row.columnconfigure(0, weight=1)
        ttk.Entry(directory_row, textvariable=self.incoming_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(directory_row, text="选择", command=self._choose_incoming).grid(row=0, column=1, padx=(8, 0))
        ttk.Checkbutton(card, text="收到网页文本时自动复制到电脑剪贴板", variable=self.auto_copy_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=7)
        ttk.Checkbutton(card, text="关闭窗口时最小化到系统托盘", variable=self.minimize_tray_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=7)
        actions = ttk.Frame(card)
        actions.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(actions, text="保存并重启节点", style="Accent.TButton", command=self._save_settings).pack(side="left")
        ttk.Button(actions, text="打开接收目录", command=self._open_incoming_folder).pack(side="left", padx=8)
        ttk.Button(actions, text="安装右键发送入口", command=self._install_send_to).pack(side="left")
        ttk.Button(actions, text="移除右键入口", command=self._remove_send_to).pack(side="left", padx=8)

        note = ttk.LabelFrame(self.settings_tab, text="连接说明", padding=16)
        note.pack(fill="x", pady=(14, 0))
        ttk.Label(note, text="• 两台设备必须处于同一 Wi-Fi 或局域网，风桥会通过 UDP 广播声明本机节点。\n• Windows 防火墙首次询问时，仅允许专用网络。\n• 更换配对码会立即让旧二维码和旧链接失效。\n• 安装右键入口后，可在资源管理器的“发送到”菜单选择 WindBridge。\n• 传输内容不会经过第三方云端，但请只在可信网络中使用。", justify="left", style="Hint.TLabel").pack(anchor="w")

    def _refresh_pairing(self) -> None:
        self.url_text.set(self.access_url)
        qr = qrcode.QRCode(version=None, box_size=7, border=2)
        qr.add_data(self.access_url)
        qr.make(fit=True)
        image = qr.make_image(fill_color=THEME["deep"], back_color=THEME["surface"]).convert("RGB")
        image.thumbnail((205, 205))
        self.qr_photo = ImageTk.PhotoImage(image)
        self.qr_label.configure(image=self.qr_photo)

    def _start_server(self) -> None:
        if self.server:
            self.server.stop()
        if self.discovery:
            self.discovery.stop()
            self.discovery = None
        app = create_app(self.state, resource_path("web"), self.settings.control_token)
        candidate = LocalServer(app, "0.0.0.0", self.settings.port)
        try:
            candidate.start()
        except OSError as exc:
            self.server = None
            self.node_state.set("节点启动失败")
            self.status_text.set(f"端口 {self.settings.port} 无法使用：{exc}")
            return
        self.server = candidate
        try:
            discovery = DiscoveryResponder(socket.gethostname(), self.local_ip, self.settings.port)
            discovery.start()
            self.discovery = discovery
            discovery_note = " · 可被发现"
        except OSError:
            discovery_note = ""
        self.node_state.set(f"在线 · {self.local_ip}:{self.settings.port}{discovery_note}")
        self.status_text.set("风桥已就绪 · 请让另一台设备扫描二维码或打开连接地址")

    def _share_files(self) -> None:
        paths = filedialog.askopenfilenames(title="选择要随风发送的文件")
        if not paths:
            return
        added = self.state.add_outbound(paths)
        self.status_text.set(f"已添加 {len(added)} 个共享文件")
        self._refresh_state(force=True)
        self._show_page(1)

    def _on_desktop_drop(self, event: object) -> None:
        raw = getattr(event, "data", "")
        paths = self.root.tk.splitlist(raw) if raw else ()
        added = self.state.add_outbound(paths)
        self.status_text.set(f"拖放共享完成：{len(added)} 个文件")
        self._refresh_state(force=True)

    def _remove_shared(self) -> None:
        selected = self.outbound_tree.selection()
        if selected and self.state.remove_outbound(selected[0]):
            self.status_text.set("已取消共享；原文件未被删除")
            self._refresh_state(force=True)

    def _open_received(self) -> None:
        selected = self.inbound_tree.selection()
        item = self.state.get_inbound(selected[0]) if selected else None
        if item:
            self._open_path(Path(item.path))

    def _open_incoming_folder(self) -> None:
        self.state.incoming_dir.mkdir(parents=True, exist_ok=True)
        self._open_path(self.state.incoming_dir)

    @staticmethod
    def _open_path(path: Path) -> None:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _copy_url(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.access_url)
        self.status_text.set("连接地址已复制")

    def _open_web(self) -> None:
        webbrowser.open(self.access_url)

    def _rotate_pairing(self) -> None:
        self.state.rotate_token()
        self._refresh_pairing()
        self.status_text.set("配对码已更新，旧链接已失效")

    def _publish_text(self) -> None:
        text = self.clipboard_editor.get("1.0", "end-1c")
        self.state.publish_clipboard(text, "desktop")
        self.last_clipboard_stamp = self.state.clipboard_updated_at
        self.clipboard_meta.set(f"电脑更新于 {self.state.clipboard_updated_at.replace('T', ' ')}")
        self.status_text.set("文本已发送到风桥")

    def _paste_system_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self.status_text.set("系统剪贴板中没有可读取的文本")
            return
        self.clipboard_editor.delete("1.0", "end")
        self.clipboard_editor.insert("1.0", text)

    def _copy_current_text(self) -> None:
        text = self.clipboard_editor.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_text.set("当前文本已复制")

    def _choose_incoming(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.incoming_var.get() or str(Path.home()))
        if selected:
            self.incoming_var.set(selected)

    def _save_settings(self) -> None:
        try:
            port = int(self.port_var.get())
        except (TypeError, ValueError, tk.TclError):
            messagebox.showerror("端口无效", "端口必须是 1024 到 65535 之间的整数。")
            return
        if not 1024 <= port <= 65535:
            messagebox.showerror("端口无效", "端口必须是 1024 到 65535 之间的整数。")
            return
        incoming = Path(self.incoming_var.get()).expanduser()
        try:
            incoming.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("目录不可用", str(exc))
            return
        self.settings.port = port
        self.settings.incoming_dir = str(incoming.resolve())
        self.settings.auto_copy_received_text = self.auto_copy_var.get()
        self.settings.minimize_to_tray = self.minimize_tray_var.get()
        self.settings.save()
        self.state.set_incoming_dir(self.settings.incoming_dir)
        self._refresh_pairing()
        self._start_server()

    @staticmethod
    def _send_to_path() -> Path:
        appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return appdata / "Microsoft" / "Windows" / "SendTo" / "发送到 WindBridge.cmd"

    @staticmethod
    def _launcher_line() -> str:
        if getattr(sys, "frozen", False):
            return f'start "" "{sys.executable}" --share %*'
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        launcher = pythonw if pythonw.is_file() else Path(sys.executable)
        main_file = Path(__file__).resolve().parents[1] / "main.py"
        return f'start "" "{launcher}" "{main_file}" --share %*'

    def _install_send_to(self) -> None:
        if sys.platform != "win32":
            messagebox.showinfo("当前系统不支持", "资源管理器发送入口仅适用于 Windows。")
            return
        target = self._send_to_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"@echo off\n{self._launcher_line()}\n", encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror("安装失败", str(exc))
            return
        self.status_text.set("已安装资源管理器“发送到 WindBridge”入口")

    def _remove_send_to(self) -> None:
        target = self._send_to_path()
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            messagebox.showerror("移除失败", str(exc))
            return
        self.status_text.set("已移除资源管理器发送入口")

    def _start_tray(self) -> None:
        if self.tray_icon:
            return
        icon_path = resource_path("assets/app_icon.png")
        if not icon_path.is_file():
            return
        image = Image.open(icon_path).convert("RGBA")
        menu = pystray.Menu(
            pystray.MenuItem("打开 WindBridge", lambda _icon, _item: self.root.after(0, self._restore_window), default=True),
            pystray.MenuItem("打开移动端页面", lambda _icon, _item: self.root.after(0, self._open_web)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda _icon, _item: self.root.after(0, self._shutdown)),
        )
        self.tray_icon = pystray.Icon("WindBridge", image, "WindBridge 风桥", menu)
        try:
            self.tray_icon.run_detached()
        except Exception:
            self.tray_icon = None

    def _restore_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _poll_state(self) -> None:
        self._refresh_state()
        self.root.after(700, self._poll_state)

    def _refresh_state(self, force: bool = False) -> None:
        snapshot = self.state.snapshot()
        revision = int(snapshot["revision"])
        if force or revision != self.last_revision:
            self.last_revision = revision
            self.outbound_count.set(str(snapshot["outbound_count"]))
            self.inbound_count.set(str(snapshot["inbound_count"]))
            self.transfer_size.set(human_size(int(snapshot["outbound_bytes"]) + int(snapshot["inbound_bytes"])))
            self._populate_file_tree(self.outbound_tree, self.state.list_outbound())
            self._populate_file_tree(self.inbound_tree, self.state.list_inbound())
            for item in self.activity_tree.get_children():
                self.activity_tree.delete(item)
            for event in snapshot["events"]:
                self.activity_tree.insert("", "end", values=(event["time"].replace("T", " "), event["message"]))

        clip = self.state.clipboard_snapshot()
        stamp = str(clip["updated_at"])
        if stamp and stamp != self.last_clipboard_stamp and clip["source"] == "web":
            self.last_clipboard_stamp = stamp
            text = str(clip["text"])
            self.clipboard_editor.delete("1.0", "end")
            self.clipboard_editor.insert("1.0", text)
            self.clipboard_meta.set(f"网页更新于 {stamp.replace('T', ' ')}")
            self.status_text.set("收到一段网页文本")
            if self.settings.auto_copy_received_text:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)

    @staticmethod
    def _populate_file_tree(tree: ttk.Treeview, files: list[dict[str, object]]) -> None:
        selected = set(tree.selection())
        for item in tree.get_children():
            tree.delete(item)
        for file in files:
            tree.insert("", "end", iid=str(file["id"]), values=(file["name"], human_size(int(file["size"])), str(file["created_at"]).replace("T", " ")))
        for item in selected:
            if tree.exists(item):
                tree.selection_add(item)

    def _on_close(self) -> None:
        if self.settings.minimize_to_tray and self.tray_icon:
            self.root.withdraw()
            return
        self._shutdown()

    def _shutdown(self) -> None:
        if self.tray_icon:
            tray, self.tray_icon = self.tray_icon, None
            tray.stop()
        if self.discovery:
            self.discovery.stop()
            self.discovery = None
        if self.server:
            self.server.stop()
            self.server = None
        self.root.destroy()
