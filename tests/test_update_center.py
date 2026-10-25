"""The Update Center page: wiring, the check flow, the skip round-trip, and
the engine (yt-dlp) surface.

Guards live next to the page (pages/updates.py) because the wiring it pins
- lazy build, rail row, shortcut, declared prefs, the engine updater -
is spread across the shell and the page module, and each one fails
silently when missing: a page nobody can reach, a stamp that reads
"never" after every restart, a check that touches Tk from a worker
thread, an engine update stranded on another tab.
"""

import pathlib
import re
import unittest

PROJECT_DIR = pathlib.Path(__file__).resolve().parents[1]


def _source() -> str:
    """ui.py plus every page module (the corpus rule)."""
    parts = [(PROJECT_DIR / "ui.py").read_text(encoding="utf-8")]
    pages_dir = PROJECT_DIR / "pages"
    for f in sorted(pages_dir.glob("*.py")):
        parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _method_source(name: str) -> str:
    m = re.search(
        r"\n    def %s\(.*?(?=\n    def |\n    @|\Z)" % re.escape(name),
        _source(),
        re.DOTALL,
    )
    assert m is not None, "no method named %r" % name
    return m.group(0)


class UpdateCenterWiringTests(unittest.TestCase):
    def test_the_page_is_reachable_three_ways(self):
        src = _source()
        # lazily built like every other page...
        self.assertIn(
            "('updates', 'tab_updates', 'build_updates_view', 'Update Center'),",
            src)
        # ...named in the header switch...
        self.assertIn("'updates': 'Update Center',", src)
        # ...and its frame exists in the shell.
        self.assertIn(
            "self.tab_updates = ctk.CTkFrame(self.content_frame", src)

    def test_the_rail_and_shortcuts_reach_the_page(self):
        src = _source()
        self.assertIn("'updates': ('update', 'Updates'),", src)
        self.assertIn('"updates": "8"', src)
        self.assertIn('("SETUP", ("settings", "performance", "updates"))', src)
        # The Ctrl+N loop must list it, or the hint lies.
        self.assertIn(
            '("downloader", "queue", "history", "studio", "aep", "settings",',
            src)
        self.assertIn('"performance", "updates"),', src)

    def test_the_page_carries_its_own_drawn_mark(self):
        # The section's logo is geometry, not a font glyph: the rail row and
        # the page header share the same sparkle, painted from the palette.
        src = _source()
        self.assertIn("if name == 'update':",
                      (PROJECT_DIR / "ui_theme.py").read_text(
                          encoding="utf-8"))

    def test_the_last_check_stamp_is_a_declared_pref(self):
        # _load_prefs keeps only declared keys: an undeclared stamp would
        # read "never" again after every restart.
        self.assertIn('"last_update_check": "",', _source())
        body = _method_source("_updates_record_check")
        self.assertIn('self._set_pref("last_update_check"', body)


class UpdateCenterCheckFlowTests(unittest.TestCase):
    def test_the_check_runs_off_the_ui_thread_and_marshals_back(self):
        body = _method_source("_updates_check_now")
        self.assertIn("self._start_worker(worker)", body)
        self.assertIn("self.after(0, lambda: self._updates_after_check(",
                      body)

    def test_the_result_reuses_the_platform_gates(self):
        body = _method_source("_updates_after_check")
        self.assertIn("updater.is_newer_version(remote_ver)", body)
        self.assertIn("updater.available_update(release)", body)

    def test_install_hands_off_instead_of_reimplementing(self):
        body = _method_source("_updates_install")
        self.assertIn("updater.is_frozen()", body)
        self.assertIn("updater.self_update_supported()", body)
        self.assertIn("self.check_for_app_updates()", body)
        self.assertIn("self._offer_macos_download(local_ver, release)", body)

    def test_the_notes_browser_reads_the_release_body(self):
        body = _method_source("_updates_fill_notes")
        self.assertIn('(release or {}).get("body")', body)


class UpdateCenterSkipRoundTripTests(unittest.TestCase):
    def test_undo_skip_clears_the_pref_the_startup_nag_honours(self):
        body = _method_source("_updates_undo_skip")
        self.assertIn('self._set_pref("skipped_version", "")', body)
        # The nag reads the same key and must keep doing so.
        nag = _method_source("_offer_startup_update")
        self.assertIn('get(\n            "skipped_version", "")', nag)

    def test_the_skip_card_only_shows_while_a_skip_is_in_force(self):
        body = _method_source("_updates_sync_skip_card")
        self.assertIn("self.updates_skip_card.pack(", body)
        self.assertIn("self.updates_skip_card.pack_forget()", body)


class MovedUpdateFlowsTests(unittest.TestCase):
    """The flows that moved out of ui.py keep their names and their guards."""

    def test_every_moved_flow_is_still_defined_once(self):
        src = _source()
        for name in ("_check_macos_update", "_after_macos_update_check",
                     "_offer_macos_download", "_check_updates_on_startup",
                     "_hide_update_banner", "_show_update_banner",
                     "_offer_startup_update"):
            self.assertEqual(src.count("def %s(" % name), 1, name)

    def test_the_startup_check_stays_rate_limited_and_frozen_only(self):
        body = _method_source("_check_updates_on_startup")
        self.assertIn("download_queue._update_check_done_today('app')", body)
        self.assertIn("updater.is_frozen()", body)
        self.assertIn("download_queue._mark_update_check_done('app')", body)


class SingleUpdateSurfaceTests(unittest.TestCase):
    """The Update Center is the only place the app can be updated from."""

    def test_the_speed_tab_no_longer_offers_app_updates(self):
        src = _source()
        self.assertNotIn("self.app_update_btn = ", src)
        self.assertNotIn(".app_update_btn.configure(", src)

    def test_the_flows_reach_the_old_button_only_through_the_guard(self):
        # ui_widgets hosts check_for_app_updates; it is not in the page
        # corpus, so it is read directly here.
        wsrc = (PROJECT_DIR / "ui_widgets.py").read_text(encoding="utf-8")
        self.assertNotIn(".app_update_btn.configure(", wsrc)
        self.assertIn("def _app_update_btn_set(", wsrc)
        self.assertIn("self._app_update_btn_set(", wsrc)
        self.assertIn("self._app_update_btn_set(", _source())


class EngineUpdateSurfaceTests(unittest.TestCase):
    """yt-dlp is the app's engine; its update lives on the Performance page."""

    def test_the_engine_card_lives_on_the_performance_page(self):
        body = _method_source("build_performance_view")
        self.assertIn(
            'self._settings_card(maint, "Downloader engine (yt-dlp)")', body)
        self.assertIn("self.ytdlp_update_btn = ctk.CTkButton(", body)
        self.assertIn("command=self.update_ytdlp_clicked", body)
        self.assertIn("self.ytdlp_ver_lbl = ctk.CTkLabel(", body)

    def test_the_update_center_page_no_longer_offers_engine_updates(self):
        # Single surface means all updates: the engine card moved out of the
        # Update Center page so it lives next to the other download-tuning
        # controls on the Performance tab.
        body = _method_source("build_updates_view")
        self.assertNotIn("ytdlp_update_btn", body)
        self.assertNotIn("ytdlp_ver_lbl", body)
        self.assertNotIn("Downloader engine (yt-dlp)", body)
        # The check button and install button still live on Update Center.
        self.assertIn("updates_check_btn", body)
        self.assertIn("updates_install_btn", body)

    def test_the_flows_moved_with_the_widgets(self):
        src = _source()
        self.assertEqual(src.count("def update_ytdlp_clicked("), 1)
        self.assertEqual(src.count("def _ytdlp_update_check_worker("), 1)
        psrc = (PROJECT_DIR / "pages" / "updates.py").read_text(
            encoding="utf-8")
        usrc = (PROJECT_DIR / "ui.py").read_text(encoding="utf-8")
        self.assertIn("def update_ytdlp_clicked(", psrc)
        self.assertIn("def _ytdlp_update_check_worker(", psrc)
        self.assertNotIn("def update_ytdlp_clicked(", usrc)
        self.assertNotIn("def _ytdlp_update_check_worker(", usrc)

    def test_the_nudge_points_at_the_update_center(self):
        # The old toast sent users hunting for a button on another tab.
        body = _method_source("_ytdlp_update_check_worker")
        self.assertNotIn("Performance tab", body)
        self.assertIn("Update Center", body)

    def test_both_flows_stay_off_the_ui_thread(self):
        self.assertIn("self._start_worker(worker)",
                      _method_source("update_ytdlp_clicked"))
        self.assertIn("self.after(0,",
                      _method_source("update_ytdlp_clicked"))


class EngineProbeGuardTests(unittest.TestCase):
    """Two silent-failure bugs the move had to fix, pinned so they stay fixed."""

    def test_the_probe_paints_through_a_guard_for_an_unbuilt_page(self):
        # The startup probe marshals to the main thread; the page builds
        # lazily on first visit. A bare self.ytdlp_ver_lbl.configure raised
        # inside an after() callback, where only the console ever saw it.
        worker = _method_source("_ytdlp_update_check_worker")
        self.assertIn("self._ytdlp_label_set(", worker)
        self.assertNotIn("self.ytdlp_ver_lbl.configure(", worker)
        guard = _method_source("_ytdlp_label_set")
        self.assertIn('getattr(self, "ytdlp_ver_lbl", None)', guard)

    def test_the_click_handler_also_paints_and_reenables_through_guards(self):
        body = _method_source("update_ytdlp_clicked")
        self.assertIn("self._ytdlp_btn_set(", body)
        self.assertIn("self._ytdlp_label_set(", body)
        self.assertNotIn("self.ytdlp_update_btn.configure(", body)
        self.assertNotIn("self.ytdlp_ver_lbl.configure(", body)

    def test_a_completed_update_repaints_even_when_the_probe_was_throttled(self):
        # After an update the click flow re-runs the probe with force=True:
        # the daily throttle would skip a plain re-run and leave the label
        # frozen at "Updating yt-dlp..." until the marker rolls over.
        self.assertIn("force=True", _method_source("update_ytdlp_clicked"))
        self.assertIn("not force",
                      _method_source("_ytdlp_update_check_worker"))


class EngineAutoUpdateTests(unittest.TestCase):
    """The startup probe can install engine updates - packaged builds only.

    yt-dlp breaks on major sites constantly and this app's entire job is
    downloading, so packaged builds install an available engine update
    unattended instead of only nudging. The three things that must never
    regress: the pref survives a restart (declared in _default_prefs), a
    dev environment is never pip-mutated silently (the sys.frozen gate
    comes first), and a successful install re-probes fresh instead of
    painting the stale closure's "update available" label.
    """

    def test_the_pref_is_declared_so_it_survives_a_restart(self):
        # _load_prefs keeps only declared keys - an undeclared toggle would
        # snap back to its default after every launch.
        self.assertIn('"engine_auto_update": True', _source())

    def test_the_engine_card_offers_the_toggle_and_it_persists(self):
        body = _method_source("build_performance_view")
        self.assertIn("Update the engine automatically at startup", body)
        self.assertIn("command=self._apply_engine_auto_pref", body)
        self.assertIn("self.engine_auto_var = tk.BooleanVar(", body)
        persist = _method_source("_apply_engine_auto_pref")
        self.assertIn('self._set_pref("engine_auto_update"', persist)
        self.assertIn("bool(self.engine_auto_var.get())", persist)

    def test_auto_update_never_touches_a_dev_environment(self):
        # The frozen gate comes before the pref read, so no pref value can
        # ever turn an unattended pip install on in a source run.
        body = _method_source("_ytdlp_auto_update_allowed")
        self.assertIn('if not getattr(sys, "frozen", False):', body)
        self.assertIn('"engine_auto_update", True', body)
        gate = body.index('if not getattr(sys, "frozen", False):')
        pref = body.index('"engine_auto_update", True')
        self.assertLess(gate, pref)

    def test_a_successful_install_reenters_fresh_and_skips_the_nudge(self):
        body = _method_source("_ytdlp_update_check_worker")
        self.assertIn("self._ytdlp_auto_update_allowed()", body)
        self.assertIn("self._ytdlp_attempt_auto_update(local)", body)
        self.assertIn("_ytdlp_update_check_worker(force=True)", body)
        # Ordering is the contract: after a successful install the worker
        # re-enters (force=True - the daily marker is already stamped) and
        # returns BEFORE the stale-closure nudge is scheduled.
        attempt = body.index("self._ytdlp_attempt_auto_update(local)")
        nudge = body.index("def push_banner")
        first_return = body.index("return", attempt)
        self.assertLess(attempt, nudge)
        self.assertLess(first_return, nudge)

    def test_the_attempt_swallows_errors_and_reports_the_new_version(self):
        body = _method_source("_ytdlp_attempt_auto_update")
        self.assertIn("downloader.update_ytdlp()", body)
        self.assertIn("return downloader.get_ytdlp_version()", body)
        # A failure must degrade to None so the caller keeps the manual
        # nudge, never propagate into the probe thread.
        self.assertIn("except Exception", body)
        self.assertIn("return None", body)


if __name__ == "__main__":
    unittest.main()
