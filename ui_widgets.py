"""Themed widgets and app methods lifted out of ui.py.

Two things live here, both moved to keep ui.py under the 6000-line guard the
module-split tests enforce:

* ``_QueueRowList`` - the queue's themed stand-in for the old raw tk.Listbox.
* ``build_update_banner`` - the inline update offer row.
* ``UiSplitsMixin`` - app methods that are self-contained (own dialogs and
  workers, no page-build state) and so moved verbatim: the self-update flow,
  the custom-colours card builder and the studio export worker. They stay
  methods - the mixin is mixed into UniversalAudioStudio - so every call site
  and command= reference in ui.py resolves unchanged.
"""
import logging
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, cast

import customtkinter as ctk

import downloader
from ui_theme import UITheme, _on_color, custom_palette

logger = logging.getLogger(__name__)


def _shorten_release_notes(body, limit=400):
    """Trim release notes for the banner expander; the full text stays.

    Keeps whole lines under *limit* characters and marks the cut, so a long
    changelog shows its headline items without pushing the banner down the
    page. The expander still shows the untrimmed body on demand.
    """
    text = str(body or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0].strip()
    if not cut:
        cut = text[:limit].strip()
    return cut + "\n... (full notes on the Release page)"


def build_update_banner(parent, palette, local_ver: str, remote_ver: str,
                        on_accept=None, on_later=None, on_skip=None,
                        release_notes="") -> tuple:
    """Fill *parent* (a frame) with the in-UI update offer. Returns its buttons.

    Lives here rather than on the app because it is widget construction with no
    app state in it: given a parent and a palette it makes a row of label and
    two buttons, and hands the caller the widgets so it can wire the commands
    and restyle them however the rest of the app does.

    Why a banner and not a modal: an "update available" dialog interrupts
    whatever the user was doing to ask a question they did not raise, and the
    answer only mattered because the question was a button. Inline, the same
    choice waits without blocking - someone mid-download can finish first.

    The text states only what is always true: installing closes the app and
    relaunches it. Whether Windows shows an admin prompt depends on where the
    app is installed (per-user installs need none), and the confirmation
    dialog the button leads to spells that out for this machine.

    *on_skip* adds a third "Skip this version" answer: declining a
    version should silence it until a newer one ships, not re-ask
    every launch. *release_notes* feeds an inline "What's new"
    expander so the user is not asked to update blind.
    """
    body = ctk.CTkFrame(parent, fg_color="transparent")
    accent = palette.get("accent", UITheme.COLOR_PRIMARY)

    ctk.CTkLabel(body, text="↑", font=UITheme.F(14, "bold"),
                 text_color=accent, width=18).pack(side="left", padx=(0, 6))

    # Packed, like every other widget here. When this builder moved out
    # of ui.py the frame that holds the banner lost its pack() call and the
    # offer silently rendered as an empty strip.
    body.pack(fill="x")

    ctk.CTkLabel(
        body,
        text=f"Update available: {local_ver} → {remote_ver}. Installing "
             f"closes the app and relaunches it.",
        font=UITheme.F(11), anchor="w", justify="left",
        wraplength=520,
        text_color=palette.get("text", "#ecf0f1"),
    ).pack(side="left", fill="x", expand=True, padx=(0, 8))

    later = ctk.CTkButton(body, text="Later", width=70,
                          command=on_later or (lambda: None))
    later.pack(side="right", padx=(8, 0))

    skip = None
    if on_skip is not None:
        skip = ctk.CTkButton(body, text="Skip this version", width=130,
                             command=on_skip)
        skip.pack(side="right", padx=(8, 0))

    now = ctk.CTkButton(body, text="Update now", width=110,
                        command=on_accept or (lambda: None))
    now.pack(side="right")

    if str(release_notes or "").strip():
        try:
            notes_box = ctk.CTkFrame(body, fg_color="transparent")
            notes_box.pack(side="bottom", fill="x", padx=(24, 0), pady=(6, 0))
            full = str(release_notes).strip()
            preview = _shorten_release_notes(full)
            notes_lbl = ctk.CTkLabel(
                notes_box, text=preview, font=UITheme.F(10),
                anchor="w", justify="left",
                text_color=palette.get("sub", "#95a5a6"))
            notes_lbl.pack(side="top", anchor="w", fill="x")

            state = {"open": False}

            def _toggle():
                state["open"] = not state["open"]
                if state["open"]:
                    notes_lbl.configure(text=full)
                    notes_btn.configure(text="Hide what\u2019s new \u25b2")
                else:
                    notes_lbl.configure(text=preview)
                    notes_btn.configure(text="What\u2019s new \u25bc")

            notes_btn = ctk.CTkButton(
                notes_box, text="What\u2019s new \u25bc", width=130, height=22,
                font=UITheme.F(10), command=_toggle)
            notes_btn.pack(side="top", anchor="w", pady=(4, 0))
        except Exception:
            pass  # Notes are a nicety; never lose the offer over them.

    if skip is not None:
        return now, later, skip
    return now, later


def hide_scrollbar_until_hover(bar, fill: str, handle: str, accent: str) -> None:
    """Keep a CTkScrollbar permanently invisible while staying functional.

    The scrollbar keeps its grid cell and all bindings so wheel scrolling
    (bound to the canvas by CustomTkinter) keeps working, but the bar and
    its handle are painted in the well's fill colour so they are never
    visible - no hover reveal, no handle, nothing.

    Nothing is unbound and no geometry changes: the widget keeps its grid
    cell and all its bindings, so it still scrolls while invisible - only
    the pixels are withheld.

    The colours are cached on the bar so a later theme repaint refreshes
    them. Lives here rather than on the app because it is widget styling
    with no app state in it.
    """
    try:
        bar.configure(fg_color=fill, button_color=fill,
                      button_hover_color=handle)
        setattr(bar, "_sb_fill", fill)
        setattr(bar, "_sb_handle", handle)
        setattr(bar, "_sb_accent", accent)

        def _show(_event=None):
            try:
                bar.configure(button_color=getattr(bar, "_sb_handle", handle))
            except Exception:
                pass

        def _hide(_event=None):
            try:
                bar.configure(button_color=getattr(bar, "_sb_fill", fill))
            except Exception:
                pass

        setattr(bar, "_sb_hover_handlers", (_show, _hide))

        if not getattr(bar, "_sb_bound", False):
            bar._canvas.bind("<Enter>", _show, add="+")
            bar._canvas.bind("<Leave>", _hide, add="+")
            bar._sb_bound = True
    except Exception:
        pass


class _QueueRowList(ctk.CTkScrollableFrame):
    """Themed stand-in for the queue's raw ``tk.Listbox``.

    Speaks the small subset of the Listbox API that
    ``_rebuild_queue_list`` and friends use (``size``/``insert``/
    ``delete``/``get``/``itemconfig``/``curselection``), so the refresh
    logic — in-place row updates instead of a full rebuild on every
    progress tick — is unchanged. Rows are CTk labels, so they follow the
    active palette like every other widget; the old tk.Listbox sat
    entirely outside the theme walker and kept hardcoded dark rows after
    switching to a Light theme.
    """

    def __init__(self, master, palette=None, **kwargs):
        # Plain attributes first: CTkFrame.__init__ may re-configure itself
        # through the override below, which touches them.
        pal = dict(palette or {})
        self._labels: list[str] = []
        self._rows: list[Any] = []
        self._overrides: dict[int, str] = {}  # per-row text_color (placeholder)
        self._selected: int | None = None
        self._select_all_mode: bool = False
        self._row_fg = pal.get("text", "#ecf0f1")
        self._sel_bg = pal.get("accent", "#3498db")
        self._sel_fg = _on_color(
            self._sel_bg, pal.get("text", "#ecf0f1"), pal.get("bg", "#1e1e24"))
        super().__init__(
            master,
            # The page is a surface card; filling this with the same color would
            # make its own corner notches paint themselves invisible, and it read
            # as a flat ring instead of a well. The window background color sinks
            # it into the card and the notches pick up the page's surface.
            fg_color=pal.get("bg", "#1e1e24"),
            corner_radius=UITheme.RADIUS_LG,
            border_width=UITheme.BORDER_W,
            border_color=pal.get("hover", "#34495e"),
            **kwargs,
        )
        # Let the theme walker repaint the panel like any other widget.
        setattr(self, "_theme_roles", {"fg_color": "bg",
                                       "border_color": "hover"})

    # --- Listbox-compatible API (the only surface ui.py uses) ------

    def size(self) -> int:
        return len(self._labels)

    def get(self, index: int) -> str:
        return self._labels[index] if 0 <= index < len(self._labels) else ""

    def insert(self, index, text: str) -> None:
        # Only append semantics are used (always called with tk.END).
        i = len(self._labels)
        self._labels.append(text)
        row = ctk.CTkLabel(
            self,
            text=text,
            font=UITheme.F(11),
            anchor="w",
            corner_radius=UITheme.RADIUS_MD,
            fg_color="transparent",
            text_color=self._row_fg,
            cursor="hand2",
        )
        row.pack(fill="x", padx=6, pady=1)
        row.bind("<Button-1>", lambda e, idx=i: self._select(idx))
        self._rows.append(row)

    def delete(self, first, last=None) -> None:
        # Listbox semantics: the only call shape is delete(0, tk.END).
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self._labels.clear()
        self._overrides.clear()
        self._selected = None
        self._select_all_mode = False

    def itemconfig(self, index, **kwargs) -> None:
        if not isinstance(index, int) or not (0 <= index < len(self._rows)):
            return
        if "text" in kwargs:
            self._labels[index] = str(kwargs["text"])
            # Real content replaces any placeholder styling on the row.
            self._overrides.pop(index, None)
            self._rows[index].configure(text=self._labels[index])
        if "foreground" in kwargs:
            self._overrides[index] = str(kwargs["foreground"])
        self._paint(index)

    def curselection(self):
        if self._select_all_mode:
            return tuple(range(len(self._labels)))
        return () if self._selected is None else (self._selected,)

    # --- theming ---------------------------------------------------

    def configure(self, cnf=None, **kwargs):
        """Accept CTk options plus the legacy Listbox theming keys
        (bg/fg/selectbackground/selectforeground) the theme pass uses."""
        data = dict(cnf or {})
        data.update(kwargs)
        for old, attr in (("fg", "_row_fg"),
                          ("selectbackground", "_sel_bg"),
                          ("selectforeground", "_sel_fg")):
            if old in data:
                setattr(self, attr, data.pop(old))
        if "bg" in data:
            data["fg_color"] = data.pop("bg")
        if data:
            super().configure(**data)
        for i in range(len(self._rows)):
            self._paint(i)

    config = configure

    def _select(self, index: int) -> None:
        if not (0 <= index < len(self._labels)):
            return
        prev, self._selected = self._selected, index  # browse: click selects
        if prev is not None and prev != index:
            self._paint(prev)
        self._paint(index)

    def select_set(self, index: int) -> None:
        """Move the highlight without a click - the listbox spelling."""
        self._select(index)

    def select_all(self) -> None:
        self._select_all_mode = True
        self._selected = None
        for i in range(len(self._rows)):
            self._paint(i)
        try:
            self.update_idletasks()
        except Exception:
            pass

    def select_clear(self) -> None:
        self._select_all_mode = False
        self._selected = None
        for i in range(len(self._rows)):
            self._paint(i)

    def _paint(self, i: int) -> None:
        if not (0 <= i < len(self._rows)):
            return
        if self._select_all_mode or i == self._selected:
            self._rows[i].configure(
                fg_color=self._sel_bg, text_color=self._sel_fg)
        elif i in self._overrides:
            self._rows[i].configure(
                fg_color="transparent", text_color=self._overrides[i])
        else:
            self._rows[i].configure(
                fg_color="transparent", text_color=self._row_fg)


class UiSplitsMixin:
    """Self-contained app methods moved out of ui.py to keep it under 6000 lines.

    Each one owns its own dialogs and worker threads and touches no state from
    the page-build pipeline, so mixing this into the app class is behaviourally
    identical to leaving the definitions in ui.py - every ``self.`` reference
    and ``command=self.method`` call site keeps resolving, and no test scrapes
    these bodies from ui.py's source.

    The names below are the app attributes and methods these bodies borrow;
    declaring them (as Any, since the app is untyped) is what lets a type
    checker see inside the mixin. Annotating ``self`` with the app class
    instead would be the neater trick, but pyright rejects it: a parameter
    type must be a supertype of the class it is declared in, and the app is a
    *subtype* of this mixin. Assignments to new names (the swatch rows, the
    mode entry) need no declaration.
    """

    after: Any
    _show_info_dialog: Any
    _show_warning_dialog: Any
    _show_error_dialog: Any
    _show_success_dialog: Any
    _set_pref: Any
    _prefs: Any
    _check_macos_update: Any
    _do_self_restart: Any
    _start_worker: Any
    update_dl_status: Any
    show_toast: Any
    _settings_card: Any
    settings_scroll: Any
    tab_aep: Any
    aep_src_path: Any
    aep_src_lbl: Any
    aep_src_ver_lbl: Any
    aep_year_var: Any
    aep_dest_lbl: Any
    aep_convert_btn: Any
    aep_progress: Any
    aep_busy: Any
    _show_error_dialog: Any
    _CUSTOM_START_THEMES: Any
    _CUSTOM_ROLE_GROUPS: Any
    _on_custom_start: Any
    _on_custom_mode: Any
    _commit_custom_hex: Any
    _refresh_custom_theme_ui: Any
    reset_custom_palette: Any
    _style_option_menu: Any
    _style_button: Any
    _custom_mode: Any
    _custom_roles: Any
    set_custom_role: Any
    studio_file_path: Any
    btn_export: Any
    update_studio_progress: Any
    sp_sld: Any
    rv_sld: Any
    _ensure_ffmpeg: Any

    def _app_update_btn_set(self, **kwargs) -> None:
        """Touch the old Speed-tab app-update button if one exists.

        The Update Center is the only surface that updates the app now, so
        the button is gone; these flows keep working (and would decorate a
        button again if some build still had one) through this guard.
        """
        btn = getattr(self, "app_update_btn", None)
        if btn is not None:
            try:
                btn.configure(**kwargs)
            except Exception:
                pass

    def check_for_app_updates(self):
        """Check the remote manifest and trigger an in-place self-update."""
        import updater  # local module
        from version import __version__ as local_ver

        if not updater.is_frozen():
            self._show_info_dialog(
                "Update Unavailable",
                "Self-update only works in the packaged app.\n\n"
                "You are running from source (python ui.py), so there is no\n"
                "EXE to update. Build and run the .exe to use app updates.",
            )
            return

        if not updater.self_update_supported():
            # macOS: the app cannot replace itself here, but it can still report
            # that a newer version exists and take the user to the download.
            self._check_macos_update()
            return

        self._app_update_btn_set(state="disabled", text="Checking...")
        self.update_dl_status("Checking for app updates...", "#3498db")

        def worker():
            try:
                info = updater.get_remote_update_info()
            except Exception:
                info = None

            if not info or not info.get("version") or not info.get("download_url"):
                self.after(0, lambda: self.update_dl_status("Could not reach update server.", "#e74c3c"))
                self.after(0, lambda: self._app_update_btn_set(state="normal", text="Check for App Updates"))
                self.after(0, lambda: self.show_toast("No update information available right now.", "warning"))
                return

            remote_ver = info["version"]
            dl_url = info["download_url"]

            if not updater.is_newer_version(remote_ver):
                self.after(0, lambda: self.show_toast(f"You already have the latest version ({local_ver}).", "success"))
                self.after(0, lambda: self._app_update_btn_set(state="normal", text="Check for App Updates"))
                return


            # Update available -- confirm with the user. The install note tells
            # the truth about the UAC prompt: updater.launch_updater only needs
            # elevation when the install directory is not writable (a per-user
            # install updates with no prompt at all).
            install_dir = os.path.dirname(os.path.abspath(sys.executable))
            probe = os.path.join(install_dir, "_update_probe.tmp")
            try:
                with open(probe, "w", encoding="utf-8") as fh:
                    fh.write("probe")
                os.remove(probe)
                needs_admin = False
            except OSError:
                needs_admin = True
            install_note = (
                "The app will close automatically when the update is ready, "
                "then relaunch itself.\n\n"
                + (
                    "Because this app is installed under 'C:\\Program Files', "
                    "Windows will show an admin (UAC) prompt when installing. "
                    "Click Yes, and the app will update and relaunch "
                    "automatically."
                    if needs_admin else
                    "The app will update and relaunch automatically."
                )
            )
            msg = (
                f"A new version is available:\n\n"
                f"  Current: {local_ver}\n"
                f"  Latest:  {remote_ver}\n\n"
                f"Do you want to download and install it now?\n"
                f"{install_note}"
            )

            import threading
            confirm_event = threading.Event()
            confirm_result = {"val": False}

            def _ask_user():
                confirm_result["val"] = messagebox.askyesno("Update Available", msg)
                confirm_event.set()   # Signal only after the user has answered.

            self.after(0, lambda: self.update_dl_status(f"Update available (v{remote_ver}). Confirming...", "#f39c12"))
            self.after(0, _ask_user)

            # Block the worker thread until the dialog closes (or times out).
            confirm_event.wait(timeout=120)
            result = confirm_result["val"] if confirm_event.is_set() else False

            if not result:
                # User declined (or timed out).
                self.after(0, lambda: self._app_update_btn_set(state="normal", text="Check for App Updates"))
                return

            self.after(0, lambda: self.update_dl_status(f"Downloading update v{remote_ver}...", "#3498db"))

            # Download the new EXE.
            new_exe_path = updater.download_update(dl_url)
            if not new_exe_path:
                self.after(0, lambda: self.update_dl_status("Download failed. Please try again.", "#e74c3c"))
                self.after(0, lambda: self._show_error_dialog("Update Error", "Failed to download the update."))
                self.after(0, lambda: self._app_update_btn_set(state="normal", text=f"Update to v{remote_ver}"))
                return

            old_exe_path = sys.executable
            parent_pid = os.getpid()

            self.after(0, lambda: self.update_dl_status("Update downloaded. Installing...", "#f39c12"))

            launched = updater.launch_updater(
                old_exe_path,
                new_exe_path,
                parent_pid,
                # Pass the app exe so the updater relaunches it after installing.
                extra_args=[old_exe_path],
            )

            if not launched:
                self.after(0, lambda: self._show_error_dialog(
                    "Update Not Installed",
                    "Could not start the updater.\n\n"
                    "Either updater_cli.exe is missing, or admin permission "
                    "was declined when Windows asked."))
                self.after(0, lambda: self._app_update_btn_set(state="normal", text="Check for App Updates"))
                return

            # The updater will replace the EXE and we exit so the file can be replaced.
            self.after(0, lambda: self.update_dl_status("Update installed. Restarting...", "#27ae60"))
            self.after(500, lambda: self._do_self_restart())


        self._start_worker(worker)

    def _build_custom_theme_card(self):
        """The 'Custom colors' card: pick each role, watch contrast as you go."""
        card = self._settings_card(self.settings_scroll, "Custom colors")
        card.pack(fill="x", padx=0, pady=(0, 8))
        pal = getattr(self, "_palette", {}) or {}

        intro = ctk.CTkLabel(
            card,
            # One sentence, no paragraph: this card sits under the theme dropdown
            # and says what it does and what it will not ask about. The long
            # version explained the derivation, which the copy no longer needs
            # to carry - the derived shades simply stay in step by themselves.
            text="Start from a preset, then adjust. Hover shades follow your "
                 "colours automatically.",
            font=UITheme.F(11), anchor="w", wraplength=660, justify="left",
            text_color=pal.get("sub", "#95a5a6"),
        )
        intro.pack(fill="x", padx=16, pady=(0, 10))
        setattr(intro, "_theme_roles", {"text_color": "sub"})

        # Start-from row. Seeding beats starting from blank: a user who picks a
        # preset wants those colours, not an empty grid to fill in. One control,
        # not two. This used to be a dropdown plus a separate
        # "Use this palette" button, which asked for a confirmation that had
        # nothing to confirm: picking a preset to start from is not a proposal.
        # Selecting one now seeds it directly, like every other dropdown here.
        start_row = ctk.CTkFrame(card, fg_color="transparent")
        start_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(start_row, text="Copy from:", font=UITheme.F(11),
                     anchor="w").pack(side="left")
        self._custom_start_menu = ctk.CTkOptionMenu(
            start_row, values=list(self._CUSTOM_START_THEMES),
            command=self._on_custom_start, width=190,
        )
        self._custom_start_menu.set("TuneLab Dark")
        self._custom_start_menu.pack(side="left", padx=(8, 0))
        self._style_option_menu(self._custom_start_menu)

        # One swatch row per editable role. The swatch is a button rather than a
        # label so the whole row is a pointer target; the hex entry beside it
        # makes every role reachable without a mouse at all.
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0, 6))
        self._custom_swatch_rows = {}
        row_index = 0
        for title, roles in self._CUSTOM_ROLE_GROUPS:
            head = ctk.CTkLabel(grid, text=title, font=UITheme.F(11, "bold"),
                                anchor="w")
            head.grid(row=row_index, column=0, columnspan=3, sticky="w",
                      pady=(6, 2))
            setattr(head, "_theme_roles", {"text_color": "text"})
            row_index += 1
            for role in roles:
                label = ctk.CTkLabel(grid, text=role, font=UITheme.F(11),
                                     anchor="w", width=110)
                label.grid(row=row_index, column=0, sticky="w")
                setattr(label, "_theme_roles", {"text_color": "sub"})
                swatch = ctk.CTkButton(
                    grid, text="", width=54, height=UITheme.H_XS,
                    command=lambda r=role: self._pick_custom_role(r),
                )
                swatch.grid(row=row_index, column=1, padx=(0, 6))
                value = ctk.CTkEntry(grid, width=92)
                value.grid(row=row_index, column=2, sticky="w")
                value.bind("<Return>", lambda e, r=role: self._commit_custom_hex(r))
                value.bind("<FocusOut>",
                           lambda e, r=role: self._commit_custom_hex(r))
                self._custom_swatch_rows[role] = (label, swatch, value)
                row_index += 1
        grid.grid_columnconfigure(2, weight=1)

        # Displayed capitalised, stored lowercase: the mode key is compared
        # against 'light' in custom_palette and is written to prefs as-is.
        self._custom_mode_var = tk.StringVar(
            value=self._custom_mode.capitalize())
        mode_row = ctk.CTkFrame(card, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(0, 12))

        mode_menu = ctk.CTkOptionMenu(
            mode_row, values=["Dark", "Light"],
            variable=self._custom_mode_var, command=self._on_custom_mode,
            width=104,
        )
        mode_menu.pack(side="left")
        self._custom_mode_menu = mode_menu
        self._style_option_menu(mode_menu)
        reset_btn = ctk.CTkButton(
            mode_row, text="Reset", width=88, height=UITheme.H_XS,
            font=UITheme.F(11),
            command=lambda: self.reset_custom_palette(
                self._custom_mode_menu.get().lower()),
        )
        # Named *_btn rather than `reset`: tests/test_download_queue.py scans
        # ui.py for `x = self._queue_manager` aliases and then any `x.<attr>`
        # in the file, so a local named `reset` here would make the queue-alias
        # sweep read this button's .pack as queue API.
        reset_btn.pack(side="left", padx=(8, 0))
        self._style_button(reset_btn, "ghost")

        self._refresh_custom_theme_ui()

    def _pick_custom_role(self, role: str):
        """Open the OS colour chooser for *role*, then apply the result."""
        from tkinter import colorchooser
        current = custom_palette(self._custom_roles,
                                 self._custom_mode).get(role, "#000000")
        # cast, not self: the chooser wants a real Tk Misc, and the checker
        # cannot see that this mixin only ever runs on the app window.
        chosen = colorchooser.askcolor(color=current, parent=cast(tk.Misc, self),
                                       title="Pick %s" % role)
        if chosen and chosen[1]:
            self.set_custom_role(role, chosen[1])

    def export_studio_track(self):
        if not self.studio_file_path:
            self._show_warning_dialog("File Missing", "Please select an audio file first.")
            return

        original_name = os.path.splitext(os.path.basename(self.studio_file_path))[0]
        default_output_name = f"{original_name} - Slowed + Reverb.mp3"

        dest = filedialog.asksaveasfilename(
            initialfile=default_output_name,
            defaultextension=".mp3",
            filetypes=[("MP3 Audio file", "*.mp3")],
            title="Export Remix Output Target"
        )
        if not dest:
            return

        self.btn_export.configure(text="Encoding (Using all CPU cores)...", state="disabled")
        self.update_studio_progress(0.0)

        # Capture widget values on the main thread before starting the worker.
        _src = self.studio_file_path
        _speed = float(self.sp_sld.get())
        _reverb = float(self.rv_sld.get())

        def run_export():
            temp_wav = dest + ".temp.wav"
            try:
                self.update_studio_progress(0.1)
                audio, sr = downloader.process_studio_dsp(_src, _speed, _reverb)

                if audio is not None:
                    self.update_studio_progress(0.4)
                    try:
                        import soundfile as sf
                    except Exception:
                        self.after(0, lambda: self._show_error_dialog(
                            "Missing Dependency",
                            "The required package 'soundfile' is not installed.\n\n"
                            "Install it in your environment with:\n    python -m pip install soundfile\n\n"
                            "Then retry the export."
                        ))
                        return
                    sr_value = sr if sr is not None else 44100
                    sr_int = int(sr_value)
                    sf.write(temp_wav, audio.T, sr_int, subtype='PCM_16')


                    self.update_studio_progress(0.7)

                    ffmpeg_bin = self._ensure_ffmpeg()
                    if not ffmpeg_bin:
                        raise RuntimeError(
                            "ffmpeg was not found. Install ffmpeg or place ffmpeg.exe "
                            "next to the app to export the studio remix."
                        )
                    cmd = [
                        ffmpeg_bin, "-y",
                        "-i", temp_wav,
                        "-threads", "0",
                        "-preset", "ultrafast",
                        "-c:a", "libmp3lame",
                        "-q:a", "2",
                        dest
                    ]

                    completed = subprocess.run(cmd, **downloader._no_window_kwargs())
                    if completed.returncode != 0:
                        raise RuntimeError(
                            f"ffmpeg failed with exit code {completed.returncode}."
                        )
                    self.update_studio_progress(1.0)
                    self.after(0, lambda: self._show_success_dialog(
                        "Export complete",
                        f"Saved {os.path.basename(dest)}",
                        detail=dest))
                else:
                    self.update_studio_progress(0.0)
                    self.after(0, lambda: self._show_error_dialog(
                        "Export Failed", "The audio could not be processed."))
            except Exception as e:
                self.update_studio_progress(0.0)
                self.after(0, lambda err=e: self._show_error_dialog(
                    "Export Interrupted", "The export failed.", detail=str(err)))
            finally:
                if os.path.exists(temp_wav):
                    try:
                        os.remove(temp_wav)
                    except Exception:
                        logger.debug("Failed to remove temp wav", exc_info=True)
                self.after(0, lambda: self.btn_export.configure(text="Render & Export Full Studio Remix Track", state="normal"))

        self._start_worker(run_export)

    # --- AEP Version Converter (TAB: 'aep') ---
    def build_aep_view(self):
        """File card, target-year card, destination + Convert.

        Accepts .aep projects and .ffx animation presets (aep_convert
        dispatches on the extension). The page is deliberately plain data
        flow: pick a file (which reads and shows the AE version that saved
        it), pick a target year
        (2022-2026 radio chips), confirm the auto-named destination, press
        Convert. The heavy work runs on a worker thread via _start_worker;
        every widget touch afterwards goes through after(0, ...) because Tk
        widgets may only be touched on the main thread.
        """
        self.aep_src_path = ""
        self.aep_src_lbl_version = ""
        self.aep_busy = False
        import tkinter as tk

        scroll = ctk.CTkScrollableFrame(self.tab_aep, fg_color="transparent")
        scroll.pack(fill="both", expand=True,
                    padx=UITheme.RADIUS_CARD, pady=UITheme.RADIUS_CARD)

        # Source file card.
        src_card = self._settings_card(scroll, "Project or preset file")
        src_card.pack(fill="x", padx=0, pady=(0, 8))
        row = ctk.CTkFrame(src_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 4))
        self.aep_src_lbl = ctk.CTkLabel(
            row, text="No .aep or .ffx file chosen...",
            font=UITheme.F(12, "italic"), anchor="w")
        self.aep_src_lbl.pack(side="left", fill="x", expand=True)
        browse = ctk.CTkButton(row, text="Browse File", width=110,
                               command=self.browse_aep_file)
        browse.pack(side="right", padx=(10, 0))
        self._style_button(browse, "secondary")
        self.aep_src_ver_lbl = ctk.CTkLabel(
            src_card, text="Pick a project or preset to read the version that saved it.",
            font=UITheme.F(11), anchor="w")
        self.aep_src_ver_lbl.pack(fill="x", padx=16, pady=(0, 10))

        # Target year card: five radio chips, defaulting to the newest.
        tgt_card = self._settings_card(scroll, "Convert to")
        tgt_card.pack(fill="x", padx=0, pady=(0, 8))
        self.aep_year_var = tk.IntVar(value=2026)
        chips = ctk.CTkFrame(tgt_card, fg_color="transparent")
        chips.pack(fill="x", padx=16, pady=(0, 4))
        self.aep_year_buttons = []
        for i, _yr in enumerate((2023, 2024, 2025, 2026)):
            rb = ctk.CTkRadioButton(
                chips, text=str(_yr), variable=self.aep_year_var,
                value=_yr, command=self._on_aep_year_change)
            rb.grid(row=i // 3, column=i % 3, padx=(0, 14), pady=(0, 4),
                    sticky="w")
            self.aep_year_buttons.append((_yr, rb))
        ctk.CTkLabel(
            tgt_card,
            text="The copy is re-stamped for that year's After Effects. "
                 "Going older never migrates effects or features, so newer "
                 "content - or a preset's newer effects - may not work "
                 "there. The original is untouched.",
            font=UITheme.F(11), wraplength=600, justify="left",
            anchor="w").pack(fill="x", padx=16, pady=(0, 10))

        # Destination + Convert card.
        out_card = self._settings_card(scroll, "Destination")
        out_card.pack(fill="x", padx=0, pady=(0, 8))
        self.aep_dest_lbl = ctk.CTkLabel(
            out_card, text="Choose a file first.",
            font=UITheme.F(11), anchor="w")
        self.aep_dest_lbl.pack(fill="x", padx=16, pady=(0, 4))
        # Convert button + progress.
        self.aep_convert_btn = ctk.CTkButton(
            out_card, text="Convert File", width=200,
            command=self.start_aep_convert)
        self.aep_convert_btn.pack(anchor="w", padx=16, pady=(2, 6))
        self._style_button(self.aep_convert_btn, "primary")
        self.aep_progress = ctk.CTkProgressBar(out_card, width=400)
        self.aep_progress.pack(fill="x", padx=16, pady=(0, 12))
        self.aep_progress.set(0.0)

    def browse_aep_file(self):
        """Pick a project or preset, then read the AE version that saved it."""
        start = getattr(self, "_prefs", {}).get("aep_last_dir", "") or ""
        if not (start and os.path.isdir(start)):
            start = os.path.expanduser("~")
        sel = filedialog.askopenfilename(
            title="Select After Effects Project or Preset",
            initialdir=start,
            filetypes=[("After Effects files", "*.aep *.ffx"),
                       ("After Effects Project", "*.aep"),
                       ("After Effects Preset", "*.ffx"),
                       ("All files", "*.*")])
        if not sel:
            return
        self.aep_src_path = sel
        self.aep_src_version = ""
        try:
            self._set_pref("aep_last_dir", os.path.dirname(os.path.abspath(sel)))
        except Exception:
            pass
        self.aep_src_lbl.configure(text=os.path.basename(sel))
        self.aep_src_ver_lbl.configure(text="Reading file version...")
        self._refresh_aep_dest_label()
        self._start_worker(self._aep_read_version_worker)

    def _aep_read_version_worker(self):
        """Read the source version off the worker thread; marshal to UI."""
        # local module; py_aep itself stays optional (presets never need it)
        import aep_convert  # local module
        path = self.aep_src_path
        try:
            ver = aep_convert.read_version(path)
            desc = aep_convert.describe_version(ver)
            label = "Saved by %s." % desc
        except aep_convert.AepMissingDependency as exc:
            # Not the file's fault: the running Python lacks py-aep. The
            # version label only holds one line, so keep it short and put the
            # interpreter path + fixes in a dialog.
            self.after(0, lambda t=str(exc): self._aep_missing_dependency(t))
            return
        except Exception as exc:
            label = "Could not read this file: %s" % exc
            ver = ""
        self.after(0, lambda t=label, v=ver: self._aep_version_ready(t, v))

    def _aep_version_ready(self, label, version):
        """Show the read version, then refresh the dest line with from-to."""
        try:
            self.aep_src_lbl_version = version
            self.aep_src_ver_lbl.configure(text=label)
        except Exception:
            pass
        # Disable target years older than the source release: the converter
        # refuses those (matte layer id layout differs) and would only error.
        try:
            src_year = int(version) if version else None
            if src_year is not None:
                for yr, btn in getattr(self, "aep_year_buttons", []):
                    btn.configure(state="disabled" if yr < src_year else "normal")
                if src_year > int(self.aep_year_var.get()):
                    self.aep_year_var.set(src_year)
        except Exception:
            pass
        self._refresh_aep_dest_label()

    def _aep_missing_dependency(self, message):
        """Show the py-aep install dialog; keep the version line short."""
        try:
            self.aep_src_ver_lbl.configure(
                text="Converter library missing - see the popup.")
        except Exception:
            pass
        self._show_error_dialog("Converter Library Missing", message=message)

    def _aep_target_year(self):
        try:
            return int(self.aep_year_var.get())
        except Exception:
            return 2026

    def _refresh_aep_dest_label(self):
        """Show where the converted copy will land, with the from-to route."""
        if not getattr(self, "aep_src_path", ""):
            try:
                self.aep_dest_lbl.configure(text="Choose a file first.")
            except Exception:
                pass
            return
        import aep_convert  # local module
        year = self._aep_target_year()
        try:
            dest = aep_convert.output_path_for(self.aep_src_path, year)
        except Exception:
            return
        src_ver = getattr(self, "aep_src_lbl_version", "") or ""
        try:
            if src_ver:
                try:
                    route = "%s \u2192 %s: " % (
                        aep_convert.describe_version(src_ver),
                        aep_convert.describe_version(
                            aep_convert.TARGET_VERSIONS[year]))
                except Exception:
                    route = ""
                self.aep_dest_lbl.configure(
                    text="%sSaves as: %s" % (route, os.path.basename(dest)))
            else:
                self.aep_dest_lbl.configure(
                    text="Saves as: %s" % os.path.basename(dest))
        except Exception:
            pass

    def _on_aep_year_change(self):
        self._refresh_aep_dest_label()

    def start_aep_convert(self):
        """Validate, then convert on a worker thread (never block the UI)."""
        if getattr(self, "aep_busy", False):
            return
        if not getattr(self, "aep_src_path", ""):
            self.show_toast("Pick a project or preset first.", "warning")
            return
        year = self._aep_target_year()
        self.aep_busy = True
        try:
            self.aep_convert_btn.configure(state="disabled",
                                           text="Converting...")
            self.aep_progress.set(0.15)
        except Exception:
            pass
        self._start_worker(lambda: self._aep_convert_worker(year))

    def _aep_convert_worker(self, year):
        """Run the relabel off-thread; all widget touches via after(0, ...)."""
        import traceback

        import aep_convert  # local module
        src = self.aep_src_path
        try:
            result = aep_convert.convert(src, year)
        except Exception as exc:
            # Keep the full traceback: the one-line str(exc) is what the old
            # system box showed, and it is never enough to debug a bad file.
            err, tb = str(exc), traceback.format_exc()
            self.after(0, lambda e=err, t=tb: self._aep_convert_failed(e, t))
            return
        try:
            self.aep_progress.set(0.9)
        except Exception:
            pass
        self.after(0, lambda res=result: self._aep_convert_done(res))

    def _aep_convert_done(self, result):
        """Re-enable the UI and confirm the converted copy's path."""
        self.aep_busy = False
        try:
            self.aep_convert_btn.configure(state="normal",
                                           text="Convert File")
            self.aep_progress.set(1.0)
        except Exception:
            pass
        import aep_convert  # local module
        try:
            back = aep_convert.describe_version(
                aep_convert.read_version(result["out_path"]))
        except Exception:
            back = "AE %d" % result["year"]
        self.show_toast("Saved %s (%s)."
                        % (os.path.basename(result["out_path"]), back),
                        "success")
        self._show_success_dialog(
            "Conversion Complete",
            "Your file now opens in AE %d.\nSaved as:\n%s"
            % (result["year"], result["out_path"]))

    def _aep_convert_failed(self, message, detail=None):
        """Restore the UI, then show the failure with a copyable traceback."""
        self.aep_busy = False
        try:
            self.aep_convert_btn.configure(state="normal",
                                           text="Convert File")
            self.aep_progress.set(0.0)
        except Exception:
            pass
        self._show_error_dialog("Conversion Failed", message, detail=detail)
