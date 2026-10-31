import json
import os
import re
import subprocess
import tempfile
import threading
import queue
import logging
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any, Optional
import sys
import ctypes

logger = logging.getLogger("universal_audio_studio.ui")

try:
    import customtkinter as ctk
except Exception:
    # Provide a clear actionable error when running without the required UI package.
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Missing Dependency",
            "The required package 'customtkinter' is not installed in this environment.\n\n"
            "Install it using:\n\n"
            "    pip install customtkinter\n\n"
            "Then re-run the application."
        )
    except Exception:
        # If tkinter messagebox also fails for some reason, fallback to console.
        print(
            "Missing dependency: customtkinter. Install it with 'pip install customtkinter' and rerun."
        )
    sys.exit(1)

import downloader
import download_queue

if TYPE_CHECKING:
    # Provide typings to the language server without requiring the package at runtime.
    import vlc  # type: ignore


# Heavy imports deferred until actually needed
sd = None
_vlc = None

def _lazy_import_sounddevice():
    global sd
    if sd is None:
        try:
            import sounddevice as _sd
            sd = _sd
        except ImportError:
            pass
    return sd

_np = None

def _lazy_import_numpy():
    global _np
    if _np is None:
        try:
            import numpy as _numpy
            _np = _numpy
        except Exception:
            pass
    return _np

def _lazy_import_vlc() -> Any:
    global _vlc
    if _vlc is None:
        try:
            import vlc as __vlc  # type: ignore[reportMissingImports]
            _vlc = __vlc
        except Exception:
            pass
    return _vlc


# Helper for faster PySceneDetect execution in a separate process to avoid GIL/GUI freezes
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")



# ---------------------------------------------------------------
# Colour / icon / typography primitives
# ---------------------------------------------------------------
# Moved to ui_theme.py. Imported here rather than renamed at the call sites so
# every existing reference (ui.UITheme, from ui import COLOR_THEMES, the tests
# that scrape these names) keeps working exactly as before.
from ui_theme import (  # noqa: F401  (re-exported)
    COLOR_THEMES,
    CUSTOM_CONTRAST_PAIRS,
    CUSTOM_DERIVED_ROLES,
    CUSTOM_LIFT_TARGET,
    CUSTOM_THEME_HOVERS,
    CUSTOM_THEME_NAME,
    CUSTOM_THEME_ROLES,
    LEGACY_HEX_ROLES,
    UITheme,
    _contrast,
    _HEX_RE,
    _icon_shapes,
    _ICON_GRID,
    _ICON_SS,
    _lift,
    _mix,
    _normalize_hex,
    _on_color,
    _paint_icon,
    _rel_luminance,
    _render_icon_image,
    _ring_color,
    _sb_row_state,
    _split_headline,
    _TRACEBACK_MARKERS,
    _UI_FONT_FAMILY,
    _ui_font,
    contrast_failures,
    custom_palette,
)

# The queue's themed row container also moved out; imported (not aliased) so
# ui._QueueRowList is this exact class even though the instantiation now
# lives in the queue page module - nothing can quietly end up with two copies.
from ui_widgets import (  # noqa: E402  (after the ctk import)
    _QueueRowList,
    UiSplitsMixin,
    hide_scrollbar_until_hover,
)

from pages.history import HistoryPageMixin  # noqa: E402
from pages.queue import QueuePageMixin  # noqa: E402
from pages.updates import UpdatesPageMixin  # noqa: E402
from pages.downloader import DownloaderPageMixin  # noqa: E402

class UniversalAudioStudio(ctk.CTk, UiSplitsMixin, QueuePageMixin,
                          HistoryPageMixin, UpdatesPageMixin,
                          DownloaderPageMixin):
    # -----------------
    # Persistent UI Preferences
    # -----------------
    _PREF_FILENAME = "ui_prefs.json"

    def _get_pref_path(self) -> str:
        """Store prefs in the per-user data folder when packaged, beside ui.py
        when running from source.

        The Program Files install directory is not writable by standard users,
        so storing next to the EXE would silently drop every preference.
        Deliberately delegates to ``downloader._get_user_data_dir()`` so prefs
        land in the same folder as history and the caches on every platform
        (``%APPDATA%`` on Windows, ``~/Library/Application Support`` on macOS).
        """
        if getattr(sys, "frozen", False):
            base_dir = downloader._get_user_data_dir()
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_dir, self._PREF_FILENAME)

    def _default_prefs(self) -> dict:
        return {
            "theme_mode": "Dark",
            "accent_theme": "blue",
            "overlay_enabled": False,
            "compact_enabled": False,
            "opacity_enabled": False,
            "opacity_alpha": 1.0,
            "font_scale": 1.0,
            "padding_scale": 1.0,
            "disable_maximize": True,
            "nav_animation_enabled": True,
            "nav_animation_speed": 12,
            "sidebar_collapsed": False,
            # Off by default: a rail that throws itself open every time the
            # pointer crosses it steals attention from whatever you are doing.
            "sidebar_peek_on_hover": False,
            "color_theme": "TuneLab Dark",
            # User-built palette. Roles only: the hovers are derived from them
            # (see custom_palette), so saving them here would just be a second
            # source of truth to fall out of step.
            "custom_theme_roles": {},
            "custom_theme_mode": "dark",
            "soundcloud_direct_first": True,
            "save_folder": "",
            "audio_format": "mp3_vbr",
            "window_geometry": "",
            "window_maximized": False,
            # Performance settings. These must be declared here, not just
            # written: _load_prefs keeps only keys already in this table, so a
            # written-but-undeclared key is dropped on every launch - and the
            # next save persists the truncated table, so the value is destroyed
            # rather than merely ignored. That is why "concurrent fragment
            # downloads" kept reverting to 8 no matter what was applied.
            # The defaults are downloader.DEFAULT_PERF_CONFIG's, kept in step by
            # the test that compares the two tables.
            "use_aria2": True,
            "aria2_connections": 16,
            "concurrent_fragment_downloads": 8,
            "max_video_resolution": "Best (up to 4K)",
            "cookies_file": "",
            # The AEP converter's Browse dialog opens here. Without it the
            # dialog restarts in the working directory every time, and
            # project files almost always live in one folder.
            "aep_last_dir": "",
            # Version the user pressed "Skip this version" on ("" = none).
            # Declared because _load_prefs keeps only keys in this table: a
            # written-but-undeclared key is dropped on the next launch, which
            # would turn a permanent skip back into tomorrow's nag.
            "skipped_version": "",
            # When the last app-update check ran, for the Update
            # Center's "Last checked" line. Declared like
            # skipped_version: _load_prefs drops undeclared keys.
            "last_update_check": "",
            # Startup engine (yt-dlp) auto-install - the Update Center
            # engine card's checkbox writes it, the startup probe reads
            # it (packaged builds only). Declared for the same reason.
            "engine_auto_update": True,
            # History tab view choice ("list" or "gallery") - the history
            # page writes it when the user toggles view mode. Declared so
            # _load_prefs keeps it across launches.
            "history_view": "list",
        }

    def _load_prefs(self) -> dict:
        path = self._get_pref_path()
        defaults = self._default_prefs()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    defaults.update({k: v for k, v in data.items() if k in defaults})
        except Exception:
            return defaults
        return defaults

    def _save_prefs(self) -> None:
        # Resolve the path outside the try: the except handler logs with it,
        # so it must be bound even if the very first operation fails.
        path = self._pref_path
        try:
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._prefs, f, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            # Never crash the UI over a pref write, but do leave a trace: a
            # silently unwritable prefs path would drop every setting.
            logger.warning("Could not save preferences to %s: %s", path, e)

    def _set_pref(self, key: str, value) -> None:
        if key not in self._prefs:
            self._prefs[key] = value
        else:
            self._prefs[key] = value
        self._save_prefs()

    def _remember_window_geometry(self) -> None:
        """Persist the current window size/position for the next launch."""
        try:
            st = str(self.state())
            if st == "zoomed":
                # Maximized: keep the last normal-size geometry (this one is
                # the screen size) but remember to re-maximize on restore.
                self._set_pref("window_maximized", True)
                return
            if st != "normal":
                # Minimized/iconic: neither value is trustworthy here; keep
                # whatever the last known-good save recorded.
                return
            self._set_pref("window_maximized", False)
            geo = str(self.geometry() or "")
            if re.match(r"^\d+x\d+[+-]\d+[+-]\d+$", geo):
                self._set_pref("window_geometry", geo)
        except Exception:
            pass

    def _restore_window_geometry(self) -> None:
        """Reapply the saved window geometry when it still fits a screen.

        Also re-maximizes the window when it was closed that way: the state()
        read happens while the window is still withdrawn (before deiconify),
        and Tk applies the zoomed state when the window maps.
        # Fixed-size window: ignore saved geometry.
        return

        """
        geo = str(self._prefs.get("window_geometry", "") or "").strip()
        m = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geo)
        if m:
            # Clamp to the window's own minimum so a stale tiny geometry can't
            # make the app unusable (minsize(800, 680) in __init__).
            w = max(int(m.group(1)), 800)
            h = max(int(m.group(2)), 680)
            x = int(m.group(3))
            y = int(m.group(4))
            try:
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
            except Exception:
                sw = sh = 0
            # Skip the restore when the saved frame is fully off every attached
            # screen (monitor unplugged since last run): Tk would place it there
            # anyway and the window would be unreachable.
            if sw and sh and not (x >= sw or y >= sh or x + w <= 0 or y + h <= 0):
                try:
                    self.geometry(f"{w}x{h}{m.group(3)}{m.group(4)}")
                except Exception:
                    pass
        if self._prefs.get("window_maximized"):
            try:
                self.state("zoomed")
            except Exception:
                pass  # Tk builds without a zoomed state (macOS) keep geometry.

    def _apply_prefs_to_ctk(self) -> None:
        try:
            ctk.set_appearance_mode(self._prefs.get("theme_mode", "Dark") or "Dark")
        except Exception:
            pass
        try:
            ctk.set_default_color_theme(self._prefs.get("accent_theme", "blue") or "blue")
        except Exception:
            pass
        try:
            font_scale = float(self._prefs.get("font_scale", 1.0) or 1.0)
            ctk.set_widget_scaling(font_scale)
        except Exception:
            pass

    def _apply_prefs_to_window(self) -> None:
        try:
            enabled = bool(self._prefs.get("opacity_enabled", False))
            alpha = float(self._prefs.get("opacity_alpha", 1.0) or 1.0)
            # Always route through the helper: on Windows an exact 1.0 alpha
            # opts OUT of DWM's composited/double-buffered presentation, which
            # lets unpainted intermediate states flash black on screen. A
            # 0.999 alpha is visually identical but keeps compositing active.
            if enabled:
                self._apply_window_alpha(alpha)
            else:
                self._apply_window_alpha(1.0)
        except Exception:
            pass

    def _apply_window_alpha(self, alpha: float) -> None:
        """Set window opacity, keeping DWM double-buffering alive on Windows."""
        try:
            a = float(alpha)
            win32 = str(self.tk.call('tk', 'windowingsystem')) == 'win32'
            if win32 and a >= 0.999:
                a = 0.999
            self.wm_attributes('-alpha', a)
        except Exception:
            pass
        # Apply window constraints such as disabling maximize if requested
        try:
            if bool(self._prefs.get("disable_maximize", False)):
                self._disable_maximize(True)
            else:
                self._disable_maximize(False)
        except Exception:
            pass

    def _apply_app_icon(self) -> None:
        """Give the window TuneLab's own icon.

        Tk's default is the feather, and that is what the taskbar, the title bar
        and Alt-Tab show until something replaces it. The asset sits next to the
        source in a checkout and in the bundle root when frozen (the PyInstaller
        spec bundles it), so one lookup covers both.

        The PNG goes through iconphoto, which every Tk honours; the .ico is set
        too on Windows, where the taskbar entry prefers it. Neither is worth a
        dialog at startup, so both are best effort.
        """
        here = os.path.dirname(os.path.abspath(__file__))
        # Frozen copies bundle the assets next to the executable (sys._MEIPASS);
        # a checkout has them under assets/. Both are one lookup away.
        roots = [getattr(sys, "_MEIPASS", None), here,
                 os.path.join(here, "assets")]

        def _find(name: str) -> str | None:
            for root in roots:
                if not root:
                    continue
                path = os.path.join(root, name)
                if os.path.isfile(path):
                    return path
            return None

        png = _find("tune_lab.png")
        ico = _find("tune_lab.ico")
        # Windows gets the .ico: it is the format the shell already understands,
        # and Tk's own photo->HICON conversion renders the PNG into the title
        # bar's slot stretched. Everywhere else (macOS, Linux) uses the PNG,
        # which is the only thing iconphoto reads.
        if sys.platform == "win32" and ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                logger.debug("iconbitmap failed", exc_info=True)
        elif png:
            try:
                photo = tk.PhotoImage(file=png)
                self.iconphoto(True, photo)
                self._app_icon = photo      # or the image is collected away
            except Exception:
                logger.debug("iconphoto failed", exc_info=True)

    def _disable_maximize(self, disable: bool = True) -> None:
        """On Windows, remove the maximize box and thick frame to prevent fullscreen/maximize.

        This is a best-effort change using Win32 APIs; non-Windows platforms are ignored.
        """
        if sys.platform != "win32":
            try:
                # Tkinter fullscreen attribute as fallback
                self.wm_attributes("-fullscreen", False if disable else False)
            except Exception:
                pass
            return

        try:
            GWL_STYLE = -16
            WS_MAXIMIZEBOX = 0x00010000
            WS_THICKFRAME = 0x00040000
            hwnd = int(self.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            if disable:
                style = style & ~WS_MAXIMIZEBOX & ~WS_THICKFRAME
            else:
                style = style | WS_MAXIMIZEBOX | WS_THICKFRAME
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)
            # Apply the change
            SWP_NOMOVE = 0x2
            SWP_NOSIZE = 0x1
            SWP_NOZORDER = 0x4
            SWP_FRAMECHANGED = 0x20
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
        except Exception:
            pass

    def __init__(self):
        # Thread-dispatch state must exist BEFORE super().__init__() so the
        # overridden after() (below) is safe even while CTk builds the widget.
        self._ui_closed = False
        self._ui_queue = queue.Queue()
        self._tk_main_thread = threading.current_thread()

        super().__init__()

        # Start the main-thread poller that drains worker-queued UI callbacks.
        # It runs once the main loop gets control and keeps re-arming itself.
        try:
            super().after(25, self._drain_ui_queue)
        except Exception:
            pass

        # Build the UI with the window hidden, then reveal it once at the end.
        # While it is mapped, Tk does geometry and redraw work for each of the
        # ~112 widgets as they are added, which is the largest single cost of
        # starting up - and it means the user watches a half-drawn window
        # assemble itself. customtkinter's withdraw() is written for exactly
        # this: it notes the window was never shown and re-shows it on the
        # first update()/mainloop(). We also reveal it explicitly at the end so
        # this never depends on that behaviour staying.
        self.withdraw()

        # -----------------
        # UI Preferences
        # -----------------
        self._pref_path = self._get_pref_path()
        self._prefs = self._load_prefs()

        # Cache derived scales (recomputed on apply)
        self._font_scale = float(self._prefs.get("font_scale", 1.0) or 1.0)
        self._padding_scale = float(self._prefs.get("padding_scale", 1.0) or 1.0)

        # Active color palette (Monkeytype-style theme engine)
        self._color_theme_name = self._prefs.get("color_theme", "TuneLab Dark")
        # The custom palette lives in COLOR_THEMES like any other so that every
        # lookup site (apply_color_theme, the role walk, the probes, the audit)
        # resolves it without a special case. It is rebuilt from the saved roles
        # at startup, which is also what re-derives its hovers.
        raw_roles = self._prefs.get("custom_theme_roles") or {}
        if not isinstance(raw_roles, dict):
            raw_roles = {}
        # Keep only the roles the picker offers. A prefs file written before a
        # role became derived (or hand-edited) can still name it, and carrying
        # that forward would let a dead key shadow the derivation: the value
        # would be ignored on read but written back out on the next save, so the
        # file would keep a colour the UI can no longer show or change.
        self._custom_roles = {
            role: value for role, value in raw_roles.items()
            if role in CUSTOM_THEME_ROLES
        }
        self._custom_mode = "light" if self._prefs.get(
            "custom_theme_mode") == "light" else "dark"
        COLOR_THEMES[CUSTOM_THEME_NAME] = custom_palette(
            self._custom_roles, self._custom_mode)
        if self._color_theme_name not in COLOR_THEMES:
            self._color_theme_name = "TuneLab Dark"
        self._palette = dict(COLOR_THEMES[self._color_theme_name])


        # Apply CTk global scaling/theme early (before building widgets)
        self._apply_prefs_to_ctk()

        # Make window opacity reflect saved prefs early
        self._apply_prefs_to_window()

        # Pylance: declare dynamic attributes up-front to avoid "attribute of None" / unknown attribute errors.

        self._vlc_instance = None
        self._vlc_player = None
        self._preview_proc = None
        self._preview_via_sd = False
        self._clipper_vlc_instance = None
        self._clipper_vlc_player = None
        self._clipper_auto_select = False
        self._clipper_fast_detect = False
        self._clipper_hover_preview_enabled = True
        self._clipper_hover_preview_muted = True
        self._clipper_thumb_generated = set()
        # Registry of themed widgets: (widget, {option: role}). Built alongside
        # the legacy _theme_roles attributes so a theme switch only touches
        # widgets that are actually themed instead of cget()ing ~10 options
        # on all ~840. Populated by _register_themed_widgets; late-built pages
        # route through _ensure_page_built.
        self._themed_registry: list = []
        # Toast stack, unfocused-completion badge and view caches (declared
        # here so Pylance sees them before first use).
        self._active_toasts: list[Any] = []
        self._toast_anim_id: Any = None
        self._unfocused_done: int = 0
        self._queue_refresh_pending: bool = False
        self._history_view_sig: Any = None
        # Last URL/mode started, so a failed download's dialog can offer
        # "Try again" without the user re-pasting the link.
        self._last_dl_url: str = ""
        self._last_dl_was_video: bool = False

        self.title("TuneLab")
        self._apply_app_icon()
        # Fixed-size window: no resizing, no maximize.
        self.minsize(800, 680)
        self.maxsize(800, 680)
        self.resizable(False, False)
        # Center on screen.
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - 800) // 2
        y = (sh - 680) // 2
        self.geometry(f"800x680+{x}+{y}")

        # Set window background to match theme (prevents white border)
        bg_color = self._palette.get('bg', '#2b2b2b')
        self.configure(bg=bg_color, highlightthickness=0, bd=0)
        try:
            self.attributes('-bg', bg_color)
        except Exception:
            pass

        # Handle window close event to stop the video bridge server
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self.studio_file_path = None

        # -----------------
        # Collapsible navigation rail (slides by clipping, never re-lays out)
        # -----------------
        self._sidebar_expanded = not bool(self._prefs.get("sidebar_collapsed", False))
        self._sb_shown = self._sidebar_expanded   # state the pixels currently show
        self._sb_anim_after_id = None
        # Hover / press / peek state. Everything visual is derived from these
        # three in _repaint_nav_rows, so no handler has to guess what a row
        # should look like.
        self._active_nav_name = None
        self._sb_hover = None
        self._sb_press = None
        self._sb_peek_after_id = None
        self._sb_peeking = False
        self._sb_peek_pref = False
        self._tooltips_enabled = False
        self._sb_popups = []      # the one reused tooltip popup, tracked so a
                                  # failed configure can never strand it on screen
        self._sb_tooltip_after_id = None
        self._sb_tip_owner = None  # the row the bubble is describing
        self._sb_badges = {}
        self._sb_footer_word = None
        self._sb_h = 0
        # A floating rounded rail rather than a flush panel: insetting it and
        # giving it the card radius plus a hairline edge is what makes the
        # window read as "curved" instead of four square slabs.
        self.sidebar = ctk.CTkFrame(
            self,
            width=UITheme.SB_W_EXPANDED if self._sidebar_expanded else UITheme.SB_W_COLLAPSED,
            corner_radius=UITheme.RADIUS_CARD,
            fg_color=self._palette.get('sidebar', UITheme.SIDEBAR_BG),
            border_width=UITheme.BORDER_W,
            border_color=self._palette.get('hover', UITheme.SIDEBAR_HOVER),
        )
        setattr(self.sidebar, "_theme_roles",
                {"fg_color": "sidebar", "border_color": "hover"})
        self.sidebar.pack(side="left", fill="y", padx=(12, 0), pady=12)
        self.sidebar.pack_propagate(False)
        self._sidebar_cur_w = UITheme.SB_W_EXPANDED if self._sidebar_expanded else UITheme.SB_W_COLLAPSED

        # -----------------
        # Main area (header + pages)
        # -----------------
        self.main_container = ctk.CTkFrame(self, fg_color=self._palette.get('bg', UITheme.SURFACE_BG))
        self.main_container.pack(side="left", fill="both", expand=True)

        self._header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent", height=42)
        # Lines the title up with the left edge of the content card below it.
        self._header_frame.pack(fill="x", padx=12, pady=(14, 0))
        self.title_lbl = ctk.CTkLabel(
            self._header_frame,
            text="",
            font=UITheme.SECTION_FONT,
            anchor="w",
        )
        self.title_lbl.pack(side="left")

        # Update banner. Created here, before the content area is packed, so it
        # sits between the header and the pages rather than being appended
        # after them - pack order decides the layout, so a banner built on
        # demand later would land under the content instead of above it.
        #
        # This replaces a modal "Update Available" yes/no dialog. A modal for
        # something the user did not ask about interrupts whatever they were
        # doing, and the answer only mattered because the question was a
        # button: the banner carries the same choice inline and waits.
        self._update_banner = ctk.CTkFrame(self.main_container, fg_color="transparent")

        # Central content area. This one deliberately stays a transparent
        # hole: a filled frame here would paint its own square canvas over the
        # rounded corners the pages draw, which is exactly what made the card
        # look square. The pages below carry the surface, radius and edge.
        self.content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_frame.pack(
            pady=12,
            padx=(12, 12),
            fill="both",
            expand=True,
        )

        self.tab_downloader = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tab_studio = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tab_customization = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tab_performance = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tab_queue = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tab_history = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tab_updates = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.tab_aep = ctk.CTkFrame(self.content_frame, fg_color="transparent")

        # The single page registry, built once every page frame exists (history
        # is created last, so this cannot sit with the others above). show_frame
        # used to rebuild this dict inline on every click, which left any other
        # tool wanting "all the pages" with no way to ask - the theme-follow probe
        # hard-coded its own tuple and so silently skipped whichever page came
        # next. Entries for lazily built pages are filled in by
        # _ensure_page_built on first visit.
        # typed dict[str, Any]: _ensure_page_built stores getattr(self, attr,
        # None), which is Optional until the page has actually been built.
        self._page_frames: dict[str, Any] = {
            'downloader': self.tab_downloader,
            'queue': self.tab_queue,
            'history': self.tab_history,
            'studio': self.tab_studio,
            'aep': self.tab_aep,
            'settings': self.tab_customization,
            'performance': self.tab_performance,
            'updates': self.tab_updates,
        }

        # Every page is a card: same surface, same corner radius and same
        # hairline edge as the dialogs. They are stacked in one hole and
        # raised on switch, so they all need the identical shape or a switch
        # would flash a differently edged panel.
        for _page in (self.tab_downloader, self.tab_studio, self.tab_aep,
                      self.tab_customization, self.tab_performance,
                      self.tab_queue, self.tab_history, self.tab_updates):
            _page.configure(
                fg_color=self._palette.get('surface', UITheme.SURFACE_BG),
                corner_radius=UITheme.RADIUS_CARD,
                border_width=UITheme.BORDER_W,
                border_color=self._palette.get('hover', UITheme.SIDEBAR_HOVER),
            )
            setattr(_page, "_theme_roles",
                    {"fg_color": "surface", "border_color": "hover"})

        # --- Download queue manager (lazy import to avoid circular deps) ---
        self._queue_manager = None
        self._queue_initialized = False

        # Motion + rail preferences are read before any view is built: the
        # "Sidebar & motion" card seeds its widgets from these values.
        try:
            self.nav_anim_enabled = bool(self._prefs.get('nav_animation_enabled', True))
            self.nav_anim_speed = int(self._prefs.get('nav_animation_speed', 12) or 12)
        except Exception:
            self.nav_anim_enabled = True
            self.nav_anim_speed = 12
        # Hover-peek only means something while the rail is collapsed, and it
        # stays off unless it was asked for.
        self._sb_peek_pref = bool(self._prefs.get('sidebar_peek_on_hover', False))
        self._tooltips_enabled = False

        # Downloader builds now; the rest build on first visit (see show_frame
        # and _ensure_page_built). Building everything up front cost ~1-1.5s of
        # the ~2.8s construct for pages the user may never open.
        self._built_pages: set = set()
        self.build_downloader_view()
        self._built_pages.add('downloader')

        # -----------------
        # Rail contents (brand, grouped nav rows, badge slots, footer toggle)
        # -----------------

        # Saved download settings (#1 save folder, #2 audio format).
        try:
            _saved_folder = str(self._prefs.get('save_folder', '') or '').strip()
            if _saved_folder:
                downloader.set_download_folder(_saved_folder)
            downloader.set_audio_format(str(self._prefs.get('audio_format', 'mp3_vbr')))
        except Exception:
            logger.debug("Applying download prefs failed", exc_info=True)

        # Apply saved performance prefs at startup so the "fast downloader"
        # settings survive restarts and are active before the user opens the
        # Performance tab.
        try:
            _perf_cfg = downloader.perf_cfg_from_prefs(self._prefs)
            downloader.set_performance_config(_perf_cfg)
            # Register the speed label callback for live download speed updates
            try:
                downloader.set_speed_ui_callback(self.update_speed_label)
            except Exception:
                logger.debug("Failed to register speed UI callback", exc_info=True)
        except Exception:
            logger.debug("Applying performance prefs failed", exc_info=True)

        # Proactive yt-dlp staleness check (#3): background, non-blocking.
        self._start_worker(self._ytdlp_update_check_worker)

        self._build_sidebar()
        self._nav_anim_after_id = None
        self.after(200, self._position_nav_indicator_initial)

        # Apply saved runtime preferences to controls + visuals
        # (controls are created in build_customization_view / apply_* methods)
        self._apply_prefs_to_window()

        # Auto-check for app updates (non-blocking, shows banner if available)
        self.after(3000, self._check_updates_on_startup)

        # Apply the saved color theme to every widget
        self.apply_color_theme(self._color_theme_name)
        # Index the shell + downloader page into the theme registry: every
        # later switch replays only these entries instead of probing the tree.
        try:
            self._register_themed_widgets(self)
        except Exception:
            logger.debug("Theme registry startup pass failed", exc_info=True)

        # Collapse/expand shortcut (like VS Code's side bar)
        self.bind('<Control-b>', lambda e: self.toggle_sidebar())

        # Paste a link from anywhere on the app into the URL box.
        self.bind('<Control-v>', self._paste_url_anywhere)
        self.bind('<Control-V>', self._paste_url_anywhere)

        # Quick nav: Ctrl+1..8 jump straight to a page.
        for _n, _page in enumerate(
            ("downloader", "queue", "history", "studio", "aep", "settings",
             "performance", "updates"),
            start=1,
        ):
            self.bind(f'<Control-{_n}>', lambda e, p=_page: self.show_frame(p))

        # Clear the unfocused-completion badge as soon as the user looks at
        # the app again.
        self.bind('<FocusIn>', lambda e: self._clear_completion_badge())

        # Start by showing downloader
        self.show_frame('downloader')

        # Everything exists now. Resolve the layout in one pass and show the
        # finished window, instead of letting Tk reveal it widget by widget.
        self._restore_window_geometry()
        self.update_idletasks()
        self.deiconify()
        # customtkinter 6.0 withdraws the window inside its own __init__
        # (titlebar repaint) and again on the first mainloop(), while its
        # recovery deiconify() is skipped whenever withdraw() ran before the
        # window was flagged as shown - which ours does above. Pumping one
        # update() here flags the window as shown (its update() override
        # sets _window_exists) and paints it once, so mainloop() takes no
        # further window-state actions. Without this the app starts with a
        # hidden window: mainloop runs, no error, nothing on screen.
        self.update()
        # Keyboard order and the focus ring, once the window is actually on
        # screen. The list is built from the live tree and keeps only what is
        # mapped, so running it while the window was still withdrawn left the
        # rail out of it entirely - every rail row is a CTkFrame, and none of
        # them had been laid out yet, so Tab could reach every button on the
        # page and still not change page.
        self._collect_focusables()
        # Caret in the URL box from the first frame: paste + Enter should
        # work without reaching for the mouse first.
        self.url_entry.focus_set()

    def _start_worker(self, target):
        threading.Thread(target=target, daemon=True).start()

    def after(self, ms, func=None, *args, **kwargs):  # type: ignore[reportIncompatibleMethodOverride]
        """Thread-safe ``after``: worker threads never touch Tk directly.

        Calls made on the Tk owner (main) thread pass through to the normal
        ``after`` so timer IDs and ``after_cancel`` keep working exactly as
        before. Calls from background threads are marshalled onto the main
        thread via ``_ui_queue``; the requested delay (if any) is honored
        with a real main-thread timer. If the app is shutting down the call
        is dropped instead of crashing Tkinter.
        """
        if func is None:
            return None
        if threading.current_thread() is self._tk_main_thread:
            return super().after(ms, func, *args, **kwargs)
        if self._ui_closed:
            return None
        try:
            self._ui_queue.put((int(ms or 0), func, args, kwargs))
        except Exception:
            pass
        return None

    def _drain_ui_queue(self):
        """Main-thread poller that runs UI callbacks queued by workers."""
        while True:
            try:
                ms, func, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                if ms:
                    super().after(
                        ms, lambda f=func, a=args, k=kwargs: f(*a, **k)
                    )
                else:
                    func(*args, **kwargs)
            except Exception:
                logger.debug("Deferred UI callback failed", exc_info=True)
        if not getattr(self, "_ui_closed", False):
            try:
                super().after(25, self._drain_ui_queue)
            except Exception:
                pass

    # --- TAB 1 DESIGN ---
    def build_downloader_view(self):
        # Page title lives in the header only (title_lbl) — no in-page H1.

        self.url_entry = ctk.CTkEntry(
            self.tab_downloader,
            width=300,
            height=UITheme.H_LG,
            corner_radius=UITheme.RADIUS_FIELD,
            border_width=UITheme.BORDER_W,
            border_color=(getattr(self, "_palette", {}) or {}).get(
                "hover", UITheme.SIDEBAR_HOVER),
            placeholder_text="Paste URL (YouTube, SoundCloud, etc.) or search..."
        )
        setattr(self.url_entry, "_theme_roles", {"border_color": "hover"})
        self.url_entry.pack(pady=(14,8), padx=UITheme.PAD_X, fill="x")

        # Inline clear button: overlays the field's right edge and only shows
        # while there is text to clear (Escape does the same from the keyboard).
        self.btn_clear_url = ctk.CTkButton(
            self.url_entry, text="", width=24, height=UITheme.H_XS,
            fg_color="transparent", corner_radius=12, cursor="hand2",
            command=self._on_clear_url_clicked,
        )
        self._style_button(self.btn_clear_url, "ghost", bordered=False,
                           icon="close")
        try:
            # The X should read as muted (sub), not full-strength text.
            sub = (getattr(self, "_palette", {}) or {}).get("sub", "#95a5a6")
            self.btn_clear_url.configure(text_color=sub)
            setattr(self.btn_clear_url, "_theme_roles",
                    {**self._BTN_ROLES["ghost"], "text_color": "sub"})
            # _style_button drew the icon in the ghost label colour; the mark
            # has to be redrawn in the muted one or it sits brighter than the
            # control it belongs to.
            setattr(self.btn_clear_url, "_icon_ink", "sub")
            image = self._button_icon("close", sub)
            if image is not None:
                self.btn_clear_url.configure(image=image)
        except Exception:
            pass
        self._url_clear_btn_visible = False

        # Segmented toggle inside a neutral container.
        action_row = ctk.CTkFrame(self.tab_downloader, fg_color="transparent")
        action_row.pack(pady=(0, UITheme.RHYTHM), padx=UITheme.PAD_X, fill="x")

        toggle_container = ctk.CTkFrame(
            action_row, fg_color=UITheme.TOGGLE_CONTAINER_BG,
            corner_radius=UITheme.RADIUS_LG, border_width=1,
            border_color=UITheme.TOGGLE_CONTAINER_BORDER)
        toggle_container.pack(side="left", padx=(0, 12))

        self._dl_format = tk.StringVar(value="audio")
        self.btn_fmt_audio = ctk.CTkButton(
            toggle_container, text="Audio", width=80, height=UITheme.H_SM,
            corner_radius=UITheme.RADIUS_MD, border_width=0,
            fg_color="transparent", text_color=UITheme.TOGGLE_INACTIVE_TEXT,
            hover_color=UITheme.TOGGLE_INACTIVE_HOVER_FILL,
            command=lambda: self._set_dl_format("audio"))
        self.btn_fmt_audio.pack(side="left", padx=2, pady=2)
        self.btn_fmt_video = ctk.CTkButton(
            toggle_container, text="Video", width=80, height=UITheme.H_SM,
            corner_radius=UITheme.RADIUS_MD, border_width=0,
            fg_color="transparent", text_color=UITheme.TOGGLE_INACTIVE_TEXT,
            hover_color=UITheme.TOGGLE_INACTIVE_HOVER_FILL,
            command=lambda: self._set_dl_format("video"))
        self.btn_fmt_video.pack(side="left", padx=2, pady=2)

        self.btn_download = ctk.CTkButton(
            action_row, text="Download", width=160, height=UITheme.H_LG,
            cursor="hand2", command=self._download_current,
            fg_color=UITheme.COLOR_PINK, hover_color=UITheme.COLOR_PINK_HOVER,
            text_color="#ffffff", corner_radius=UITheme.RADIUS_MD)
        self.btn_download.pack(side="left", padx=6)

        self.btn_add_to_queue = ctk.CTkButton(
            action_row, text="Add to Queue", width=140, height=UITheme.H_LG,
            cursor="hand2", command=self._add_current_to_queue)
        self.btn_add_to_queue.pack(side="left", padx=6)
        self._style_button(self.btn_add_to_queue, "secondary")

        # Row 2: previews in a single row (was a 2x2 grid); stops are danger.
        preview_frame = ctk.CTkFrame(self.tab_downloader, fg_color="transparent")
        preview_frame.pack(pady=(0, UITheme.RHYTHM))
        preview_frame.pack_forget()

        self.btn_preview_audio = ctk.CTkButton(
            preview_frame,
            text="Preview Audio",
            width=118, height=UITheme.H_SM,
            cursor="hand2",
            command=lambda: self._start_worker(self.preview_audio)
        )
        self.btn_preview_audio.grid(row=0, column=0, padx=4)
        self._style_button(self.btn_preview_audio, "secondary", icon="play")
        self.btn_stop_audio = ctk.CTkButton(
            preview_frame,
            text="Stop Audio",
            width=118, height=UITheme.H_SM,
            cursor="hand2",
            command=self.stop_preview_audio,
            state="disabled"
        )
        self.btn_stop_audio.grid(row=0, column=1, padx=4)
        self._style_button(self.btn_stop_audio, "danger", icon="stop")
        self.btn_stop_audio.grid_remove()

        self.btn_preview_video = ctk.CTkButton(
            preview_frame,
            text="Preview Video",
            width=118, height=UITheme.H_SM,
            cursor="hand2",
            command=lambda: self._start_worker(self.preview_video)
        )
        self.btn_preview_video.grid(row=0, column=2, padx=4)
        self._style_button(self.btn_preview_video, "secondary", icon="play")
        self.btn_stop_video = ctk.CTkButton(
            preview_frame,
            text="Stop Video",
            width=118, height=UITheme.H_SM,
            cursor="hand2",
            command=self.stop_preview_video,
            state="disabled"
        )
        self.btn_stop_video.grid(row=0, column=3, padx=4)
        self._style_button(self.btn_stop_video, "danger", icon="stop")
        self.btn_stop_video.grid_remove()

        self.url_entry.bind("<Leave>", lambda e: self._restore_hover_detail())
        # Enter = the obvious next action: one input downloads right away,
        # a multi-URL paste goes to the queue. (#1 on the UI wish list.)
        self.url_entry.bind("<Return>", self._on_url_enter)
        self.url_entry.bind("<KP_Enter>", self._on_url_enter)
        # Escape empties the box without leaving the field.
        self.url_entry.bind("<Escape>", self._clear_url_entry)
        self.url_entry.bind("<KeyRelease>", lambda e: self._sync_clear_btn())
        # A paste that skips the keyboard (context menu) fires no KeyRelease
        # on the entry; re-check right after the class binding inserted text.
        self.url_entry.bind(
            "<<Paste>>", lambda e: self.after(1, self._sync_clear_btn)
        )
        pal = getattr(self, "_palette", {}) or {}
        pill_bg = pal.get("sidebar_active", UITheme.SIDEBAR_ACTIVE)

        self._status_pill = ctk.CTkFrame(
            self.tab_downloader,
            corner_radius=15,
            fg_color=pill_bg,
        )
        self._status_pill.pack(pady=(0, UITheme.RHYTHM), padx=UITheme.PAD_X)
        setattr(self._status_pill, "_theme_roles", {"fg_color": "sidebar_active"})
        self._status_dot = ctk.CTkLabel(
            self._status_pill, text="●", font=UITheme.F(10),
            text_color=pal.get("sub", UITheme.COLOR_GRAY),
        )
        self._status_dot.pack(side="left", padx=(14, 6), pady=(5, 5))
        setattr(self._status_dot, "_theme_roles", {"text_color": "sub"})
        self.dl_status = ctk.CTkLabel(
            self._status_pill,
            # Not a bare "System Ready": on a fresh launch that states the
            # obvious and wastes the one line the user actually reads. It now
            # says what to do next, and every later update_dl_status() call
            # replaces it with the real outcome of the last action.
            text="Paste a link or search a song to begin",
            font=UITheme.F(12),
            text_color=_on_color(
                pill_bg, pal.get("text", "#ecf0f1"), pal.get("bg", "#1e1e24")),
        )
        self.dl_status.pack(side="left", padx=(0, 14), pady=(5, 5))
        setattr(self.dl_status, "_theme_roles", {"text_color": "text"})

        # Progress row: bar + cancel side by side. Cancel only enables while
        # a download is in flight, so it no longer deserves its own row.
        # The whole row starts hidden: an idle bar reading 0% and a disabled
        # Cancel sit in prime page space while telling the user nothing, and
        # they pushed the settings and queue controls down the page. It appears
        # the moment a download starts and goes away again when it ends.
        self._progress_row = progress_row = ctk.CTkFrame(
            self.tab_downloader, fg_color="transparent")
        progress_row.pack(fill="x", padx=UITheme.PAD_X, pady=(0, UITheme.RHYTHM))
        self.progress_bar = ctk.CTkProgressBar(progress_row, width=200)
        self.progress_bar.set(0)
        self.progress_bar.pack(side="left", fill="x", expand=True)
        self.btn_cancel_download = ctk.CTkButton(
            progress_row,
            text="Cancel Download",
            width=150, height=UITheme.H_SM,
            cursor="hand2",
            command=self._cancel_active_download,
            state="disabled",
        )
        self.btn_cancel_download.pack(side="left", padx=(10, 0))
        self._style_button(self.btn_cancel_download, "danger", icon="stop")
        progress_row.pack_forget()

        self.dl_detail = ctk.CTkLabel(self.tab_downloader, text="", font=UITheme.F(11), text_color="#95a5a6")
        self._pack_h_if_used(self.dl_detail, pady=(0, UITheme.RHYTHM // 2))

        # Speed + ETA label below progress bar
        self.dl_speed_lbl = ctk.CTkLabel(self.tab_downloader, text="", font=UITheme.F(11), text_color="#7f8c8d")
        self._pack_h_if_used(self.dl_speed_lbl, pady=(0, UITheme.RHYTHM))

        # Unified save-path bar: button + current path in one centered row.
        path_bar = ctk.CTkFrame(self.tab_downloader, fg_color="transparent")
        path_bar.pack(fill="x", padx=UITheme.PAD_X, pady=(0, UITheme.RHYTHM))
        path_row = ctk.CTkFrame(path_bar, fg_color="transparent")
        path_row.pack(anchor="center")
        self.save_folder_lbl = ctk.CTkButton(
            path_row,
            text="",
            width=320, height=UITheme.H_CTRL,
            fg_color="transparent",
            corner_radius=UITheme.RADIUS_MD,
            cursor="hand2",
            command=self._choose_save_folder,
        )
        self.save_folder_lbl.pack(side="left")
        self._style_button(self.save_folder_lbl, "ghost", bordered=False, icon="folder")
        self._update_save_folder_label()

        # Audio quality on its own row.
        quality_row = ctk.CTkFrame(self.tab_downloader, fg_color="transparent")
        quality_row.pack(pady=(0, UITheme.RHYTHM), padx=UITheme.PAD_X, fill="x")
        self.quality_lbl = ctk.CTkLabel(quality_row, text="Audio quality:", font=UITheme.F(12))
        self.quality_lbl.pack(side="left", padx=(0, 8))
        self.fmt_option = ctk.CTkOptionMenu(
            quality_row,
            width=190,
            values=[p["label"] for p in downloader.AUDIO_FORMATS.values()],
            command=self._on_dl_quality_change,
        )
        self.fmt_option.set(
            downloader.AUDIO_FORMATS.get(
                downloader.get_audio_format(), {"label": "MP3 (VBR High)"}
            )["label"]
        )
        self.fmt_option.pack(side="left")
        self._style_option_menu(self.fmt_option)
        # Warm neutral surface (not blue sidebar_active).
        try:
            pal = getattr(self, "_palette", {}) or {}
            self.fmt_option.configure(fg_color=pal.get("surface", UITheme.SURFACE_BG),
                                      border_color=pal.get("hover", UITheme.SIDEBAR_HOVER))
        except Exception:
            pass

        # Outdated yt-dlp notice (hidden until a check finds one).
        self._ytdlp_notice_lbl = ctk.CTkLabel(
            self.tab_downloader,
            text="",
            font=UITheme.F(11, "bold"),
            text_color="#f39c12",
            wraplength=340,
            justify="center",
        )
        self._pack_h_if_used(
            self._ytdlp_notice_lbl, padx=UITheme.PAD_X,
            pady=(UITheme.RHYTHM, UITheme.RHYTHM))

        # place downloader frame in content area
        self.tab_downloader.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Embedded preview panel (hidden until used; re-packs at the end
        # when a preview starts, so build order here does not matter).
        self.preview_panel = tk.Frame(self.tab_downloader, bg="black", width=280, height=170)
        self.preview_panel.pack(pady=(4, 8))
        self.preview_panel.pack_forget()

        # --- Queue + Tag Editor controls ---
        self._last_downloaded_file = None
        self._last_dl_was_video = False

    def _pack_h_if_used(self, label, **pack_kwargs):
        """Pack a text row only while it has something to say.

        The Downloader page stacks several single-line labels (detail, speed,
        save folder, yt-dlp notice, tag hint) that are empty on a fresh launch.
        A packed-but-empty CTkLabel still claims its full line height, so five
        invisible rows added up to the large dead gap down the middle of the
        page. Hiding them removes the gap and lets the remaining rows move up.

        Every later text change goes through ``configure(text=...)``, not a
        StringVar, so ``configure`` itself is what gets wrapped - watching for a
        textvariable (the obvious approach) misses every real update and the
        label stays hidden after its first message.
        """
        label._tunelab_pack_kwargs = pack_kwargs
        label.pack(**pack_kwargs)
        original_configure = label.configure

        def _configure_and_sync(*a, **kw):
            result = original_configure(*a, **kw)
            if "text" in kw:
                try:
                    self._sync_h_if_used(label)
                except Exception:
                    logger.debug("Optional text row sync failed", exc_info=True)
            return result

        label.configure = _configure_and_sync
        self._sync_h_if_used(label)
        return label

    def _sync_h_if_used(self, label) -> None:
        """Show/hide one optional text row to match whether it has text."""
        pack_kwargs = getattr(label, "_tunelab_pack_kwargs", None)
        if pack_kwargs is None:
            return
        try:
            if str(label.cget("text") or "").strip():
                if not label.winfo_manager():
                    label.pack(**pack_kwargs)
            elif label.winfo_manager():
                label.pack_forget()
        except Exception:
            logger.debug("Could not sync an optional text row", exc_info=True)

    def _show_stop_button(self, button, running: bool) -> None:
        """Show a preview's Stop button only while that preview is running.

        Paired with the state= toggle so the two can never drift: a Stop button
        that is visible but disabled is the thing this replaces, and one that is
        enabled but hidden would strand a preview with no way to end it.
        """
        try:
            button.configure(state="normal" if running else "disabled")
            if running:
                button.grid()
            else:
                button.grid_remove()
        except Exception:
            logger.debug("Could not update the preview Stop button",
                         exc_info=True)



    def _clear_url_entry(self, _event=None):
        """Escape (and the ✕ button) empty the URL box; keep focus in it."""
        try:
            self.url_entry.delete(0, "end")
        except Exception:
            pass
        self._sync_clear_btn()
        return "break"

    def _on_clear_url_clicked(self):
        self._clear_url_entry()
        self.url_entry.focus_set()

    def _paste_url_anywhere(self, _event=None):
        """Ctrl+V anywhere lands the clipboard in the URL box.

        Pasting a link is what this app is for, and the box is empty as often
        as not, so making the user click it first is pure friction.

        A field keeps the paste only if it is one the user can actually type
        into. A URL entry left holding focus from startup goes on holding it
        while the user browses another page, where Tk cannot route keys to it
        at all - so letting that unmapped widget claim every paste would
        silently drop the link. Mapped is what decides it.

        Multiple pasted lines go in whole - Enter already splits them and sends
        the batch to the queue.
        """
        try:
            focus = self.focus_get()
        except Exception:
            focus = None
        if isinstance(focus, (ctk.CTkEntry, ctk.CTkTextbox, tk.Entry, tk.Text)):
            try:
                if focus.winfo_ismapped():
                    return None
            except Exception:
                return None
        try:
            text = str(self.clipboard_get() or "").strip()
        except Exception:
            return "break"
        if not text:
            return "break"
        self.show_frame("downloader")
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)
        self.url_entry.focus_set()
        self._sync_clear_btn()
        return "break"

    def _on_url_enter(self, _event=None):
        """Pressing Enter in the URL box starts the obvious next action.

        A single URL (or a search term / Spotify URI) downloads right away;
        multiple pasted URLs go to the queue instead, matching what the
        buttons do. Returns "break" so Tk doesn't beep or move focus.
        """
        try:
            if str(self.btn_download.cget("state")) == "disabled":
                # A direct download is running (the buttons are disabled
                # while it is); mirror the buttons instead of racing it.
                return "break"
        except Exception:
            pass
        raw = self.url_entry.get().strip()
        if not raw:
            return "break"
        if len(self._split_input_urls(raw)) > 1:
            self._add_current_to_queue()
        else:
            self._start_worker(self.download_mp3)
        return "break"

    def _add_current_to_queue_video(self):
        """Add the current URL(s) to the queue as video (MP4)."""
        self.show_toast("Adding video to queue...", "info")
        raw = self.url_entry.get().strip()
        if not raw:
            self.show_toast("Please enter a URL first.", "warning")
            return
        urls = self._split_input_urls(raw)
        if not urls:
            self.show_toast("No valid URLs found.", "warning")
            return
        self._init_queue_manager()
        if not self._queue_manager:
            self.show_toast("Queue manager is not available.", "error")
            return
        try:
            self._enqueue_urls(urls, is_video=True)
        except Exception as e:
            self.show_toast(f"Queue error: {e}", "error")

    def _set_dl_format(self, fmt: str):
        self._dl_format.set(fmt)
        if fmt == "audio":
            self.btn_fmt_audio.configure(fg_color=UITheme.TOGGLE_ACTIVE_FILL, border_color=UITheme.TOGGLE_ACTIVE_BORDER, text_color=UITheme.TOGGLE_ACTIVE_TEXT, border_width=1, hover_color=UITheme.TOGGLE_ACTIVE_HOVER_FILL)
            self.btn_fmt_video.configure(fg_color="transparent", border_color=UITheme.TOGGLE_CONTAINER_BORDER, text_color=UITheme.TOGGLE_INACTIVE_TEXT, border_width=0, hover_color=UITheme.TOGGLE_INACTIVE_HOVER_FILL)
            # Brighten inactive text on hover
            self.btn_fmt_video.bind("<Enter>", lambda e: self.btn_fmt_video.configure(text_color=UITheme.TOGGLE_INACTIVE_HOVER_TEXT))
            self.btn_fmt_video.bind("<Leave>", lambda e: self.btn_fmt_video.configure(text_color=UITheme.TOGGLE_INACTIVE_TEXT))
            try:
                self.quality_lbl.configure(text="Audio quality:")
            except Exception:
                pass
            try:
                self.fmt_option.configure(values=[p["label"] for p in downloader.AUDIO_FORMATS.values()])
                self.fmt_option.set(downloader.AUDIO_FORMATS.get(
                    downloader.get_audio_format(), {"label": "MP3 (VBR High)"})["label"])
            except Exception:
                pass
        else:
            self.btn_fmt_audio.configure(fg_color="transparent", border_color=UITheme.TOGGLE_CONTAINER_BORDER, text_color=UITheme.TOGGLE_INACTIVE_TEXT, border_width=0, hover_color=UITheme.TOGGLE_INACTIVE_HOVER_FILL)
            self.btn_fmt_video.configure(fg_color=UITheme.TOGGLE_ACTIVE_FILL, border_color=UITheme.TOGGLE_ACTIVE_BORDER, text_color=UITheme.TOGGLE_ACTIVE_TEXT, border_width=1, hover_color=UITheme.TOGGLE_ACTIVE_HOVER_FILL)
            self.btn_fmt_audio.bind("<Enter>", lambda e: self.btn_fmt_audio.configure(text_color=UITheme.TOGGLE_INACTIVE_HOVER_TEXT))
            self.btn_fmt_audio.bind("<Leave>", lambda e: self.btn_fmt_audio.configure(text_color=UITheme.TOGGLE_INACTIVE_TEXT))
            try:
                self.quality_lbl.configure(text="Video quality:")
            except Exception:
                pass
            try:
                self.fmt_option.configure(values=downloader.VIDEO_RESOLUTION_OPTIONS)
                self.fmt_option.set(str(self._prefs.get("max_video_resolution", "Best (up to 4K)")))
            except Exception:
                pass
        self._audit_toggle_contrast()

    def _audit_toggle_contrast(self):
        pairs = [
            (UITheme.TOGGLE_ACTIVE_FILL, UITheme.TOGGLE_ACTIVE_TEXT),
            (UITheme.TOGGLE_ACTIVE_HOVER_FILL, UITheme.TOGGLE_ACTIVE_TEXT),
            (UITheme.TOGGLE_INACTIVE_HOVER_FILL, UITheme.TOGGLE_INACTIVE_HOVER_TEXT),
            (UITheme.TOGGLE_CONTAINER_BG, UITheme.TOGGLE_INACTIVE_TEXT),
        ]
        for fill, text in pairs:
            try:
                if _contrast(fill, text) < 4.5:
                    logger.warning("toggle contrast low: %s on %s = %.2f", text, fill, _contrast(fill, text))
            except Exception:
                pass



    def _download_current(self):
        if self._dl_format.get() == "video":
            self._start_worker(self.download_mp4)
        else:
            self._start_worker(self.download_mp3)


    def _add_current_to_queue(self):
        """Add the current URL(s) to the queue without starting download (audio)."""
        import time
        now = time.monotonic()
        if getattr(self, "_last_queue_add_at", 0) and now - self._last_queue_add_at < 0.5:
            return
        self._last_queue_add_at = now
        raw = self.url_entry.get().strip()
        if not raw:
            self.show_toast("Please enter a URL first.", "warning")
            return
        urls = self._split_input_urls(raw)
        if not urls:
            self.show_toast("No valid URLs found.", "warning")
            return
        self._init_queue_manager()
        if not self._queue_manager:
            self.show_toast("Queue manager is not available.", "error")
            return
        self._enqueue_urls(urls, is_video=(self._dl_format.get() == "video"))

    @staticmethod
    def _split_input_urls(raw: str) -> list[str]:
        """Split free-form input into a list of http(s) URLs."""
        urls: list[str] = []
        for chunk in re.split(r'[\n,;]+', raw):
            chunk = chunk.strip()
            if chunk.startswith(('http://', 'https://')):
                urls.append(chunk)
        return urls

    def _enqueue_urls(self, urls: list[str], is_video: bool = False):
        """Add URLs to the queue (supports bulk paste of multiple URLs)."""
        queue = self._queue_manager
        if queue is None:
            self._show_error_dialog("Queue Error", "Queue manager is not available.")
            return

        added = queue.add(urls, is_video=is_video)
        self._refresh_queue_tab()
        # Clear the input so the next link can be pasted immediately.
        try:
            self.url_entry.delete(0, "end")
            self._sync_clear_btn()
        except Exception:
            pass
        noun = "item" if added == 1 else "items"
        self.update_dl_status(f"Added {added} {noun} to queue.", "#27ae60")
        self.show_toast(f"Added {added} {noun} to queue. Open Queue to view.", "success")

    # -----------------
    # Themed dialogs (replacement for the gray OS message boxes)
    # -----------------
    def _show_dialog(self, title: str, message: str, kind: str = "info",
                     detail: Optional[str] = None,
                     action_label: Optional[str] = None,
                     action_cb=None):
        """Themed stand-in for ``messagebox.show{info,error,warning}``.

        The system boxes are gray OS chrome: they ignore the active palette,
        squeeze a multi-line yt-dlp failure into one clipped line, and give no
        way to copy the error text. This dialog uses the current theme, wraps
        the message, shows technical detail in a separate muted block with a
        Copy button, and can offer one secondary action (e.g. Try again).

        Same ``(title, message)`` shape as messagebox so call sites stay
        readable. Returns the Toplevel (mostly for tests); nothing blocks.
        """
        message, detail = _split_headline(message, detail)

        pal = getattr(self, "_palette", {}) or {}
        role = {"info": "accent", "success": "success",
                "warning": "warning", "error": "danger"}.get(kind, "accent")
        accent = pal.get(role, UITheme.COLOR_PRIMARY)
        accent_hover = pal.get(role + "_hover", accent)
        bg = pal.get("surface", UITheme.SURFACE_BG)
        field_bg = pal.get("bg", "#1e1e24")
        text = pal.get("text", "#ecf0f1")
        sub = pal.get("sub", "#9baaab")
        on_accent = _on_color(accent, "#ffffff", field_bg)
        glyph = {"info": "ℹ", "success": "✓", "warning": "⚠",
                 "error": "✗"}.get(kind, "ℹ")

        dlg = ctk.CTkToplevel(self, fg_color=bg)
        dlg.title(title)
        dlg.resizable(False, False)
        try:
            dlg.transient(self)
        except Exception:
            pass

        head = ctk.CTkFrame(dlg, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(18, 4))
        ctk.CTkLabel(head, text=glyph, font=UITheme.F(20, "bold"),
                     text_color=accent, width=30).pack(side="left")
        ctk.CTkLabel(head, text=title, font=UITheme.F(15, "bold"),
                     text_color=text).pack(side="left")

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(2, 2))
        ctk.CTkLabel(body, text=str(message), font=UITheme.F(12),
                     text_color=text, wraplength=430,
                     justify="left").pack(anchor="w")

        detail = "" if detail is None else str(detail).strip()
        if detail:
            lines = detail.splitlines()
            # Cap what is displayed: a 40-line yt-dlp traceback would otherwise
            # push the buttons off the screen. "Copy details" always copies the
            # complete text, never the truncated preview.
            if len(lines) > 8:
                shown = "\n".join(lines[:8]) + \
                    f"\n… plus {len(lines) - 8} more lines — use Copy details"
            else:
                shown = detail
            box = ctk.CTkFrame(body, fg_color=field_bg,
                               corner_radius=UITheme.RADIUS_FIELD,
                               border_width=UITheme.BORDER_W,
                               border_color=pal.get("hover", sub))
            box.pack(fill="x", anchor="w", pady=(12, 0))
            ctk.CTkLabel(box, text=shown, font=UITheme.F(10), text_color=sub,
                         wraplength=400, justify="left", anchor="w",
                         takefocus=1).pack(side="left", fill="x", expand=True,
                                           padx=12, pady=9)

        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(14, 18))

        def _close(_event=None):
            try:
                dlg.grab_release()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        ctk.CTkButton(row, text="OK", width=104, height=UITheme.H_LG,
                      corner_radius=UITheme.RADIUS_MD,
                      fg_color=accent,
                      hover_color=accent_hover, text_color=on_accent,
                      font=UITheme.F(12, "bold"),
                      command=_close).pack(side="right")

        if detail:
            def _copy():
                try:
                    dlg.clipboard_clear()
                    dlg.clipboard_append(detail)
                except Exception:
                    logger.exception("Could not copy dialog detail")

            ctk.CTkButton(row, text="Copy details", width=112, height=UITheme.H_LG,
                          corner_radius=UITheme.RADIUS_MD,
                          fg_color="transparent", border_width=UITheme.BORDER_W,
                          border_color=pal.get("hover", sub), text_color=sub,
                          hover_color=pal.get("hover", bg),
                          font=UITheme.F(11),
                          command=_copy).pack(side="right", padx=(0, 10))

        if action_label and action_cb:
            def _run_action():
                _close()
                try:
                    action_cb()
                except Exception:
                    logger.exception("Dialog action %r failed", action_label)

            ctk.CTkButton(row, text=action_label, width=112, height=UITheme.H_LG,
                          corner_radius=UITheme.RADIUS_MD,
                          fg_color="transparent", border_width=UITheme.BORDER_W,
                          border_color=accent, text_color=accent,
                          hover_color=pal.get("hover", bg),
                          font=UITheme.F(12, "bold"),
                          command=_run_action).pack(side="right", padx=(0, 10))

        def _on_key(event):
            if event.keysym in ("Return", "KP_Enter", "Escape", "space"):
                _close()
                return "break"

        for _key in ("<Return>", "<KP_Enter>", "<Escape>", "<space>"):
            dlg.bind(_key, _on_key)
        dlg.protocol("WM_DELETE_WINDOW", _close)

        def _center():
            # Center over the app window (not the screen) once the Toplevel has
            # computed its size, so a long error lands where the user is
            # already looking.
            try:
                dlg.update_idletasks()
                w = max(dlg.winfo_reqwidth(), 400)
                h = dlg.winfo_reqheight()
                pw = max(self.winfo_width(), 640)
                ph = max(self.winfo_height(), 420)
                x = self.winfo_rootx() + max(0, (pw - w) // 2)
                y = self.winfo_rooty() + max(0, (ph - h) // 3)
                dlg.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass

        def _grab():
            # grab_set() only sticks once the window is viewable; doing it on a
            # short delay avoids the blocking wait_visibility() call.
            try:
                dlg.grab_set()
                dlg.focus_set()
            except Exception:
                pass

        dlg.after(0, _center)
        dlg.after(90, _grab)
        return dlg

    def _show_info_dialog(self, title: str, message: str,
                          detail: Optional[str] = None):
        return self._show_dialog(title, message, "info", detail=detail)

    def _show_success_dialog(self, title: str, message: str,
                             detail: Optional[str] = None):
        return self._show_dialog(title, message, "success", detail=detail)

    def _show_warning_dialog(self, title: str, message: str,
                             detail: Optional[str] = None):
        return self._show_dialog(title, message, "warning", detail=detail)

    def _show_error_dialog(self, title: str, message: str,
                           detail: Optional[str] = None,
                           action_label: Optional[str] = None, action_cb=None):
        return self._show_dialog(title, message, "error", detail=detail,
                                 action_label=action_label, action_cb=action_cb)

    # -----------------
    # Toast notifications (non-blocking)
    # -----------------
    def show_toast(self, message: str, toast_type: str = "info", duration: int = 3500):
        """Show a non-blocking toast notification at the bottom-right.

        Toasts stack upward instead of drawing on top of each other, can be
        dismissed early with a click, and are capped at four so a burst of
        messages can never cover the window.

        toast_type: 'info' (accent), 'success', 'warning', 'error' (danger)
        duration: milliseconds before auto-dismiss
        """
        # Toast colors come from the active palette (same semantic roles as
        # the buttons), not fixed hexes that ignore theme switches.
        pal = getattr(self, "_palette", {}) or {}
        role = {"info": "accent", "success": "success",
                "warning": "warning", "error": "danger"}.get(toast_type, "accent")
        fg_color = pal.get(role, "#2980b9")
        on_color = _on_color(fg_color, "#ffffff", pal.get("bg", "#1e1e24"))

        try:
            # Drop entries whose widget was destroyed, then cap the stack
            # (oldest first) so rapid successions can't flood the window.
            self._active_toasts = [t for t in self._active_toasts if t.winfo_exists()]
            while len(self._active_toasts) >= 4:
                try:
                    self._active_toasts.pop(0).destroy()
                except Exception:
                    pass

            toast = ctk.CTkFrame(self, fg_color=fg_color,
                                 corner_radius=UITheme.RADIUS_MD)
            setattr(toast, "_theme_roles", {"fg_color": role})

            icon = {"info": "ℹ", "success": "✓", "warning": "⚠", "error": "✗"}.get(toast_type, "ℹ")
            lbl = ctk.CTkLabel(
                toast, text=f" {icon} {message}",
                font=UITheme.F(12), text_color=on_color,
                wraplength=340, justify="right",
            )
            lbl.pack(padx=16, pady=10)

            # Start off the right edge and let _reposition_toasts glide it in;
            # the rest of the stack slides up to make room in the same loop.
            # setattr, not plain assignment: a toast is a bare CTkFrame, so
            # these slots are per-instance extras rather than declared widget
            # attributes (the same shape as the _theme_roles tag above).
            setattr(toast, "_toast_relx",
                    1.12 if getattr(self, "nav_anim_enabled", True) else 0.98)
            setattr(toast, "_toast_rely", 0.955)
            setattr(toast, "_toast_leaving", False)

            self._active_toasts.append(toast)
            self._reposition_toasts()

            def _dismiss(*_args):
                if getattr(toast, "_toast_leaving", False):
                    return
                setattr(toast, "_toast_leaving", True)
                try:
                    self._active_toasts.remove(toast)
                except ValueError:
                    pass
                # Recount the slots first so the stack starts closing the gap
                # while this toast is still flying off.
                self._reposition_toasts()
                if not getattr(self, "nav_anim_enabled", True):
                    try:
                        toast.destroy()
                    except Exception:
                        pass
                    return
                self._fly_off_toast(toast)

            # Click anywhere on the toast to dismiss it immediately.
            toast.bind("<Button-1>", _dismiss)
            lbl.bind("<Button-1>", _dismiss)

            # Auto-dismiss after duration
            self.after(duration, _dismiss)
        except Exception:
            pass

    def _fly_off_toast(self, toast, steps: int = 7):
        """Glide a dismissed toast off the right edge, then destroy it."""
        def step(i: int):
            try:
                if not toast.winfo_exists():
                    return
                t = min(1.0, i / steps)
                eased = 1 - (1 - t) * (1 - t)   # ease-out, like the nav indicator
                toast.place(relx=0.98 + 0.16 * eased,
                            rely=getattr(toast, "_toast_rely", 0.955),
                            anchor="se")
                if i < steps:
                    self.after(16, lambda: step(i + 1))
                else:
                    toast.destroy()
            except Exception:
                try:
                    toast.destroy()
                except Exception:
                    pass

        step(0)

    def _reposition_toasts(self, _event=None):
        """Glide every toast toward its slot in the bottom-right stack.

        Positions are eased instead of snapped: a new toast arrives from the
        right edge and the stack below slides up to close the gap, so the pile
        never blinks into place. One loop drives every toast; its trailing
        after() is cancelled and restarted whenever the stack changes.
        """
        self._active_toasts = [t for t in self._active_toasts if t.winfo_exists()]
        if not self._active_toasts:
            return
        animate = bool(getattr(self, "nav_anim_enabled", True))
        moving = False
        for i, t in enumerate(self._active_toasts):
            target_x, target_y = 0.98, 0.955 - i * 0.065
            cur_x = getattr(t, "_toast_relx", target_x)
            cur_y = getattr(t, "_toast_rely", target_y)
            if animate:
                new_x = cur_x + (target_x - cur_x) * 0.35
                new_y = cur_y + (target_y - cur_y) * 0.35
                if abs(target_x - new_x) > 0.001 or abs(target_y - new_y) > 0.001:
                    moving = True
                else:
                    new_x, new_y = target_x, target_y
            else:
                new_x, new_y = target_x, target_y
            t._toast_relx, t._toast_rely = new_x, new_y
            try:
                t.place(relx=new_x, rely=new_y, anchor="se")
            except Exception:
                pass
        if moving:
            pending = getattr(self, "_toast_anim_id", None)
            if pending:
                try:
                    self.after_cancel(pending)
                except Exception:
                    pass
            self._toast_anim_id = self.after(28, self._reposition_toasts)

    def update_speed_label(self, speed_text: str):
        """Update the speed/ETA label below the progress bar."""
        self.after(0, lambda: self.dl_speed_lbl.configure(text=speed_text))

    def _tag_target_text(self) -> str:
        """What the caption under "Edit Tags" says, given what has been saved."""
        path = getattr(self, "_last_downloaded_file", None)
        if not path:
            return "Tags are edited here, after a download."
        name = os.path.basename(str(path))[:52]
        return f"Editing tags in: {name}" if name else "Tags are edited here."

    def _refresh_tag_target(self) -> None:
        """Point the tag caption at the file "Edit Tags" would actually open."""
        try:
            self.tag_target_lbl.configure(text=self._tag_target_text())
        except Exception:
            pass

    def _open_tag_editor(self):
        filepath = self._last_downloaded_file
        if not filepath or not os.path.exists(filepath):
            self._show_warning_dialog("No File", "No downloaded file available to edit.")
            return
        try:
            from tag_editor import open_tag_editor
            open_tag_editor(self, filepath, on_save=self._on_tags_saved)
        except Exception as e:
            self._show_error_dialog("Tag Editor", f"Could not open tag editor: {e}")

    def _on_tags_saved(self):
        self.show_toast("Tags updated successfully.", "success")
















    def _clear_completion_badge(self, _event=None):
        self._unfocused_done = 0
        try:
            self.title("TuneLab")
        except Exception:
            pass

    def _downloads_in_flight(self) -> bool:
        """True while a direct download or the queue worker is busy."""
        try:
            if self._queue_manager is not None and self._queue_manager.is_running:
                return True
        except Exception:
            pass
        try:
            # set_download_buttons_state(False) disables these for the whole
            # duration of a direct download, so their state is the flag.
            return str(self.btn_download.cget("state")) == "disabled"
        except Exception:
            return False

    def _on_closing(self):
        """Handle window close event, asking first when downloads run."""
        if self._downloads_in_flight():
            if not messagebox.askyesno(
                "Downloads in Progress",
                "Downloads are still running.\n\nQuit anyway?",
            ):
                return
        self._remember_window_geometry()
        self._ui_closed = True
        self.destroy()

    # --- PREVIEW HANDLING ---
    def _ensure_ffplay(self):
        """Return a usable ffplay executable, or None if it can't be found."""
        return downloader.find_helper("ffplay", include_path=True)

    def _ensure_ffmpeg(self):
        """Return a usable ffmpeg executable (bundled or on PATH), else None."""
        return downloader.find_helper("ffmpeg", include_path=True)

    def preview_audio(self):
        url = self.url_entry.get().strip()
        if not url:
            self.show_toast("Please enter a URL to preview.", "warning")
            return
        if not downloader.can_resolve_preview():
            self._show_error_dialog(
                "Dependency Missing",
                "Neither the 'yt_dlp' Python module nor a local 'yt-dlp.exe' was found.\n\n"
                "Install yt-dlp (python -m pip install yt-dlp) or run a download first to "
                "generate the bundled yt-dlp.exe, then retry.",
            )
            return

        self.btn_preview_audio.configure(state="disabled")
        self._show_stop_button(self.btn_stop_audio, True)
        self.update_dl_status("Preparing audio preview...", "#f39c12")

        def worker():
            try:
                stream_url = downloader.resolve_preview_stream(url, audio_only=True)
                ffplay = self._ensure_ffplay()
                if ffplay:
                    cmd = [ffplay, '-nodisp', '-autoexit', '-t', '30', stream_url]
                    self._preview_proc = subprocess.Popen(cmd, **downloader._no_window_kwargs())
                    self._preview_proc.wait()
                    return
                # ffplay is not bundled -- decode the first 30s with the bundled
                # ffmpeg into raw PCM and play it through sounddevice, so the
                # preview works in the packaged app without extra installs.
                _sd = _lazy_import_sounddevice()
                _np = _lazy_import_numpy()
                ffmpeg = self._ensure_ffmpeg()
                if _sd is None or _np is None or not ffmpeg:
                    raise RuntimeError(
                        "Audio preview needs ffplay.exe or (ffmpeg.exe + sounddevice). "
                        "ffplay was not found.\n\n"
                        "Install ffmpeg/ffplay or place ffplay.exe next to the app "
                        "to use previews."
                    )
                self._preview_via_sd = True
                proc = subprocess.Popen(
                    [ffmpeg, '-v', 'error', '-t', '30', '-i', stream_url,
                     '-f', 'f32le', '-ac', '2', '-ar', '44100', '-'],
                    stdout=subprocess.PIPE,
                    **downloader._no_window_kwargs(),
                )
                self._preview_proc = proc
                raw, _ = proc.communicate()
                if proc.returncode != 0 or not raw:
                    raise RuntimeError(
                        "Could not stream a preview (ffmpeg returned an error). "
                        "The video may not allow previews."
                    )
                # ffmpeg's stdout is bytes at runtime; tolerate the str that
                # some Popen overload resolutions may infer here.
                pcm = raw if isinstance(raw, bytes) else raw.encode()
                data = _np.frombuffer(pcm, dtype=_np.float32).reshape(-1, 2)
                _sd.play(data, 44100)
                _sd.wait()
            except Exception as e:
                logger.exception("Audio preview failed")
                self.after(0, lambda err=e: self._show_error_dialog('Preview Error', f'Audio preview failed:\n{err}'))
            finally:
                self._preview_via_sd = False
                self.after(0, lambda: self.btn_preview_audio.configure(state='normal'))
                self.after(0, lambda: self._show_stop_button(self.btn_stop_audio, False))
                self.after(0, lambda: self.update_dl_status('System Ready', '#95a5a6'))

        self._start_worker(worker)

    def stop_preview_audio(self):
        try:
            _sd = _lazy_import_sounddevice()
            if getattr(self, '_preview_via_sd', False) and _sd is not None:
                # Playing through sounddevice: interrupt the playback.
                try:
                    _sd.stop()
                except Exception:
                    logger.debug("Failed to stop sounddevice preview", exc_info=True)
            elif hasattr(self, '_preview_proc') and self._preview_proc:
                try:
                    self._preview_proc.terminate()
                except Exception:
                    try:
                        self._preview_proc.kill()
                    except Exception:
                        logger.debug("Failed to kill preview process")
            self._preview_proc = None
        finally:
            self.btn_preview_audio.configure(state="normal")
            self._show_stop_button(self.btn_stop_audio, False)

    def preview_video(self):
        url = self.url_entry.get().strip()
        if not url:
            self.show_toast("Please enter a URL to preview.", "warning")
            return
        if not downloader.can_resolve_preview():
            self._show_error_dialog(
                "Dependency Missing",
                "Neither the 'yt_dlp' Python module nor a local 'yt-dlp.exe' was found.\n\n"
                "Install yt-dlp (python -m pip install yt-dlp) or run a download first to "
                "generate the bundled yt-dlp.exe, then retry.",
            )
            return

        self.btn_preview_video.configure(state="disabled")
        self._show_stop_button(self.btn_stop_video, True)
        self.update_dl_status("Preparing video preview...", "#8e44ad")

        def worker():
            try:
                stream_url = downloader.resolve_preview_stream(url, audio_only=False)

                if _lazy_import_vlc() is not None:
                    def start_vlc():  # type: ignore[call-arg]

                        try:
                            try:
                                if hasattr(self, '_vlc_player') and self._vlc_player:
                                    self._vlc_player.stop()
                            except Exception:
                                pass

                            self.preview_panel.pack(pady=(6,12))
                            self.preview_panel.update_idletasks()
                            handle = self.preview_panel.winfo_id()

                            # VLC module is optional at type-check time.
                            _vlc = _lazy_import_vlc()
                            if _vlc is None:
                                raise RuntimeError("VLC module not available")
                            vlc_instance = _vlc.Instance()
                            self._vlc_instance = vlc_instance
                            vlc_player = vlc_instance.media_player_new()
                            self._vlc_player = vlc_player

                            media = vlc_instance.media_new(stream_url)
                            vlc_player.set_media(media)

                            try:
                                vlc_player.set_hwnd(handle)
                            except Exception:
                                try:
                                    vlc_player.set_xwindow(handle)
                                except Exception:
                                    pass

                            vlc_player.play()

                        except Exception as e:
                            # start_vlc itself was dispatched with after(0, ...),
                            # so this is on the main thread and can use the themed
                            # dialog like every other message.
                            self._show_error_dialog(
                                'Preview Error',
                                f'Embedded video preview failed:\n{e}')

                    self.after(0, start_vlc)
                else:
                    ffplay = self._ensure_ffplay()
                    if not ffplay:
                        raise RuntimeError(
                            "ffplay was not found. Install ffmpeg/ffplay or place ffplay.exe "
                            "next to the app to use previews."
                        )
                    cmd = [
                        ffplay,
                        '-autoexit',
                        '-t', '30',
                        '-fs', '0',
                        '-noborder',
                        '-window_title', 'Video Preview',
                        '-geometry', '480x270',
                        stream_url,
                    ]
                    self._preview_proc = subprocess.Popen(cmd, **downloader._no_window_kwargs())
                    self._preview_proc.wait()

            except Exception as e:
                err = e
                self.after(0, lambda err=err: self._show_error_dialog('Preview Error', f'Video preview failed:\n{err}'))
            finally:
                self.after(0, lambda: self.btn_preview_video.configure(state='normal'))
                self.after(0, lambda: self._show_stop_button(self.btn_stop_video, False))
                self.after(0, lambda: self.update_dl_status('System Ready', '#95a5a6'))

        self._start_worker(worker)

    def stop_preview_video(self):
        try:
            if _lazy_import_vlc() is not None and hasattr(self, '_vlc_player') and self._vlc_player:
                try:
                    self._vlc_player.stop()
                except Exception:
                    pass
                try:
                    self.preview_panel.pack_forget()
                except Exception:
                    pass
                self._vlc_player = None

            if hasattr(self, '_preview_proc') and self._preview_proc:
                try:
                    self._preview_proc.terminate()
                except Exception:
                    try:
                        self._preview_proc.kill()
                    except Exception:
                        logger.debug("Failed to kill preview process")
                        pass
                self._preview_proc = None
        finally:
            self.btn_preview_video.configure(state="normal")
            self._show_stop_button(self.btn_stop_video, False)









    def update_dl_status(self, text, color):
        themed = self._map_color(color)
        # Remember the palette role so a theme switch while a status is
        # showing repaints the pill instead of freezing the old hue.
        role = LEGACY_HEX_ROLES.get(str(color).lower())

        def _apply():
            # The status pill on the Downloader tab is the single home of
            # download status — there is deliberately no second copy in the
            # header (a duplicate "Finished!" up there was just noise).
            try:
                self.dl_status.configure(text=text, text_color=themed)
                if role:
                    setattr(self.dl_status, "_theme_roles", {"text_color": role})
            except Exception:
                pass
            # The pill's dot echoes the status color.
            try:
                self._status_dot.configure(text_color=themed)
                if role:
                    setattr(self._status_dot, "_theme_roles",
                            {"text_color": role})
            except Exception:
                pass

        self.after(0, _apply)



    def _set_hover_detail(self, text, color):
        try:
            self._dl_detail_backup_text = self.dl_detail.cget("text")
            self._dl_detail_backup_color = self.dl_detail.cget("text_color")
        except Exception:
            self._dl_detail_backup_text = ""
            self._dl_detail_backup_color = "#95a5a6"
        self.update_dl_detail(text, color)

    def _restore_hover_detail(self):
        if hasattr(self, "_dl_detail_backup_text"):
            self.update_dl_detail(self._dl_detail_backup_text, getattr(self, "_dl_detail_backup_color", "#95a5a6"))













    # --- TAB 2 DESIGN ---
    def build_studio_view(self):
        self.file_frame = ctk.CTkFrame(self.tab_studio, fg_color="transparent")
        self.file_frame.pack(pady=(12,4), padx=20, fill="x")
        self.file_lbl = ctk.CTkLabel(self.file_frame, text="Load a music file...", font=UITheme.F(12, "italic"), text_color="#95a5a6")
        self.file_lbl.pack(side="left", padx=10, pady=10)
        self.btn_browse_studio = ctk.CTkButton(
            self.file_frame, text="Browse Audio", width=100,
            command=self.load_studio_file)
        self.btn_browse_studio.pack(side="right", padx=10, pady=10)
        self._style_button(self.btn_browse_studio, "secondary")

        self.sp_lbl = ctk.CTkLabel(self.tab_studio, text="Speed: 0.85x", font=UITheme.F(14, "bold"))
        self.sp_lbl.pack(anchor="w", padx=20, pady=(6,0))
        self.sp_sld = ctk.CTkSlider(self.tab_studio, from_=0.5, to=1.5, command=lambda v: self.sp_lbl.configure(text=f"Speed: {float(v):.2f}x"))  # type: ignore[arg-type]


        self.sp_sld.set(0.85)
        self.sp_sld.pack(fill="x", padx=20, pady=(4,10))

        self.rv_lbl = ctk.CTkLabel(self.tab_studio, text="Reverb Depth: 40%", font=UITheme.F(14, "bold"))
        self.rv_lbl.pack(anchor="w", padx=20, pady=(4,0))
        self.rv_sld = ctk.CTkSlider(self.tab_studio, from_=0.0, to=1.0, command=lambda v: self.rv_lbl.configure(text=f"Reverb Depth: {int(float(v)*100)}%"))  # type: ignore[arg-type]


        self.rv_sld.set(0.40)
        self.rv_sld.pack(fill="x", padx=20, pady=(4,10))

        self.ctrl_frame = ctk.CTkFrame(self.tab_studio, fg_color="transparent")
        self.ctrl_frame.pack(pady=(6,10))
        self.btn_play = ctk.CTkButton(self.ctrl_frame, text="Play", width=115, command=self.play_preview)
        self.btn_play.grid(row=0, column=0, padx=6)
        self._style_button(self.btn_play, "primary", icon="play")
        self.btn_stop = ctk.CTkButton(self.ctrl_frame, text="Stop", width=115, command=self.stop_preview, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=6)
        self._style_button(self.btn_stop, "danger", icon="stop")

        self.btn_export = ctk.CTkButton(self.tab_studio, text="Export Remix", font=UITheme.F(12, "bold"), width=280, height=40, command=self.export_studio_track)
        self.btn_export.pack(pady=(4,10))
        self._style_button(self.btn_export, "primary", icon="download")

        self.studio_progress_bar = ctk.CTkProgressBar(self.tab_studio, width=300)
        self.studio_progress_bar.set(0)
        self.studio_progress_bar.pack(pady=(4, 10), padx=20, fill="x")
        self.tab_studio.place(relx=0, rely=0, relwidth=1, relheight=1)

    def load_studio_file(self):
        sel = filedialog.askopenfilename(title="Select File", filetypes=[("Audio Assets", "*.mp3 *.wav *.flac *.m4a")])
        if sel:
            self.studio_file_path = sel
            self.file_lbl.configure(text=os.path.basename(sel), text_color="#2ecc71")

    def build_customization_view(self):
        # Page title lives in the header only — no in-page H1.
        # One control owns theme mode now: every palette carries its own
        # Light/Dark 'mode' and apply_color_theme syncs CTk from it, so the
        # separate "Theme Mode" dropdown was redundant and is gone.

        # The Appearance page outgrew the window: measured, its cards want ~1142px of
        # height against a minsize of 680, so the last card was simply cut off
        # unless the window was maximized. The Performance page solved the same
        # problem with a scroll well; this one needs it too. Insets match that
        # page's, for the same reason (a square canvas over rounded card
        # corners): see the comment above the Performance scroll frame.
        settings_scroll = ctk.CTkScrollableFrame(
            self.tab_customization, fg_color="transparent")
        settings_scroll.pack(fill="both", expand=True,
                             padx=UITheme.RADIUS_CARD,
                             pady=UITheme.RADIUS_CARD)
        self.settings_scroll = settings_scroll

        theme_card = self._settings_card(settings_scroll, "Theme")
        theme_card.pack(fill="x", padx=0, pady=(0, 8))
        ctk.CTkLabel(
            theme_card, text="Color theme:",
            font=UITheme.F(12), anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 4))
        # CUSTOM_THEME_NAME is injected into COLOR_THEMES at startup, so it is
        # in this list by the time the page is built.
        self.theme_menu = ctk.CTkOptionMenu(
            theme_card,
            values=list(COLOR_THEMES.keys()),
            command=self.apply_color_theme,
            width=220
        )
        self.theme_menu.set(self._color_theme_name)
        self.theme_menu.pack(anchor="w", padx=16, pady=(0, 6))
        self._style_option_menu(self.theme_menu)
        ctk.CTkLabel(
            theme_card,
            text="Light/Dark follows the palette you pick here.",
            font=UITheme.F(10), anchor="w", text_color="#95a5a6",
        ).pack(fill="x", padx=16, pady=(0, 12))

        self._build_custom_theme_card()

        # Theme selection lives in the dropdown above only (the duplicate row
        # of clickable swatch dots was removed as redundant UI).

        # There is no Background card here any more. A photo or animated GIF
        # sat behind every page, where it was visible only in the margins
        # between cards and could only ever cost legibility there - and it cost
        # a full settings card, a file dialog, an animation timer and a scrim
        # baked into every frame to maintain. The palettes carry the whole
        # appearance now.
        #
        # Cache-clearing moved to the Performance tab (it is maintenance,
        # not appearance).

        # Rail behaviour. The collapse state, hover-peek and motion lengths
        # are appearance choices, so they sit here rather than in Performance.
        rail_card = self._settings_card(settings_scroll, "Sidebar & motion")
        rail_card.pack(fill="x", padx=0, pady=(0, 8))

        self.sb_collapsed_var = tk.BooleanVar(value=not self._sidebar_expanded)
        self.sb_collapsed_chk = ctk.CTkCheckBox(
            rail_card, text="Start with the rail collapsed to icons",
            variable=self.sb_collapsed_var, command=self._on_sb_collapsed_pref)
        self.sb_collapsed_chk.pack(anchor="w", padx=16, pady=(4, 0))
        ctk.CTkLabel(
            rail_card,
            text="Ctrl+B, or the row at the bottom of the rail, collapses it any time.",
            font=UITheme.F(11), text_color="#95a5a6", anchor="w",
            wraplength=560, justify="left").pack(anchor="w", padx=16, pady=(0, 4))

        self.sb_peek_var = tk.BooleanVar(value=bool(self._sb_peek_pref))
        self.sb_peek_chk = ctk.CTkCheckBox(
            rail_card, text="Glide the rail open while the pointer rests on an icon",
            variable=self.sb_peek_var, command=self._on_sb_peek_pref)
        self.sb_peek_chk.pack(anchor="w", padx=16, pady=(0, 0))
        ctk.CTkLabel(
            rail_card,
            text="Off by default — a rail that opens itself every time the pointer "
                 "crosses it gets in the way. When on, only the icon column arms "
                 "it, nothing moves but the width, and it closes as you leave.",
            font=UITheme.F(11), text_color="#95a5a6", anchor="w",
            wraplength=560, justify="left").pack(anchor="w", padx=16, pady=(0, 4))

        self.nav_anim_var = tk.BooleanVar(value=bool(self.nav_anim_enabled))
        self.nav_anim_chk = ctk.CTkCheckBox(
            rail_card, text="Animate the accent pill and the rail's slide",
            variable=self.nav_anim_var, command=self._on_nav_anim_pref)
        self.nav_anim_chk.pack(anchor="w", padx=16, pady=(0, 2))

        ctk.CTkLabel(rail_card, text="Motion length (lower is snappier):",
                     font=UITheme.F(12), anchor="w").pack(anchor="w", padx=16,
                                                          pady=(2, 0))
        self.nav_anim_speed_slider = ctk.CTkSlider(
            rail_card, from_=4, to=30, number_of_steps=26,
            command=self._on_nav_speed)
        self.nav_anim_speed_slider.set(self.nav_anim_speed)
        self.nav_anim_speed_slider.pack(padx=16, pady=(0, 2), fill="x")
        self.nav_anim_speed_lbl = ctk.CTkLabel(
            rail_card, text=f"{int(self.nav_anim_speed)} frames",
            font=UITheme.F(10), text_color="#95a5a6", anchor="w")
        self.nav_anim_speed_lbl.pack(anchor="w", padx=16, pady=(0, 12))

        self.tab_customization.place(relx=0, rely=0, relwidth=1, relheight=1)

    # --- Sidebar & motion preferences ------------------------------------
    # Each one applies the moment it is changed: the rail is cheap to
    # reconfigure, and making the user restart to see the effect of a
    # checkbox is how you end up with settings nobody tunes.

    def _on_sb_collapsed_pref(self):
        want_collapsed = bool(self.sb_collapsed_var.get())
        self._set_pref('sidebar_collapsed', want_collapsed)
        if want_collapsed == self._sidebar_expanded:
            self.toggle_sidebar()   # preview the choice immediately

    def _on_sb_peek_pref(self):
        self._sb_peek_pref = bool(self.sb_peek_var.get())
        self._set_pref('sidebar_peek_on_hover', self._sb_peek_pref)
        if not self._sb_peek_pref:
            # Turning it off means off now, not whenever the pointer moves.
            self._sb_cancel_peek()
            if self._sb_peeking:
                self._sb_peeking = False
                self._animate_sidebar(False)

    def _on_nav_anim_pref(self):
        self.nav_anim_enabled = bool(self.nav_anim_var.get())
        self._set_pref('nav_animation_enabled', self.nav_anim_enabled)

    def _on_nav_speed(self, value):
        try:
            self.nav_anim_speed = int(float(value))
        except Exception:
            return
        self._set_pref('nav_animation_speed', self.nav_anim_speed)
        try:
            self.nav_anim_speed_lbl.configure(
                text=f"{self.nav_anim_speed} frames")
        except Exception:
            pass

    def build_performance_view(self):
        # Use a scrollable frame so all settings are reachable even on small screens
        saved = downloader.perf_cfg_from_prefs(self._prefs)
        _saved_aria = saved["use_aria2"]
        _saved_connections = saved["aria2_connections"]
        _saved_frags = saved["concurrent_fragment_downloads"]

        # No label_text: the header title already says "Performance Settings".
        #
        # The inset is not decoration. A CTkScrollableFrame is a rounded frame
        # wrapped around a plain ``tkinter.Canvas``, and that canvas always
        # paints a square rectangle - packed edge to edge here it covered the
        # page card's RADIUS_CARD corners and left the one square box in an app
        # that is otherwise curved. Pulling it in past the radius puts the
        # canvas's corners on the card's straight edges, where its colour is
        # the card's own and the square is invisible.
        scroll = ctk.CTkScrollableFrame(self.tab_performance, fg_color="transparent")
        scroll.pack(fill="both", expand=True,
                    padx=UITheme.RADIUS_CARD, pady=UITheme.RADIUS_CARD)

        # Card 1: download tuning (+ Apply, which commits these controls).
        # padx is 0 because the scroll frame already provides the page's
        # inset; the cards still land the same distance from the page edge as
        # every other control in the app.
        tuning = self._settings_card(scroll, "Downloads")
        tuning.pack(fill="x", padx=0, pady=(0, 8))

        self.aria2_var = tk.BooleanVar(value=_saved_aria)
        self.aria2_chk = ctk.CTkCheckBox(tuning, text="Enable aria2 external downloader", variable=self.aria2_var)
        self.aria2_chk.pack(anchor="w", padx=16, pady=(4, 0))
        ctk.CTkLabel(tuning, text="Uses aria2 for parallel connections (faster downloads).", font=UITheme.F(11), text_color="#95a5a6", wraplength=600, justify="left").pack(anchor="w", padx=16, pady=(0, 2))

        ctk.CTkLabel(tuning, text="aria2 connections:  (max 16 — aria2 hard limit)", font=UITheme.F(12)).pack(anchor="w", padx=16, pady=(2, 0))
        self.aria2_conn_slider = ctk.CTkSlider(tuning, from_=1, to=16, number_of_steps=15)
        self.aria2_conn_slider.set(_saved_connections)
        self.aria2_conn_slider.pack(padx=16, pady=(0, 2), fill="x")

        ctk.CTkLabel(tuning, text="Concurrent fragment downloads:", font=UITheme.F(12)).pack(anchor="w", padx=16, pady=(2, 0))
        # Range comes from downloader so the slider and the clamp that reads the
        # saved value can never disagree about what the maximum is.
        self.concurrent_frag_slider = ctk.CTkSlider(
            tuning, from_=1, to=downloader.FRAGMENT_DOWNLOADS_MAX,
            number_of_steps=downloader.FRAGMENT_DOWNLOADS_MAX - 1)
        self.concurrent_frag_slider.set(_saved_frags)
        self.concurrent_frag_slider.pack(padx=16, pady=(0, 2), fill="x")

        ctk.CTkLabel(tuning, text="SoundCloud downloads:", font=UITheme.F(12)).pack(anchor="w", padx=16, pady=(2, 0))
        self.soundcloud_var = tk.BooleanVar(value=bool(self._prefs.get("soundcloud_direct_first", True)))
        self.soundcloud_chk = ctk.CTkCheckBox(tuning, text="Try downloading from SoundCloud first, fall back to YouTube", variable=self.soundcloud_var, command=self.apply_soundcloud_pref)
        self.soundcloud_chk.pack(anchor="w", padx=16, pady=(0, 4))

        # Video download quality cap (saves time/disk when 4K isn't needed;
        # the cap is applied at download time — nothing is resized afterwards).
        ctk.CTkLabel(tuning, text="Max video resolution:", font=UITheme.F(12)).pack(anchor="w", padx=16, pady=(2, 0))
        self.video_res_var = tk.StringVar(value=str(self._prefs.get("max_video_resolution", "Best (up to 4K)")))
        self.video_res_menu = ctk.CTkOptionMenu(
            tuning, values=downloader.VIDEO_RESOLUTION_OPTIONS, variable=self.video_res_var,
            command=self._on_video_res_change, width=200)
        self.video_res_menu.pack(anchor="w", padx=16, pady=(0, 4))
        self._style_option_menu(self.video_res_menu)

        # Cookies file (optional) for age-gated/region-blocked videos.
        ctk.CTkLabel(tuning, text="Cookies file (optional, Netscape format):",
                     font=UITheme.F(12)).pack(anchor="w", padx=16, pady=(6, 0))
        self.cookies_file_var = tk.StringVar(
            value=str(self._prefs.get("cookies_file", "")))
        self.cookies_file_entry = ctk.CTkEntry(
            tuning, textvariable=self.cookies_file_var, width=320)
        self.cookies_file_entry.pack(anchor="w", padx=16, pady=(0, 2))
        self.cookies_browse_btn = ctk.CTkButton(
            tuning, text="Browse", width=80,
            command=self._choose_cookies_file)
        self.cookies_browse_btn.pack(anchor="w", padx=16, pady=(0, 2))
        self._style_button(self.cookies_browse_btn, "ghost", bordered=True)
        ctk.CTkButton(
            tuning, text="Clear", width=80,
            command=self._clear_cookies_file).pack(anchor="w", padx=16, pady=(0, 6))

        self.apply_perf_btn = ctk.CTkButton(tuning, text="Apply Performance Settings", command=self.apply_performance_settings, width=260)
        self.apply_perf_btn.pack(anchor="w", padx=16, pady=(6, 14))
        self._style_button(self.apply_perf_btn, "primary")

        # Card 2: maintenance actions.
        maint = self._settings_card(scroll, "Maintenance")
        maint.pack(fill="x", padx=0, pady=(0, 0))

        # Engine (yt-dlp) updater: lives here in Performance so it is next to
        # the other download-tuning controls, not just on the Update Center page.
        engine = self._settings_card(maint, "Downloader engine (yt-dlp)")
        engine.pack(fill="x", padx=0, pady=(8, 8))
        self.ytdlp_update_btn = ctk.CTkButton(
            engine, text="⮔ Update yt-dlp", width=200, cursor="hand2",
            command=self.update_ytdlp_clicked,
        )
        self.ytdlp_update_btn.pack(anchor="w", padx=16, pady=(4, 1))
        self._style_button(self.ytdlp_update_btn, "secondary", icon="download")
        self.ytdlp_ver_lbl = ctk.CTkLabel(
            engine,
            text=f"yt-dlp version: {downloader.get_ytdlp_version() or 'not detected'}",
            font=UITheme.F(10),
            text_color=(getattr(self, "_palette", {}) or {}).get("sub", "#95a5a6"),
            anchor="w")
        self.ytdlp_ver_lbl.pack(anchor="w", padx=16, pady=(0, 4))

        # Unattended startup installs: opt-out for packaged builds only
        # (frozen engine = a user-space copy of yt-dlp.exe that -U rewrites;
        # the dev environment is never pip-mutated silently, so the toggle
        # is inert there - see _ytdlp_auto_update_allowed).
        self.engine_auto_var = tk.BooleanVar(
            value=bool((getattr(self, "_prefs", None) or {}).get(
                "engine_auto_update", True)))
        ctk.CTkCheckBox(
            engine,
            text="Update the engine automatically at startup",
            variable=self.engine_auto_var,
            command=self._apply_engine_auto_pref,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        self.clear_cache_btn = ctk.CTkButton(
            maint, text="Clear Download Cache", width=260,
            command=self.clear_download_cache,
        )
        self.clear_cache_btn.pack(anchor="w", padx=16, pady=(8, 2))
        # Ghost, not a full danger fill: this opens a confirmation dialog and
        # only deletes a rebuildable cache, so it should not be the loudest
        # control in the Maintenance list. Same reasoning as Clear History.
        self._style_button(self.clear_cache_btn, "ghost", bordered=True, icon="trash")

        self.perf_status = ctk.CTkLabel(maint, text="Current: default", font=UITheme.F(11), text_color="#95a5a6", anchor="w")
        self.perf_status.pack(anchor="w", padx=16, pady=(2, 14))

    def apply_performance_settings(self):
        cfg = {
            'use_aria2': bool(self.aria2_var.get()),
            'aria2_connections': downloader._clamp_aria2_connections(self.aria2_conn_slider.get()),
            'concurrent_fragment_downloads': int(self.concurrent_frag_slider.get()),
            'cookies_file': str(self.cookies_file_var.get()).strip(),
        }
        try:
            downloader.set_performance_config(cfg)
            # Persist all settings
            self._set_pref('use_aria2', cfg['use_aria2'])
            self._set_pref('aria2_connections', cfg['aria2_connections'])
            self._set_pref('concurrent_fragment_downloads', cfg['concurrent_fragment_downloads'])
            self._set_pref('cookies_file', cfg['cookies_file'])
            self.perf_status.configure(text=f"Current: aria2={cfg['use_aria2']}, conns={cfg['aria2_connections']}, frags={cfg['concurrent_fragment_downloads']}")
            # Honest feedback
            _aria2_path = downloader.get_fast_downloader_path() if cfg['use_aria2'] else None
            if cfg['use_aria2']:
                if _aria2_path:
                    self.show_toast(
                        f"Settings applied — aria2 found at {_aria2_path}",
                        "success", duration=5000)
                else:
                    # The install instructions are too long for a toast;
                    # this one stays a real dialog.
                    #
                    # The old wording here pointed users at the EXE's own
                    # folder, which is wrong for a packaged build: PyInstaller's
                    # onedir layout puts the collected binaries in an _internal
                    # subfolder *beside* the EXE, so a user who followed that
                    # instruction to the letter still got "aria2 was NOT found".
                    # List the folders that are actually searched instead, so
                    # the message cannot send anyone somewhere we never look.
                    _searched = downloader._bundle_search_dirs()
                    _where = "\n".join("    - %s" % d for d in _searched)
                    _msg = (
                        "Settings applied, but aria2 was NOT found on your system.\n\n"
                        "The 'use aria2' toggle will have no effect until aria2 is installed.\n\n"
                        "To get aria2:\n"
                        "  1. Download from https://aria2.github.io/\n"
                        "  2. Copy aria2c.exe into one of these folders:\n"
                        f"{_where}\n"
                        "  3. Restart the app\n\n"
                        "Or install via package manager:\n"
                        "  - Windows: choco install aria2   (or scoop install aria2)\n"
                        "  - macOS:   brew install aria2\n\n"
                        "Until then, leave this disabled."
                    )
                    self._show_info_dialog("Performance", _msg)
            else:
                self.show_toast("Performance settings applied (aria2 disabled).", "success")
        except Exception as e:
            self._show_error_dialog("Performance Error", f"Failed to apply settings:\n{e}")

    def apply_soundcloud_pref(self):
        """Persist the 'try SoundCloud direct first' preference for MP3 downloads."""
        enabled = bool(self.soundcloud_var.get())
        self._set_pref('soundcloud_direct_first', enabled)
        self.update_dl_detail(
            "SoundCloud direct download " + ("ENABLED" if enabled else "DISABLED")
            + " (falls back to YouTube when unavailable).",
            "#95a5a6",
        )

    def _choose_cookies_file(self):
        choice = filedialog.askopenfilename(
            title="Select cookies file (Netscape format)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if choice:
            self.cookies_file_var.set(choice)
            self.apply_performance_settings()

    def _clear_cookies_file(self):
        self.cookies_file_var.set("")
        self.apply_performance_settings()

    def _on_video_res_change(self, value):
        """Persist the max video resolution preference live (no Apply needed)."""
        res = str(value)
        self._set_pref('max_video_resolution', res)
        downloader.performance_config['max_video_resolution'] = res
        label = res  # Already human-friendly (e.g. "1080p", "Best (up to 4K)")
        self.update_dl_detail(f"Max video resolution: {label}.", "#95a5a6")

    # Pages whose views are built on demand instead of at startup.
    # Each entry maps the page name to (tab attribute, builder, title).
    # Downloader builds in __init__ (it is the landing page); the rest build
    # on first show_frame, which keeps ~5/6 of widget construction out of
    # startup. _page_frames entries start as None until built.
    _LAZY_PAGES = (
        ('queue', 'tab_queue', 'build_queue_view', 'Download Queue'),
        ('history', 'tab_history', 'build_history_view', 'Download History'),
        ('studio', 'tab_studio', 'build_studio_view', 'Slowed + Reverb Studio'),
        ('aep', 'tab_aep', 'build_aep_view', 'AEP Version Converter'),
        ('settings', 'tab_customization', 'build_customization_view',
         'Appearance'),
        ('performance', 'tab_performance', 'build_performance_view',
         'Performance Settings'),
        ('updates', 'tab_updates', 'build_updates_view', 'Update Center'),
    )

    def _discover_theme_roles(self, w) -> dict:
        """The option->role pairs *w*'s current colours match in the legacy table.

        The startup sweep in apply_color_theme does this for every widget once,
        but a page built after startup never passes through that sweep - so a
        lazily built label carrying an old hardcoded hex would keep it through
        every later theme switch. Same table, per widget, at registration time.
        """
        found = {}
        for opt in ('fg_color', 'hover_color', 'border_color',
                    'text_color', 'progress_color', 'button_color',
                    'button_hover_color', 'label_fg_color',
                    'label_text_color'):
            try:
                cur = w.cget(opt)
            except Exception:
                continue
            if not isinstance(cur, str) or cur.lower() in ('transparent', ''):
                continue
            role = LEGACY_HEX_ROLES.get(cur.lower())
            if role:
                found[opt] = role
        return found

    def _register_themed_widgets(self, root=None):
        """Index *root*'s subtree into the theme registry.

        Runs once per page right after it is built (and once for the shell at
        startup). Each entry remembers the widget and its option->role map,
        so a later theme switch configures exactly those options instead of
        probing every widget for options it may not have.
        """
        if root is None:
            root = self
        try:
            widgets = list(self._iter_widgets(root))
        except Exception:
            return 0
        before = len(self._themed_registry)
        seen = {id(w) for w, _roles in self._themed_registry}
        for w in widgets:
            if id(w) in seen:
                continue
            try:
                roles = getattr(w, "_theme_roles", None)
                if not roles:
                    # No explicit tag: look the current colours up once so a
                    # page built after startup is not frozen at its build hex.
                    roles = self._discover_theme_roles(w)
                    if roles:
                        setattr(w, "_theme_roles", roles)
            except Exception:
                continue
            if not roles:
                continue
            try:
                self._themed_registry.append((w, dict(roles)))
            except Exception:
                continue
            seen.add(id(w))
        return len(self._themed_registry) - before

    def _ensure_page_built(self, name: str):
        """Build *name*'s view on first visit; no-op once built."""
        if name in self._built_pages:
            return
        for page, attr, builder, _title in self._LAZY_PAGES:
            if page == name:
                try:
                    getattr(self, builder)()
                except Exception:
                    logger.debug("Lazy page build %r failed", name,
                                 exc_info=True)
                    return
                self._page_frames[name] = getattr(self, attr, None)
                self._built_pages.add(name)
                # Re-run the current theme over the new widgets: they were
                # built from the active palette, but the two type walks also
                # have to see them. The role registry only records widgets
                # that carry _theme_roles; the scroll well's canvas, its
                # hide-until-hover bar and the CTk-default slider tracks are
                # painted by _style_form_controls / _style_composites, which
                # ran once at startup - before this page existed. Without
                # this the first visit shows CustomTkinter's greys until the
                # next theme switch.
                try:
                    self._register_themed_widgets(
                        getattr(self, attr, None))
                    self._style_form_controls()
                    self._style_composites()
                except Exception:
                    logger.debug("Theme styling for %r failed", name,
                                 exc_info=True)
                return

    def show_frame(self, name: str):
        # Lazily built pages do not exist yet on first click.
        self._ensure_page_built(name)
        # Re-clicking the already-active nav button must not remap pages,
        # force repaints, or restart animations — that churn was part of
        # the residual black-flash on click-through.
        if name == getattr(self, '_current_page', None):
            return
        pages = self._page_frames
        page_titles = {
            'downloader': 'Media Downloader',
            'queue': 'Download Queue',
            'history': 'Download History',
            'studio': 'Slowed + Reverb Studio',
            'aep': 'AEP Version Converter',
            'settings': 'Appearance',
            'performance': 'Performance Settings',
            'updates': 'Update Center',
        }
        self.title_lbl.configure(text=page_titles.get(name, ''))

        target = pages.get(name)
        others = [f for f in pages.values() if f is not target]

        # Map the incoming page FIRST and unmap the remaining ones after.
        # The old order (unmap everything, then map the target) briefly
        # left nothing visible; if anything forced an intermediate repaint
        # mid-switch (CustomTkinter's transparent-color detection does),
        # that showed up as a one-frame black flash.
        if target is not None:
            try:
                target.place(relx=0, rely=0, relwidth=1, relheight=1)
            except Exception:
                pass
        # Unmap the rest BEFORE any forced repaint. Forcing update_idletasks
        # here (the old code did) painted one frame with every transparent
        # page still stacked, so the outgoing page bled through the incoming
        # one — the "widgets clipping through each other" seen on click.
        # With no forced pass in between, Tk coalesces map + unmap and paints
        # only the final state; the single idletasks after the unmap keeps
        # layout resolved for the nav animation without exposing the stack.
        for f in others:
            try:
                f.place_forget()
            except Exception:
                pass
        try:
            self.update_idletasks()
        except Exception:
            pass

        btn = self.nav_buttons.get(name)
        if btn is not None:
            try:
                self._animate_nav_to(btn)
            except Exception:
                pass

        self._set_active_nav(name)
        self._current_page = name

        # Refresh dynamic tabs when they become visible
        if name == "history":
            self._refresh_history_view()
        elif name == "queue":
            self._refresh_queue_tab()

    def _set_active_nav(self, active_name: str):
        # Skip entirely when nothing changed: a repaint redraws every row
        # canvas, and page switches fire often (Ctrl+1..6, peek, clicks).
        if active_name == getattr(self, '_active_nav_name', None):
            return
        self._active_nav_name = active_name
        try:
            self._repaint_nav_rows()
        except Exception:
            pass

    # -----------------
    # Navigation indicator helpers
    # -----------------
    def _indicator_slot(self, btn):
        """Where the accent pill sits for a given nav row.

        The pill lives in the gutter between the rail edge and the chips, so
        it never covers a row's icon, and its x does not depend on the rail
        width - which is why collapsing leaves it exactly where it was.
        """
        return (3, int(btn.winfo_y()) + 6, UITheme.SB_ROW_H - 12)

    def _place_indicator(self, x, y, h):
        """Move/size the accent pill.

        CustomTkinter refuses width/height in ``place()`` (it raises), so the
        size goes through ``configure`` - which is also why the pill used to
        sit still: every placement was silently dying inside a try/except.
        """
        self.nav_indicator.configure(width=3, height=max(1, int(h)))
        self.nav_indicator.place(x=int(x), y=int(y))

    def _position_nav_indicator_initial(self, *_):
        try:
            btn = self.nav_buttons.get(getattr(self, '_active_nav_name', None)
                                       or 'downloader')
            if btn is None or not getattr(self, 'nav_indicator', None):
                return
            x, y, h = self._indicator_slot(btn)
            self._place_indicator(x, y, h)
        except Exception:
            logger.debug("nav indicator placement failed", exc_info=True)

    def _animate_nav_to(self, target_btn: ctk.CTkButton):
        if not getattr(self, 'nav_anim_enabled', True) or not getattr(self, 'nav_indicator', None):
            try:
                x, y, h = self._indicator_slot(target_btn)
                self._place_indicator(x, y, h)
            except Exception:
                pass
            return
 
        try:
            if self._nav_anim_after_id:
                try:
                    self.after_cancel(self._nav_anim_after_id)
                except Exception:
                    pass
 
            start_y = float(self.nav_indicator.winfo_y())
            start_h = float(self.nav_indicator.winfo_height())
            tx, target_y, th = self._indicator_slot(target_btn)
 
            steps = max(1, int(self.nav_anim_speed))
            def ease(t: float) -> float:
                return 1 - (1 - t) * (1 - t)
 
            def step(i: int):
                try:
                    t = min(1.0, i / steps)
                    progress = ease(t)
                    ny = start_y + (target_y - start_y) * progress
                    nh = start_h + (th - start_h) * progress
                    self._place_indicator(tx, ny, nh)
                    if i < steps:
                        self._nav_anim_after_id = self.after(12, lambda: step(i + 1))
                except Exception:
                    pass
 
            step(0)
        except Exception:
            pass

    # -----------------
    # Collapsible sidebar
    # -----------------
    # The pages you work in, then the pages you tune. The flat order is
    # unchanged - Ctrl+1..8 map to downloader, queue, history, studio,
    # aep converter, settings, performance, update center - grouping only
    # adds a header above each set.
    _SB_GROUPS = (("MENU", ("downloader", "queue", "history", "studio", "aep")),
                  ("SETUP", ("settings", "performance", "updates")))
    # Shown in each row's right slot, mirroring the <Control-N> bindings.
    _SB_KEYS = {"downloader": "1", "queue": "2", "history": "3",
                "studio": "4", "aep": "5", "settings": "6",
                "performance": "7", "updates": "8"}

    def _build_sidebar(self):
        """Brand, grouped nav rows, badge slots, footer toggle, accent pill.

        Everything in the rail is placed once at a fixed pixel position and
        the collapse never moves or rewrites any of it: ``_sb_set_width``
        changes widths only, and Tk clips what ends up outside the rail.
        The old version swapped each row's text, anchor, font size and width
        halfway through the slide, which is exactly what read as items
        popping in and out.
        """
        pal = self._palette
        # name -> (drawn icon, label). The icon names index _icon_shapes, so a
        # row's mark is geometry the palette can ink, not an emoji the system
        # font gets to decide the size, weight and colour of.
        self._sb_items = {
            'downloader': ('download', 'Downloader'),
            'queue': ('queue', 'Queue'),
            'history': ('history', 'History'),
            'studio': ('studio', 'Studio'),
            'aep': ('aep', 'AEP Convert'),
            'settings': ('settings', 'Theme'),
            'performance': ('performance', 'Speed'),
            'updates': ('update', 'Updates'),
        }
        # Hover tips: the row's own name plus its shortcut. A sentence here sits
        # in a 300px box over the page, which is a lot of furniture to drop next
        # to an icon that already says what it is.
        self._sb_tips = {name: '%s  (Ctrl+%s)' % (label, self._SB_KEYS.get(name, '?'))
                         for name, (_icon, label) in self._sb_items.items()}
        self.nav_buttons = {}
        self._sb_icons = {}
        self._sb_texts = {}
        self._sb_hints = {}
        self._sb_headers = []

        # Brand: an accent-tinted logo tile plus the wordmark. The tile sits
        # in the same 30px icon column as the rows, so it neither moves nor
        # drifts off-centre when the rail collapses to icon width. The wordmark
        # starts where a row's label starts - past the icon column - so the
        # collapsed rail (which is only pad + icon + pad wide) clips it whole
        # instead of leaving the first letter poking out, cut in half.
        self.sb_logo = ctk.CTkFrame(
            self.sidebar, width=UITheme.SB_ICON_W, height=UITheme.SB_ICON_W,
            corner_radius=UITheme.RADIUS_SM, fg_color="transparent",
        )
        self.sb_logo.place(x=UITheme.SB_PAD_X, y=14)
        # The mark is drawn, not typed: a canvas holds the note so the tile's
        # ink is the palette's accent at any size (see _icon_shapes). The box
        # is mark-sized for the same reason as a row's: opaque square corners
        # would square off the tile's RADIUS_SM corners.
        self.sb_logo_glyph = tk.Canvas(
            self.sb_logo, width=UITheme.SB_ICON_BOX + 2,
            height=UITheme.SB_ICON_BOX + 2, highlightthickness=0, bd=0,
            bg=_mix(pal.get('sidebar', UITheme.SIDEBAR_BG),
                    pal.get('accent', UITheme.COLOR_PRIMARY), 0.16),
            cursor="hand2")
        self.sb_logo_glyph.place(relx=0.5, rely=0.5, anchor="center")
        _paint_icon(self.sb_logo_glyph, 'note',
                    pal.get('accent', UITheme.COLOR_PRIMARY),
                    size=UITheme.SB_ICON_MARK - 1)
        self.sb_brand = ctk.CTkLabel(
            self.sidebar, text="TuneLab", font=UITheme.F(14, "bold"),
            anchor="w", cursor="hand2", height=UITheme.SB_ICON_W)
        self.sb_brand.place(x=UITheme.SB_LABEL_X, y=14)
        self._sb_bind_clickable(
            self.sb_logo, (self.sb_logo_glyph, self.sb_brand),
            lambda e: self.toggle_sidebar(),
            'Collapse / expand  (Ctrl+B)', self.sb_logo)

        y = 14 + UITheme.SB_ICON_W + 12
        for title, names in self._SB_GROUPS:
            hdr = ctk.CTkLabel(self.sidebar, text=" ".join(title),
                               font=UITheme.F(9, "bold"), anchor="w",
                               height=16)
            hdr.place(x=UITheme.SB_LABEL_X, y=y + 1)
            setattr(hdr, "_theme_roles", {"text_color": "sub"})
            self._sb_headers.append(hdr)
            y += 20
            for name in names:
                self._make_nav_row(name, y)
                y += UITheme.SB_ROW_H + UITheme.SB_ROW_GAP
            y += 8
        self._sb_nav_bottom = y

        # Footer: the collapse control belongs at the bottom of the rail,
        # under the list it controls, not as a bar above the brand. It is a
        # row like any other, so its label clips away when collapsed.
        self._sb_footer_sep = ctk.CTkFrame(self.sidebar, height=1,
                                           corner_radius=0, fg_color="transparent")
        self.sb_toggle_btn = ctk.CTkFrame(
            self.sidebar, width=UITheme.SB_ROW_W, height=UITheme.SB_ROW_H,
            corner_radius=UITheme.RADIUS_MD, fg_color="transparent",
            border_width=0,
        )
        self.sb_toggle_glyph = tk.Canvas(
            self.sb_toggle_btn, width=UITheme.SB_ICON_BOX,
            height=UITheme.SB_ICON_BOX, highlightthickness=0, bd=0,
            bg=pal.get('sidebar', UITheme.SIDEBAR_BG), cursor="hand2")
        self.sb_toggle_glyph.place(x=UITheme.SB_ICON_X, y=UITheme.SB_ICON_Y)
        _paint_icon(self.sb_toggle_glyph, self._sb_chevron(),
                    pal.get('sub', UITheme.COLOR_GRAY),
                    size=UITheme.SB_ICON_MARK)
        self.sb_toggle_lbl = ctk.CTkLabel(
            self.sb_toggle_btn, text='Collapse', font=UITheme.F(12),
            anchor="w", cursor="hand2", height=UITheme.SB_ROW_H)
        self.sb_toggle_lbl.place(x=UITheme.SB_TEXT_X, y=0)
        self._sb_bind_clickable(
            self.sb_toggle_btn, (self.sb_toggle_glyph, self.sb_toggle_lbl),
            lambda e: self.toggle_sidebar(),
            'Collapse / expand  (Ctrl+B)', self.sb_toggle_glyph,
            name='__footer__')

        # Accent pill: glides down the gutter to the selected row.
        self.nav_indicator = ctk.CTkFrame(
            self.sidebar,
            width=3,
            height=UITheme.SB_ROW_H - 12,
            fg_color=pal.get('accent', UITheme.COLOR_PRIMARY),
            corner_radius=1,
        )

        self._sb_set_width(UITheme.SB_W_EXPANDED if self._sidebar_expanded
                           else UITheme.SB_W_COLLAPSED)
        self._layout_sidebar()

        # Hover, peek and press are all decided in _sb_pointer_update from
        # the real pointer position, and every widget in the rail reports in
        # (Tk does not bubble events, so the chip and its labels each bind).
        for seq in ('<Enter>', '<Leave>', '<Motion>'):
            self.sidebar.bind(seq, self._sb_pointer_update)
        # Keeps the footer glued to the bottom as the window is resized.
        self.sidebar.bind('<Configure>', self._layout_sidebar)
        # Double-click empty rail space also toggles collapse.
        self.sidebar.bind('<Double-Button-1>', lambda e: self.toggle_sidebar())
        self._repaint_nav_rows()

    def _make_nav_row(self, name, y):
        """One nav row: icon column, label, and a right-hand slot.

        The slot shows the Ctrl+<n> digit, or a live badge when something is
        being counted (the Queue row shows unfinished items). Both sit at
        SB_HINT_X, past the collapsed rail's edge, so neither has to be
        hidden and nothing reflows.
        """
        icon, label = self._sb_items[name]
        row = ctk.CTkFrame(
            self.sidebar, width=UITheme.SB_ROW_W, height=UITheme.SB_ROW_H,
            corner_radius=UITheme.RADIUS_MD, fg_color="transparent",
            border_width=0,
        )
        row.place(x=UITheme.SB_PAD_X, y=y)
        # Nothing inside a chip ever moves: the icon column sits at one x, the
        # shortcut slot at another, and Tk clips whatever the rail's edge cuts.
        # The word label stops a pixel short of the chip's edges and two short of
        # its height, because a CTkLabel paints a rectangle of its own background
        # over whatever is under it - labels that spanned the row edge to edge bit
        # the selected row's hairline ring wherever they crossed and it arrived on
        # screen in dashes. It is still centred (1 + (38 - 2) / 2 == 38 / 2).
        # A canvas, not a label: the mark is drawn (see _icon_shapes), so it
        # fits its box exactly and takes whatever ink the row's state calls for.
        # The box is the mark and a pixel, never the whole column: a canvas is
        # opaque where a CTkLabel was transparent, so a box that reached the
        # chip's corners would paint its square over the chip's rounding.
        _pal = getattr(self, '_palette', {}) or {}
        ic = tk.Canvas(row, width=UITheme.SB_ICON_BOX,
                       height=UITheme.SB_ICON_BOX, highlightthickness=0,
                       bd=0, bg=_pal.get('sidebar', UITheme.SIDEBAR_BG),
                       cursor="hand2")
        ic.place(x=UITheme.SB_ICON_X, y=UITheme.SB_ICON_Y)
        _paint_icon(ic, icon, _pal.get('sub', UITheme.COLOR_GRAY),
                    size=UITheme.SB_ICON_MARK)
        tx = ctk.CTkLabel(row, text=label, font=UITheme.F(12), anchor="w",
                          cursor="hand2", height=UITheme.SB_ROW_H - 2)
        tx.place(x=UITheme.SB_TEXT_X, y=1)
        hint = ctk.CTkLabel(row, text=self._SB_KEYS.get(name, ""),
                            width=22, height=18, corner_radius=9,
                            font=UITheme.F(9, "bold"),
                            fg_color=UITheme.SIDEBAR_HOVER,
                            text_color=UITheme.COLOR_GRAY)
        hint.place(x=UITheme.SB_HINT_X, y=(UITheme.SB_ROW_H - 18) // 2)

        self._sb_bind_clickable(
            row, (ic, tx, hint), lambda e, n=name: self.show_frame(n),
            self._sb_tips[name], ic, name=name)

        # Keyboard parity. A row is a CTkFrame, which no traversal stops on and
        # which CustomTkinter binds no keys to, so without this the rail - the
        # one control that decides what the rest of the app shows - could only
        # be reached with the mouse. takefocus is set on the bare Frame because
        # CTkFrame.configure() only knows its own options.
        try:
            tk.Frame.configure(row, takefocus=1)
        except Exception:
            pass
        setattr(row, "_nav_name", name)
        for widget in (row, ic, tx, hint):
            try:
                # No add="+": CustomTkinter's bind() takes a bool and always
                # binds additively onto its internal widgets, so passing the
                # string Tk accepts would only be a lie to the type checker.
                widget.bind("<Return>", lambda _e, n=name: self._nav_activate(n))
                widget.bind("<KP_Enter>", lambda _e, n=name: self._nav_activate(n))
                widget.bind("<space>", lambda _e, n=name: self._nav_activate(n))
            except Exception:
                pass
        # The ring has to follow real focus, not just the traversal step that
        # set it: Shift-Tab and a click into the URL box both move focus without
        # going through _focus_step.
        row.bind("<FocusIn>", lambda _e, n=name: self._nav_focus(n))
        row.bind("<FocusOut>", lambda _e, n=name: self._nav_blur(n))

        self.nav_buttons[name] = row
        self._sb_icons[name] = ic
        self._sb_texts[name] = tx
        self._sb_hints[name] = hint
        return row

    def _sb_bind_clickable(self, row, children, on_click, tip, tip_anchor,
                           name=None):
        """Wire a rail row (or the brand/footer) for click, hover and press.

        Events do not bubble in Tk: the chip and each label inside it have to
        carry the bindings themselves, or hovering the text would do nothing.
        """
        def _release(event, n=name):
            # Act on release, like CTkButton: the press tint is visible for the
            # length of the click, and dragging off the row cancels the action.
            self._sb_press_release(n)
            if on_click is not None:
                on_click(event)

        for w in (row, *children):
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass   # CTkFrame has no cursor option; its labels carry it
            w.bind('<Button-1>', lambda e, n=name: self._sb_press_press(n))
            w.bind('<ButtonRelease-1>', _release)
            w.bind('<Enter>', self._sb_pointer_update)
            w.bind('<Leave>', self._sb_pointer_update)
            w.bind('<Motion>', self._sb_pointer_update)
            if tip:
                w.bind('<Enter>',
                       lambda e, a=tip_anchor, t=tip:
                       self._schedule_sb_tooltip(a, t), add='+')
                w.bind('<Leave>', lambda e, a=tip_anchor: self._hide_sb_tooltip(a),
                       add='+')

    def _sb_press_press(self, name=None):
        if name is not None and self._sb_press != name:
            self._sb_press = name
            self._repaint_nav_rows()

    def _sb_press_release(self, name=None):
        if self._sb_press is not None:
            self._sb_press = None
            self._repaint_nav_rows()

    def _refresh_sidebar_items(self):
        """Keep the one label that differs per state honest, and repaint.

        Deliberately does not touch row texts, fonts or positions: those are
        identical collapsed and expanded (the rail clips them), which is the
        whole reason the slide no longer pops. The footer word is only ever
        legible when the rail is wide, so _sb_set_width can rewrite it while
        it is clipped.
        """
        self._sb_set_footer_word(self._sb_shown)
        self._repaint_nav_rows()

    def _sb_chevron(self):
        """The footer's arrow: it points the way a click will move the rail."""
        expanded = getattr(self, '_sb_shown', self._sidebar_expanded)
        return 'chevron_left' if expanded else 'chevron_right'

    def _sb_set_footer_word(self, expanded):
        want = 'Collapse' if expanded else 'Expand'
        if getattr(self, '_sb_footer_word', None) == want:
            return
        self._sb_footer_word = want
        try:
            self.sb_toggle_lbl.configure(text=want)
            # The arrow turns with the word: a footer that reads "Expand" must
            # not still point left. The ink is whatever the last repaint chose.
            _paint_icon(self.sb_toggle_glyph, self._sb_chevron(),
                        getattr(self, '_sb_footer_ink', UITheme.COLOR_GRAY))
        except Exception:
            pass

    def toggle_sidebar(self):
        """Collapse or expand the rail (Ctrl+B, the footer row, or the brand)."""
        self._sb_cancel_peek()
        self._sb_peeking = False   # a click makes the shown state the real one
        self._sidebar_expanded = not self._sidebar_expanded
        self._set_pref('sidebar_collapsed', not self._sidebar_expanded)
        self._hide_sb_tooltip(force=True)
        self._animate_sidebar()  # repositions the accent pill when done

    def _sb_set_width(self, width):
        """The single place the rail's width is set.

        The chips follow the rail so they keep their own rounded corners
        instead of being sliced by its edge; everything *inside* a chip stays
        put and is clipped by Tk, which is what makes the transition read as
        a wipe rather than a reflow.
        """
        w = max(UITheme.SB_W_COLLAPSED,
                min(UITheme.SB_W_EXPANDED, int(round(width))))
        inner = max(UITheme.SB_ICON_W, w - 2 * UITheme.SB_PAD_X)
        try:
            self.sidebar.configure(width=w)
        except Exception:
            pass
        self._sidebar_cur_w = w
        for row in getattr(self, 'nav_buttons', {}).values():
            try:
                row.configure(width=inner)
            except Exception:
                pass
        for widget, shrink in ((getattr(self, 'sb_toggle_btn', None), 0),
                               (getattr(self, '_sb_footer_sep', None), 4)):
            if widget is None:
                continue
            try:
                widget.configure(width=max(1, inner - shrink))
            except Exception:
                pass
        # The footer word lives past the clip line while collapsed. Rewriting
        # it here - at the instant it is covered - is what keeps the wipe clean;
        # changing it at the top of a slide would show the word flipping while
        # still perfectly readable.
        if w <= UITheme.SB_LABEL_X + 8:
            self._sb_set_footer_word(self._sb_shown)

    def _layout_sidebar(self, event=None):
        """Pin the footer row and its hairline to the bottom of the rail."""
        try:
            h = self.sidebar.winfo_height()
        except Exception:
            return
        if h < 40 or h == getattr(self, '_sb_h', 0):
            return
        self._sb_h = h
        footer_y = max(getattr(self, '_sb_nav_bottom', 0) + 6,
                       h - UITheme.SB_ROW_H - 10)
        try:
            self.sb_toggle_btn.place(x=UITheme.SB_PAD_X, y=footer_y)
            self._sb_footer_sep.place(x=UITheme.SB_PAD_X + 2, y=footer_y - 9)
        except Exception:
            pass

    def _animate_sidebar(self, target_expanded=None):
        """Glide the rail's width - the only thing in it that changes.

        One eased run of _sb_set_width calls. The previous version also
        swapped every row's text/anchor/font/width at 60% of the run, which is
        exactly the "pop in and out" this replaces.
        """
        try:
            if self._sb_anim_after_id:
                try:
                    self.after_cancel(self._sb_anim_after_id)
                except Exception:
                    pass
            self._sb_anim_after_id = None

            if target_expanded is None:
                target_expanded = self._sidebar_expanded
            target_w = float(UITheme.SB_W_EXPANDED if target_expanded
                             else UITheme.SB_W_COLLAPSED)
            start_w = float(getattr(self, '_sidebar_cur_w', 0)
                            or self.sidebar.winfo_width()
                            or target_w)
            self._sb_shown = bool(target_expanded)

            def finish():
                self._sb_anim_after_id = None
                self._sb_set_width(target_w)
                # Safety net: a mid-slide reversal may never have reached the
                # clipped widths where the word is normally rewritten.
                self._sb_set_footer_word(self._sb_shown)
                try:
                    self._hide_sb_tooltip(force=True)
                    self._position_nav_indicator_initial()
                    self._repaint_nav_rows()
                except Exception:
                    pass

            if (not getattr(self, 'nav_anim_enabled', True)
                    or abs(target_w - start_w) < 1.5):
                finish()
                return

            _interval = 14  # ms (~70fps)
            _steps = max(6, int(getattr(self, 'nav_anim_speed', 12) or 12))

            def ease(t):
                return 1 - (1 - t) ** 4   # ease-out-quart: leaves fast, stops soft

            def step(i):
                t = min(1.0, i / _steps)
                self._sb_set_width(start_w + (target_w - start_w) * ease(t))
                if i < _steps:
                    self._sb_anim_after_id = self.after(
                        _interval, lambda: step(i + 1))
                else:
                    finish()

            step(0)
        except Exception:
            pass

    def _sb_pointer_update(self, event=None):
        """The single brain for hover and peek: derive it from the pointer.

        Enter/Leave fire per widget and Tk does not bubble, so moving from a
        row onto its own icon label fires Leave then Enter. Re-deriving from
        the real pointer position turns that churn into a no-op instead of a
        flicker, and clipped rows (whose geometry still says "wide") are
        excluded by the rail's visible right edge.
        """
        try:
            rail = getattr(self, 'sidebar', None)
            if rail is None or not rail.winfo_ismapped():
                return
            px, py = self.winfo_pointerxy()
            rx, ry = rail.winfo_rootx(), rail.winfo_rooty()
            rw, rh = rail.winfo_width(), rail.winfo_height()
            inside = (rx <= px < rx + rw) and (ry <= py < ry + rh)
            hover = None
            if inside:
                edge = rx + rw
                candidates = list(getattr(self, 'nav_buttons', {}).items())
                candidates.append(('__footer__',
                                   getattr(self, 'sb_toggle_btn', None)))
                for name, row in candidates:
                    if row is None or not row.winfo_ismapped():
                        continue
                    x, y = row.winfo_rootx(), row.winfo_rooty()
                    w = min(row.winfo_width(), edge - x)
                    if w <= 0:
                        continue
                    if x <= px < x + w and y <= py < y + row.winfo_height():
                        hover = name
                        break
            if hover != getattr(self, '_sb_hover', None):
                self._sb_hover = hover
                self._repaint_nav_rows()
            # Peek is armed by the nav rows, not by the whole rail: resting on
            # the footer chip - which sits in the very same column, so an x
            # band cannot tell them apart - or on the empty space under the
            # list must not throw the rail open. While a peek is already open
            # the pointer may go anywhere inside it, or the rail would slam
            # shut the moment it moved onto the labels it just revealed.
            armed = hover is not None and hover != '__footer__'
            self._sb_peek_track(inside and (armed or self._sb_peeking))
        except Exception:
            pass

    def _sb_peek_track(self, inside):
        """Let a collapsed rail glide open while the pointer is resting in it.

        Only the width changes and the icon column never moves, so the rail
        can open under the cursor without the target item shifting.
        """
        if not getattr(self, '_sb_peek_pref', False):
            return
        if inside:
            if (self._sidebar_expanded or self._sb_peeking
                    or self._sb_peek_after_id is not None
                    or getattr(self, '_sb_anim_after_id', None)):
                return
            try:
                # 220ms: passing through on the way to the content should not
                # open the rail, resting on an icon should.
                self._sb_peek_after_id = self.after(220, self._sb_peek_open)
            except Exception:
                self._sb_peek_after_id = None
            return
        self._sb_cancel_peek()
        if self._sb_peeking:
            self._sb_peeking = False
            self._animate_sidebar(False)

    def _sb_cancel_peek(self):
        pending = getattr(self, '_sb_peek_after_id', None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._sb_peek_after_id = None

    def _sb_peek_open(self):
        self._sb_peek_after_id = None
        if self._sidebar_expanded or self._sb_peeking:
            return
        self._sb_peeking = True
        self._animate_sidebar(True)

    def _nav_focus(self, name: str) -> None:
        if getattr(self, "_sb_focus_name", None) == name:
            return
        self._sb_focus_name = name
        try:
            self._repaint_nav_rows()
        except Exception:
            pass

    def _nav_blur(self, name: str) -> None:
        if getattr(self, "_sb_focus_name", None) != name:
            return
        self._sb_focus_name = None
        try:
            self._repaint_nav_rows()
        except Exception:
            pass

    def _nav_activate(self, name: str) -> str:
        """Switch page from the keyboard and keep focus on the row that did it.

        ``show_frame`` rebuilds the focus list, so without putting focus back
        the ring would disappear and Tab would restart from the top of the page
        the user had just navigated to.
        """
        self.show_frame(name)
        row = getattr(self, "nav_buttons", {}).get(name)
        if row is not None:
            try:
                self._collect_focusables()
                self._sb_focus_name = name
                self._focus_index = 0
                self._focus_target(row).focus_set()
                self._repaint_nav_rows()
            except Exception:
                logger.debug("Refocusing nav row %r failed", name, exc_info=True)
        return "break"

    def _repaint_nav_rows(self):
        """Paint every rail piece from the palette + hover/press/active state.

        Selection is an accent-tinted chip with a hairline ring and an accent
        icon. Both are mixed per palette, because the old fixed #2c3e50 chip
        vanished on the dark rails and went muddy on the light ones.
        """
        pal = getattr(self, '_palette', {}) or {}
        base = pal.get('sidebar', UITheme.SIDEBAR_BG)
        accent = pal.get('accent', UITheme.COLOR_PRIMARY)
        text_c = pal.get('text', '#ecf0f1')
        sub_c = pal.get('sub', UITheme.COLOR_GRAY)
        hover_fill = _mix(base, pal.get('hover', UITheme.SIDEBAR_HOVER), 0.85)
        active_fill = _mix(base, accent, 0.18)
        active_edge = _mix(base, accent, 0.45)
        press_fill = _mix(base, accent, 0.32)
        idle_text = _mix(base, text_c, 0.82)
        active = getattr(self, '_active_nav_name', None)
        hover = getattr(self, '_sb_hover', None)
        press = getattr(self, '_sb_press', None)

        # Unchanged rows are skipped: see _sb_row_state in ui_theme.py for why
        # re-configuring an already-correct row costs real frames.
        painted = getattr(self, '_sb_painted', None)
        if painted is None:
            painted = {}
            self._sb_painted = painted

        for name, row in getattr(self, 'nav_buttons', {}).items():
            is_active = name == active
            # A row holding keyboard focus is ringed like the selected one. It
            # is not the same thing - the selected row is the page you are on,
            # the focused row is where Tab is - but on a collapsed rail there
            # is no label to tell them apart from the chip alone, and a
            # keyboard user cannot see the pointer position either.
            focused = name == getattr(self, '_sb_focus_name', None)
            fill, edge, bw = "transparent", "transparent", 0
            icon_c, label_c = sub_c, idle_text
            if is_active:
                fill, edge, bw = active_fill, active_edge, 1
                icon_c, label_c = accent, text_c
            elif focused:
                edge, bw = accent, UITheme.BORDER_W
                icon_c, label_c = accent, text_c
            elif name == press:
                fill, icon_c, label_c = press_fill, accent, text_c
            elif name == hover:
                fill, icon_c, label_c = hover_fill, accent, text_c
            state = _sb_row_state(pal, fill, edge, bw, icon_c, label_c, base)
            if painted.get(name) == state:
                continue
            painted[name] = state
            try:
                row.configure(fg_color=fill, border_width=bw,
                              border_color=_ring_color(edge, fill, base))
                canvas = self._sb_icons[name]
                # The chip's colour travels to the icon by hand: a canvas is an
                # opaque Tk widget, not a transparent CTk label, so a background
                # left behind would frame the glyph in a little rectangle.
                canvas.configure(bg=fill if fill != "transparent" else base)
                _paint_icon(canvas, self._sb_items[name][0], icon_c)
                self._sb_texts[name].configure(text_color=label_c)
            except Exception:
                logger.debug("nav row %r repaint failed", name, exc_info=True)
            self._repaint_nav_hint(name, base, accent, text_c, sub_c)

        # Brand tile, footer chip, hairline, section headers.
        try:
            tile = _mix(base, accent, 0.16)
            self.sb_logo.configure(
                fg_color=tile,
                border_width=1, border_color=_mix(base, accent, 0.34))
            self.sb_logo_glyph.configure(bg=tile)
            _paint_icon(self.sb_logo_glyph, 'note', accent, size=17)
            self.sb_brand.configure(text_color=text_c)
        except Exception:
            pass
        try:
            on_footer = hover == '__footer__'
            foot_fill = (press_fill if press == '__footer__'
                         else (hover_fill if on_footer else "transparent"))
            self.sb_toggle_btn.configure(fg_color=foot_fill, border_width=0)
            self._sb_footer_ink = accent if on_footer else sub_c
            self.sb_toggle_glyph.configure(
                bg=foot_fill if foot_fill != "transparent" else base)
            _paint_icon(self.sb_toggle_glyph, self._sb_chevron(),
                        self._sb_footer_ink)
            self.sb_toggle_lbl.configure(
                text_color=text_c if on_footer else idle_text)
            self._sb_footer_sep.configure(fg_color=_mix(base, sub_c, 0.28))
        except Exception:
            pass
        for hdr in getattr(self, '_sb_headers', []):
            try:
                hdr.configure(text_color=_mix(base, sub_c, 0.9))
            except Exception:
                pass

    def _repaint_nav_hint(self, name, base: Optional[str] = None,
                          accent: Optional[str] = None,
                          text_c: Optional[str] = None,
                          sub_c: Optional[str] = None):
        """Right slot: an accent badge while a count is set, else the digit.

        Takes the already-mixed colors when _repaint_nav_rows is looping (so
        the palette is read once), and can be called with just a name from
        _set_nav_badge when a count changes on its own.
        """
        lbl = getattr(self, '_sb_hints', {}).get(name)
        if lbl is None:
            return
        if base is None:
            pal = getattr(self, '_palette', {}) or {}
            base = pal.get('sidebar', UITheme.SIDEBAR_BG)
            accent = pal.get('accent', UITheme.COLOR_PRIMARY)
            text_c = pal.get('text', '#ecf0f1')
            sub_c = pal.get('sub', UITheme.COLOR_GRAY)
        # A caller may hand over only the row's base fill, and a palette key
        # can come back blank, so settle every slot: _on_color() cannot take
        # a None fill and a None ink would leave the badge unreadable.
        base = base or UITheme.SIDEBAR_BG
        accent = accent or UITheme.COLOR_PRIMARY
        text_c = text_c or '#ecf0f1'
        sub_c = sub_c or UITheme.COLOR_GRAY
        count = getattr(self, '_sb_badges', {}).get(name) or 0
        try:
            if count:
                lbl.configure(
                    text=str(count if count < 100 else "99+"),
                    fg_color=accent,
                    text_color=_on_color(accent, text_c, base),
                    border_width=0)
            else:
                lbl.configure(text=self._SB_KEYS.get(name, ""),
                              fg_color="transparent", text_color=sub_c)
        except Exception:
            pass

    def _set_nav_badge(self, name: str, count) -> None:
        """Put a live count in a nav row's right slot (0 clears it)."""
        try:
            self._sb_badges[name] = int(count or 0)
        except Exception:
            return
        self._repaint_nav_hint(name)

    def _schedule_sb_tooltip(self, widget, text: str, only_when_collapsed: bool = True):
        """Delay tooltip show to avoid flicker when the mouse moves quickly."""
        try:
            # Remember what the bubble belongs to: the row, not the exact label
            # the pointer happened to be over (see _hide_sb_tooltip).
            self._sb_tip_owner = self._sb_tip_row(widget)
            # Repainting a row re-places the CTk canvas/label inside it, and Tk
            # answers by firing Enter/Leave for rows the pointer is nowhere
            # near - which used to open the wrong row's bubble, or cancel the
            # right one. An Enter from the rail only counts when the pointer is
            # genuinely on that row.
            if self._sb_in_rail(widget) and \
                    not self._sb_pointer_on(self._sb_tip_owner):
                return
            pending = getattr(self, '_sb_tooltip_after_id', None)
            if pending:
                try:
                    self.after_cancel(pending)
                except Exception:
                    pass
            self._sb_tooltip_after_id = self.after(
                450, lambda: self._show_sb_tooltip(widget, text, only_when_collapsed))
        except Exception:
            pass

    def _show_sb_tooltip(self, widget, text: str, only_when_collapsed: bool = True):
        """Floating label just outside the rail, level with *widget*.

        The collapsed nav rail uses it for icon names; the History row
        actions reuse it (``only_when_collapsed=False``) for their
        glyph-only buttons.
        """
        try:
            if not getattr(self, "_tooltips_enabled", False):
                return
        # Suppress tooltip during sidebar animation to prevent flicker.
            if getattr(self, '_sb_anim_after_id', None):
                return
            # Also while peeking: the labels are already readable then, and a
            # bubble over them would only cover the row it describes.
            if only_when_collapsed and (self._sidebar_expanded
                                        or getattr(self, '_sb_shown', False)):
                self._hide_sb_tooltip(force=True)
                return
            # One anchor per row, pinned to the rail's edge: anchoring to
            # whichever label the pointer happened to be over made the bubble
            # jump to three different spots as the mouse crossed an icon, its
            # text and its badge slot. Widgets outside the rail (the History
            # row's glyph buttons) still get their bubble beside themselves.
            rail = self.sidebar
            if self._sb_in_rail(widget):
                x = rail.winfo_rootx() + rail.winfo_width() + 6
            else:
                x = widget.winfo_rootx() + widget.winfo_width() + 8
            y = widget.winfo_rooty() + max(0, (widget.winfo_height() - 26) // 2)

            tip_bg = self._palette.get('sidebar_active', UITheme.SIDEBAR_ACTIVE)
            tip_fg = self._palette.get('text', '#ecf0f1')

            tp = self._sb_popup()
            self._sb_tooltip_lbl.configure(text=text, bg=tip_bg, fg=tip_fg)
            tp.wm_geometry(f'+{x}+{y}')

            # Avoid restack churn: only re-paint/re-show when the popup is
            # not already visible. Rapid mouse passes across icons <Enter>/
            # <Leave> fire repeatedly; re-deiconifying + update_idletasks on
            # every single one is what made the icons flicker.
            if tp.state() != 'normal' or not tp.winfo_viewable():
                tp.update_idletasks()
                tp.deiconify()
        except Exception:
            # Whatever went wrong, nothing may be left painted on screen.
            # Dropping the only reference to a mapped popup here is what used
            # to strand little boxes around the rail that never went away.
            self._drop_sb_popups()

    @staticmethod
    def _alive(widget) -> bool:
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def _sb_in_rail(self, widget) -> bool:
        """Is *widget*, or one of its ancestors, part of the rail?"""
        rail = getattr(self, 'sidebar', None)
        node = widget
        while node is not None and rail is not None:
            if node is rail:
                return True
            node = getattr(node, 'master', None)
        return False

    def _sb_tip_row(self, widget):
        """The rail row *widget* belongs to, or *widget* itself.

        The bubble is scheduled from an anchor (the icon) but has to stay put
        while the pointer wanders anywhere over the same row, so the region to
        test is the row and not the glyph.
        """
        rail = getattr(self, 'sidebar', None)
        node = getattr(widget, 'master', None)
        while node is not None and rail is not None:
            if getattr(node, 'master', None) is rail:
                return node
            node = getattr(node, 'master', None)
        return widget

    def _sb_pointer_on(self, owner) -> bool:
        """Is the pointer still on *owner* (or on the bubble above it)?

        A rail row is measured up to the rail's visible edge - collapsed, its
        geometry still claims the full expanded width and would swallow part of
        the page. The bubble itself is the exception: it hangs over the page
        just outside the rail, and a tooltip you can dismiss by hovering it
        would vanish the moment you tried to read it.
        """
        try:
            if owner is None or not owner.winfo_exists():
                return False
            px, py = self.winfo_pointerxy()
            for tp in getattr(self, '_sb_popups', []):
                if not tp.winfo_exists() or not tp.winfo_viewable():
                    continue
                if (tp.winfo_rootx() <= px < tp.winfo_rootx() + tp.winfo_width()
                        and tp.winfo_rooty() <= py
                        <= tp.winfo_rooty() + tp.winfo_height()):
                    return True
            x, y = owner.winfo_rootx(), owner.winfo_rooty()
            w, h = owner.winfo_width(), owner.winfo_height()
            rail = getattr(self, 'sidebar', None)
            if rail is not None and owner is not rail and self._sb_in_rail(owner):
                w = min(w, rail.winfo_rootx() + rail.winfo_width() - x)
            return w > 0 and h > 0 and x <= px < x + w and y <= py < y + h
        except Exception:
            return False

    def _sb_popup(self):
        """The single reused popup, created on first use.

        Reusing ONE hidden Toplevel instead of creating/destroying a borderless
        one per hover is deliberate: on Windows a freshly mapped borderless
        Toplevel paints as a solid black rectangle for a frame. Any popup that
        went missing (destroyed with its toplevel, say) is dropped here too, so
        at most one of them can ever exist.
        """
        live = [tp for tp in getattr(self, '_sb_popups', []) if self._alive(tp)]
        for dead in getattr(self, '_sb_popups', []):
            if dead not in live:
                try:
                    dead.destroy()
                except Exception:
                    pass
        self._sb_popups = live
        if live:
            return live[0]
        tp = tk.Toplevel(self)
        tp.withdraw()
        tp.overrideredirect(True)
        tp.attributes('-topmost', True)
        # The bubble is allowed to be hovered (see _sb_pointer_on), and nothing
        # in the rail learns when the pointer finally comes off it - so it has
        # to dismiss itself. A bubble that outlives its hover is the exact
        # fragment this rail used to litter the page with.
        tp.bind('<Leave>', lambda e: self._hide_sb_tooltip(force=True))
        self._sb_tooltip_lbl = tk.Label(
            tp,
            padx=9,
            pady=4,
            font=UITheme.F(10),
        )
        self._sb_tooltip_lbl.pack()
        self._sb_popups = [tp]
        return tp

    def _drop_sb_popups(self):
        """Destroy every tooltip popup (used when one cannot be trusted)."""
        for tp in getattr(self, '_sb_popups', []):
            try:
                tp.destroy()
            except Exception:
                pass
        self._sb_popups = []

    def _hide_sb_tooltip(self, widget=None, force: bool = False):
        """Withdraw the bubble once the pointer has really left its row.

        A repaint that re-places a CTk label makes Tk report a <Leave> for the
        widget the pointer is still sitting on - and hovering a row repaints it
        (icon and label change colour). Cancelling on that Leave is why the
        bubble never appeared at all while a rail row was hovered: the hover
        fired Enter, the repaint it caused fired Leave, and the pending show was
        cancelled 450ms before it was due. So a Leave only counts when the
        pointer is off the row the bubble belongs to.
        """
        owner = widget if widget is not None else getattr(self, '_sb_tip_owner', None)
        if not force and owner is not None and self._sb_pointer_on(owner):
            return
        self._sb_tip_owner = None
        # Cancel any pending delayed show when the mouse moves away (flicker fix).
        pending = getattr(self, '_sb_tooltip_after_id', None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
            self._sb_tooltip_after_id = None
        for tp in getattr(self, '_sb_popups', []):
            try:
                # Withdraw instead of destroy: creating a brand-new
                # borderless popup per Enter/Leave event is what produced
                # the transient black rectangles.
                tp.withdraw()
            except Exception:
                pass

    # -----------------
    # Color theme engine (Monkeytype-style)
    # -----------------
    def _map_color(self, color):
        """Translate a legacy hardcoded hex into the active palette."""
        try:
            role = LEGACY_HEX_ROLES.get(str(color).lower())
            if role:
                return self._palette.get(role, color)
        except Exception:
            pass
        return color

    # Semantic button roles: one accent per screen (primary), a neutral
    # secondary, danger for destructive actions — no per-widget color
    # improvisation. Maps widget option -> palette role.
    _BTN_ROLES = {
        "primary":   {"fg_color": "accent", "hover_color": "accent_hover"},
        "secondary": {"fg_color": "sidebar_active", "hover_color": "hover"},
        "danger":    {"fg_color": "danger", "hover_color": "danger_hover"},
        "success":   {"fg_color": "success", "hover_color": "success_hover"},
        "warning":   {"fg_color": "warning", "hover_color": "warning_hover"},
        "purple":    {"fg_color": "purple", "hover_color": "purple_hover"},
        "ghost":     {"hover_color": "hover"},
    }

    # --- Keyboard and pointer feedback ------------------------------------
    # CustomTkinter draws no focus ring of its own and has no pressed colour, so
    # both halves of "I did something" are missing: a keyboard user cannot see
    # where Tab is, and a mouse user sees nothing between press and release.
    # Neither needs per-widget code - one traversal list, one ring, one bind.

    def _collect_focusables(self) -> int:
        """List the controls Tab should visit, in build order, and bind the keys.

        Tk's own traversal walks CustomTkinter's internals, so the order is taken
        from the widget tree instead: the things a keyboard can actually operate,
        in the order the app built them, which is the order they read on screen.

        The rail rows lead the list because the rail is the leftmost column: a
        keyboard user has to be able to change page before they can use anything
        on a page. They are CTkFrames, which no traversal would ever stop on, so
        they are listed here and made focusable in ``_make_nav_row``.
        """
        wanted = (ctk.CTkButton, ctk.CTkEntry, ctk.CTkCheckBox, ctk.CTkSlider,
                  ctk.CTkOptionMenu, ctk.CTkComboBox, ctk.CTkRadioButton)
        # Only what is on screen. The pages are stacked with place(), so a
        # control on a page that is not showing is unmapped: Tk cannot route a
        # keypress to it, and Tab that lands on one shows a ring around something
        # the user cannot see. Page switches rebuild the list.
        rows = [r for r in getattr(self, "nav_buttons", {}).values()
                if r.winfo_ismapped()]
        controls = [w for w in self._iter_widgets()
                    if isinstance(w, wanted) and w.winfo_ismapped()]
        self._focusables = rows + controls
        self._focus_saved = None
        self._focus_index = -1
        self._press_saved = None
        self.bind("<Tab>", lambda _e: self._focus_step(1))
        self.bind("<Shift-Tab>", lambda _e: self._focus_step(-1))
        self.bind("<ISO_Left_Tab>", lambda _e: self._focus_step(-1))
        # A checkbox is operable from the keyboard the same way a button is, and
        # CustomTkinter binds no keys to it either.
        for w in self._focusables:
            toggle = getattr(w, "toggle", None)
            if not isinstance(w, ctk.CTkCheckBox) or toggle is None:
                continue
            try:
                w.bind("<Return>", lambda _e, t=toggle: t(), add="+")
                w.bind("<space>", lambda _e, t=toggle: t(), add="+")
            except Exception:
                pass
        # A press anywhere means the mouse is driving; the ring would only lie.
        self.bind("<Button-1>", lambda _e: self._set_focus_ring(None), add=True)
        self.bind("<FocusOut>", lambda _e: self._set_focus_ring(None))
        return len(self._focusables)

    @staticmethod
    def _focus_target(widget):
        """The widget that has to hold focus for *widget* to answer the keyboard.

        CustomTkinter's ``bind()`` puts the binding on the canvas and the labels
        *inside* a control, so focusing the control itself leaves the key
        bindings behind: Tab walked the ring round nicely and Enter did nothing.
        Several widgets also forward ``focus_set()`` to the same place. An entry
        wants focus on its own text widget either way, which is where the caret
        has to be.

        A rail row needs no exception. ``CTkFrame.bind`` forwards to the frame's
        own canvas, which is exactly what the ``_canvas`` branch returns - the
        generic path already puts focus where a row's Enter and space live.
        """
        for attr in ("_entry", "_canvas"):
            inner = getattr(widget, attr, None)
            if inner is not None:
                return inner
        return widget

    def _focus_step(self, delta: int) -> str:
        """Move the keyboard focus one control along and ring where it landed.

        The position is tracked here rather than read back from ``focus_get()``:
        several CustomTkinter widgets forward focus to an internal canvas, so the
        widget that ends up focused is often not the one on the list. The list is
        rebuilt as it goes, because a page switch can leave it holding controls
        that are no longer on screen.
        """
        widgets = []
        for w in getattr(self, "_focusables", []):
            try:
                if w.winfo_exists() and w.winfo_ismapped():
                    widgets.append(w)
            except Exception:
                continue
        if not widgets:
            return "break"
        index = (getattr(self, "_focus_index", -1) + delta) % len(widgets)
        target = widgets[index]
        try:
            self._focus_target(target).focus_set()
        except Exception:
            return "break"
        self._focus_index = index
        self._set_focus_ring(target)
        return "break"

    def _set_focus_ring(self, widget) -> None:
        """Ring *widget* in the accent, or clear the ring when given None.

        The border that was there before is saved and put back exactly: a ghost
        button had no border to begin with, and a filled one had the card's edge,
        so restoring anything else would leave a mark the mouse path never made.

        A rail row is handled apart from the rest: it is repainted from its own
        state machine on every hover and every page switch, so a border set here
        would be wiped by the next pointer move. The ring goes through that same
        repaint instead, and looks like what the rail already draws for the row
        that is selected.
        """
        self._restore_focus_ring()
        if widget is None:
            return
        if getattr(widget, "_nav_name", None):
            # Ring through the rail's repaint, but focus the same canvas the
            # row's key bindings were forwarded to (see _focus_target).
            self._sb_focus_name = widget._nav_name
            try:
                self._focus_target(widget).focus_set()
            except Exception:
                self._sb_focus_name = None
                return
            self._repaint_nav_rows()
            return
        pal = getattr(self, "_palette", {}) or {}
        try:
            self._focus_saved = (widget, widget.cget("border_width"),
                                 widget.cget("border_color"))
            widget.configure(border_width=UITheme.BORDER_W,
                             border_color=pal.get("accent",
                                                  UITheme.COLOR_PRIMARY))
        except Exception:
            self._focus_saved = None

    def _restore_focus_ring(self) -> None:
        if getattr(self, "_sb_focus_name", None):
            self._sb_focus_name = None
            try:
                self._repaint_nav_rows()
            except Exception:
                pass
        saved = getattr(self, "_focus_saved", None)
        self._focus_saved = None
        if not saved:
            return
        widget, width, color = saved
        try:
            widget.configure(border_width=width, border_color=color)
        except Exception:
            pass

    @staticmethod
    def _press_tint(fill: str) -> str:
        """A held-down version of *fill*: away from its own background."""
        try:
            dark = _rel_luminance(fill) < 0.45
        except Exception:
            dark = True
        return _mix(fill, "#000000", 0.20) if dark else _mix(fill, "#ffffff", 0.24)

    def _press_in(self, btn) -> None:
        """Darken a button for as long as it is held."""
        try:
            fill = str(btn.cget("fg_color") or "")
        except Exception:
            return
        if fill in ("", "transparent"):
            return          # a ghost button has no fill to deepen
        try:
            self._press_saved = (btn, fill)
            btn.configure(fg_color=self._press_tint(fill))
        except Exception:
            self._press_saved = None

    def _press_out(self, btn) -> None:
        """Put the button's own fill back."""
        saved = getattr(self, "_press_saved", None)
        if not saved or saved[0] is not btn:
            return
        try:
            btn.configure(fg_color=saved[1])
        except Exception:
            pass
        self._press_saved = None

    def _button_icon(self, name: str, ink: str, px: int = 18):
        """A CTkImage of drawn mark *name* in *ink*, for a button's ``image=``.

        Both appearances are rendered, because CustomTkinter picks between them
        by the app's appearance mode and the palette owns that mode. Rendering
        only the current one would leave a button with a dark-on-dark icon the
        moment the light palettes came round.
        """
        cache = getattr(self, "_icon_cache", None)
        if cache is None:
            cache = self._icon_cache = {}
        dark_bg = ctk.get_appearance_mode().lower() != "light"
        other = _on_color("#ffffff", "#0d1117", "#f5f7fa") if dark_bg \
            else _on_color("#101418", "#f2f4f8", "#0d1117")
        key = (name, ink, other, int(px))
        hit = cache.get(key)
        if hit is not None:
            return hit
        light = _render_icon_image(name, ink, px)
        dark = _render_icon_image(name, other, px)
        # At least one has to have rendered, and whichever did stands in for
        # the other: a button whose icon is invisible in one appearance is
        # better than one that has no icon at all.
        if light is None:
            light = dark
        if dark is None:
            dark = light
        if light is None:
            return None
        try:
            image = ctk.CTkImage(light_image=light, dark_image=dark,
                                 size=(int(px), int(px)))
        except Exception:
            logger.debug("Wrapping icon %r in a CTkImage failed", name,
                         exc_info=True)
            return None
        cache[key] = image
        return image

    def _refresh_button_icons(self) -> int:
        """Re-draw every button icon in its button's new label ink.

        A palette switch moves a button's fill, so its label colour can flip
        between the palette's text tone and its background tone (a yellow
        accent wants dark letters). The icon has to follow that decision, not
        the theme it happened to be built under. The cache is keyed by ink, so
        entries survive a switch and only genuinely-new inks re-render.
        """
        done = 0
        for widget in self._iter_widgets():
            name = getattr(widget, "_icon_name", "")
            if not name or not isinstance(widget, ctk.CTkButton):
                continue
            try:
                ink = str(widget.cget("text_color") or "")
                if not ink.startswith("#"):
                    continue
                image = self._button_icon(name, ink)
                if image is None:
                    continue
                widget.configure(image=image)
                done += 1
            except Exception:
                logger.debug("Repainting a button icon failed", exc_info=True)
        return done

    def _style_button(self, btn, role: str, bordered: bool = True, icon: str = ""):
        """Paint *btn* with the semantic palette *role*.

        Build-time colors come from the active palette instead of
        hardcoded hexes, the label color is chosen for WCAG contrast
        against the fill (``_on_color``), and the option->role mapping is
        remembered on the widget (``_theme_roles``) so every later theme
        switch repaints it too.

        Shape is part of the recipe too: every button is lifted to the
        shared control radius (a call site may ask for a rounder chip,
        never a boxier one), and ghost buttons get the hairline outline
        the dialogs use for secondary actions. Pass ``bordered=False`` for
        a ghost control that already sits inside another outlined widget.

        ``icon`` names a mark in ``_icon_shapes``. It is drawn in whatever
        ink the label ended up with, so an icon can never drift away from
        its own button's contrast, and it is remembered for the repaint that
        a theme switch does.
        """
        pal = getattr(self, "_palette", {}) or {}
        roles = self._BTN_ROLES.get(role)
        if not roles:
            return btn
        # Values are mixed: hex colours plus the int corner_radius/border_width.
        colors: dict[str, Any] = {}
        for opt, role_name in roles.items():
            val = pal.get(role_name)
            if val:
                colors[opt] = val
        if role == "ghost":
            colors.setdefault("fg_color", "transparent")
        fill = colors.get("fg_color", "transparent")
        if fill == "transparent":
            colors["text_color"] = pal.get("text", "#ecf0f1")
        else:
            colors["text_color"] = _on_color(
                fill, pal.get("text", "#ecf0f1"), pal.get("bg", "#1e1e24"))
        if icon:
            image = self._button_icon(icon, colors["text_color"])
            if image is not None:
                colors["image"] = image
                colors["compound"] = "left"
                setattr(btn, "_icon_name", icon)
                setattr(btn, "_icon_ink", "text_color")
            else:
                # No Pillow: a label with a missing picture in it would read as
                # a rendering fault, so the control keeps its text alone.
                setattr(btn, "_icon_name", "")
        # Curved ends everywhere: a call site may ask for something rounder
        # (a pill chip) but never boxier than the shared control radius.
        try:
            if int(btn.cget("corner_radius") or 0) < UITheme.RADIUS_MD:
                colors["corner_radius"] = UITheme.RADIUS_MD
        except Exception:
            colors["corner_radius"] = UITheme.RADIUS_MD
        if role == "ghost":
            # Ghost means outlined — the dialog recipe. Filled buttons
            # already separate themselves from the surface by their fill.
            colors["border_width"] = UITheme.BORDER_W if bordered else 0
            if bordered:
                colors["border_color"] = pal.get("hover", "#34495e")
        try:
            btn.configure(**colors)
        except Exception:
            logger.debug("Styling button as %r failed", role, exc_info=True)
        try:
            tag = dict(getattr(btn, "_theme_roles", None) or {})
            tag.update(roles)
            tag["text_color"] = (
                "text" if colors.get("text_color") == pal.get("text") else "bg")
            if colors.get("border_color"):
                tag["border_color"] = "hover"
            setattr(btn, "_theme_roles", tag)
        except Exception:
            pass
        # Press feedback. CTk gives a button a hover_color but no pressed color,
        # so a click used to show nothing at all until the pointer came back off
        # it. These go on additively so CTk's own click handling still runs.
        try:
            btn.bind("<ButtonPress-1>",
                     lambda _e, b=btn: self._press_in(b), add="+")
            btn.bind("<ButtonRelease-1>",
                     lambda _e, b=btn: self._press_out(b), add="+")
            btn.bind("<Leave>", lambda _e, b=btn: self._press_out(b), add="+")
            # ... and CustomTkinter binds no keys at all, so a button that has
            # been tabbed to cannot be pressed from the keyboard. Enter and space
            # are what every other control answers to, and invoke() is the same
            # path a click takes.
            btn.bind("<Return>", lambda _e, b=btn: b.invoke(), add="+")
            btn.bind("<KP_Enter>", lambda _e, b=btn: b.invoke(), add="+")
            btn.bind("<space>", lambda _e, b=btn: b.invoke(), add="+")
        except Exception:
            pass
        return btn

    def _style_option_menu(self, menu):
        """Theme a CTkOptionMenu: neutral panel + accent select button."""
        pal = getattr(self, "_palette", {}) or {}
        fill = pal.get("sidebar_active", "#2c3e50")
        text = _on_color(
            fill, pal.get("text", "#ecf0f1"), pal.get("bg", "#1e1e24"))
        colors = {
            "fg_color": fill,
            "button_color": pal.get("accent", "#3498db"),
            "button_hover_color": pal.get("accent_hover", "#2980b9"),
            "text_color": text,
            "corner_radius": UITheme.RADIUS_FIELD,
            "border_width": UITheme.BORDER_W,
            "border_color": pal.get("hover", "#34495e"),
        }
        try:
            menu.configure(**colors)
        except Exception:
            logger.debug("Styling option menu failed", exc_info=True)
        try:
            setattr(menu, "_theme_roles", {
                "fg_color": "sidebar_active",
                "button_color": "accent",
                "button_hover_color": "accent_hover",
                "border_color": "hover",
                "text_color": "text" if text == pal.get("text") else "bg",
            })
        except Exception:
            pass
        return menu

    # The 12 roles the user picks, grouped as they are displayed. Every entry is
    # editable: CUSTOM_THEME_ROLES is the authority for what a custom palette
    # accepts, and a role missing from this table simply keeps the preset value
    # it was seeded from rather than breaking anything.
    _CUSTOM_ROLE_GROUPS = (
        ("Background", ('bg', 'surface', 'sidebar')),
        ("Text", ('text', 'sub', 'accent')),
        ("Status", ('success', 'warning', 'danger', 'purple')),
    )

    # Palettes offered in the "Start from" menu. Every curated palette is
    # listed, minus the custom entry itself.
    _CUSTOM_START_THEMES = (
        "TuneLab Dark", "Serika Dark", "Midnight", "Moon", "Nord",
        "Gruvbox Dark", "Dracula", "Tokyo Night", "Catppuccin Mocha",
        "Metropolis", "Velvet Purple", "Pure Purple", "Laserbeam", "Crimson",
        "Horizon", "Botanical", "Monokai", "Serika Light", "Solarized Light",
        "Gruvbox Light", "Soft Lilac Light",
    )

    def _on_custom_start(self, theme_name: str) -> None:
        self.start_custom_from(theme_name)

    def _commit_custom_hex(self, role: str):
        """Apply whatever is in a role's hex entry, or restore it if invalid."""
        row = (getattr(self, "_custom_swatch_rows", None) or {}).get(role)
        if not row:
            return
        entry = row[2]
        typed = entry.get().strip()
        if not typed:
            self._refresh_custom_theme_ui()
            return
        if not self.set_custom_role(role, typed):
            # Refuse the value but say so: silently reverting looks like the
            # keyboard ate the entry.
            self.show_toast(
                "“%s” is not a colour. Use #rgb or #rrggbb." % typed, "warning")

    def _on_custom_mode(self, mode: str) -> None:
        # Accepts the displayed capitalisation as well as the stored form, so a
        # call from a test or the reset button does not have to know which.
        mode = str(mode or "").strip().lower()
        if mode in ("light", "dark"):
            self._custom_mode = mode
            self._apply_custom_palette()

    def _refresh_custom_theme_ui(self) -> None:
        """Sync swatches, hex entries and the contrast report to the palette."""
        rows = getattr(self, "_custom_swatch_rows", None)
        if not rows:
            return
        pal = custom_palette(self._custom_roles, self._custom_mode)
        for role, (label, swatch, entry) in rows.items():
            value = pal.get(role, "#000000")
            try:
                swatch.configure(fg_color=value, hover_color=value,
                                 text_color=_on_color(value, "#ffffff",
                                                      "#000000"))
                # The swatch shows the role's own colour, which is the entire
                # point of it, so it must NOT join the role walk and be
                # repainted with something else.
                setattr(swatch, "_theme_roles", {})
            except Exception:
                logger.debug("Swatch refresh failed for %r", role, exc_info=True)
            setattr(label, "_theme_roles", {"text_color": "sub"})
            try:
                if entry.get().strip().lower() != value:
                    entry.delete(0, "end")
                    entry.insert(0, value)
            except Exception:
                pass
        try:
            self._custom_mode_var.set(self._custom_mode.capitalize())
        except Exception:
            pass

    def _settings_card(self, parent, title):
        """Bordered card with a section header.

        The settings pages group their controls into these instead of one
        flat undifferentiated list. Colors come from the palette and the
        option->role pairs are tagged so theme switches repaint the card.
        """
        pal = getattr(self, "_palette", {}) or {}
        card = ctk.CTkFrame(
            parent,
            corner_radius=UITheme.RADIUS_LG,
            fg_color=pal.get("sidebar", "#1b2532"),
            border_width=1,
            border_color=pal.get("hover", "#34495e"),
        )
        setattr(card, "_theme_roles",
                {"fg_color": "sidebar", "border_color": "hover"})
        hdr = ctk.CTkLabel(
            card, text=title, font=UITheme.F(13, "bold"), anchor="w",
            text_color=pal.get("text", "#ecf0f1"),
        )
        hdr.pack(fill="x", padx=16, pady=(12, 4))
        setattr(hdr, "_theme_roles", {"text_color": "text"})
        return card

    def _iter_widgets(self, root=None):
        if root is None:
            root = self
        for child in root.winfo_children():
            yield child
            yield from self._iter_widgets(child)

    def _style_form_controls(self, pal=None):
        """Paint every checkbox, slider and progress bar from the palette.

        Walks the live tree by *type* instead of a list of attribute names.
        The name lists this replaces had gone stale: they still named four
        checkboxes that no longer exist and missed the two the rail settings
        card adds, so those two kept CustomTkinter's built-in blue in every
        one of the 21 palettes.

        The options a call site never sets are the other half of the problem:
        CTk hands out its own theme colors for those, and ``cget()`` returns
        them as *tuples*, which the role walk skips because it only remaps
        strings. Nothing else would ever have recolored them, so a slider's
        track and a progress bar's trough stayed CTk's grays and a slider's
        knob hovered CTk's blue whatever the palette said.
        """
        pal = pal or getattr(self, "_palette", {}) or {}
        accent = pal.get("accent", UITheme.COLOR_PRIMARY)
        accent_hover = pal.get("accent_hover", "#2980b9")
        text = pal.get("text", "#ecf0f1")
        # The unchecked ring has to be *seen*: the palette's hover tone is a
        # surface step, too close to the page on the light themes, so the
        # ring uses the muted text tone instead.
        edge = pal.get("sub", UITheme.COLOR_GRAY)
        # Tracks and troughs are the inactive half of a control, so they take
        # the raised-surface tone (same one the cards' hairlines use).
        trough = pal.get("hover", UITheme.SIDEBAR_HOVER)
        # The checkmark is drawn *on* the accent, so it is chosen for contrast
        # (a palette text tone would vanish into a yellow or cyan accent).
        on_accent = _on_color(accent, text, pal.get("bg", "#1e1e24"))
        recipes = (
            (ctk.CTkCheckBox, {"fg_color": accent, "hover_color": accent_hover,
                               "border_color": edge,
                               "checkmark_color": on_accent, "text_color": text}),
            (ctk.CTkSlider, {"fg_color": trough, "progress_color": accent,
                             "button_color": text,
                             "button_hover_color": accent_hover}),
            (ctk.CTkProgressBar, {"fg_color": trough, "progress_color": accent,
                                  "border_color": trough}),
        )
        done = 0
        for widget in self._iter_widgets():
            for cls, colors in recipes:
                if not isinstance(widget, cls):
                    continue
                try:
                    widget.configure(**colors)
                    done += 1
                except Exception:
                    logger.debug("Styling a %s failed", cls.__name__,
                                 exc_info=True)
                break
        return done

    def _style_composites(self, pal=None) -> int:
        """Repaint the parts of composite widgets that no theme walk reaches.

        Two CustomTkinter widgets keep their colour inside a child the option
        walk cannot see, which is why both went stale:

        * ``CTkScrollableFrame`` paints a plain ``tkinter.Canvas`` behind its
          contents and resolves that canvas's colour once, when the frame is
          built - and afterwards only inside its own ``configure()`` or when the
          *appearance mode* flips. Switching between two dark palettes changes
          neither, so the Performance page's scroll well went on showing the
          background of whichever palette was live at startup while the cards
          on top of it moved to the new one.
        * ``CTkOptionMenu`` opens a ``tkinter.Menu``, which is not a CTk widget
          and so never inherits the menu button's palette: the dropdown list was
          CustomTkinter's grey in all 21 themes.

        Painted by type, the way ``_style_form_controls`` does, so a widget
        built later is covered without being named here.
        """
        pal = pal or getattr(self, "_palette", {}) or {}
        trough = pal.get("hover", UITheme.SIDEBAR_HOVER)
        # The handle is the part the user aims at, so it takes the muted text
        # tone rather than another surface step the trough would swallow.
        handle = pal.get("sub", UITheme.COLOR_GRAY)
        accent = pal.get("accent", UITheme.COLOR_PRIMARY)
        panel = pal.get("sidebar_active", UITheme.SIDEBAR_ACTIVE)
        panel_text = _on_color(panel, pal.get("text", "#ecf0f1"),
                               pal.get("bg", "#1e1e24"))
        done = 0
        for widget in self._iter_widgets():
            try:
                if isinstance(widget, ctk.CTkScrollableFrame):
                    # Resolve the well's own fill through its *remembered role*
                    # first. Its fg_color is a concrete hex captured when the
                    # frame was built, so keeping that literal is exactly the
                    # staleness being fixed; the role is what says "this is the
                    # bg tone", and the palette is what says what that is now.
                    roles = getattr(widget, "_theme_roles", None) or {}
                    fill = pal.get(roles.get("fg_color") or "")
                    if not fill:
                        try:
                            fg = widget.cget("fg_color")
                        except Exception:
                            fg = None
                        # A well that says "transparent" is showing whatever card
                        # it sits on - cards use the sidebar tone, so the canvas
                        # must match it or its square corners show behind curved
                        # card edges when the theme switches.
                        fill = (fg if isinstance(fg, str)
                                and fg.lower() not in ("transparent", "")
                                else pal.get("surface", UITheme.SURFACE_BG))
                    widget._parent_canvas.configure(bg=fill)
                    # The frame itself is a bare tkinter.Frame; CTk repaints it
                    # in the same two lines it uses internally.
                    tk.Frame.configure(widget, bg=fill)
                    bar = getattr(widget, "_scrollbar", None)
                    if bar is not None:
                        hide_scrollbar_until_hover(bar, fill, handle, accent)
                    done += 1
                elif isinstance(widget, ctk.CTkOptionMenu):
                    dropdown = getattr(widget, "_dropdown_menu", None)
                    if dropdown is None:
                        continue
                    dropdown.configure(fg_color=panel, hover_color=trough,
                                       text_color=panel_text)
                    done += 1
            except Exception:
                logger.debug("Styling a composite widget failed", exc_info=True)
        return done

    # --- Custom palette editing ------------------------------------------------
    # Editing writes straight into COLOR_THEMES[CUSTOM_THEME_NAME] and re-runs
    # the normal apply path, so a hand-built palette is repainted by exactly the
    # same code a curated one is. Nothing here touches a widget's colour option
    # directly, which is what keeps the role walk authoritative.

    def _apply_custom_palette(self, persist: bool = True):
        """Rebuild, save and activate the custom palette."""
        pal = custom_palette(self._custom_roles, self._custom_mode)
        COLOR_THEMES[CUSTOM_THEME_NAME] = pal
        if persist:
            self._set_pref("custom_theme_roles", dict(self._custom_roles))
            self._set_pref("custom_theme_mode", self._custom_mode)
        self.apply_color_theme(CUSTOM_THEME_NAME)
        self._refresh_custom_theme_ui()
        return pal

    def set_custom_role(self, role: str, value) -> bool:
        """Set one role of the custom palette. False if *value* is not a colour."""
        if role not in CUSTOM_THEME_ROLES:
            return False
        norm = _normalize_hex(value)
        if norm is None:
            return False
        self._custom_roles = dict(self._custom_roles)
        self._custom_roles[role] = norm
        self._apply_custom_palette()
        return True

    def reset_custom_palette(self, mode: Optional[str] = None) -> None:
        """Drop every custom role and fall back to the built-in starting point."""
        self._custom_roles = {}
        if mode in ("light", "dark"):
            self._custom_mode = mode
        self._apply_custom_palette()

    def start_custom_from(self, theme_name: str) -> None:
        """Seed the custom roles from a curated palette, so editing starts sane.

        Copying the 12 roles a user can edit is enough: the hovers come out of
        the derivation, and they land close to the source palette's own because
        that palette moves each one toward its bg by a similar step.
        """
        src = COLOR_THEMES.get(theme_name)
        if not src or theme_name == CUSTOM_THEME_NAME:
            return
        self._custom_roles = {
            role: src[role] for role in CUSTOM_THEME_ROLES if role in src
        }
        self._custom_mode = src.get("mode") or "dark"
        self._apply_custom_palette()

    def apply_color_theme(self, name):
        """Apply a named color theme to the entire UI and remember it."""
        pal = COLOR_THEMES.get(name)
        if not pal:
            return
        self._color_theme_name = name
        self._palette = dict(pal)
        self._set_pref('color_theme', name)

        # Keep the dropdown label in sync when switched via swatches/shortcut.
        try:
            if hasattr(self, 'theme_menu'):
                self.theme_menu.set(name)
        except Exception:
            pass

        # Match Light/Dark appearance so entries/menus follow the palette —
        # the palette owns the mode now (the Theme Mode dropdown is gone).
        try:
            ctk.set_appearance_mode('Light' if pal.get('mode') == 'light' else 'Dark')
        except Exception:
            pass

        # Window background
        try:
            self.configure(fg_color=pal['bg'])
        except Exception:
            pass
        try:
            self._window_bg = pal['bg']
            self.configure(bg=pal['bg'])
        except Exception:
            pass

        # Main container background
        try:
            self.main_container.configure(fg_color=pal['bg'])
        except Exception:
            pass

        # Walk every widget and remap any themed colors by remembered role.
        # The first pass discovers roles from legacy hardcoded hexes; afterwards
        # each widget remembers which role each option holds, so switching
        # between themes keeps working even though old values are long gone.
        # Fast path: the theme registry (populated per page at build time by
        # _register_themed_widgets) already holds (widget, roles) pairs, so a
        # switch configures only those options instead of cget()ing ~10 options
        # on every widget and comparing each one.
        registry = list(getattr(self, "_themed_registry", None) or [])
        if registry:
            for w, roles in registry:
                try:
                    alive = bool(w.winfo_exists())
                except Exception:
                    continue
                if not alive or not roles:
                    continue
                for opt, role in roles.items():
                    new_val = pal.get(role)
                    if not new_val:
                        continue
                    try:
                        cur = w.cget(opt)
                    except Exception:
                        continue
                    if not isinstance(cur, str) or cur.lower() in ('transparent', ''):
                        continue
                    if str(new_val).lower() == cur.lower():
                        continue
                    try:
                        w.configure(**{opt: new_val})
                    except Exception:
                        pass
        else:
            roles_seen = ('fg_color', 'hover_color', 'border_color',
                          'text_color', 'progress_color', 'button_color',
                          'button_hover_color', 'label_fg_color',
                          'label_text_color')
            for w in self._iter_widgets():
                try:
                    roles = getattr(w, '_theme_roles', None)
                    if roles is None:
                        roles = {}
                        setattr(w, '_theme_roles', roles)
                except Exception:
                    continue
                for opt in roles_seen:
                    try:
                        cur = w.cget(opt)
                    except Exception:
                        continue
                    if not isinstance(cur, str) or cur.lower() in ('transparent', ''):
                        continue
                    role = roles.get(opt)
                    if role is None:
                        role = LEGACY_HEX_ROLES.get(cur.lower())
                        if role is None:
                            continue
                        roles[opt] = role
                    new_val = pal.get(role)
                    if not new_val:
                        continue
                    # Skip the configure when the widget already holds this exact
                    # colour. CTk re-runs its whole draw pipeline on every
                    # configure() - canvas item create/delete plus a font
                    # re-measure - and the walk below issues one per themed option
                    # per widget. On startup, where the widgets were just built from
                    # this very palette, 221 of the 223 configures that pass through
                    # here changed nothing, so they were 221 full redraws plus the
                    # 542-widget cget() sweep to discover that. Comparing first
                    # keeps theme *switches* correct (those genuinely differ) while
                    # making the startup pass nearly free.
                    if str(new_val).lower() == cur.lower():
                        continue
                    try:
                        w.configure(**{opt: new_val})
                    except Exception:
                        pass

        # Structural pieces that don't use legacy hexes:
        try:
            self.nav_indicator.configure(fg_color=pal['accent'])
        except Exception:
            pass
        # Queue rows are CTk widgets now, but their palette-derived colors
        # are plain values the role walk can't discover — re-feed them
        # explicitly so a theme switch repaints panel, rows and selection.
        try:
            qrows = getattr(self, "queue_rows", None)
            if qrows is not None:
                qrows.configure(
                    bg=pal.get('bg', '#2c3e50'),
                    fg=pal.get('text', '#ecf0f1'),
                    selectbackground=pal.get('accent', '#3498db'),
                    selectforeground=_on_color(
                        pal.get('accent', '#3498db'),
                        pal.get('text', '#ecf0f1'), pal.get('bg', '#1e1e24')),
                )
        except Exception:
            pass
        # Form controls (checkboxes, sliders, progress bars) are painted from
        # the palette by *type*, not by name: the name lists that used to live
        # here had gone stale — they still named four checkboxes that no
        # longer exist and missed the two the rail settings card adds — and
        # they never touched the options a call site leaves unset (a track, a
        # trough, a checkmark), which is where CTk's own colors leaked in.
        # Every part of a control is set in the one pass below.
        self._style_form_controls(pal)
        # Scroll wells and option-menu dropdowns keep their colour in children
        # the role walk above has no option for (a bare Canvas and a
        # tkinter.Menu), so they are repainted separately - without this the
        # Performance page's background stayed on the old palette.
        self._style_composites(pal)
        # Button icons are pictures, so they do not re-tint themselves the way a
        # colour option does: each one is redrawn in whatever ink its button's
        # new label colour resolved to.
        self._refresh_button_icons()

        # Header + rail text accents
        try:
            self.title_lbl.configure(text_color=pal['text'])
        except Exception:
            pass
        # The rail derives every piece of it (chips, badges, brand tile,
        # footer, section headers) from the palette, so a theme switch is just
        # a repaint - this used to hand-tune two labels and leave the rest of
        # the rail on the previous theme's colors.
        self._repaint_nav_rows()

        # Swatch selection ring: the clickable swatch dots are gone (theme
        # picking lives in the dropdown now), so there is nothing left to ring.

    def clear_download_cache(self):
        # Run in a worker thread because filesystem cleanup can be slow
        def worker():
            try:
                # MessageBoxes must appear on the main thread; ask the user
                # there and block the worker until they answer.
                confirm_event = threading.Event()
                confirm_result = {"val": False}

                def _ask():
                    confirm_result["val"] = messagebox.askyesno(
                        "Clear Download Cache",
                        "This will try to remove yt-dlp cache and app temp files.\n\nProceed?",
                    )
                    confirm_event.set()

                self.after(0, _ask)  # marshalled to the main thread
                confirm_event.wait(timeout=120)
                if not confirm_result["val"]:
                    return

                self.after(0, lambda: self.clear_cache_btn.configure(state="disabled"))

                result = downloader.clear_app_cache()
                total = int(result.get("total_removed", 0))
                removed_paths = result.get("removed_paths", [])
                freed_bytes = int(result.get("total_freed_bytes", 0) or 0)

                def _fmt_bytes(n: int) -> str:
                    units = ["B", "KB", "MB", "GB", "TB"]
                    f = float(n)
                    for u in units:
                        if f < 1024 or u == units[-1]:
                            return f"{f:.2f} {u}" if u != "B" else f"{int(f)} {u}"
                        f /= 1024
                    return f"{n} B"

                msg = f"Cleared cache. Removed {total} item(s) (~{_fmt_bytes(freed_bytes)})."

                # Keep messagebox short; only show first few paths if any
                if removed_paths:
                    preview = ", ".join(removed_paths[:5])
                    if len(removed_paths) > 5:
                        preview += f" (+{len(removed_paths)-5} more)"
                    msg += f"\n\nExamples: {preview}"

                self.after(0, lambda: self.show_toast(msg, "success", duration=6000))
                self.after(0, lambda: self.update_dl_status("Cache cleared.", "#2ecc71"))
            except Exception as e:
                # Same late-binding trap as the yt-dlp updater: `e` is gone by
                # the time this queued lambda runs, so str(e) raised NameError
                # and a failed cache clear reported nothing at all.
                err_text = str(e)
                self.after(0, lambda: self._show_error_dialog("Cache Clear Error", err_text))
            finally:
                self.after(0, lambda: self.clear_cache_btn.configure(state="normal"))

        self._start_worker(worker)

    def play_preview(self):
        if not self.studio_file_path:
            self.show_toast("Please load an audio file first.", "warning")
            return
        if _lazy_import_sounddevice() is None:
            self._show_error_dialog("Module Missing", "sounddevice package missing.")
            return
        self.btn_play.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        # Read widget values on the main thread; playback_worker must not touch Tk.
        _path = self.studio_file_path
        _speed = float(self.sp_sld.get())
        _reverb = float(self.rv_sld.get())
        self._start_worker(lambda: self.playback_worker(_path, _speed, _reverb))

    def playback_worker(self, path, speed, reverb):
        try:
            _sd = _lazy_import_sounddevice()
            if _sd is None:
                raise RuntimeError("The 'sounddevice' package is not installed. Please install it in your environment using:\n\n    pip install sounddevice")
            
            audio, sr = downloader.process_studio_dsp(path, speed, reverb)
            if audio is not None and sr is not None:
                _sd.play(audio.T, sr)
                try:
                    _sd.wait()
                except Exception:
                    logger.debug("sounddevice playback wait interrupted", exc_info=True)
                self.after(0, self.reset_studio_buttons)
            else:
                self.after(0, self.reset_studio_buttons)
        except RuntimeError as e:
            self.after(0, lambda err=e: self._show_error_dialog("Missing Dependency", str(err)))
            self.after(0, self.reset_studio_buttons)
        except Exception as e:
            self.after(0, lambda err=e: self._show_error_dialog("Playback Error", f"Could not play preview:\n{err}"))
            self.after(0, self.reset_studio_buttons)

    def stop_preview(self):
        _sd = _lazy_import_sounddevice()
        if _sd:
            try:
                _sd.stop()
            except Exception:
                logger.debug("sounddevice stop raised", exc_info=True)
        self.reset_studio_buttons()

    def reset_studio_buttons(self):
        self.after(0, lambda: self.btn_play.configure(state="normal"))
        self.after(0, lambda: self.btn_stop.configure(state="disabled"))

    def update_studio_progress(self, value):
        self.after(0, lambda: self.studio_progress_bar.set(min(max(value, 0.0), 1.0)))


def _setup_logging() -> None:
    """Route all app logs to %TEMP%/tunelab.log plus the console.

    Safe to call more than once: adding a handler is idempotent because we
    guard against duplicate handlers on the root logger.
    """
    log_path = os.path.join(tempfile.gettempdir(), "tunelab.log")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == os.path.abspath(log_path)
               for h in root.handlers):
        try:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except Exception:
            pass  # Non-writable TEMP etc. — fall back to console only.
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)


if __name__ == "__main__":
    # Kept so `python ui.py` and the PyInstaller entry script both still start
    # the app. The startup logic itself moved to main.py; see the note there
    # about why this indirection exists.
    import main

    _setup_logging()
    main.run(UniversalAudioStudio)


