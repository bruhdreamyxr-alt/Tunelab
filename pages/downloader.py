"""The Downloader page: URL entry, MP3/MP4 download, cancel, preview, prefs.

Extracted from ui.py in stages (see DOWNLOADER_EXTRACTION_PLAN.md). This
first pass is a stub mixin that only declares the names the shell owns; the
handlers and builders move here in later steps.
"""

from typing import Any

import customtkinter as ctk

from ui_theme import UITheme


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

    # Placeholder so the mixin is importable and instantiable as a type.
    _downloader_page_stub: bool = True
