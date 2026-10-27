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

logger = logging.getLogger("universal_audio_studio.pages.downloader")


class DownloaderPageMixin:
    """The Downloader page, mixed into UniversalAudioStudio."""

    # Names the shell (or another page) owns: declared so the type checker
    # can see them from here, the convention ui_widgets uses.
    _last_dl_url: Any
    _last_dl_was_video: Any
    _last_downloaded_file: Any
    _prefs: Any
    _set_pref: Any
    _show_error_dialog: Any
    _show_progress_row: Any
    _start_worker: Any
    _style_button: Any
    after: Any
    btn_cancel_download: Any
    btn_download_mp3: Any
    btn_download_mp4: Any
    btn_edit_tags: Any
    btn_preview_video: Any
    btn_stop_video: Any
    download_mp3: Any
    download_mp4: Any
    on_dl_cancelled: Any
    on_dl_error: Any
    on_dl_success: Any
    progress_bar: Any
    set_download_buttons_state: Any
    show_toast: Any
    tab_downloader: Any
    update_dl_detail: Any
    update_dl_status: Any
    update_progress_bar: Any
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
