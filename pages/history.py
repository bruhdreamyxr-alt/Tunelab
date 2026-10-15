"""The Download History page: search, sort, paging, re-download and
pruning. Extracted from ui.py alongside the queue page."""

import logging
import os
import subprocess
import sys
from tkinter import messagebox
from typing import Any

import customtkinter as ctk
from ui_theme import UITheme
import downloader


logger = logging.getLogger("universal_audio_studio.pages.history")


class HistoryPageMixin:
    """The Download History page: search, sort, paging, re-download and"""

    # Names the shell (or another page) owns: declared so the type
    # checker can see them from here, the convention ui_widgets uses.
    _hide_sb_tooltip: Any
    _init_queue_manager: Any
    _queue_manager: Any
    _schedule_sb_tooltip: Any
    _show_error_dialog: Any
    _start_worker: Any
    _style_button: Any
    after: Any
    after_cancel: Any
    download_mp3: Any
    download_mp4: Any
    show_frame: Any
    show_toast: Any
    tab_history: Any
    url_entry: Any


    def build_history_view(self):
        """Build the Download History tab: scrollable list of past downloads
        with re-download buttons and a clear-history control."""
        # Page title lives in the header only — no in-page H1.

        # Top controls: Clear History button + count label
        ctrl_row = ctk.CTkFrame(self.tab_history, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=UITheme.PAD_X, pady=(14, 6))

        self.btn_clear_history = ctk.CTkButton(
            ctrl_row, text="Clear History", width=140, height=UITheme.H_CTRL,
            command=self._clear_history,
        )
        self.btn_clear_history.pack(side="left")
        # A "danger" fill for a control that only opens a confirmation dialog
        # makes destructive the most colourful thing on the page - the eye went
        # to Clear History before the download controls. The genuinely immediate
        # red actions (Stop, Cancel) keep the full danger fill.
        self._style_button(self.btn_clear_history, "ghost", bordered=True, icon="trash")

        self.history_count_lbl = ctk.CTkLabel(ctrl_row, text="0 entries", font=UITheme.F(12), text_color="#95a5a6")
        self.history_count_lbl.pack(side="left", padx=(12, 0))

        # Offered only when something is actually prunable, so the row does not
        # carry another permanent button on a clean history.
        self.btn_prune_history = ctk.CTkButton(
            ctrl_row, text="Remove Missing Files", width=190, height=UITheme.H_CTRL,
            command=self._prune_missing_history, state="disabled",
        )
        self.btn_prune_history.pack(side="right")
        self._style_button(self.btn_prune_history, "ghost", icon="trash")

        # Search bar
        search_row = ctk.CTkFrame(self.tab_history, fg_color="transparent")
        search_row.pack(fill="x", padx=20, pady=(0, 6))
        self.history_search_var = ctk.StringVar()
        self.history_search_entry = ctk.CTkEntry(
            search_row,
            # No placeholder_text: customtkinter 6.0.0 silently skips the
            # placeholder of any entry backed by a textvariable, because
            # _activate_placeholder() guards on `self._textvariable == ""` and
            # that compares the StringVar OBJECT to a string - always False. The
            # field rendered as an unlabelled empty box, which read as broken.
            # Forcing the placeholder on by hand was tried and reverted: it
            # fights the library's own focus/insert handling and produced
            # "Search by title or URL...mary". The label to the left says what
            # the box is for instead.
            textvariable=self.history_search_var, height=UITheme.H_FIELD,
            corner_radius=UITheme.RADIUS_FIELD,
            border_width=UITheme.BORDER_W,
            border_color=(getattr(self, "_palette", {}) or {}).get(
                "hover", UITheme.SIDEBAR_HOVER),
        )
        setattr(self.history_search_entry, "_theme_roles", {"border_color": "hover"})
        # A visible label rather than a placeholder: the placeholder cannot be
        # made to work on a textvariable-backed entry (see above), and an
        # unlabelled box gives the user nothing to go on.
        ctk.CTkLabel(
            search_row, text="Search", font=UITheme.F(11),
            text_color=(getattr(self, "_palette", {}) or {}).get("sub", "#95a5a6"),
        ).pack(side="left", padx=(0, 8))
        self.history_search_entry.pack(side="left", fill="x", expand=True)
        # Debounced: a rebuild destroys and recreates every row widget, so
        # firing it on every keystroke made typing a 4-char query cost ~14s on
        # a 200-row history. Refresh 150ms after the last keystroke instead.
        self._history_search_after = None
        self.history_search_var.trace_add("write", lambda *_: self._schedule_history_search())

        # Sort controls
        self._history_sort_key = "date"
        self._history_sort_reverse = True
        sort_row = ctk.CTkFrame(self.tab_history, fg_color="transparent")
        sort_row.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(sort_row, text="Sort by:", font=UITheme.F(11), text_color="#95a5a6").pack(side="left")
        for lbl, key in [("Date", "date"), ("Title", "title"), ("Status", "status")]:
            btn = ctk.CTkButton(
                sort_row, text=lbl, width=60, height=UITheme.H_XS,
                font=UITheme.F(10),
                command=lambda k=key: self._set_history_sort(k),
            )
            self._style_button(btn, "ghost")
            btn.pack(side="left", padx=2)

        # Scrollable list of history entries
        _pal = getattr(self, "_palette", {}) or {}
        self.history_scroll = ctk.CTkScrollableFrame(
            self.tab_history, label_text="Past Downloads",
            corner_radius=UITheme.RADIUS_LG,
            border_width=UITheme.BORDER_W,
            # Left on its defaults this panel kept CustomTkinter's own gray,
            # which sat on top of the palette like a foreign window. The page is
            # a surface card, so the well is the window background color: that
            # contrast is also what makes its rounded corners visible.
            fg_color=_pal.get("bg", UITheme.SURFACE_BG),
            border_color=_pal.get("hover", UITheme.SIDEBAR_HOVER),
            label_fg_color=_pal.get("hover", UITheme.SIDEBAR_HOVER),
            label_text_color=_pal.get("text", "#ecf0f1"),
        )
        setattr(self.history_scroll, "_theme_roles",
                {"fg_color": "bg", "border_color": "hover",
                 "label_fg_color": "hover", "label_text_color": "text"})
        self.history_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Internal container for entry widgets (rebuilt on refresh)
        self._history_entries_frame = ctk.CTkFrame(self.history_scroll, fg_color="transparent")
        self._history_entries_frame.pack(fill="both", expand=True)

        self._refresh_history_view()
        self.tab_history.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _schedule_history_search(self):
        """Debounce the history search: refresh 150ms after the last keystroke."""
        try:
            pending = getattr(self, "_history_search_after", None)
            if pending:
                self.after_cancel(pending)
        except Exception:
            pass
        try:
            self._history_search_after = self.after(150, self._refresh_history_view)
        except Exception:
            self._refresh_history_view()

    def _show_all_history(self):
        """Expand a paginated history list; reset by a new query or sort."""
        self._history_show_all = True
        self._refresh_history_view(force=True)

    def _set_history_sort(self, key):
        if self._history_sort_key == key:
            self._history_sort_reverse = not self._history_sort_reverse
        else:
            self._history_sort_key = key
            self._history_sort_reverse = True if key == "date" else False
        self._history_show_all = False
        self._refresh_history_view()

    def _refresh_history_view(self, force: bool = False):
        """Rebuild the history entry list from the saved history file.

        Skips the (expensive) widget rebuild when the filtered and sorted
        result matches what is already on screen: show_frame calls this
        every time the tab opens, and recreating every row on each visit
        was a visible stutter.
        """
        history = []
        self._init_queue_manager()
        if self._queue_manager:
            try:
                history = self._queue_manager.get_history()
            except Exception:
                history = []
        total_all = len(history)

        # Apply search filter. A visible placeholder is stored in the same
        # StringVar as real input (customtkinter inserts it straight into the
        # entry), so "is the placeholder showing?" has to be asked explicitly -
        # otherwise the list filters itself by the string "Search by title or
        # URL..." and silently shows nothing.
        query = self.history_search_var.get().strip().lower()
        entry = getattr(self, "history_search_entry", None)
        if entry is not None and getattr(entry, "_placeholder_text_active", False):
            query = ""
        if query:
            history = [e for e in history if query in e.get("title", "").lower() or query in e.get("url", "").lower()]

        # Apply sorting
        sort_key = self._history_sort_key
        reverse = self._history_sort_reverse
        def _sort_key(entry):
            if sort_key == "date":
                return entry.get("completed_at", 0) or 0
            elif sort_key == "title":
                return (entry.get("title") or entry.get("url") or "").lower()
            elif sort_key == "status":
                return entry.get("status", "")
            return 0
        history = sorted(history, key=_sort_key, reverse=reverse)

        # Signature of what should be on screen; identical content means
        # the widgets are already correct and can be left alone. The
        # pagination state is part of the signature: "Show all" changes which
        # rows are visible without changing the entries themselves.
        sig = (
            query,
            self._history_sort_key,
            self._history_sort_reverse,
            bool(getattr(self, "_history_show_all", False)),
            tuple(
                (e.get("url"), e.get("title"), e.get("status"),
                 e.get("filepath"), e.get("completed_at"))
                for e in history
            ),
        )
        if not force and sig == self._history_view_sig:
            return
        self._history_view_sig = sig

        for w in self._history_entries_frame.winfo_children():
            w.destroy()

        # With a query active the label says "12 of 240 entries": a bare "12"
        # reads like the history shrank rather than like a filter is on.
        if query and total_all != len(history):
            self.history_count_lbl.configure(
                text=f"{len(history)} of {total_all} entries")
        else:
            self.history_count_lbl.configure(text=f"{len(history)} entries")

        # Only offer the prune when there is something to prune, and count from
        # the unfiltered list so a search box cannot make a missing file look
        # like there is nothing to clean up.
        missing = self._missing_history_count()
        try:
            self.btn_prune_history.configure(
                state="normal" if missing else "disabled",
                text=f"Remove {missing} Missing File{'s' if missing != 1 else ''}"
                if missing else "Remove Missing Files",
            )
        except Exception:
            logger.debug("Could not update the prune-history button",
                         exc_info=True)

        if not history:
            msg = "No matching history entries." if query else "No download history yet.\nDownloads you complete will appear here."
            ctk.CTkLabel(
                self._history_entries_frame,
                text=msg,
                font=UITheme.F(12), text_color="#95a5a6",
            ).pack(pady=30)
            return

        # Pagination: the signature guard skips no-op refreshes, but the first
        # render of a big history still destroys and recreates every row. Cap
        # it; a query narrows the list, which is also why a search resets the
        # cap even when its text matches what's already shown.
        _HISTORY_PAGE = 75
        if query or getattr(self, "_history_show_all", False):
            limit = len(history)
        else:
            limit = _HISTORY_PAGE
        shown = history[:limit]
        for idx, entry in enumerate(shown):
            self._add_history_entry(idx, entry)
        if len(history) > len(shown):
            more = ctk.CTkButton(
                self._history_entries_frame,
                text=f"Show all {len(history)} entries",
                height=UITheme.H_SM,
                command=self._show_all_history,
            )
            self._style_button(more, "ghost")
            more.pack(pady=8)

    def _add_history_entry(self, idx, entry):
        """Add a single history row with title, date, status, and re-download."""
        url = entry.get("url", "")
        title = entry.get("title") or url[:60] or "Unknown"
        status = entry.get("status", "unknown")
        filepath = entry.get("filepath", "")
        completed = entry.get("completed_at")
        is_video = entry.get("is_video", False)

        # Format timestamp
        date_str = "Unknown"
        if completed:
            try:
                from datetime import datetime
                date_str = datetime.fromtimestamp(completed).strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = "Unknown"

        # Status styling
        status_colors = {
            "done": "#2ecc71", "failed": "#e74c3c",
            "skipped": "#f39c12", "pending": "#3498db",
        }
        status_color = status_colors.get(status, "#95a5a6")

        # File existence check
        file_exists = bool(filepath and os.path.exists(filepath))

        # Entry frame
        row = ctk.CTkFrame(self._history_entries_frame, fg_color="transparent")
        row.pack(fill="x", pady=3, padx=4)

        # Left: title + metadata
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)

        title_lbl = ctk.CTkLabel(left, text=title, font=UITheme.F(12, "bold"),
                                 anchor="w", wraplength=380, justify="left")
        title_lbl.pack(anchor="w")

        meta_parts = [f"{'Video' if is_video else 'Audio'}  •  {date_str}"]
        meta_parts.append(f"File: {'✓ exists' if file_exists else '✗ missing'}")
        meta_text = "  |  ".join(meta_parts)
        meta_lbl = ctk.CTkLabel(left, text=meta_text, font=UITheme.F(10),
                                text_color="#7f8c8d", anchor="w")
        meta_lbl.pack(anchor="w")

        # Right: status badge + buttons
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")

        status_lbl = ctk.CTkLabel(right, text=status.upper(), font=UITheme.F(10, "bold"),
                                  text_color=status_color, width=70)
        status_lbl.pack(side="left", padx=(0, 6))

        # Re-download button
        btn_redl = ctk.CTkButton(
            right, text="", width=34, height=UITheme.H_SM,
            command=lambda u=url, v=is_video: self._redownload(u, v),
        )
        self._style_button(btn_redl, "primary", icon="refresh")
        btn_redl.pack(side="left", padx=2)
        # Glyph-only buttons get hover tooltips (reusing the sidebar popup,
        # which already avoids the transient-black-flicker traps).
        btn_redl.bind("<Enter>", lambda e, b=btn_redl: self._schedule_sb_tooltip(b, "Re-download this URL", only_when_collapsed=False))
        btn_redl.bind("<Leave>", lambda e: self._hide_sb_tooltip())

        # Open file button (only if file exists)
        if file_exists:
            btn_open = ctk.CTkButton(
                right, text="", width=34, height=UITheme.H_SM,
                command=lambda p=filepath: self._open_file(p),
            )
            self._style_button(btn_open, "secondary", icon="folder")
            btn_open.pack(side="left", padx=2)
            btn_open.bind("<Enter>", lambda e, b=btn_open: self._schedule_sb_tooltip(b, "Open file", only_when_collapsed=False))
            btn_open.bind("<Leave>", lambda e: self._hide_sb_tooltip())

    def _redownload(self, url, is_video):
        """Re-download a URL from history by injecting it into the downloader."""
        self.show_frame("downloader")
        try:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            if is_video:
                self._start_worker(self.download_mp4)
            else:
                self._start_worker(self.download_mp3)
        except Exception as e:
            self._show_error_dialog("Re-download Error",
                                    "Could not start the re-download.",
                                    detail=str(e))

    @staticmethod
    def _open_file_command(filepath, mode="open", platform=None, is_dir=False):
        """Return the OS command that opens *filepath* or reveals its folder.

        Extracted from _open_file so the platform branching is testable
        without a live Tk window. ``mode`` is "open" (launch with the
        default app) or "reveal" (show it in a file manager). Returns a
        Popen argv list, or a shell string on Windows where ``start`` is a
        shell builtin rather than an executable.
        """
        plat = platform if platform is not None else sys.platform
        if plat == "darwin":
            # macOS: `open` launches the file; `-R` reveals it in Finder.
            return ["open", filepath] if mode == "open" else ["open", "-R", filepath]
        if plat.startswith(("linux", "freebsd", "openbsd")):
            return ["xdg-open", filepath]
        # Windows (and anything else): the old code always ran `start`, which
        # silently did nothing on Mac/Linux.
        if mode == "reveal":
            return ["explorer", "/select,", filepath]
        if is_dir:
            return ["explorer", filepath]
        return f'start "" "{filepath}"'

    def _open_file(self, filepath):
        """Open a downloaded file with the system default app."""
        is_dir = os.path.isdir(filepath)
        for mode in ("open", "reveal"):
            try:
                cmd = self._open_file_command(filepath, mode=mode, is_dir=is_dir)
                if isinstance(cmd, str):
                    subprocess.Popen(cmd, shell=True)
                else:
                    subprocess.Popen(cmd, **downloader._no_window_kwargs())
                return
            except Exception:
                continue
        self._show_error_dialog(
            "Open Error",
            "Could not open that file — it may have been moved or deleted.",
            detail=filepath)

    def _prune_missing_history(self):
        """Offer to drop history entries whose file no longer exists."""
        if not self._queue_manager:
            self._init_queue_manager()
        if not self._queue_manager:
            self._show_error_dialog("Error", "Could not initialize download queue.")
            return
        count = self._missing_history_count()
        if not count:
            self.show_toast("No missing files in history", "info")
            return
        if not messagebox.askyesno(
            "Remove Missing Files",
            f"Remove {count} history entr{'y' if count == 1 else 'ies'} whose "
            f"file no longer exists?\n\nThis only removes the history records; "
            f"nothing on disk is deleted.",
        ):
            return
        try:
            removed = self._queue_manager.prune_missing_history()
        except Exception as e:
            self._show_error_dialog("Remove Missing Files",
                                    "Could not update the history.",
                                    detail=str(e))
            return
        self._refresh_history_view()
        self.show_toast(f"Removed {removed} missing entr"
                        f"{'y' if removed == 1 else 'ies'}", "success")

    def _missing_history_count(self) -> int:
        """How many history entries point at a file that is gone."""
        if not self._queue_manager:
            return 0
        try:
            history = self._queue_manager.get_history() or []
        except Exception:
            return 0
        count = 0
        for entry in history:
            if not isinstance(entry, dict):
                continue
            filepath = str(entry.get("filepath") or "")
            if filepath and not os.path.exists(filepath):
                count += 1
        return count

    def _clear_history(self):
        """Wipe the download history after confirmation."""
        if not self._queue_manager:
            self._init_queue_manager()
        if not self._queue_manager:
            self._show_error_dialog("Error", "Could not initialize download queue.")
            return
        if not messagebox.askyesno("Clear History", "Delete all download history?\n\nThis cannot be undone."):
            return
        try:
            self._queue_manager.clear_history()
            self._refresh_history_view()
            self.show_toast("History cleared", "success")
        except Exception as e:
            self._show_error_dialog("Clear History", "Could not clear the history.",
                                    detail=str(e))


