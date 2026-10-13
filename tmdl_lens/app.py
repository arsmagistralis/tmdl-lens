"""
app.py - Main UI for tmdl-lens.

CustomTkinter dark-theme desktop application.
Native Windows titlebar with "tmdl-lens" as the window title.
"""

import os
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk

# Ensure tmdl_lens/ is importable when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tmdl_lens.config import load_result, save as save_config, validate_config
from tmdl_lens.pipeline import Pipeline, PipelineConfig, PipelineResult
from tmdl_lens.version import __version__ as APP_VERSION

try:
    from tmdl_lens.watcher import TmdlWatcher, WATCHER_AVAILABLE
except ImportError:
    WATCHER_AVAILABLE = False
    TmdlWatcher = None


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

COLORS = {
    "bg":          "#1a1d26",
    "surface":     "#22263a",
    "border":      "#313650",
    "border_hi":   "#3d4260",
    "accent":      "#5b9cf6",
    "accent_dim":  "#1f3d72",
    "green":       "#34c78a",
    "amber":       "#f5a623",
    "red":         "#e05c5c",
    "text_1":      "#f0f3fa",
    "text_2":      "#9aa3b8",
    "text_3":      "#6b738f",
}

LOG_COLORS = {
    "ok":   "#34c78a",
    "warn": "#f5a623",
    "err":  "#e05c5c",
    "info": "#5b9cf6",
    "msg":  "#9aa3b8",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        self._config_load = load_result()
        self.config_data = self._config_load.config
        self._last_run: str = "never"
        self._run_thread: threading.Thread | None = None
        self._watcher: TmdlWatcher | None = None
        self._watcher_config: dict = {}
        self._watcher_enabled: bool = (
            WATCHER_AVAILABLE
            and self.config_data.get("features", {}).get("watcher", True)
        )
        self._loading: bool = False

        self._build_window()
        self._build_layout()
        self._loading = True
        self._load_ui_from_config()
        self._loading = False
        self._auto_save_config()

        saved_folder = self.config_data.get("reports_folder", "").strip()
        if saved_folder and os.path.isdir(saved_folder):
            self._scan_reports(saved_folder)
        self.after(0, self._set_watcher_idle)

    # ── Window ────────────────────────────────────────────────────────────────

    def _build_window(self):
        self.title("tmdl-lens")
        self.geometry("1200x820")
        self.minsize(960, 660)
        self.configure(fg_color=COLORS["bg"])
        self.after(0, self._center_window)

        # Intercept close to allow future tray minimise
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)  # status bar
        self.grid_columnconfigure(0, weight=0)  # sidebar
        self.grid_columnconfigure(1, weight=1)  # main

        self._build_sidebar()
        self._build_main()
        self._build_statusbar()

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(
            self, width=48, corner_radius=0,
            fg_color="#141720",
            border_width=1, border_color=COLORS["border"],
        )
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(10, weight=1)

        # Nav buttons - top
        self._nav_btns = {}
        nav_items = [
            ("generator", "⊞", "Generator"),
            ("schedule",  "◷", "Schedule"),
            ("history",   "↺", "Run History"),
        ]
        for i, (key, icon, tip) in enumerate(nav_items):
            btn = ctk.CTkButton(
                sidebar, text=icon, width=32, height=32,
                corner_radius=7, font=ctk.CTkFont(size=14),
                fg_color=COLORS["accent_dim"] if i == 0 else "transparent",
                text_color=COLORS["accent"] if i == 0 else COLORS["text_3"],
                hover_color=COLORS["border"],
                command=lambda k=key: self._nav_click(k),
            )
            btn.grid(row=i, column=0, padx=8, pady=(8 if i == 0 else 3, 3))
            self._nav_btns[key] = btn

        # Settings - bottom
        settings_btn = ctk.CTkButton(
            sidebar, text="⚙", width=32, height=32,
            corner_radius=7, font=ctk.CTkFont(size=14),
            fg_color="transparent",
            text_color=COLORS["text_3"],
            hover_color=COLORS["border"],
            command=lambda: self._nav_click("settings"),
        )
        settings_btn.grid(row=11, column=0, padx=8, pady=(0, 12), sticky="s")
        self._nav_btns["settings"] = settings_btn

    def _nav_click(self, key: str):
        for k, btn in self._nav_btns.items():
            if k == key:
                btn.configure(
                    fg_color=COLORS["accent_dim"],
                    text_color=COLORS["accent"],
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["text_3"],
                )

    # ── Main area ─────────────────────────────────────────────────────────────

    def _build_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color=COLORS["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)  # content
        main.grid_rowconfigure(1, weight=0)  # action bar
        main.grid_columnconfigure(0, weight=1)

        self._build_content(main)
        self._build_actionbar(main)

    # ── Content ───────────────────────────────────────────────────────────────

    def _build_content(self, parent):
        content = ctk.CTkFrame(parent, corner_radius=0, fg_color=COLORS["bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)  # log panel

        self._build_tab_configure(content)
        self._build_log_panel(content)

    # ── Configure tab ─────────────────────────────────────────────────────────

    def _build_tab_configure(self, parent):
        frame = ctk.CTkScrollableFrame(
            parent, corner_radius=0,
            fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["border_hi"],
            scrollbar_button_hover_color=COLORS["border_hi"],
        )
        frame.grid(row=0, column=0, sticky="nsew")

        pad = {"padx": 22, "pady": (0, 0)}

        # ── Paths ─────────────────────────────────────────────────────────────
        self._section_header(frame, "Paths", required=True)

        # Reports folder
        self._field_label(frame, "Reports folder")
        self._reports_var = tk.StringVar()
        self._path_row(frame, self._reports_var, "Browse...", self._browse_reports)

        ctk.CTkFrame(frame, height=8, fg_color="transparent").pack(fill="x")

        # Output folder
        self._field_label(frame, "Output folder", sub="leave blank to save README next to each .pbip file")
        self._output_var = tk.StringVar()
        self._path_row(frame, self._output_var, "Browse...", self._browse_output,
                       placeholder="default: next to each .pbip file")

        self._divider(frame)

        # ── Options ───────────────────────────────────────────────────────────
        self._section_header(frame, "Options", required=False)

        # Output format selector
        format_row = ctk.CTkFrame(
            frame,
            fg_color=COLORS["surface"],
            border_width=1, border_color=COLORS["border"],
            corner_radius=6,
        )
        format_row.pack(fill="x", padx=22)
        info = ctk.CTkFrame(format_row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        ctk.CTkLabel(
            info, text="Output format",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_1"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            info, text="HTML opens in any browser - MD produces README.md for GitHub",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_3"], anchor="w",
        ).pack(anchor="w")
        self._format_var = tk.StringVar(value="HTML")
        ctk.CTkOptionMenu(
            format_row,
            values=["HTML", "MD", "TXT"],
            variable=self._format_var,
            width=80, height=28,
            fg_color=COLORS["bg"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_hi"],
            text_color=COLORS["text_1"],
            font=ctk.CTkFont(size=12),
        ).pack(side="right", padx=14)

        ctk.CTkFrame(frame, height=6, fg_color="transparent").pack(fill="x")

        self._overwrite_var = tk.BooleanVar(value=False)
        self._toggle_row(
            frame,
            "Overwrite existing files",
            "Re-generate even if output file already exists",
            self._overwrite_var,
        )
        ctk.CTkFrame(frame, height=6, fg_color="transparent").pack(fill="x")

        self._dax_var = tk.BooleanVar(value=True)
        self._toggle_row(
            frame,
            "Include DAX expressions",
            "Append full DAX for each measure in the output",
            self._dax_var,
        )
        ctk.CTkFrame(frame, height=6, fg_color="transparent").pack(fill="x")

        self._skip_var = tk.BooleanVar(value=False)
        self._toggle_row(
            frame,
            "Skip reports with no TMDL changes",
            "Compare file hash - skip if unchanged since last run",
            self._skip_var,
        )

        self._divider(frame)

        # ── File Watcher ──────────────────────────────────────────────────────
        self._watcher_badge = self._section_header(frame, "File Watcher", badge="idle")

        self._watch_var = tk.BooleanVar(value=True)
        self._watch_var.trace_add("write", self._on_watch_toggle)
        self._toggle_row(
            frame,
            "Watch for TMDL changes",
            "Auto-generate docs on file save",
            self._watch_var,
        )

        # Debounce sub-row
        debounce_frame = ctk.CTkFrame(
            frame,
            fg_color=COLORS["surface"],
            border_width=1, border_color=COLORS["border"],
            corner_radius=6,
        )
        debounce_frame.pack(fill="x", padx=22, pady=(6, 0))

        ctk.CTkLabel(
            debounce_frame, text="debounce",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_1"],
        ).pack(side="left", padx=(12, 8), pady=8)

        self._debounce_var = tk.StringVar(value="10 sec")
        debounce_menu = ctk.CTkOptionMenu(
            debounce_frame,
            values=["5 sec", "10 sec", "30 sec"],
            variable=self._debounce_var,
            width=90, height=26,
            fg_color=COLORS["bg"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_hi"],
            text_color=COLORS["text_1"],
            font=ctk.CTkFont(size=13),
        )
        debounce_menu.pack(side="left", pady=8)

        self._watch_count_label = ctk.CTkLabel(
            debounce_frame, text="watching 0 reports",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_1"],
        )
        self._watch_count_label.pack(side="right", padx=12, pady=8)

        self._divider(frame)

        self._section_header(frame, "Documentation metadata (optional)")

        self._field_label(frame, "Owner")
        self._owner_var = tk.StringVar()
        self._text_entry_row(frame, self._owner_var, "e.g. John Smith")

        ctk.CTkFrame(frame, height=8, fg_color="transparent").pack(fill="x")

        self._field_label(frame, "Team")
        self._team_var = tk.StringVar()
        self._text_entry_row(frame, self._team_var, "e.g. BI Team")

        ctk.CTkFrame(frame, height=8, fg_color="transparent").pack(fill="x")

        self._field_label(frame, "Refresh schedule")
        self._refresh_var = tk.StringVar()
        self._text_entry_row(frame, self._refresh_var, "e.g. Daily at 06:00 UTC")

        ctk.CTkLabel(
            frame,
            text="Optional - leave blank to omit from the generated documentation.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_2"],
            justify="left",
        ).pack(anchor="w", padx=22, pady=(4, 20))

        ctk.CTkFrame(frame, height=20, fg_color="transparent").pack(fill="x")

    # ── Log panel ─────────────────────────────────────────────────────────────

    def _build_log_panel(self, parent):
        panel = ctk.CTkFrame(
            parent, width=340, corner_radius=0,
            fg_color=COLORS["surface"],
            border_width=1, border_color=COLORS["border"],
        )
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_propagate(False)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(
            panel, height=36, corner_radius=0,
            fg_color=COLORS["surface"],
            border_width=0,
        )
        header.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(
            header, text="Output log",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_2"],
        ).pack(side="left", padx=14)

        self._log_status_dot = ctk.CTkLabel(
            header, text="●", font=ctk.CTkFont(size=10),
            text_color=COLORS["green"],
        )
        self._log_status_dot.pack(side="right", padx=14)

        sep = ctk.CTkFrame(panel, height=1, corner_radius=0, fg_color=COLORS["border"])
        sep.grid(row=0, column=0, sticky="ews")

        # Log body - native tk.Text for colour tags
        log_body_frame = ctk.CTkFrame(panel, corner_radius=0, fg_color=COLORS["surface"])
        log_body_frame.grid(row=1, column=0, sticky="nsew")
        log_body_frame.grid_rowconfigure(0, weight=1)
        log_body_frame.grid_columnconfigure(0, weight=1)

        self._log_text = tk.Text(
            log_body_frame,
            bg=COLORS["surface"], fg=COLORS["text_2"],
            font=("Courier New", 11),
            relief="flat", bd=0,
            state="disabled",
            wrap="word",
            cursor="arrow",
            selectbackground=COLORS["border"],
        )
        self._log_text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=8)

        scrollbar = ctk.CTkScrollbar(log_body_frame, command=self._log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=8)
        self._log_text.configure(yscrollcommand=scrollbar.set)

        # Configure colour tags
        for tag, color in LOG_COLORS.items():
            self._log_text.tag_configure(tag, foreground=color)
        self._log_text.tag_configure("time", foreground="#8b94aa")

        self._log_initial_messages()

    def _log_initial_messages(self):
        self.log("tmdl-lens ready", "info")
        self.log("load a reports folder and press Run Now", "msg")
        if not WATCHER_AVAILABLE:
            self.log("watchdog not installed - file watcher disabled", "warn")
            self.log('install with: pip install watchdog', "warn")
        elif not self.config_data.get("features", {}).get("watcher", True):
            self.log('file watcher disabled in config.json (features.watcher)', "warn")
        self.log(f"config: {self._config_load.path}", "info")
        if self._config_load.migrated_from:
            self.log(f"config copied from {self._config_load.migrated_from}", "info")
        if self._config_load.failed:
            self.log(f"could not load config: {self._config_load.error}", "err")
            self.log("config.json will not be overwritten until you press Save", "err")
        for warning in self._config_load.warnings:
            self.log(warning, "warn")
        for warning in validate_config(self.config_data):
            self.log(warning, "warn")

    # ── Action bar ────────────────────────────────────────────────────────────

    def _build_actionbar(self, parent):
        bar = ctk.CTkFrame(
            parent, height=52, corner_radius=0,
            fg_color=COLORS["bg"],
            border_width=1, border_color=COLORS["border"],
        )
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_columnconfigure(10, weight=1)

        # Run Now
        self._run_btn = ctk.CTkButton(
            bar, text="▶  Run Now",
            width=120, height=34,
            corner_radius=6,
            fg_color=COLORS["accent"],
            hover_color="#6ba3f9",
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_run_now,
        )
        self._run_btn.grid(row=0, column=0, padx=(14, 6), pady=10)

        # Save Config
        ctk.CTkButton(
            bar, text="Save config",
            width=110, height=34,
            corner_radius=6,
            fg_color=COLORS["surface"],
            hover_color=COLORS["border_hi"],
            text_color=COLORS["text_1"],
            border_width=1, border_color=COLORS["border"],
            font=ctk.CTkFont(size=13),
            command=self._on_save_config,
        ).grid(row=0, column=1, padx=4, pady=10)

        # Clear Log
        ctk.CTkButton(
            bar, text="Clear log",
            width=100, height=34,
            corner_radius=6,
            fg_color="transparent",
            hover_color=COLORS["border"],
            text_color=COLORS["text_2"],
            font=ctk.CTkFont(size=13),
            command=self._on_clear_log,
        ).grid(row=0, column=2, padx=4, pady=10)

        # Last run label
        self._last_run_label = ctk.CTkLabel(
            bar, text="last run · never",
            font=ctk.CTkFont(family="Courier New", size=11),
            text_color=COLORS["text_2"],
        )
        self._last_run_label.grid(row=0, column=11, padx=14, pady=10, sticky="e")

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        bar = ctk.CTkFrame(
            self, height=24, corner_radius=0,
            fg_color="#141720",
            border_width=1, border_color=COLORS["border"],
        )
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(10, weight=1)

        # Watcher status
        ctk.CTkLabel(
            bar, text="●",
            font=ctk.CTkFont(size=8),
            text_color=COLORS["green"],
        ).grid(row=0, column=0, padx=(14, 2), pady=0)

        self._watcher_label = ctk.CTkLabel(
            bar, text="watcher idle",
            font=ctk.CTkFont(family="Courier New", size=11),
            text_color=COLORS["text_2"],
        )
        self._watcher_label.grid(row=0, column=1, padx=(0, 12), pady=0)

        # Report count
        self._report_count_label = ctk.CTkLabel(
            bar, text="0 reports",
            font=ctk.CTkFont(family="Courier New", size=11),
            text_color=COLORS["text_2"],
        )
        self._report_count_label.grid(row=0, column=11, padx=(0, 14), pady=0, sticky="e")

        # Author
        ctk.CTkLabel(
            bar, text="github.com/nox-magistralis",
            font=ctk.CTkFont(family="Courier New", size=11),
            text_color=COLORS["text_3"],
        ).grid(row=0, column=12, padx=(0, 14), pady=0, sticky="e")

        ctk.CTkLabel(
            bar, text=f"v{APP_VERSION}",
            font=ctk.CTkFont(family="Courier New", size=11),
            text_color=COLORS["text_3"],
        ).grid(row=0, column=13, padx=(0, 14), pady=0, sticky="e")

    # ── UI component helpers ──────────────────────────────────────────────────

    def _section_header(self, parent, title: str, required: bool = False,
                        badge: str = ""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(18, 6))

        ctk.CTkLabel(
            row, text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text_1"],
        ).pack(side="left")

        badge_label = None

        if required:
            ctk.CTkLabel(
                row, text="required",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["accent"],
                fg_color=COLORS["accent_dim"],
                corner_radius=3,
                padx=6, pady=2,
            ).pack(side="left", padx=8)

        if badge:
            badge_label = ctk.CTkLabel(
                row, text=badge,
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_3"],
                fg_color=COLORS["surface"],
                corner_radius=3,
                padx=6, pady=2,
            )
            badge_label.pack(side="left", padx=8)

        ctk.CTkFrame(row, height=1, fg_color=COLORS["border"]).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )
        return badge_label

    def _field_label(self, parent, text: str, sub: str = ""):
        label_row = ctk.CTkFrame(parent, fg_color="transparent")
        label_row.pack(fill="x", padx=22, pady=(0, 4))
        ctk.CTkLabel(
            label_row, text=text,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_1"],
        ).pack(side="left")
        if sub:
            ctk.CTkLabel(
                label_row, text=f"  ({sub})",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_2"],
            ).pack(side="left")

    def _path_row(self, parent, var: tk.StringVar, btn_text: str,
                  cmd, placeholder: str = ""):
        row = ctk.CTkFrame(
            parent,
            fg_color=COLORS["surface"],
            border_width=1, border_color=COLORS["border"],
            corner_radius=6,
        )
        row.pack(fill="x", padx=22)
        row.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(
            row, textvariable=var,
            fg_color="transparent",
            border_width=0,
            text_color=COLORS["text_1"],
            placeholder_text=placeholder,
            placeholder_text_color=COLORS["text_3"],
            font=ctk.CTkFont(size=13),
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=4)

        ctk.CTkButton(
            row, text=btn_text,
            width=82, height=28,
            corner_radius=3,
            fg_color=COLORS["border"],
            hover_color=COLORS["border_hi"],
            text_color=COLORS["text_1"],
            font=ctk.CTkFont(size=13),
            command=cmd,
        ).grid(row=0, column=1, padx=(0, 6), pady=4)

    def _text_entry_row(self, parent, var: tk.StringVar, placeholder: str = ""):
        row = ctk.CTkFrame(
            parent,
            fg_color=COLORS["surface"],
            border_width=1, border_color=COLORS["border"],
            corner_radius=6,
        )
        row.pack(fill="x", padx=22)
        ctk.CTkEntry(
            row, textvariable=var,
            fg_color="transparent",
            border_width=0,
            text_color=COLORS["text_1"],
            placeholder_text=placeholder,
            placeholder_text_color=COLORS["text_3"],
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", padx=10, pady=6)

    def _toggle_row(self, parent, title: str, subtitle: str,
                    var: tk.BooleanVar, disabled: bool = False):
        row = ctk.CTkFrame(
            parent,
            fg_color=COLORS["surface"],
            border_width=1, border_color=COLORS["border"],
            corner_radius=6,
        )
        row.pack(fill="x", padx=22)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        ctk.CTkLabel(
            info, text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_3"] if disabled else COLORS["text_1"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            info, text=subtitle,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_3"],
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkSwitch(
            row, text="", variable=var,
            width=36, height=20,
            switch_width=36, switch_height=18,
            button_color="white",
            button_hover_color="#dddddd",
            progress_color=COLORS["accent"],
            fg_color=COLORS["border_hi"],
            state="disabled" if disabled else "normal",
        ).pack(side="right", padx=14)

    def _divider(self, parent):
        ctk.CTkFrame(parent, height=1, fg_color=COLORS["border"]).pack(
            fill="x", padx=22, pady=(18, 0)
        )

    # ── Config load/save ──────────────────────────────────────────────────────

    def _load_ui_from_config(self):
        c = self.config_data
        self._reports_var.set(c.get("reports_folder", ""))
        self._output_var.set(c.get("output_folder", ""))
        self._overwrite_var.set(c.get("overwrite_readme", False))
        output_format = c.get("output_format", "html")
        self._format_var.set(output_format.upper() if output_format in ("html", "md", "txt") else "HTML")
        self._dax_var.set(c.get("include_dax", True))
        self._skip_var.set(c.get("skip_unchanged", True))
        self._watch_var.set(False)  # always off on startup - user enables manually
        self._debounce_var.set(f"{c.get('watch_debounce', 10)} sec")
        self._owner_var.set(c.get("owner", ""))
        self._team_var.set(c.get("team", ""))
        self._refresh_var.set(c.get("refresh_schedule", ""))

    def _collect_config(self) -> dict:
        debounce_raw = self._debounce_var.get().replace(" sec", "")
        try:
            debounce = int(debounce_raw)
        except ValueError:
            debounce = 10

        return {
            "reports_folder":   self._reports_var.get().strip(),
            "output_folder":    self._output_var.get().strip(),
            "overwrite_readme": self._overwrite_var.get(),
            "output_format":    self._format_var.get().lower(),
            "include_dax":      self._dax_var.get(),
            "skip_unchanged":   self._skip_var.get(),
            "watch_debounce":   debounce,
            "owner":            self._owner_var.get().strip(),
            "team":             self._team_var.get().strip(),
            "refresh_schedule": self._refresh_var.get().strip(),
            "file_hashes":      self.config_data.get("file_hashes", {}),
            "features":         self.config_data.get("features", {}),
        }

    # ── Browse handlers ───────────────────────────────────────────────────────

    def _browse_reports(self):
        folder = filedialog.askdirectory(title="Select reports folder")
        if folder:
            self._reports_var.set(folder)
            self._scan_reports(folder)
            if self._watch_var.get():
                self.after(200, lambda: self._start_watcher(folder))

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self._output_var.set(folder)

    def _scan_reports(self, folder: str):
        count = 0
        if os.path.isdir(folder):
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.endswith(".pbip"):
                        count += 1
        self._watch_count_label.configure(text=f"watching {count} reports")
        self._report_count_label.configure(
            text=f"{count} {'report' if count == 1 else 'reports'}"
        )

    # ── Action handlers ───────────────────────────────────────────────────────

    def _write_config(self, config: dict) -> bool:
        ok = save_config(config)
        if not ok:
            self.log(f"warning: settings could not be saved to {self._config_load.path}", "warn")
        return ok

    def _on_save_config(self):
        self.config_data = self._collect_config()
        if self._write_config(self.config_data):
            self._config_load.error = ""
            self.log("config saved", "ok")

    def _on_clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _on_run_now(self):
        config = self._collect_config()
        reports_folder = config.get("reports_folder", "").strip()

        if not reports_folder:
            self.log("no reports folder set", "err")
            return
        if not os.path.isdir(reports_folder):
            self.log(f"folder not found: {reports_folder}", "err")
            return

        # Disable button during run
        self._run_btn.configure(state="disabled", text="Running...")
        self._run_thread = threading.Thread(
            target=self._run_pipeline_async,
            args=(config,),
            daemon=True,
        )
        self._run_thread.start()

    # ── Watcher control ───────────────────────────────────────────────────────

    def _start_watcher(self, folder: str):
        if not self._watcher_enabled:
            self.log("watcher unavailable - check requirements.txt", "warn")
            return
        if not folder or not os.path.isdir(folder):
            self.log("watcher not started - no reports folder selected", "msg")
            return
        self._stop_watcher()
        self._watcher_config = self._collect_config()
        debounce_raw = self._debounce_var.get().replace(" sec", "")
        try:
            debounce = int(debounce_raw)
        except ValueError:
            debounce = 10
        self._watcher = TmdlWatcher(
            folder=folder,
            debounce_seconds=debounce,
            callback=self._on_watcher_trigger,
        )
        self._watcher.start()
        self.log(f"watcher started · {folder}", "info")
        self.after(0, lambda: self._watcher_label.configure(text="watcher active"))
        self.after(0, lambda: self._watcher_badge.configure(
            text="active", text_color=COLORS["green"]
        ))

    def _set_watcher_idle(self):
        self._watcher_label.configure(text="watcher idle")
        self._watcher_badge.configure(text="idle", text_color=COLORS["text_3"])

    def _stop_watcher(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
            self.log("watcher stopped", "msg")
        self.after(0, self._set_watcher_idle)

    def _on_watch_toggle(self, *_):
        """Called when the watch toggle changes value."""
        if self._loading:
            return
        folder = self._reports_var.get().strip()
        if self._watch_var.get():
            output_folder = self._output_var.get().strip() or folder
            has_readmes = any(
                fname == "README.md" or fname.endswith(".html")
                for _, _, files in os.walk(output_folder)
                for fname in files
            )
            if not has_readmes:
                self.log("no README files found - run the generator first", "warn")
                self._loading = True
                self._watch_var.set(False)
                self._loading = False
                return
            self._start_watcher(folder)
        else:
            self._stop_watcher()

    def _on_watcher_trigger(self, pbip_path: str):
        """Called from watchdog thread when a debounced change fires."""
        pbip_name = os.path.splitext(os.path.basename(pbip_path))[0]
        self.log(f"change detected - {pbip_name}", "warn")
        config = self._watcher_config

        pipeline_config = PipelineConfig(
            reports_folder=config["reports_folder"],
            output_folder=config.get("output_folder", ""),
            include_dax=config.get("include_dax", True),
            output_format=config.get("output_format", "html"),
            overwrite=True,
            skip_unchanged=config.get("skip_unchanged", False),
            owner=config.get("owner", ""),
            team=config.get("team", ""),
            refresh_schedule=config.get("refresh_schedule", ""),
        )

        pipeline = Pipeline(
            config=pipeline_config,
            saved_hashes=config.get("file_hashes", {}),
            logger=lambda msg, level: self.log(msg, level),
        )

        result = pipeline.run_single(pbip_path)
        if result.content_hash:
            self.after(0, lambda h=result.content_hash, k=result.hash_key: self._persist_hashes({k: h}))
        if result.success:
            now = datetime.now().strftime("%H:%M:%S")
            self.after(0, lambda: self._last_run_label.configure(
                text=f"last run - {now}"
            ))

    def _run_pipeline_async(self, config: dict):
        """Run the full pipeline in a background thread."""
        pipeline_config = PipelineConfig(
            reports_folder=config["reports_folder"],
            output_folder=config.get("output_folder", ""),
            include_dax=config.get("include_dax", True),
            output_format=config.get("output_format", "html"),
            overwrite=config.get("overwrite_readme", False),
            skip_unchanged=config.get("skip_unchanged", False),
            owner=config.get("owner", ""),
            team=config.get("team", ""),
            refresh_schedule=config.get("refresh_schedule", ""),
        )

        pipeline = Pipeline(
            config=pipeline_config,
            saved_hashes=config.get("file_hashes", {}),
            logger=lambda msg, level: self.log(msg, level),
        )

        try:
            result = pipeline.run()
        except Exception as e:
            self.log(f"pipeline error: {e}", "err")
            self.after(0, lambda: self._run_btn.configure(
                state="normal", text="▶  Run Now"
            ))
            return
        self._on_pipeline_done(result)

    def _on_pipeline_done(self, result: PipelineResult):
        """Update UI after pipeline run completes."""
        now = datetime.now().strftime("%H:%M:%S")
        self._last_run = now
        self.after(0, lambda: self._run_btn.configure(
            state="normal", text="▶  Run Now"
        ))
        self.after(0, lambda: self._last_run_label.configure(
            text=f"last run - {now}"
        ))
        self.after(0, lambda: self._persist_hashes(result.hashes))

    def _persist_hashes(self, new_hashes: dict):
        """Merge freshly computed hashes into config.json (main thread only)."""
        if not new_hashes:
            return
        self.config_data.setdefault("file_hashes", {}).update(new_hashes)
        if self._config_load.failed:
            return
        self._write_config(self._collect_config())

    # -- Log -------------------------------------------------------------------

    def log(self, message: str, level: str = "msg"):
        def _append():
            self._log_text.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_text.insert("end", ts, "time")
            self._log_text.insert("end", "  ")
            self._log_text.insert("end", message + "\n", level)
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
        self.after(0, _append)

    # ── Close ─────────────────────────────────────────────────────────────────

    def _auto_save_config(self):
        """Write config.json on first launch only - don't overwrite an existing file."""
        from tmdl_lens.config import config_path
        if self._config_load.failed:
            return
        if not os.path.exists(config_path()):
            self.config_data = self._collect_config()
            self._write_config(self.config_data)

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _on_close(self):
        """Auto-save config on close so settings persist without requiring manual Save."""
        self.config_data = self._collect_config()
        if not self._config_load.failed:
            self._write_config(self.config_data)
        self._stop_watcher()
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
