"""The Update Center page: wiring, the check flow, and the skip round-trip.

Guards live next to the page (pages/updates.py) because the wiring it pins
- lazy build, rail row, shortcut, declared prefs - is spread across the
shell and the page module, and each one fails silently when missing: a
page nobody can reach, a stamp that reads "never" after every restart, a
check that touches Tk from a worker thread.
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
        self.assertIn("'updates': ('refresh', 'Updates'),", src)
        self.assertIn('"updates": "8"', src)
        self.assertIn('("SETUP", ("settings", "performance", "updates"))', src)
        # The Ctrl+N loop must list it, or the hint lies.
        self.assertIn(
            '("downloader", "queue", "history", "studio", "aep", "settings",',
            src)
        self.assertIn('"performance", "updates"),', src)

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


if __name__ == "__main__":
    unittest.main()
