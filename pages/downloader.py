"""The Downloader page: URL entry, MP3/MP4 download, cancel, preview, prefs.

Extracted from ui.py in stages (see DOWNLOADER_EXTRACTION_PLAN.md). This
first pass is a stub mixin that only declares the names the shell owns; the
handlers and builders move here in later steps.
"""

import logging
import os
import threading
from tkinter import filedialog
from typing import Any

import customtkinter as ctk
import downloader
from ui_theme import UITheme

logger = logging.getLogger("universal_audio_studio.pages.downloader")


class DownloaderPageMixin:
    """The Downloader page, mixed into UniversalAudioStudio."""

    # Names the shell (or another page) owns: declared so the type checker
    # can see them from here, the convention ui_widgets uses.
    _init_queue_manager: Any
    _last_dl_url: Any
    _last_dl_was_video: Any
    _last_downloaded_file: Any
    _last_title_pct: Any
    _map_color: Any
    _prefs: Any
    _progress_row: Any
    _queue_manager: Any
    _split_input_urls: Any
    _track_search_after: Any
    _track_search_generation: Any
    _refresh_tag_target: Any
    _set_pref: Any
    _show_error_dialog: Any
    _start_worker: Any
    _style_button: Any
    _ui_closed: Any
    _unfocused_done: Any
    _url_clear_btn_visible: Any
    after: Any
    btn_cancel_download: Any
    btn_clear_url: Any
    btn_download_mp3: Any
    btn_download_mp4: Any
    btn_edit_tags: Any
    _dl_format: Any
    dl_progress_status: Any
    dl_detail: Any
    dl_status: Any
    focus_displayof: Any
    fmt_option: Any
    progress_bar: Any
    quit: Any
    destroy: Any
    save_folder_lbl: Any
    show_frame: Any
    show_toast: Any
    tab_downloader: Any
    title: Any
    update_dl_status: Any
    url_entry: Any

    def _update_save_folder_label(self):
        try:
            folder = downloader.get_download_folder()
            text = folder
            if len(text) > 40:
                text = text[:18] + "…" + text[-18:]
            self.save_folder_lbl.configure(text=text)
            # Full path as tooltip via title attribute (best effort).
            try:
                self.save_folder_lbl.configure(tooltip_text=folder)
            except Exception:
                pass
        except Exception:
            logger.debug("Save-folder label update failed", exc_info=True)



    def _choose_save_folder(self):
        start = downloader.get_download_folder()
        choice = filedialog.askdirectory(
            initialdir=start if os.path.isdir(start) else os.path.expanduser("~"),
            title="Choose where downloads are saved",
        )
        if not choice:
            return
        downloader.set_download_folder(choice)
        self._set_pref('save_folder', choice)
        self._update_save_folder_label()
        self.update_dl_detail(f"New downloads will be saved to:\n{choice}", "#95a5a6")

    def _on_audio_format_change(self, label):
        reverse = {p['label']: key for key, p in downloader.AUDIO_FORMATS.items()}
        key = reverse.get(label, 'mp3_vbr')
        downloader.set_audio_format(key)
        self._set_pref('audio_format', key)
        fmt_info = downloader.AUDIO_FORMATS.get(key)
        fmt_label = fmt_info.get('label', key) if fmt_info else key
        try:
            if hasattr(self, 'fmt_option'):
                self.fmt_option.set(fmt_label)
        except Exception:
            pass



    def _do_self_restart(self):
        """Graceful shutdown so the updater can replace the running EXE."""
        self._ui_closed = True
        try:
            self.quit()
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    def _cancel_active_download(self):
        """Ask the running download worker to stop (cooperative cancellation)."""
        requested = downloader.request_cancel_download()
        if not requested:
            return
        self.update_dl_status("Cancelling...", "#f39c12")
        self.update_dl_detail("Waiting for the current download to stop...", "#95a5a6")
        self.btn_cancel_download.configure(state="disabled")

    def on_dl_cancelled(self):
        self.after(0, lambda: self._finalize_download(None, "__cancelled__"))

    def update_dl_detail(self, text, color):
        themed = self._map_color(color)
        self.after(0, lambda: self.dl_detail.configure(text=text, text_color=themed))

    def _show_progress_row(self, visible: bool) -> None:
        """Show the progress bar + Cancel only while a download is running."""
        def _apply():
            row = getattr(self, "_progress_row", None)
            pill = getattr(self, "_status_pill", None)
            context = getattr(self, "dl_context_frame", None)
            if row is None:
                return
            try:
                if visible:
                    self._track_search_generation = getattr(
                        self, "_track_search_generation", 0) + 1
                    pending = getattr(self, "_track_search_after", None)
                    if pending:
                        try:
                            self.after_cancel(pending)
                        except Exception:
                            logger.debug("Could not cancel pending track search",
                                         exc_info=True)
                        self._track_search_after = None
                    if context is not None and context.winfo_manager():
                        context.pack_forget()
                    if pill is not None and pill.winfo_manager():
                        pill.pack_forget()
                    if not row.winfo_manager():
                        row.pack(fill="x", padx=UITheme.PAD_X,
                                 pady=(0, UITheme.RHYTHM))
                else:
                    if pill is not None and not pill.winfo_manager():
                        pill.pack(before=row, padx=UITheme.PAD_X,
                                  pady=(0, UITheme.RHYTHM))
                    if row.winfo_manager():
                        row.pack_forget()
                    if (context is not None
                            and not context.winfo_manager()):
                        context.pack(
                            fill="both", expand=True, padx=UITheme.PAD_X,
                            pady=(UITheme.RHYTHM, 8))
                        self._schedule_track_search()
            except Exception:
                logger.debug("Could not toggle the progress row",
                             exc_info=True)

        self.after(0, _apply)

    def _retry_last_download(self):
        """Re-run the last download with the same URL and audio/video mode."""
        try:
            url = (self.url_entry.get() or "").strip() or self._last_dl_url
        except Exception:
            url = self._last_dl_url
        if not url:
            self.show_toast("Nothing to retry — paste a link first", "warning")
            return
        self.show_frame("downloader")
        try:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            self._on_url_changed()
        except Exception:
            pass
        if getattr(self, "_last_dl_was_video", False):
            self._start_worker(self.download_mp4)
        else:
            self._start_worker(self.download_mp3)

    def set_download_buttons_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        label = "Download" if enabled else "Downloading..."
        self.after(0, lambda: self.btn_download.configure(state=state, text=label))
        cancel_state = "disabled" if enabled else "normal"
        try:
            self.after(0, lambda: self.btn_cancel_download.configure(state=cancel_state))
        except Exception:
            pass
        self._show_progress_row(not enabled)

    def _sync_clear_btn(self):
        """Show the inline ✕ only while the URL box has text."""
        try:
            self._sync_download_status()
            show = bool(self.url_entry.get().strip())
            if show == self._url_clear_btn_visible:
                return
            self._url_clear_btn_visible = show
            if show:
                self.btn_clear_url.place(relx=1.0, rely=0.5, anchor="e", x=-6)
            else:
                self.btn_clear_url.place_forget()
        except Exception:
            pass

    def _sync_download_status(self):
        """Keep the one status line useful without echoing the entered source."""
        raw = self.url_entry.get().strip()
        if not raw:
            status = "Paste a link or search a song to begin"
        else:
            status = ("Ready to add links to the queue."
                      if len(self._split_input_urls(raw)) > 1
                      else "Ready to download.")
        if (not self._progress_row.winfo_manager()
                and self.dl_status.cget("text") != status):
            self.update_dl_status(status, "#95a5a6")

    def _on_url_changed(self):
        """Sync the URL controls and debounce title-search suggestions."""
        self._sync_clear_btn()
        self._schedule_track_search()

    def _schedule_track_search(self):
        raw = self.url_entry.get().strip()
        provider = str(
            self.track_search_provider_var.get()).strip().lower()
        provider_key = "soundcloud" if provider == "soundcloud" else "youtube"
        self._track_search_generation = getattr(
            self, "_track_search_generation", 0) + 1
        generation = self._track_search_generation
        pending = getattr(self, "_track_search_after", None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                logger.debug("Could not cancel pending track search",
                             exc_info=True)
            self._track_search_after = None

        if not raw:
            self._show_track_search_message(
                "Paste a link above, or search for a track on YouTube or SoundCloud.")
            return
        urls = self._split_input_urls(raw)
        if urls:
            message = ("Multiple links detected. Add them to the queue."
                       if len(urls) > 1
                       else "Link ready. Choose a format and download, or add it to the queue.")
            self._show_track_search_message(message)
            return
        if len(raw) < 2:
            self._show_track_search_message(
                f"Keep typing to search {provider} (at least 2 characters).")
            return
        if str(self.btn_download.cget("state")) == "disabled":
            self._show_track_search_message(
                "Search suggestions are paused while a download is running.")
            return

        self._show_track_search_message(f"Searching {provider}…")
        self._track_search_after = self.after(
            450, lambda: self._start_track_search(
                raw, generation, provider_key))

    def _on_track_search_provider_change(self, _value=None):
        self._schedule_track_search()

    def _start_track_search(self, query: str, generation: int,
                            provider: str = "youtube"):
        self._track_search_after = None

        def _search():
            try:
                results = downloader.search_tracks(
                    query, limit=3, provider=provider)
                error = None
            except Exception as exc:
                logger.warning("%s search suggestions failed: %s",
                               provider, exc, exc_info=True)
                results = []
                error = exc
            try:
                self.after(
                    0, lambda: self._show_track_search_results(
                        query, generation, provider, results, error))
            except Exception:
                logger.debug("Could not display track search suggestions",
                             exc_info=True)

        try:
            threading.Thread(
                target=_search, daemon=True,
                name=f"{provider}-track-search").start()
        except Exception as exc:
            logger.exception("Could not start %s search suggestions", provider)
            self._show_track_search_results(
                query, generation, provider, [], exc)

    def _show_track_search_message(self, message: str):
        self.dl_context_title.configure(text="Discover music")
        self.dl_context_hint.configure(text=message)
        for child in self.dl_search_results.winfo_children():
            child.destroy()

    def _show_track_search_results(self, query, generation, provider,
                                   results, error):
        if generation != self._track_search_generation:
            return
        if self.url_entry.get().strip() != query:
            return
        if provider != str(
                self.track_search_provider_var.get()).strip().lower():
            return
        if str(self.btn_download.cget("state")) == "disabled":
            return
        for child in self.dl_search_results.winfo_children():
            child.destroy()
        provider_title = (
            "SoundCloud" if provider == "soundcloud" else "YouTube")
        self.dl_context_title.configure(text=f"{provider_title} results")
        if error is not None:
            self.dl_context_hint.configure(
                text=(f"{provider_title} search is unavailable right now. "
                      "You can still paste a link."))
            return
        if not results:
            self.dl_context_hint.configure(
                text=(f"No {provider_title} matches found. Try another title "
                      "or paste a link."))
            return
        self.dl_context_hint.configure(
            text=f"{len(results)} matches · Choose a track to use its link.")
        palette = getattr(self, "_palette", {}) or {}
        for index, result in enumerate(results, start=1):
            row = ctk.CTkFrame(
                self.dl_search_results,
                fg_color=palette.get("surface", UITheme.SURFACE_BG),
                corner_radius=UITheme.RADIUS_MD,
                border_width=1,
                border_color=palette.get("hover", UITheme.SIDEBAR_HOVER),
            )
            setattr(row, "_theme_roles",
                    {"fg_color": "surface", "border_color": "hover"})
            row.pack(fill="x", pady=3)
            rank = ctk.CTkLabel(
                row, text=f"{index:02}", width=34,
                font=UITheme.F(11, "bold"),
                text_color=palette.get("accent", UITheme.COLOR_PRIMARY),
            )
            setattr(rank, "_theme_roles", {"text_color": "accent"})
            rank.pack(side="left", padx=(10, 4), pady=8)
            text_frame = ctk.CTkFrame(row, fg_color="transparent")
            text_frame.pack(side="left", fill="x", expand=True,
                            padx=(2, 8), pady=7)
            title_label = ctk.CTkLabel(
                text_frame, text=result["title"], font=UITheme.F(12, "bold"),
                anchor="w", justify="left", wraplength=360,
            )
            setattr(title_label, "_theme_roles", {"text_color": "text"})
            title_label.pack(fill="x")
            details = [str(result.get("uploader") or provider_title)]
            duration = result.get("duration")
            if isinstance(duration, (int, float)) and duration >= 0:
                seconds = int(duration)
                if seconds >= 3600:
                    duration_text = (
                        f"{seconds // 3600}:{(seconds % 3600) // 60:02}:"
                        f"{seconds % 60:02}")
                else:
                    duration_text = f"{seconds // 60}:{seconds % 60:02}"
                details.append(duration_text)
            details_label = ctk.CTkLabel(
                text_frame, text=" · ".join(details), font=UITheme.F(10),
                text_color=palette.get("sub", "#95a5a6"),
                anchor="w", wraplength=360,
            )
            setattr(details_label, "_theme_roles", {"text_color": "sub"})
            details_label.pack(fill="x")
            select = ctk.CTkButton(
                row, text="Use track", width=92, height=UITheme.H_SM,
                command=lambda item=result: self._use_track_search_result(item),
            )
            select.pack(side="right", padx=10, pady=8)
            self._style_button(select, "primary")

    def _use_track_search_result(self, result):
        url = str(result.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            logger.warning("Ignoring search result without a valid URL")
            self._show_track_search_message(
                "That result did not include a usable link. Try another match.")
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self._on_url_changed()
        self.url_entry.focus_set()

    def download_mp3(self):
        self._dl_finalized = False
        url = downloader.clean_url(self.url_entry.get().strip())
        if not url:
            return
        self._last_dl_url = url
        self._last_dl_was_video = False
        self._last_downloaded_file = None
        self.set_download_buttons_state(False)
        self.progress_bar.set(0)
        self.update_dl_status("Downloading audio...", "#3498db")
        self.update_dl_detail("", "#95a5a6")
        downloader.begin_download_session()
        try:
            downloader.download_track(
                url,
                self.update_dl_status,
                self.on_dl_success,
                self.on_dl_error,
                progress_callback=self.update_progress_bar,
                detail_callback=self.update_dl_detail,
                soundcloud_direct_first=bool(self._prefs.get('soundcloud_direct_first', True)),
            )
        except downloader.DownloadCancelled:
            self.on_dl_cancelled()
        except Exception as e:
            logger.exception("MP3 download failed unexpectedly")
            self.on_dl_error(f"Unexpected download error: {e}")
        finally:
            self.set_download_buttons_state(True)
            if not getattr(self, "_dl_finalized", True):
                self._dl_timeout_id = self.after(2000, lambda: self._dl_timeout_check())

    def download_mp4(self):
        self._dl_finalized = False
        url = downloader.clean_url(self.url_entry.get().strip())
        if not url:
            return
        self._last_dl_url = url
        self._last_dl_was_video = True
        self._last_downloaded_file = None
        self.set_download_buttons_state(False)
        self.progress_bar.set(0)
        self.update_dl_status("Downloading video...", "#27ae60")
        downloader.begin_download_session()
        try:
            downloader.download_video_mp4(url, self.update_dl_status, self.on_dl_success, self.on_dl_error, progress_callback=self.update_progress_bar)
        except downloader.DownloadCancelled:
            self.on_dl_cancelled()
        except Exception as e:
            logger.exception("MP4 download failed unexpectedly")
            self.on_dl_error(f"Unexpected download error: {e}")
        finally:
            self.set_download_buttons_state(True)
            if not getattr(self, "_dl_finalized", True):
                self._dl_timeout_id = self.after(2000, lambda: self._dl_timeout_check())

    def on_dl_success(self, folder):
        # Cancel any pending timeout.
        tid = getattr(self, "_dl_timeout_id", None)
        if tid is not None:
            try:
                self.after_cancel(tid)
            except Exception:
                pass
            self._dl_timeout_id = None
        # Cancel any pending (deferred) error display.
        pending = getattr(self, "_pending_dl_error_id", None)
        if pending is not None:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
            self._pending_dl_error_id = None
        self.after(0, lambda: self._finalize_download(folder, None))

    def on_dl_error(self, err):
        # Defer the error so a fallback download that ultimately succeeds
        # (e.g. Instagram "no video formats" then a fallback) cancels it.
        try:
            self._pending_dl_error_id = self.after(1500, lambda: self._finalize_download(downloader.get_download_folder(), err))
        except Exception:
            self.after(0, lambda: self._finalize_download(None, err))

    def _finalize_download(self, folder, err):
        # Cancel any pending timeout.
        tid = getattr(self, "_dl_timeout_id", None)
        if tid is not None:
            try:
                self.after_cancel(tid)
            except Exception:
                pass
            self._dl_timeout_id = None
        self._dl_finalized = True
        self._pending_dl_error_id = None
        # Some extractors (e.g. Instagram) report "no video formats" for the
        # primary format selection but still download a fallback. If a file was
        # produced, treat it as success.
        if err and folder and os.path.isdir(str(folder)) and "no video formats" in str(err).lower():
            try:
                if any(os.path.isfile(os.path.join(str(folder), n))
                       for n in os.listdir(str(folder))):
                    err = None
            except Exception:
                pass
        if err == "__cancelled__":
            self.update_dl_status("Cancelled", "#f39c12")
            self.progress_bar.set(0)
            self.update_dl_detail("", "#95a5a6")
            # Remove leftover partial/fragment files from the cancelled download.
            try:
                folder = downloader.get_download_folder()
                for name in os.listdir(folder):
                    if ".part" in name:
                        try:
                            os.remove(os.path.join(folder, name))
                        except Exception:
                            pass
            except Exception:
                pass
            self.show_toast("Download cancelled", "warning")
        elif err:
            cleaned_err = downloader._strip_ansi(err) if hasattr(downloader, '_strip_ansi') else str(err)
            self.update_dl_status("Failed", "#e74c3c")
            self.progress_bar.set(0)
            headline = next((ln.strip() for ln in cleaned_err.splitlines()
                             if ln.strip()), "The download failed.")
            self._show_error_dialog(
                "Download Failed", headline, detail=cleaned_err,
                action_label="Try again", action_cb=self._retry_last_download)
        else:
            self.update_dl_status("Finished!", "#2ecc71")
            self.progress_bar.set(1.0)
            self.update_dl_detail(str(folder), "#95a5a6")
            self._bump_completion_badge()
            if folder and os.path.isdir(str(folder)):
                if getattr(self, "_last_dl_was_video", False):
                    vid_exts = {'.mp4', '.mkv', '.webm', '.mov', '.avi'}
                    cands = [os.path.join(str(folder), n) for n in os.listdir(str(folder))
                             if os.path.isfile(os.path.join(str(folder), n))
                             and os.path.splitext(n)[1].lower() in vid_exts]
                    downloaded_file = max(cands, key=os.path.getmtime) if cands else None
                else:
                    downloaded_file = self._newest_media_file(folder)
                if downloaded_file:
                    self._last_downloaded_file = downloaded_file
                    self._refresh_tag_target()
                    downloader._strip_zone_identifier(downloaded_file)
                    meta = downloader.get_last_dl_metadata()
                    if meta and downloaded_file.lower().endswith(('.mp3', '.flac')):
                        downloader.write_id3_tags(
                            downloaded_file,
                            artist=meta.get("artist", ""),
                            title=meta.get("title", ""),
                            album=meta.get("album", ""),
                            genre=meta.get("genre", ""),
                            year=meta.get("year", ""),
                            artwork_path=meta.get("artwork_path", ""),
                        )
            downloader.open_in_file_manager(str(folder))
            self._save_direct_download_to_history(folder, err,
                filepath=self._last_downloaded_file, is_video=self._last_dl_was_video)
            name = os.path.basename(self._last_downloaded_file or "") or "Download complete"
            self.show_toast(f"Saved  {name}", "success")
        self.title("TuneLab")
        self._last_title_pct = None
        self.set_download_buttons_state(True)

    def update_progress_bar(self, value):
        value = min(max(value, 0.0), 1.0)

        def _apply():
            self.progress_bar.set(value)
            pct = int(value * 100)
            if pct != getattr(self, "_last_title_pct", None):
                self._last_title_pct = pct
                self.title(f"TuneLab — {pct}%")
            try:
                self.dl_progress_text.configure(text=f"{pct}%")
            except Exception:
                pass

        self.after(0, _apply)

    def _bump_completion_badge(self):
        """Count downloads that finished while the window was unfocused."""
        try:
            if self.focus_displayof() is not None:
                return
        except Exception:
            return
        self._unfocused_done += 1
        try:
            self.title(f"TuneLab ({self._unfocused_done} new)")
        except Exception:
            pass

    @staticmethod
    def _newest_media_file(folder):
        """Return the path to the newest media file in *folder*, or None."""
        if not folder or not os.path.isdir(folder):
            return None
        return downloader.pick_produced_media_file(str(folder))

    def _save_direct_download_to_history(self, folder, err, filepath=None, is_video=False):
        """Save a direct (non-queue) download to the history file."""
        try:
            self._init_queue_manager()
            if not self._queue_manager:
                return
            url = self.url_entry.get().strip()
            if not url:
                return
            meta = downloader.get_last_dl_metadata() or {}
            resolved_path = filepath
            if not resolved_path:
                resolved_path = self._newest_media_file(folder)
            entry = {
                "url": url,
                "title": meta.get("title") or meta.get("artist") or url[:60],
                "status": "done" if not err else "failed",
                "filepath": str(resolved_path) if resolved_path else (str(folder) if folder else ""),
                "timestamp": __import__("time").time(),
                "completed_at": __import__("time").time(),
                "is_video": bool(is_video),
            }
            self._queue_manager.upsert_history_entry(entry)
        except Exception as e:
            logger.warning("Failed to save download to history: %s", e)

    def _on_dl_quality_change(self, label):
        if getattr(self, "_dl_format", None) and self._dl_format.get() == "video":
            self._set_pref('max_video_resolution', label)
            downloader.performance_config['max_video_resolution'] = label
            self.update_dl_detail(f"Video quality: {label}.", "#95a5a6")
        else:
            self._on_audio_format_change(label)

    def _dl_timeout_check(self):
        if getattr(self, "_dl_finalized", True):
            return
        self.after(0, lambda: self._finalize_download(None, "Timed out"))
