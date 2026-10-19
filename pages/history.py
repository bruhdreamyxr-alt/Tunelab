"""The Download History page: search, sort, paging, re-download and
pruning. Extracted from ui.py alongside the queue page."""

import logging
import os
import subprocess
import sys
from tkinter import messagebox
from typing import Any, Optional

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
    _set_pref: Any
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

        # List / Gallery view toggle. Persists so the choice survives a
        # restart; the gallery is video-only (thumbnails come from a local
        # ffmpeg frame grab), so audio entries keep a neutral tile there.
        self.history_view_var = ctk.StringVar(
            value="Gallery" if self._history_view_pref() == "gallery" else "List")
        self.history_view_toggle = ctk.CTkSegmentedButton(
            ctrl_row, values=["List", "Gallery"],
            variable=self.history_view_var,
            command=self._on_history_view_toggled,
        )
        self.history_view_toggle.pack(side="right", padx=(0, 12))
        self.history_view_toggle.set(self.history_view_var.get())

        # Search bar + sort filters on one header row, so the page opens with
        # one compact control band instead of two stacked strips.
        search_row = ctk.CTkFrame(self.tab_history, fg_color="transparent")
        search_row.pack(fill="x", padx=20, pady=(0, 8))
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
        self.history_search_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))
        # Debounced: a rebuild destroys and recreates every row widget, so
        # firing it on every keystroke made typing a 4-char query cost ~14s on
        # a 200-row history. Refresh 150ms after the last keystroke instead.
        self._history_search_after = None
        self.history_search_var.trace_add("write", lambda *_: self._schedule_history_search())

        # Sort filters on the same row.
        ctk.CTkLabel(search_row, text="Sort by:", font=UITheme.F(11),
                     text_color="#95a5a6").pack(side="left", padx=(0, 4))
        self._history_sort_key = "date"
        self._history_sort_reverse = True
        for lbl, key in [("Date", "date"), ("Title", "title"), ("Status", "status")]:
            btn = ctk.CTkButton(
                search_row, text=lbl, width=60, height=UITheme.H_XS,
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
            border_color=UITheme.BORDER_SOFT,
            label_fg_color=_pal.get("hover", UITheme.SIDEBAR_HOVER),
            label_text_color=_pal.get("text", "#ecf0f1"),
        )
        setattr(self.history_scroll, "_theme_roles",
                {"fg_color": "bg", "label_fg_color": "hover",
                 "label_text_color": "text"})
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

    def _history_view_pref(self) -> str:
        """The persisted view mode: 'gallery' or 'list' (default)."""
        return "gallery" if str(
            (getattr(self, "_prefs", None) or {}).get("history_view", "")
        ).lower() == "gallery" else "list"

    def _on_history_view_toggled(self, _value=None):
        """Persist the List/Gallery choice and repaint immediately."""
        choice = "gallery" if str(self.history_view_var.get()).lower() == "gallery" else "list"
        self._set_pref("history_view", choice)
        self._refresh_history_view(force=True)

    def _history_entries(self):
        """The saved history: SQLite when it answers, else the JSON file.

        The library database is the long-term store (see library_db); the
        JSON file stays the compatibility floor for fresh installs and for
        any moment the database cannot be opened. The first call also runs
        the one-time import of the existing JSON entries.
        """
        self._init_queue_manager()
        records = []
        if self._queue_manager:
            try:
                records = self._queue_manager.get_history()
            except Exception:
                records = []
        try:
            import library_db
            library_db.ensure_migrated(records)
            rows = library_db.entries()
            if rows is not None:
                return rows
        except Exception:
            logger.debug("Library read unavailable; using JSON history",
                         exc_info=True)
        return records

    def _refresh_history_view(self, force: bool = False,
                              _entries=None, _missing: "int | None" = None):
        """Rebuild the history entry list from the saved history file.

        Skips the (expensive) widget rebuild when the filtered and sorted
        result matches what is already on screen: show_frame calls this
        every time the tab opens, and recreating every row on each visit
        was a visible stutter.

        The disk work (SQLite/JSON read, migration, exists() probes) can
        arrive pre-fetched from the _refresh_history_async worker through
        ``_entries``/``_missing``: then the body below is a pure main-thread
        render and never touches the disk. A direct call with no overrides
        reads synchronously - the path the tests and the explicit actions
        (clear, prune, sort, search) take. The synchronous read claims the
        next async generation first, so a tab-switch read already in flight
        cannot land after it and overwrite the fresh result.
        """
        if _entries is None:
            try:
                self._history_read_gen = int(
                    getattr(self, "_history_read_gen", 0)) + 1
            except Exception:
                try:
                    self._history_read_gen = 1
                except Exception:
                    pass
            _entries = self._history_entries()
        history = _entries
        total_all = len(history)
        # Folder->media resolutions are only valid for this pass: a prune or
        # an outside delete can change what a folder holds, so a cache that
        # lived across refreshes could serve a stale poster. Reset per
        # refresh; within one refresh the same folder is still asked several
        # times per entry (kind + video/audio path, grid + tile), so the
        # cache still removes the repeated directory scans.
        try:
            self._history_folder_cache = {}
        except Exception:
            pass
        # Keep the unfiltered list: the prune button counts missing files
        # across ALL of history, and a search must not hide that count.
        # Counting from the already-fetched list (not a second DB + JSON
        # fetch via _missing_history_count) keeps a page switch to one read.
        full_history = history

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
            self._history_view_pref(),
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
        # like there is nothing to clean up. Counted from the entries already
        # in hand: _missing_history_count() would re-fetch the history (a
        # second DB read + JSON parse + migration check) on every refresh.
        # The async worker pre-computes this off-thread and hands it in as
        # _missing, so the tab-switch render never probes the disk either.
        if _missing is None:
            _missing = sum(
                1 for e in full_history
                if isinstance(e, dict)
                and str(e.get("filepath") or "")
                and not os.path.exists(str(e.get("filepath"))))
        missing = _missing
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
        if shown and self._history_view_pref() == "gallery":
            # Poster grid. Returns so the list rows below do not
            # render on top of the tiles; the empty-state message above is
            # untouched, so an empty history still reads the same either way.
            self._render_history_gallery(shown)
            return
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
    # --- Async tab-switch read ---------------------------------------------
    # The tab switch itself must never wait on disk: the SQLite read, the
    # JSON fallback, the one-time migration and the per-entry exists()
    # probes all run here on a worker thread. Only plain data crosses back
    # to the main thread, where _refresh_history_view renders it. The
    # generation counter drops stale results: hopping away and back starts
    # a newer read, and the older worker's payload is discarded on arrival.

    def _refresh_history_async(self, force: bool = False):
        """Re-read history off the UI thread, then render on it."""
        try:
            self._history_read_gen = int(
                getattr(self, "_history_read_gen", 0)) + 1
        except Exception:
            self._history_read_gen = 1
        gen = self._history_read_gen
        if getattr(self, "_history_read_pending", False):
            if force:
                try:
                    self.after(
                        0,
                        lambda: self._refresh_history_view(force=True))
                except Exception:
                    pass
            return
        self._history_read_pending = True

        def _read():
            try:
                entries = self._history_entries()
            except Exception:
                logger.debug("Async history read failed", exc_info=True)
                entries = []
            try:
                missing = sum(
                    1 for e in entries
                    if isinstance(e, dict)
                    and str(e.get("filepath") or "")
                    and not os.path.exists(str(e.get("filepath"))))
            except Exception:
                missing = 0

            def _apply():
                self._history_read_pending = False
                if gen != getattr(self, "_history_read_gen", gen):
                    return
                try:
                    self._refresh_history_view(
                        force=True, _entries=entries, _missing=missing)
                except Exception:
                    logger.debug("Async history render failed", exc_info=True)
            try:
                self.after(0, _apply)
            except Exception:
                self._history_read_pending = False

        try:
            import threading as _th
            _th.Thread(target=_read, daemon=True).start()
        except Exception:
            self._history_read_pending = False
            try:
                self._refresh_history_view(force=force)
            except Exception:
                logger.debug("Sync history fallback failed", exc_info=True)


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

        # Right: status badge + buttons — packed FIRST so it always keeps its
        # space and never gets pushed off the right edge by a long title on
        # narrow windows (the old left-first expand=True layout hid the
        # re-download/open buttons unless the window was full screen).
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right", fill="y", padx=(6, 0))

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

        # Left: title + metadata — takes whatever width remains after the
        # action buttons claim theirs, so they stay visible at any window size.
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=(0, 4))

        title_lbl = ctk.CTkLabel(left, text=title, font=UITheme.F(12, "bold"),
                                 anchor="w", wraplength=380, justify="left")
        title_lbl.pack(anchor="w")

        meta_parts = [f"{'Video' if is_video else 'Audio'}  •  {date_str}"]
        meta_parts.append(f"File: {'✓ exists' if file_exists else '✗ missing'}")
        meta_text = "  |  ".join(meta_parts)
        meta_lbl = ctk.CTkLabel(left, text=meta_text, font=UITheme.F(10),
                                text_color="#7f8c8d", anchor="w")
        meta_lbl.pack(anchor="w")

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

    # --- Gallery view -------------------------------------------------------
    # A wrapping grid of poster tiles. Thumbnails are extracted locally with
    # the bundled ffmpeg (downloader.extract_video_thumbnail) and loaded in a
    # background worker so a grid of posters never blocks the UI thread; each
    # image is applied through self.after() because only the main thread may
    # touch Tk. Audio (or an entry whose file is gone) gets a neutral
    # placeholder tile - the gallery is video-only by the standing decision,
    # so nothing here ever reaches for the network.

    _GALLERY_TILE_W = 200
    _GALLERY_THUMB_H = 112   # 16:9-ish poster area
    _GALLERY_PAD = 12
    # Classification reads the REAL file, because history's is_video flag
    # lies: existing rows recorded .mp4 downloads as audio (the direct-
    # download path wrote the wrong flag), and some rows store a folder as
    # filepath. Deciding on the flag alone is exactly how real videos ended
    # up with a text placeholder instead of a poster.
    _GALLERY_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi",
                           ".flv", ".wmv", ".mpg", ".mpeg", ".3gp", ".ts")
    _GALLERY_AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg",
                           ".opus", ".wma", ".aiff", ".aif")

    def _entry_resolved_path(self, entry) -> str:
        """The entry's file: a folder filepath resolves to the media inside.

        Folder resolutions are cached on self keyed by folder path:
        pick_produced_media_file scans the directory (getmtime per file), and
        without the cache every gallery redraw re-scanned the same folder
        once per classifier call - several scans per entry per refresh. The
        dict itself is deliberately NOT mutated: the signature tuple in
        _refresh_history_view hashes entry contents, and an extra key would
        both leak into comparisons and never match across fresh DB reads.
        """
        path = str(entry.get("filepath") or "")
        if path and os.path.isdir(path):
            try:
                cache = getattr(self, "_history_folder_cache", None)
                if cache is None:
                    cache = self._history_folder_cache = {}
                if path in cache:
                    return cache[path]
                resolved = downloader.pick_produced_media_file(path) or ""
                cache[path] = resolved
                # Folders come and go; an unbounded cache of dead paths is a
                # slow leak, so cap it well above any real history size.
                if len(cache) > 512:
                    try:
                        cache.pop(next(iter(cache)))
                    except Exception:
                        pass
                path = resolved
            except Exception:
                path = ""
        return path

    def _entry_video_kind(self, entry) -> str:
        """'video' or 'audio' from the actual file, never the flag alone.

        A recognized extension always decides (an .mp4 is a video even when
        history says otherwise); the flag only breaks ties for containers
        not listed above.
        """
        path = self._entry_resolved_path(entry)
        ext = os.path.splitext(path)[1].lower()
        if ext in self._GALLERY_AUDIO_EXTS:
            return "audio"
        if ext in self._GALLERY_VIDEO_EXTS:
            return "video"
        return "video" if entry.get("is_video") else "audio"

    def _entry_video_path(self, entry) -> Optional[str]:
        """The existing local video file to grab a frame from, or None."""
        if self._entry_video_kind(entry) != "video":
            return None
        path = self._entry_resolved_path(entry)
        if not path or not os.path.isfile(path):
            return None
        return path

    def _entry_audio_path(self, entry):
        """The existing local audio file to pull cover art from, or None."""
        if self._entry_video_kind(entry) != "audio":
            return None
        path = self._entry_resolved_path(entry)
        if not path or not os.path.isfile(path):
            return None
        return path


    def _render_history_gallery(self, shown):
        """Draw the poster grid for *shown* and kick off thumbnail loading."""
        grid = ctk.CTkFrame(self._history_entries_frame, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=4, pady=4)
        cols = self._gallery_column_count()

        row = None
        pending = []  # (kind, media_path, image_label) needing a poster
        for i, entry in enumerate(shown):
            if i % cols == 0:
                row = ctk.CTkFrame(grid, fg_color="transparent")
                row.pack(fill="x", pady=(0, self._GALLERY_PAD))
            vid = self._entry_video_path(entry)
            aud = self._entry_audio_path(entry)
            tile, img_lbl = self._build_gallery_tile(row, entry)
            tile.pack(side="left", padx=(0, self._GALLERY_PAD))
            if img_lbl is not None:
                if vid:
                    pending.append(("video", vid, img_lbl))
                elif aud:
                    pending.append(("audio", aud, img_lbl))
        if pending:
            self._start_worker(lambda: self._load_gallery_thumbs(pending))

    def _gallery_column_count(self) -> int:
        """How many tiles fit across, from the scroll viewport width."""
        try:
            inner = int(self.history_scroll._parent_canvas.winfo_width()) - 40
        except Exception:
            inner = 800
        tile_w = self._GALLERY_TILE_W + self._GALLERY_PAD
        return max(1, inner // tile_w)

    def _build_gallery_tile(self, parent, entry):
        """One poster tile; returns (tile, image_label_or_None).

        The image label exists for any entry whose file is still on disk:
        videos get an ffmpeg frame, audio gets embedded/sidecar cover art.
        """
        w = self._GALLERY_TILE_W
        title = entry.get("title") or entry.get("url", "")[:48] or "Unknown"
        filepath = str(entry.get("filepath") or "")
        # Decided from the real file, not entry["is_video"] - see
        # _entry_video_kind. Feeding the kind into _redownload also fixes a
        # mis-flagged .mp4 re-downloading as if it were audio.
        is_video = self._entry_video_kind(entry) == "video"
        vid = self._entry_video_path(entry)
        tile = ctk.CTkFrame(parent, width=w, corner_radius=UITheme.RADIUS_MD)

        # Poster area: a fixed-size well so tiles stay aligned while posters
        # load, and so a slow ffmpeg grab never reflows the grid.
        poster = ctk.CTkFrame(tile, height=self._GALLERY_THUMB_H,
                              corner_radius=UITheme.RADIUS_SM,
                              fg_color=("#2b2b2b", "#1f1f1f"))
        poster.pack(fill="x", padx=6, pady=(6, 0))
        poster.pack_propagate(False)
        img_lbl = None
        kind = self._entry_video_kind(entry)
        audio_path = self._entry_audio_path(entry)
        if vid or audio_path:
            img_lbl = ctk.CTkLabel(poster, text="...", font=UITheme.F(9),
                                   text_color="#95a5a6")
            img_lbl.pack(expand=True)
        else:
            # Neutral placeholder keeps the grid complete for entries whose
            # file has since been moved or deleted.
            label = "Video" if is_video else ("Audio" if kind == "audio" else "?")
            ctk.CTkLabel(poster, text=label, font=UITheme.F(10),
                         text_color="#7f8c8d").pack(expand=True)

        ctk.CTkLabel(tile, text=title, font=UITheme.F(10), anchor="w",
                     wraplength=w - 16, justify="left",
                     height=UITheme.H_CTRL).pack(fill="x", padx=8, pady=(4, 2))

        # The same two actions a list row offers: open the file, re-download.
        actions = ctk.CTkFrame(tile, fg_color="transparent")
        actions.pack(fill="x", padx=6, pady=(0, 6))
        btn_open = ctk.CTkButton(actions, text="Open", width=70,
                                 height=UITheme.H_SM, font=UITheme.F(9),
                                 command=lambda p=filepath: self._open_file(p))
        btn_open.pack(side="left", expand=True, fill="x", padx=(0, 3))
        btn_dl = ctk.CTkButton(
            actions, text="Re-download", width=84, height=UITheme.H_SM,
            font=UITheme.F(9),
            command=lambda u=entry.get("url", ""), v=is_video:
                self._redownload(u, v))
        btn_dl.pack(side="left", expand=True, fill="x")
        if vid:
            tile.bind("<Button-1>", lambda e, p=vid: self._open_file(p))
        return tile, img_lbl

    def _load_gallery_thumbs(self, pending):
        """Worker: grab posters per tile, then apply images on the UI thread.

        Runs off-thread (thumbnail extraction is an ffmpeg subprocess, cover
        reads parse the audio files). Only plain Pillow images are built
        here: CTkImage wraps a Tk photo image and MUST be created on the UI
        thread, so the worker hands Pillow images back and the single
        after(0) batch constructs each CTkImage just before configuring its
        label. One batch, not one callback per tile: N separate after(0)
        callbacks mean N separate event-loop wakes, each painting an
        intermediate grid state (tile 1 filled, tiles 2..N still "..."),
        which reads as flicker. The batch applies only to tiles still alive
        - a refresh or page switch may have destroyed some between
        scheduling and application. The CTkImages are pinned on the labels
        (``_gallery_photo``) so Tk never holds a freed bitmap.
        """
        Image = downloader._mod_image()
        ctk_image = getattr(ctk, "CTkImage", None)
        if Image is None or ctk_image is None:
            # No Pillow: tiles keep their placeholder text, still usable.
            logger.debug("Gallery posters unavailable (Pillow missing)")
            return
        size = (self._GALLERY_TILE_W - 12, self._GALLERY_THUMB_H)
        ready = []    # (img_lbl, PIL-display-image) successfully built
        missing = []  # img_lbl with no producible poster
        for item in pending:
            if len(item) == 3:
                kind, path, img_lbl = item
            else:
                kind, path, img_lbl = "video", item[0], item[1]
            disp = None
            try:
                if kind == "audio":
                    thumb_path = (
                        downloader.extract_audio_artwork(path)
                        if path and os.path.exists(path) else None)
                else:
                    thumb_path = (
                        downloader.extract_video_thumbnail(path)
                        if path and os.path.exists(path) else None)
                if thumb_path and os.path.exists(thumb_path):
                    img = Image.open(thumb_path)
                    img.load()
                    disp = img.convert("RGB").resize(size)
            except Exception:
                logger.debug("Gallery thumb failed for %s", path,
                             exc_info=True)
            if disp is None:
                missing.append(img_lbl)
            else:
                ready.append((img_lbl, disp))
        if not ready and not missing:
            return
        # One trip to the UI thread for the whole grid. Dead tiles are
        # skipped; a label the user cannot see is left alone rather than
        # touched. Pinning first keeps the bitmap alive past this callback.
        def _apply():
            for img_lbl, disp_img in ready:
                try:
                    if not img_lbl.winfo_exists():
                        continue
                    tk_img = ctk_image(light_image=disp_img,
                                       dark_image=disp_img, size=size)
                    img_lbl._gallery_photo = tk_img
                    img_lbl.configure(image=tk_img, text="")
                except Exception:
                    pass
            for img_lbl in missing:
                # Nothing producible (ffmpeg/Pillow failed, or the file went
                # away since the grid was drawn): say so instead of leaving
                # the "..." well waiting forever.
                try:
                    if img_lbl.winfo_exists():
                        img_lbl.configure(text="No preview")
                except Exception:
                    pass
        try:
            self.after(0, _apply)
        except Exception:
            logger.debug("Gallery poster apply skipped (window closing)",
                         exc_info=True)

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
            try:
                import library_db
                library_db.prune_missing()
            except Exception:
                logger.debug("Library prune skipped", exc_info=True)
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
        history = self._history_entries() or []
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
            try:
                import library_db
                library_db.clear()
            except Exception:
                logger.debug("Library clear skipped", exc_info=True)
            self._refresh_history_view()
            self.show_toast("History cleared", "success")
        except Exception as e:
            self._show_error_dialog("Clear History", "Could not clear the history.",
                                    detail=str(e))


