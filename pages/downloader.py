"""The Downloader page: URL entry, MP3/MP4 download, cancel, preview, prefs.

Extracted from ui.py in stages (see DOWNLOADER_EXTRACTION_PLAN.md). This
first pass is a stub mixin that only declares the names the shell owns; the
handlers and builders move here in later steps.
"""

import logging
import os
from tkinter import filedialog
from typing import Any

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
    _queue_manager: Any
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
            self.save_folder_lbl.configure(
                text=f"Saves to: {downloader.get_download_folder()}"
            )
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
        self.update_dl_detail(f"Audio format set to {fmt_label}.", "#95a5a6")



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
        row = getattr(self, "_progress_row", None)
        if row is None:
            return
        try:
            if visible:
                if not row.winfo_manager():
                    row.pack(fill="x", padx=UITheme.PAD_X,
                             pady=(0, UITheme.RHYTHM))
            elif row.winfo_manager():
                row.pack_forget()
        except Exception:
            logger.debug("Could not toggle the progress row", exc_info=True)

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
            self._sync_clear_btn()
        except Exception:
            pass
        if getattr(self, "_last_dl_was_video", False):
            self._start_worker(self.download_mp4)
        else:
            self._start_worker(self.download_mp3)

    def set_download_buttons_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.after(0, lambda: self.btn_download_mp3.configure(state=state))
        self.after(0, lambda: self.btn_download_mp4.configure(state=state))
        cancel_state = "disabled" if enabled else "normal"
        self.after(0, lambda: self.btn_cancel_download.configure(state=cancel_state))
        self._show_progress_row(not enabled)

    def _sync_clear_btn(self):
        """Show the inline ✕ only while the URL box has text."""
        try:
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

    def download_mp3(self):
        url = self.url_entry.get().strip()
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

    def download_mp4(self):
        url = self.url_entry.get().strip()
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

    def on_dl_success(self, folder):
        self.after(0, lambda: self._finalize_download(folder, None))

    def on_dl_error(self, err):
        self.after(0, lambda: self._finalize_download(None, err))

    def _finalize_download(self, folder, err):
        # Some extractors (e.g. Instagram) report "no video formats" for the
        # primary format selection but still download a fallback. Treat a
        # finished file as success so the user isn't shown a spurious error.
        if err and folder and os.path.isdir(str(folder)):
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
                "is_video": bool(is_video),
            }
            self._queue_manager.upsert_history_entry(entry)
        except Exception as e:
            logger.warning("Failed to save download to history: %s", e)
