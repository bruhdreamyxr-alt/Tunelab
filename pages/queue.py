"""The Download Queue page: everything that builds and drives tab_queue.
Extracted from ui.py so the shell stops growing - the methods are
mixed into UniversalAudioStudio and keep their exact names."""

import logging
import os
import tkinter as tk
from typing import Any

import customtkinter as ctk
from ui_theme import UITheme
from ui_widgets import _QueueRowList
import downloader
import download_queue


logger = logging.getLogger("universal_audio_studio.pages.queue")


class QueuePageMixin:
    """The Download Queue page: everything that builds and drives tab_queue."""

    # Names the shell (or another page) owns: declared so the type
    # checker can see them from here, the convention ui_widgets uses.
    _bump_completion_badge: Any
    _last_downloaded_file: Any
    _refresh_tag_target: Any
    _set_nav_badge: Any
    _style_button: Any
    after: Any
    btn_edit_tags: Any
    show_toast: Any
    tab_queue: Any
    update_dl_status: Any


    def _init_queue_manager(self):
        if self._queue_initialized:
            return
        self._queue_initialized = True
        try:
            self._queue_manager = download_queue.DownloadQueue(
                download_fn=downloader.download_track,
                video_fn=downloader.download_video_mp4,
                find_file_fn=downloader._find_latest_mp3,
                save_folder_fn=downloader.get_download_folder,
            )
            self._queue_manager.set_callbacks(
                on_item_complete=self._on_queue_item_complete,
                on_queue_done=lambda: self.after(0, self._refresh_queue_tab),
                on_progress=self._on_queue_progress)
            # Re-fill the queue with items left pending from the previous session.
            restored = self._queue_manager.restore()
            if restored:
                logger.debug("Restored %d item(s) into the queue", restored)
                self._refresh_queue_tab()
            # Keep the SQLite library in step with every history write.
            try:
                import library_db
                download_queue.set_history_sink(library_db.record)
            except Exception:
                logger.debug("Library sink not attached", exc_info=True)
        except Exception as e:
            logger.debug("Queue manager init failed: %s", e)

    def _on_queue_item_complete(self, status, item):
        def _do():
            if status == "done":
                self._last_downloaded_file = getattr(item, 'filepath', None) or self._last_downloaded_file
                self.btn_edit_tags.configure(state="normal")
                self._refresh_tag_target()
                self.update_dl_status(f"Downloaded: {os.path.basename(str(item.filepath) if item.filepath else '')}", "#2ecc71")
                self._bump_completion_badge()
        self.after(0, _do)
        # This callback runs on the queue worker thread; never touch Tk directly.
        self.after(0, self._refresh_queue_tab)

    def _on_queue_progress(self, item, pct=None, text=None):
        """Called from the queue worker thread; refresh the queue display."""
        if pct is not None:
            item._progress = pct
        self._schedule_queue_refresh()

    def _schedule_queue_refresh(self):
        """Coalesce refresh storms from the worker thread.

        yt-dlp fires progress callbacks many times a second; queueing one
        full refresh per event flooded the Tk event loop (visible stutter)
        for updates the eye cannot resolve anyway. At most one refresh per
        ~120 ms keeps the display smooth for a fraction of the cost.
        """
        if self._queue_refresh_pending:
            return
        self._queue_refresh_pending = True

        def _run():
            self._queue_refresh_pending = False
            self._refresh_queue_tab()

        self.after(120, _run)

    def _refresh_queue_tab(self):
        try:
            self._rebuild_queue_list()
        except Exception:
            pass

    def build_queue_view(self):
        # Page title lives in the header only — no in-page H1.

        # Themed row list (CTk labels) replacing the raw tk.Listbox, so the
        # queue follows the active palette like every other widget.
        pal = getattr(self, "_palette", {}) or {}
        self.queue_rows = _QueueRowList(self.tab_queue, palette=pal)

        # Bottom toolbar: packed FIRST so it claims its space at the bottom
        # and stays visible at any window height. The listbox below then fills
        # whatever vertical room remains (fill="both", expand=True).
        #
        # Buttons are trimmed to the essentials (Start / Skip / Remove /
        # Clear Done). Up, Down, Retry, Cancel and Clear move to a secondary
        # row so the primary bar never overflows on narrow windows.
        queue_btn_row = ctk.CTkFrame(self.tab_queue, fg_color="transparent")
        queue_btn_row.pack(side="bottom", fill="x", padx=UITheme.PAD_X, pady=(6, 10))

        self.btn_queue_start = ctk.CTkButton(
            queue_btn_row, text="Start", width=72, height=UITheme.H_CTRL,
            command=self._queue_start)
        self.btn_queue_start.pack(side="left", padx=3)
        self._style_button(self.btn_queue_start, "primary", icon="play")

        # Ghost utilities: act on the selected row.
        self.btn_queue_skip = ctk.CTkButton(
            queue_btn_row, text="Skip", width=52, height=UITheme.H_CTRL,
            command=self._queue_skip_selected)
        self.btn_queue_skip.pack(side="left", padx=3)
        self._style_button(self.btn_queue_skip, "ghost", bordered=True, icon="skip")

        self.btn_queue_remove = ctk.CTkButton(
            queue_btn_row, text="Remove", width=62, height=UITheme.H_CTRL,
            command=self._queue_remove_selected)
        self.btn_queue_remove.pack(side="left", padx=3)
        self._style_button(self.btn_queue_remove, "danger", icon="trash")

        self.btn_queue_clear_done = ctk.CTkButton(
            queue_btn_row, text="Clear Done", width=72, height=UITheme.H_CTRL,
            command=self._queue_clear_completed)
        self.btn_queue_clear_done.pack(side="left", padx=3)
        self._style_button(self.btn_queue_clear_done, "danger", icon="check")

        # Secondary row: less-frequent actions, kept out of the primary bar
        # so it stays narrow enough to fit at any window width.
        queue_btn_row2 = ctk.CTkFrame(self.tab_queue, fg_color="transparent")
        queue_btn_row2.pack(side="bottom", fill="x", padx=UITheme.PAD_X, pady=(0, 6))

        self.btn_queue_up = ctk.CTkButton(
            queue_btn_row2, text="Up", width=44, height=UITheme.H_CTRL,
            command=lambda: self._queue_move_selected(-1))
        self.btn_queue_up.pack(side="left", padx=3)
        self._style_button(self.btn_queue_up, "ghost", bordered=True, icon="chevron_up")

        self.btn_queue_down = ctk.CTkButton(
            queue_btn_row2, text="Down", width=52, height=UITheme.H_CTRL,
            command=lambda: self._queue_move_selected(1))
        self.btn_queue_down.pack(side="left", padx=3)
        self._style_button(self.btn_queue_down, "ghost", bordered=True, icon="chevron_down")

        self.btn_queue_retry = ctk.CTkButton(
            queue_btn_row2, text="Retry", width=60, height=UITheme.H_CTRL,
            command=self._queue_retry_failed)
        self.btn_queue_retry.pack(side="left", padx=3)
        self._style_button(self.btn_queue_retry, "ghost", bordered=True, icon="refresh")

        self.btn_queue_cancel = ctk.CTkButton(
            queue_btn_row2, text="Cancel", width=62, height=UITheme.H_CTRL,
            command=self._queue_cancel_all)
        self.btn_queue_cancel.pack(side="left", padx=3)
        self._style_button(self.btn_queue_cancel, "danger", icon="close")

        self.btn_queue_clear = ctk.CTkButton(
            queue_btn_row2, text="Clear", width=52, height=UITheme.H_CTRL,
            command=self._queue_clear)
        self.btn_queue_clear.pack(side="left", padx=3)
        self._style_button(self.btn_queue_clear, "danger", icon="trash")

        # Listbox fills all remaining space above the toolbar.
        self.queue_rows.pack(pady=(14, 0), padx=UITheme.PAD_X,
                             fill="both", expand=True)

        self.queue_status = ctk.CTkLabel(self.tab_queue, text="Idle", font=UITheme.F(11),
                                         text_color=(getattr(self, "_palette", {}) or {}).get("sub", "#95a5a6"))
        self.queue_status.pack(pady=(6, 0))

        self.tab_queue.place(relx=0, rely=0, relwidth=1, relheight=1)

    @staticmethod
    def _queue_row_label(idx, item, active_idx):
        """Format one queue row; kept pure so tests can pin the rendering."""
        icon = {"pending": "○", "active": "▶", "done": "✓", "failed": "✗",
                "skipped": "⊘", "cancelled": "⊘"}.get(item.status, "○")
        # Name the track, not the address. The queue already resolved a title
        # for anything it has downloaded, and the History tab has been showing
        # it all along - so a row that fell back to a raw URL was displaying
        # less than the app already knew. A pending item has no title yet, and
        # the URL it was pasted as is the only honest thing to show.
        title = str(getattr(item, "title", "") or "").strip()

        def _clip(text, n):
            # A hard cut reads as the whole title; the ellipsis says the row
            # is only showing the head of it.
            return text if len(text) <= n else text[:n - 1] + "…"

        # Show progress hint for the active item (e.g. "▶ [ACTIVE] 45% ...").
        if idx == active_idx and item.status == "active":
            progress = getattr(item, '_progress', None)
            pct = f" {int(progress*100)}%" if progress is not None else ""
            subject = title or item.url
            return f"{icon} [ACTIVE]{pct} {_clip(subject, 45)}"
        subject = title or item.url
        return f"{icon} [{item.status.upper():>9}] {_clip(subject, 50)}"

    def _rebuild_queue_list(self):
        lb = self.queue_rows
        if not self._queue_manager:
            lb.delete(0, tk.END)
            self._queue_show_empty_placeholder()
            self._update_queue_status()
            return
        active_idx = self._queue_manager.active_index
        labels = [self._queue_row_label(i, item, active_idx)
                  for i, item in enumerate(self._queue_manager.items)]
        if not labels:
            lb.delete(0, tk.END)
            self._queue_show_empty_placeholder()
        elif lb.size() != len(labels):
            lb.delete(0, tk.END)
            for label in labels:
                lb.insert(tk.END, label)
        else:
            # Same row count (the usual progress-tick case): touch only the
            # rows whose text changed. The old delete-everything + re-insert
            # ran on every yt-dlp progress callback — it flooded the event
            # loop (stutter), repainted the whole list, and threw away the
            # selection on every tick.
            for i, label in enumerate(labels):
                if lb.get(i) != label:
                    lb.itemconfig(i, text=label)
        self._update_queue_status()

    def _queue_show_empty_placeholder(self):
        """Fill the blank row list with a hint so an empty queue reads as
        'nothing here yet' instead of a dead panel."""
        pal = getattr(self, "_palette", {}) or {}
        self.queue_rows.insert(
            tk.END, "  Queue is empty — paste links on the Downloader page")
        try:
            self.queue_rows.itemconfig(0, foreground=pal.get("sub", "#95a5a6"))
        except Exception:
            pass

    def _update_queue_status(self):
        """Status line: "3 of 5 items • 60% • Active"."""
        items = self._queue_manager.items if self._queue_manager else []
        total = len(items)
        done = sum(1 for it in items if it.status in ("done", "failed", "skipped"))
        overall = int((done / total) * 100) if total else 0
        running = bool(self._queue_manager and self._queue_manager.is_running)
        self.queue_status.configure(
            text=f"{done}/{total} items • {overall}% • {'Active' if running else 'Idle'}")
        # Same number in the rail's right slot, so the collapsed rail still
        # reports work waiting for its turn (0 clears back to the "2" digit).
        self._set_nav_badge('queue', max(0, total - done))

    def _queue_start(self):
        self._init_queue_manager()
        if self._queue_manager and self._queue_manager.items and not self._queue_manager.is_running:
            self._queue_manager.start()
            self._refresh_queue_tab()

    def _queue_cancel_all(self):
        if self._queue_manager:
            self._queue_manager.cancel()
            self._refresh_queue_tab()

    def _queue_selected_index(self):
        """Index of the highlighted queue row, or None when nothing is selected."""
        try:
            selection = self.queue_rows.curselection()
        except Exception:
            return None
        if not selection:
            return None
        return int(selection[0])

    def _queue_skip_selected(self):
        index = self._queue_selected_index()
        if index is None:
            self.show_toast("Select a queue item first.", "info")
            return
        self._init_queue_manager()
        if self._queue_manager and self._queue_manager.skip(index):
            self._refresh_queue_tab()

    def _queue_move_selected(self, delta: int):
        index = self._queue_selected_index()
        if index is None:
            self.show_toast("Select a queue item first.", "info")
            return
        self._init_queue_manager()
        if not (self._queue_manager and self._queue_manager.move(index, delta)):
            # The only reason a waiting item cannot move is its neighbour, and
            # the only neighbour that cannot move is the one in flight.
            self.show_toast("Only waiting items can be reordered.", "info")
            return
        self._refresh_queue_tab()
        try:
            self.queue_rows.select_set(index + delta)
        except Exception:
            pass

    def _queue_clear(self):
        if self._queue_manager:
            self._queue_manager.clear()
            self._refresh_queue_tab()

    def _queue_clear_completed(self):
        """Remove all done/failed/skipped items from the queue."""
        if not self._queue_manager:
            return
        cleared = self._queue_manager.clear_completed()
        if cleared:
            self._refresh_queue_tab()
            self.show_toast(f"Cleared {cleared} item(s)", "success")
        else:
            self.show_toast("Nothing to clear", "info")

    def _queue_remove_selected(self):
        if not self._queue_manager:
            return
        if not getattr(self._queue_manager, "items", None):
            # Only the empty-state placeholder row is in the list.
            return
        sel = self.queue_rows.curselection()
        if not sel:
            self.show_toast("Select an item to remove", "warning")
            return
        # Remove by index; iterate in reverse if multiple selected (browse mode = single).
        for idx in reversed(sel):
            self._queue_manager.remove_at(idx)
        self._refresh_queue_tab()

    def _queue_retry_failed(self):
        if not self._queue_manager:
            return
        reset = self._queue_manager.retry_failed()
        if reset:
            self._refresh_queue_tab()
            self.show_toast(f"Retrying {reset} item(s)", "success")
        else:
            self.show_toast("No failed items to retry", "info")


