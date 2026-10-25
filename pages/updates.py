"""The Update Center page: check, review, and install updates.

Everything update-related lives here - the app updater, the engine
(yt-dlp) updater, the startup nag, the inline banner and the macOS
download flow that used to sit in ui.py - so the shell only wires
prefs and the rail. The Performance page keeps non-update maintenance
(clearing the cache) only; "single update surface" has to mean all
updates or it means nothing.
"""

import logging
import sys
import time
import webbrowser

import tkinter as tk
from tkinter import messagebox
from typing import Any, Optional

import customtkinter as ctk
from ui_theme import UITheme, _mix, _on_color
from ui_widgets import build_update_banner
from ui_components import Spinner
import download_queue
import downloader


logger = logging.getLogger("universal_audio_studio.pages.updates")


class UpdatesPageMixin:
    """The Update Center page, mixed into UniversalAudioStudio."""

    # Names the shell (or another page) owns: declared so the type checker
    # can see them from here, the convention ui_widgets uses.
    _app_update_btn_set: Any
    _prefs: Any
    _set_pref: Any
    _settings_card: Any
    _show_error_dialog: Any
    _show_info_dialog: Any
    _show_success_dialog: Any
    _start_worker: Any
    _style_button: Any
    _update_banner: Any
    _updates_last_release: Any
    after: Any
    check_for_app_updates: Any
    content_frame: Any
    show_toast: Any
    tab_updates: Any
    update_dl_detail: Any
    update_dl_status: Any

    def _check_macos_update(self):
        """macOS update check: report a new version and offer the download.

        A Mac cannot replace its own .app while it is running, so there is no
        install step here - the user is taken to the disk image instead. Without
        this the button did nothing but explain that self-update is
        Windows-only, so Mac users were never told an update existed.
        """
        import updater  # local module
        from version import __version__ as local_ver

        self._app_update_btn_set(state="disabled", text="Checking...")
        self.update_dl_status("Checking for app updates...", "#3498db")

        def worker():
            try:
                release = updater.get_remote_release()
            except Exception:
                release = None
            self.after(0, lambda: self._after_macos_update_check(release, local_ver))

        self._start_worker(worker)

    def _after_macos_update_check(self, release, local_ver):
        """Show the result of the macOS update check."""
        import updater  # local module

        self._app_update_btn_set(state="normal", text="Check for App Updates")
        remote_ver = (release or {}).get("version")
        if not remote_ver:
            self.update_dl_status("Could not reach update server.", "#e74c3c")
            self.show_toast("No update information available right now.", "warning")
            return
        if not updater.is_newer_version(remote_ver):
            self.update_dl_status(f"Up to date (v{local_ver}).", "#27ae60")
            self.show_toast(f"You already have the latest version ({local_ver}).", "success")
            return
        if not updater.macos_download_url(release):
            # Newer, but it ships no Mac build - a Windows-only release. Say so
            # plainly instead of offering a download that does not exist, and
            # never let it turn into a recurring prompt.
            self.update_dl_status(f"Up to date (v{local_ver}).", "#27ae60")
            self._show_info_dialog(
                "No Mac Update",
                f"Version {remote_ver} has been released, but it contains no "
                f"macOS build.\n\nYou already have the newest Mac version "
                f"({local_ver}).")
            return
        self.update_dl_status(f"Update available (v{remote_ver}).", "#f39c12")
        self._offer_macos_download(local_ver, release)

    def _offer_macos_download(self, local_ver, release):
        """Offer to open the new .dmg in the browser (macOS)."""
        import updater  # local module
        import webbrowser

        remote_ver = (release or {}).get("version", "?")
        # The direct disk image when the Release has one for this Mac, otherwise
        # the Release page, so the user is never left without a route.
        target = updater.macos_download_url(release) or updater.RELEASES_PAGE

        if messagebox.askyesno(
            "Update Available",
            f"A new version is available:\n\n"
            f"  Current: {local_ver}\n"
            f"  Latest:  {remote_ver}\n\n"
            f"A Mac cannot replace the app while it is running, so this opens "
            f"the download in your browser.\n"
            f"Then drag the new app over the old one in Applications.\n\n"
            f"Open the download now?",
        ):
            try:
                webbrowser.open(target)
                self.update_dl_status(f"Opened the download for v{remote_ver}.", "#27ae60")
            except Exception as e:
                logger.warning("Could not open a browser: %s", e)
                self._show_info_dialog("Update Available", f"Download it here:\n\n{target}")

    def _check_updates_on_startup(self):
        """Quiet startup auto-check: only prompts if a newer version exists.

        Runs in a background thread so the UI stays responsive; any UI touch
        is marshalled back to the main thread via after(). Silent when the
        app is already up-to-date (no popup on every launch). Rate-limited to
        once per day.
        """
        if download_queue._update_check_done_today('app'):
            logger.debug("App update check already ran today; skipping")
            return
        import threading

        def _runner():
            try:
                import updater  # local module
                from version import __version__ as local_ver

                if not updater.is_frozen():
                    return

                release = updater.get_remote_release()
                if not release or not release.get("version"):
                    return

                if not updater.is_newer_version(release["version"]):
                    return
                # Only prompt when this platform can do something with it:
                # Windows needs the packaged ZIP, a Mac needs a .dmg for its own
                # architecture. A Windows-only release must not nag Macs.
                if not updater.available_update(release):
                    return
                download_queue._mark_update_check_done('app')

                self.after(0, lambda: self._offer_startup_update(local_ver, release))
            except Exception:
                # Never let a background update check crash the app on startup.
                pass

        threading.Thread(target=_runner, daemon=True).start()


    def _hide_update_banner(self) -> None:
        """Take the update banner down, if it is up.

        pack_forget rather than destroy: the startup check runs once a day but
        the Performance page can also offer an update, and rebuilding the
        widgets each time is work for no gain. The frame itself is permanent,
        so hiding it is one call.
        """
        try:
            self._update_banner.pack_forget()
            self._update_banner_set = False
        except Exception:
            logger.debug("Could not hide the update banner", exc_info=True)

    def _show_update_banner(self, local_ver: str, remote_ver: str,
                            on_accept=None, release_notes: str = "") -> None:
        """Offer an available update inline instead of in a modal dialog.

        The widgets are built by ui_widgets.build_update_banner; this only
        decides when they exist. Never stacks: a second update found while the
        first is up refreshes the text in place rather than adding a row.

        Besides the accept/later pair the banner carries "Skip this version":
        declining a version should silence it until a newer one ships, not
        re-ask every launch. *release_notes* fills the inline "What's new"
        expander so the offer can be judged instead of trusted.
        """
        try:
            banner = self._update_banner
            for child in banner.winfo_children():
                child.destroy()

            def _later():
                self._hide_update_banner()
                self.show_toast("Update reminder dismissed.", "info", 2500)

            def _skip():
                # skipped_version is a declared default pref - _load_prefs
                # keeps only declared keys, so without that declaration this
                # write would vanish on the next launch and the nag would
                # return the day after.
                self._set_pref("skipped_version", str(remote_ver))
                self._hide_update_banner()
                self.show_toast(f"v{remote_ver} won't be offered again.",
                                "info", 3000)

            def _accept():
                self._hide_update_banner()
                if on_accept is not None:
                    on_accept()

            now, later, skip = build_update_banner(
                banner, getattr(self, "_palette", {}) or {},
                local_ver, remote_ver, on_accept=_accept, on_later=_later,
                on_skip=_skip, release_notes=release_notes)
            self._style_button(now, "primary", bordered=True)
            self._style_button(later, "secondary", bordered=True)
            self._style_button(skip, "ghost", bordered=True)

            banner.pack(fill="x", padx=12, pady=(8, 0), before=self.content_frame)
            self._update_banner_set = True
        except Exception:
            logger.debug("Could not show the update banner", exc_info=True)

    def _offer_startup_update(self, local_ver, release):
        """Show the 'update available' prompt found by the startup check."""
        import updater  # local module

        remote_ver = (release or {}).get("version", "?")
        if not updater.self_update_supported():
            if not updater.macos_download_url(release):
                # A Windows-only release: nothing this Mac can use, so stay
                # silent rather than prompting about it.
                return
            # macOS: the dialog below promises a Windows UAC prompt and an
            # automatic relaunch, neither of which exists here, so offer the
            # download instead.
            self.update_dl_status(f"Update available (v{remote_ver}).", "#f39c12")
            self._offer_macos_download(local_ver, release)
            return

        # A version the user explicitly skipped stays skipped until a newer
        # one ships: the point of the button is to end the daily re-nag, not
        # to delay it by one launch. The Update Center's Check button
        # deliberately ignores this - asking directly is not a nag.
        skipped = str((getattr(self, "_prefs", None) or {}).get(
            "skipped_version", "") or "")
        if skipped and skipped == str(remote_ver):
            logger.debug("Not re-offering skipped update v%s", remote_ver)
            return

        # Non-blocking: the banner states the same thing the modal did, minus
        # the interruption. The banner keeps to what is always true (the app
        # closes and relaunches); the confirmation dialog then spells out
        # whether this machine needs the admin prompt. The release notes ride
        # along so the offer can be judged rather than trusted.
        self._show_update_banner(local_ver, remote_ver,
                                 on_accept=self.check_for_app_updates,
                                 release_notes=str((release or {}).get("body") or ""))


    # ------------------------------------------------------------------
    # The Update Center page
    # ------------------------------------------------------------------
    def build_updates_view(self):
        """Status, actions, the skip state, and the release-notes browser.

        Guarded so repeated calls (e.g. a failed first build that left
        _built_pages without 'updates') can never stack duplicate widgets
        inside tab_updates.
        """
        if getattr(self, "_updates_view_built", False):
            return
        if getattr(self, "updates_check_btn", None) is not None:
            return
        # Defensive: if tab_updates already holds children from a previous
        # partial build, don't stack another set on top.
        try:
            if self.tab_updates.winfo_children():
                logger.debug("Updates view already has children; skipping rebuild")
                return
        except Exception:
            pass
        from version import __version__ as local_ver

        # Same scroll-inset reasoning as the Performance page: the scroll
        # canvas is square, so it sits inside the page card's radius.
        scroll = ctk.CTkScrollableFrame(self.tab_updates,
                                        fg_color="transparent")
        scroll.pack(fill="both", expand=True,
                    padx=UITheme.RADIUS_CARD, pady=UITheme.RADIUS_CARD)

        # Header: the section's drawn mark on an accent tile - the same
        # sparkle the rail row uses, so the icon has a home rather than
        # being a renamed refresh arc. The canvas recipe mirrors the
        # sidebar's brand tile: geometry the palette can ink, never a font.
        pal = getattr(self, "_palette", {}) or {}
        accent = pal.get("accent", UITheme.COLOR_PRIMARY)
        head = ctk.CTkFrame(scroll, fg_color="transparent")
        head.pack(fill="x", padx=0, pady=(0, 8))
        ctk.CTkLabel(head, text="Update Center",
                     font=UITheme.F(15, "bold"), anchor="w"
                     ).pack(anchor="w")
        # Caption: `sub` is too light on light palettes, so resolve a text that
        # actually clears 4.5:1 against the page background.
        cap_bg = pal.get("bg", "#1e1e24")
        cap_text = _on_color(cap_bg, pal.get("text", "#ecf0f1"), pal.get("sub", "#95a5a6"))
        ctk.CTkLabel(
            head,
            text="New versions, what changed in them, and one place to "
                 "stop being asked.",
            font=UITheme.F(11), anchor="w",
            text_color=cap_text,
        ).pack(anchor="w")
        # Card 1: where this install stands, and the ways to act.
        status = self._settings_card(scroll, "This app")
        status.pack(fill="x", padx=0, pady=(0, 8))
        ctk.CTkLabel(status, text=f"Installed version: {local_ver}",
                     font=UITheme.F(12), anchor="w"
                     ).pack(anchor="w", padx=16, pady=(4, 0))
        self.updates_last_lbl = ctk.CTkLabel(
            status, text=self._updates_last_checked_text(),
            font=UITheme.F(11), anchor="w",
            text_color=(getattr(self, "_palette", {}) or {}).get("sub", "#95a5a6"))
        self.updates_last_lbl.pack(anchor="w", padx=16, pady=(0, 2))
        self.updates_status_lbl = ctk.CTkLabel(
            status, text="", font=UITheme.F(12), anchor="w",
            wraplength=640, justify="left")
        self.updates_status_lbl.pack(anchor="w", padx=16, pady=(0, 4))

        # Spinner shown while an update check is in flight.
        _pal = getattr(self, "_palette", {}) or {}
        self._updates_spinner = Spinner(status, palette=_pal, size=13)
        self._updates_spinner.pack(anchor="w", padx=(16, 0), pady=(0, 4))
        self._updates_spinner.stop()

        row = ctk.CTkFrame(status, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 8))
        self.updates_check_btn = ctk.CTkButton(
            row, text="Check for updates", width=200, cursor="hand2",
            command=self._updates_check_now)
        self.updates_check_btn.pack(side="left")
        self._style_button(self.updates_check_btn, "primary", icon="refresh")
        # Shown only when a check finds something this machine can act on,
        # then handed to the proven per-platform flow (_updates_install).
        self.updates_install_btn = ctk.CTkButton(
            row, text="Download & install", width=200, cursor="hand2",
            command=self._updates_install)
        self.updates_install_btn.pack(side="left", padx=(8, 0))
        self._style_button(self.updates_install_btn, "primary")
        self.updates_install_btn.pack_forget()
        releases_btn = ctk.CTkButton(
            row, text="Open releases page", width=200, cursor="hand2",
            command=self._updates_open_releases)
        releases_btn.pack(side="left", padx=(8, 0))
        self._style_button(releases_btn, "secondary")

        # Card 2: the downloader engine. Extractor rot is the operational
        # risk of this app, so the engine gets the same status + action
        # treatment the app itself gets - on the one update surface. The
        # startup probe paints these through guarded setters because this
        # page is built lazily and the probe can marshal back before
        # anyone has visited it.
        engine = self._settings_card(scroll, "Downloader engine (yt-dlp)")
        engine.pack(fill="x", padx=0, pady=(0, 8))
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

        # Card 3: a version the user skipped, with the way back. The skip
        # button on the banner was otherwise permanent-until-a-newer-release
        # with no way to undo it from inside the app.
        self.updates_skip_card = self._settings_card(scroll, "Skipped update")
        self.updates_skip_lbl = ctk.CTkLabel(
            self.updates_skip_card, text="", font=UITheme.F(11),
            anchor="w", wraplength=640, justify="left")
        self.updates_skip_lbl.pack(anchor="w", padx=16, pady=(4, 0))
        undo = ctk.CTkButton(
            self.updates_skip_card, text="Undo skip", width=160,
            cursor="hand2", command=self._updates_undo_skip)
        undo.pack(anchor="w", padx=16, pady=(0, 8))
        self._style_button(undo, "secondary")
        self._updates_last_release = None
        self._updates_sync_skip_card()

        # Card 4: the newest release's notes, kept where they can be re-read
        # instead of only flashing inside the banner's expander once.
        notes = self._settings_card(scroll, "What's new")
        notes.pack(fill="x", padx=0, pady=(0, 8))
        self.updates_notes_title = ctk.CTkLabel(
            notes, text="Run a check to read the newest release notes.",
            font=UITheme.F(11), anchor="w",
            text_color=(getattr(self, "_palette", {}) or {}).get("sub", "#95a5a6"))
        self.updates_notes_title.pack(anchor="w", padx=16, pady=(4, 0))
        self.updates_notes_box = ctk.CTkTextbox(notes, height=220,
                                                wrap="word")
        self.updates_notes_box.pack(fill="x", padx=16, pady=(0, 8))
        self.updates_notes_box.insert(
            "1.0",
            "Release notes appear here after every check - the same notes "
            "the update banner shows, kept so they can be re-read.")
        self.updates_notes_box.configure(state="disabled")

        # Mark the view as built so repeated calls (e.g. after a partial
        # failure that left _built_pages without 'updates') can never stack
        # duplicate widgets inside tab_updates.
        self._updates_view_built = True

    def _updates_last_checked_text(self) -> str:
        stamp = str((getattr(self, "_prefs", None) or {}).get(
            "last_update_check", "") or "")
        return "Last checked: %s" % (stamp or "never")

    def _updates_record_check(self) -> None:
        """Stamp the check time. Declared pref - _load_prefs keeps only keys
        in the defaults table, so an undeclared stamp would read "never"
        again after every restart."""
        try:
            self._set_pref("last_update_check",
                           time.strftime("%Y-%m-%d %H:%M"))
        except Exception:
            logger.debug("Could not record the update check time",
                         exc_info=True)

    def _updates_check_now(self):
        """Fetch the newest Release once and paint the result on the page."""
        import updater  # local module
        from version import __version__ as local_ver

        self.updates_check_btn.configure(state="disabled", text="Checking...")
        self.updates_status_lbl.configure(text="Checking for updates...",
                                          text_color="#3498db")
        self._updates_spinner.start()

        def worker():
            release, err = None, None
            try:
                release = updater.get_remote_release()
            except Exception as e:
                err = e
            self.after(0, lambda: self._updates_after_check(
                release, err, local_ver))

        self._start_worker(worker)

    def _updates_after_check(self, release, err, local_ver):
        """Show what the check found; never prompt from here."""
        import updater  # local module

        self.updates_check_btn.configure(state="normal",
                                         text="Check for updates")
        self._updates_spinner.stop()
        self._updates_record_check()
        try:
            self.updates_last_lbl.configure(
                text=self._updates_last_checked_text())
        except Exception:
            pass
        self.updates_install_btn.pack_forget()
        self._updates_last_release = None
        if err is not None or not release or not release.get("version"):
            self.updates_status_lbl.configure(
                text="Could not reach the update server.",
                text_color="#e74c3c")
            self.show_toast("No update information available right now.",
                            "warning")
            return
        remote_ver = str(release.get("version"))
        self._updates_fill_notes(release)
        if not updater.is_newer_version(remote_ver):
            self.updates_status_lbl.configure(
                text=f"Up to date - v{local_ver} is the newest release.",
                text_color="#27ae60")
            return
        if not updater.available_update(release):
            # Newer, but nothing this machine can run. Same rule as the
            # startup nag: say so plainly, never offer a download that does
            # not exist.
            self.updates_status_lbl.configure(
                text=f"v{remote_ver} is out, but it has no build for this "
                     f"platform - you have the newest one ({local_ver}).",
                text_color="#f39c12")
            return
        self.updates_status_lbl.configure(
            text=f"Update available: v{remote_ver} (you have {local_ver}).",
            text_color="#f39c12")
        self.updates_install_btn.pack(side="left", padx=(8, 0))
        self._updates_last_release = release
        skipped = self._updates_skip_state()
        if skipped and skipped == remote_ver:
            self.show_toast(
                f"v{remote_ver} is set to 'Skip this version' - Undo below "
                f"re-offers it.", "info", 4000)
        else:
            self.show_toast(f"Update available: v{remote_ver}.", "info", 3000)

    def _updates_install(self):
        """Hand the found update to the proven per-platform flow."""
        import updater  # local module
        from version import __version__ as local_ver

        release = getattr(self, "_updates_last_release", None)
        if not release:
            self.show_toast("Run a check first.", "warning")
            return
        if not updater.is_frozen():
            self._show_info_dialog(
                "Update Unavailable",
                "Self-update only works in the packaged app.\\n\\n"
                "You are running from source (python ui.py), so there is "
                "no EXE to update.")
            return
        if not updater.self_update_supported():
            # macOS: no self-replacement - offer the disk image instead.
            self._offer_macos_download(local_ver, release)
            return
        # Windows: the sidebar flow owns the confirm/UAC wording, the
        # download and the relaunch. It re-checks first, which is one extra
        # cheap request in exchange for exactly one install path.
        self.check_for_app_updates()

    def _updates_fill_notes(self, release):
        """Show the release's notes and date in the browser card."""
        remote_ver = str((release or {}).get("version") or "?")
        published = str((release or {}).get("published_at") or "")[:10]
        body = str((release or {}).get("body") or "").strip()
        try:
            self.updates_notes_title.configure(
                text="What's new in v%s%s" % (
                    remote_ver, f" ({published})" if published else ""))
            box = self.updates_notes_box
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", body or
                       "This release shipped without written notes.")
            box.configure(state="disabled")
        except Exception:
            logger.debug("Could not fill the release notes", exc_info=True)

    def _updates_skip_state(self) -> str:
        return str((getattr(self, "_prefs", None) or {}).get(
            "skipped_version", "") or "")

    def _updates_sync_skip_card(self):
        """Show the skip card only while a skip is in force."""
        skipped = self._updates_skip_state()
        try:
            if skipped:
                self.updates_skip_lbl.configure(
                    text=f"v{skipped} won't be offered again until a newer "
                         f"version ships. Undo makes it eligible right now.")
                self.updates_skip_card.pack(fill="x", padx=0, pady=(0, 8))
            else:
                self.updates_skip_card.pack_forget()
        except Exception:
            logger.debug("Could not refresh the skip card", exc_info=True)

    def _updates_undo_skip(self):
        """Clear the skip so the version can be offered again."""
        skipped = self._updates_skip_state()
        self._set_pref("skipped_version", "")
        self._updates_sync_skip_card()
        self.show_toast(
            f"v{skipped} can be offered again." if skipped
            else "No version was skipped.", "info", 3000)

    def _updates_open_releases(self):
        import updater  # local module
        webbrowser.open(updater.RELEASES_PAGE)

    # ------------------------------------------------------------------
    # The engine (yt-dlp) updater. Moved here from ui.py/Performance so
    # the "single update surface" doctrine covers the engine too - the
    # startup probe used to tell users to go find a button on another
    # tab, and its label refresh raised whenever the probe beat the
    # lazy page build.
    # ------------------------------------------------------------------

    def _ytdlp_label_set(self, text: str, color=None):
        """Paint the engine version line if the Update Center has been built.

        The startup probe marshals to the main thread and can fire before
        anyone has visited this page; configuring a widget that does not
        exist yet raised inside an after() callback, where the exception
        only hit the console and the label kept whatever text it had.
        """
        label = getattr(self, "ytdlp_ver_lbl", None)
        if label is None:
            return
        try:
            if color:
                label.configure(text=text, text_color=color)
            else:
                label.configure(text=text)
        except Exception:
            logger.debug("Could not paint the yt-dlp version line",
                         exc_info=True)

    def _ytdlp_btn_set(self, **kwargs):
        """Reconfigure the engine update button if the page has been built."""
        btn = getattr(self, "ytdlp_update_btn", None)
        if btn is None:
            return
        try:
            btn.configure(**kwargs)
        except Exception:
            logger.debug("Could not reconfigure the yt-dlp update button",
                         exc_info=True)

    def _ytdlp_auto_update_allowed(self) -> bool:
        """Whether the startup probe may install an engine update itself.

        Packaged builds only: the frozen engine refreshes a user-space copy
        of yt-dlp.exe (downloader.update_ytdlp), never the install dir, so
        an unattended install cannot break the installation. In a dev
        environment the same flow is ``pip install --upgrade`` and silently
        mutating someone's virtualenv on launch is a foot-gun - the button
        stays the opt-in there, whatever the pref says.
        """
        if not getattr(sys, "frozen", False):
            return False
        return bool((getattr(self, "_prefs", None) or {}).get(
            "engine_auto_update", True))

    def _apply_engine_auto_pref(self) -> None:
        """Persist the engine auto-update toggle (engine card checkbox)."""
        try:
            self._set_pref("engine_auto_update",
                           bool(self.engine_auto_var.get()))
        except Exception:
            logger.debug("Could not persist engine_auto_update",
                         exc_info=True)

    def _ytdlp_attempt_auto_update(self, before: str) -> Optional[str]:
        """Run downloader.update_ytdlp() unattended; return the new version.

        Never raises - a failed auto-update degrades to ``None`` so the
        caller keeps the manual nudge. Runs on the probe's worker thread
        (the startup probe goes through _start_worker), so the exe's
        self-update subprocess cannot block the UI.
        """
        try:
            result = downloader.update_ytdlp()
            logger.info("Engine auto-update finished: %s",
                        str(result).splitlines()[0] if result else "?")
        except Exception:
            logger.warning("Engine auto-update failed", exc_info=True)
            return None
        return downloader.get_ytdlp_version()

    def _ytdlp_update_check_worker(self, force: bool = False):
        """Background startup probe: warn only if a yt-dlp update is available.

        Packaged builds with the engine_auto_update pref on (the default)
        go further and install the update unattended instead of nudging.

        Rate-limited to once per day so we don't hit GitHub on every
        launch; force=True bypasses the throttle - the update click and
        the post-install re-probe use it to repaint the version line,
        where the throttle would otherwise leave the label frozen at
        "Updating yt-dlp..." until the marker rolls over.
        """
        if not force and download_queue._update_check_done_today('ytdlp'):
            logger.debug("yt-dlp update check already ran today; skipping")
            return
        try:
            res = downloader.check_ytdlp_update_available(timeout=10.0)
        except Exception as e:
            logger.debug("yt-dlp update check failed: %s", e)
            return
        download_queue._mark_update_check_done('ytdlp')

        status = res.get("status")
        local = res.get("local")
        latest = res.get("latest")

        # Packaged builds with the opt-out pref on: install the update right
        # here instead of nudging (yt-dlp breaks on major sites constantly,
        # and the frozen engine only ever rewrites the user-space copy in
        # the per-user data dir). On success re-enter with force=True - the
        # daily marker is already stamped, the label must repaint to the
        # NEW version (not this stale closure), and there is no nudge left
        # to push. On failure fall through: the manual path (the engine
        # card's button) still gets advertised below.
        if status == "update" and local and latest \
                and self._ytdlp_auto_update_allowed():
            after = self._ytdlp_attempt_auto_update(local)
            if after and after != local:
                logger.info("Engine auto-updated: %s -> %s", local, after)
                self.after(0, lambda: self._ytdlp_update_check_worker(force=True))
                return
            logger.warning("Engine auto-update did not apply; keeping the "
                           "manual nudge")

        def refresh_label():
            # Rebuild the friendly version label text based on probe result,
            # through the guard: this page builds lazily on first visit.
            if status == "update" and local and latest:
                self._ytdlp_label_set(
                    f"yt-dlp: {local} -> {latest} (update available!)",
                    "#f39c12")
            elif status == "current" and local:
                self._ytdlp_label_set(f"yt-dlp version: {local}", "#27ae60")
            else:
                # "unknown" or not-detected: stay neutral, don't spam user.
                self._ytdlp_label_set(
                    f"yt-dlp version: {local or 'not detected'}", "#95a5a6")

        # Always refresh the label on the main thread first (non-blocking).
        self.after(0, refresh_label)

        # Only push the nudge when an update is genuinely available - and
        # point at the one surface that can install it.
        if status == "update" and local and latest:
            def push_banner():
                self.update_dl_detail(
                    f"yt-dlp update available ({local} -> {latest}). Open the "
                    f"Update Center (Ctrl+8) to install it.",
                    "#f39c12",
                )
                # The detail label only lives on the Downloader tab; a toast
                # carries the same notice to whatever tab is on screen.
                self.show_toast(
                    f"yt-dlp update available ({local} -> {latest}) - see "
                    f"the Update Center (Ctrl+8).",
                    "warning",
                    duration=6000,
                )
            self.after(0, push_banner)

    def update_ytdlp_clicked(self):
        self._ytdlp_btn_set(state="disabled", text="Updating...")
        self._ytdlp_label_set("Updating yt-dlp...")

        def worker():
            try:
                msg = downloader.update_ytdlp(
                    status_callback=lambda text, color: self.after(
                        0, lambda t=text: self._ytdlp_label_set(t))
                )
                # The pip output is long and technical: keep a short headline in
                # the body and push the raw log into the copyable detail box.
                if "already up to date" in msg.lower():
                    self.after(0, lambda: self._show_info_dialog(
                        "yt-dlp Updater", "yt-dlp is already up to date.",
                        detail=msg))
                elif "updated" in msg.lower() and "fail" not in msg.lower():
                    self.after(0, lambda: self._show_success_dialog(
                        "yt-dlp Updater", "Update successful. Restart the app to use the new version.",
                        detail=msg))
                else:
                    self.after(0, lambda: self._show_info_dialog(
                        "yt-dlp Updater", "The updater finished — check the details.",
                        detail=msg))
                # force=True: the daily throttle would skip a plain re-run
                # and leave the version line frozen at "Updating yt-dlp...".
                self.after(0, lambda: self._ytdlp_update_check_worker(force=True))
            except Exception as e:
                logger.exception("yt-dlp update failed")
                # Bind the message now: `e` is deleted when the except block
                # ends, and this lambda runs on the next mainloop turn, so
                # str(e) inside it raised NameError and the user saw nothing.
                err_text = str(e)
                self.after(0, lambda: self._show_error_dialog(
                    "Update Error", "Failed to update yt-dlp.", detail=err_text))
            finally:
                self.after(0, lambda: self._ytdlp_btn_set(
                    state="normal", text="⮔ Update yt-dlp"))
        self._start_worker(worker)
