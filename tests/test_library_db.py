"""The Library store: SQLite history that outgrows the JSON cap.

Guards the pieces that fail silently - a record() that swallows its own
errors, a migration that would re-seed a long-lived library from the
shorter JSON file, a sink that fires on the queue worker thread - plus
the wiring that keeps the History page reading the database first.
"""

import json
import os
import pathlib
import tempfile
import unittest

import download_queue
import library_db

PROJECT_DIR = pathlib.Path(__file__).resolve().parents[1]


def _entry(url="https://example.invalid/a", title="Song", **extra):
    entry = {"url": url, "title": title, "filepath": "", "status": "done",
             "is_video": False, "started_at": 0.0, "completed_at": 1.0,
             "error": None}
    entry.update(extra)
    return entry


def _rows(**kwargs):
    """entries() with the None (unreachable db) case made explicit."""
    rows = library_db.entries(**kwargs)
    assert rows is not None, "library db unreachable in this test"
    return rows


class LibraryDbTestCase(unittest.TestCase):
    """Points the library at a temp file and resets the migration flag."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_env = os.environ.get("TUNELAB_LIBRARY_DB")
        os.environ["TUNELAB_LIBRARY_DB"] = os.path.join(
            self._tmp.name, "library.sqlite3")
        self._old_flag = library_db._migration_checked
        library_db._migration_checked = False

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("TUNELAB_LIBRARY_DB", None)
        else:
            os.environ["TUNELAB_LIBRARY_DB"] = self._old_env
        library_db._migration_checked = self._old_flag
        self._tmp.cleanup()


class RecordAndReadTests(LibraryDbTestCase):
    def test_record_reads_back_the_same_dict(self):
        entry = _entry()
        library_db.record(entry)
        self.assertEqual(_rows(), [entry])

    def test_record_upserts_by_url(self):
        library_db.record(_entry(title="Old", completed_at=1.0))
        library_db.record(_entry(title="New", completed_at=2.0))
        rows = _rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "New")
        self.assertEqual(rows[0]["completed_at"], 2.0)

    def test_search_filters_on_title_and_url(self):
        library_db.record(_entry(url="https://a.invalid/1", title="Sunrise"))
        library_db.record(_entry(url="https://b.invalid/2", title="Night"))
        self.assertEqual(len(_rows(search="sunrise")), 1)
        self.assertEqual(len(_rows(search="b.invalid")), 1)
        self.assertEqual(len(_rows(search="nothing")), 0)

    def test_newest_first_ordering(self):
        library_db.record(_entry(url="https://a.invalid/1", completed_at=1.0))
        library_db.record(_entry(url="https://b.invalid/2", completed_at=9.0))
        self.assertEqual(_rows()[0]["url"], "https://b.invalid/2")

    def test_trim_keeps_only_the_newest(self):
        old_cap = library_db.MAX_ENTRIES
        library_db.MAX_ENTRIES = 3
        try:
            for i in range(5):
                library_db.record(_entry(url="https://x/%d" % i,
                                         completed_at=float(i)))
            self.assertEqual(library_db.count(), 3)
            urls = [e["url"] for e in _rows()]
            self.assertEqual(urls, ["https://x/4", "https://x/3",
                                    "https://x/2"])
        finally:
            library_db.MAX_ENTRIES = old_cap

    def test_unreachable_db_falls_back_instead_of_raising(self):
        os.environ["TUNELAB_LIBRARY_DB"] = os.path.join(
            self._tmp.name, "no", "such", "dir", "lib.sqlite3")
        self.assertIsNone(library_db.entries())   # caller falls back to JSON
        library_db.record(_entry())               # must not raise

    def test_payload_survives_odd_values(self):
        entry = _entry(error=None, extra={"nested": True})
        library_db.record(entry)
        self.assertEqual(_rows()[0]["extra"], {"nested": True})


class PruneAndClearTests(LibraryDbTestCase):
    def test_prune_drops_only_gone_files(self):
        keep = os.path.join(self._tmp.name, "keep.mp3")
        with open(keep, "w", encoding="utf-8") as fh:
            fh.write("x")
        gone = os.path.join(self._tmp.name, "gone.mp3")
        library_db.record(_entry(url="https://a/1", filepath=keep))
        library_db.record(_entry(url="https://a/2", filepath=gone))
        library_db.record(_entry(url="https://a/3", filepath=""))
        self.assertEqual(library_db.prune_missing(), 1)
        self.assertEqual({e["url"] for e in _rows()},
                         {"https://a/1", "https://a/3"})

    def test_clear_empties_and_allows_reseed(self):
        library_db.record(_entry())
        library_db.clear()
        self.assertEqual(library_db.count(), 0)
        self.assertFalse(library_db._migration_checked)


class MigrationTests(LibraryDbTestCase):
    def test_import_runs_once_and_then_stops(self):
        records = [_entry(url="https://a/1"), _entry(url="https://a/2")]
        self.assertEqual(library_db.ensure_migrated(records), 2)
        # A later call must not re-seed, even with more records on offer.
        self.assertEqual(
            library_db.ensure_migrated(records + [_entry(url="https://a/3")]),
            0)
        self.assertEqual(library_db.count(), 2)


    def test_a_filled_database_is_never_seeded_from_json(self):
        library_db.record(_entry(url="https://keep/1"))
        self.assertEqual(
            library_db.ensure_migrated([_entry(url="https://other/2")]), 0)
        self.assertEqual({e["url"] for e in _rows()},
                         {"https://keep/1"})


class HistorySinkTests(LibraryDbTestCase):
    """download_queue routes writes to the sink; JSON stays the floor."""

    def setUp(self):
        super().setUp()
        self._old_sink = download_queue._HISTORY_SINK
        self._old_file = download_queue.HISTORY_FILE
        download_queue.HISTORY_FILE = os.path.join(self._tmp.name,
                                                   "history.json")

    def tearDown(self):
        download_queue.set_history_sink(self._old_sink)
        download_queue.HISTORY_FILE = self._old_file
        super().tearDown()

    @staticmethod
    def _queue():
        return download_queue.DownloadQueue(
            download_fn=lambda *a, **k: None,
            video_fn=lambda *a, **k: None,
            find_file_fn=lambda *a, **k: None,
            save_folder_fn=lambda: "",
        )

    def test_the_sink_receives_upserts_and_the_db_follows(self):
        seen = []
        # The app attaches library_db.record as the sink; a tee proves both
        # halves run on the same write.
        download_queue.set_history_sink(
            lambda e: (seen.append(e), library_db.record(e)))
        entry = _entry(title="From the UI")
        self._queue().upsert_history_entry(entry)
        self.assertEqual(seen, [entry])
        rows = _rows()
        self.assertEqual(rows and rows[0]["title"], "From the UI")

    def test_no_sink_means_no_database(self):
        download_queue.set_history_sink(None)
        self._queue().upsert_history_entry(_entry())
        self.assertEqual(library_db.count(), 0)

    def test_a_broken_sink_never_breaks_the_history_write(self):
        def boom(_entry_arg):
            raise RuntimeError("db is on fire")
        download_queue.set_history_sink(boom)
        self._queue().upsert_history_entry(_entry(title="Still saved"))
        with open(download_queue.HISTORY_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved[0]["title"], "Still saved")


class HistoryPageWiringTests(unittest.TestCase):
    """The History page reads the library first and prunes/clears both."""

    @staticmethod
    def _page():
        return (PROJECT_DIR / "pages" / "history.py").read_text(
            encoding="utf-8")

    def test_the_page_reads_the_library_with_a_json_fallback(self):
        src = self._page()
        self.assertIn("library_db.ensure_migrated(records)", src)
        self.assertIn("rows = library_db.entries()", src)
        self.assertIn("if rows is not None:", src)
        self.assertIn("        return records", src)

    def test_refresh_and_missing_count_go_through_the_helper(self):
        src = self._page()
        self.assertIn("history = self._history_entries()", src)
        self.assertIn("history = self._history_entries() or []", src)

    def test_prune_and_clear_cover_both_stores(self):
        src = self._page()
        self.assertIn("library_db.prune_missing()", src)
        self.assertIn("library_db.clear()", src)

    def test_the_queue_manager_attaches_the_sink(self):
        src = (PROJECT_DIR / "pages" / "queue.py").read_text(
            encoding="utf-8")
        self.assertIn("download_queue.set_history_sink(library_db.record)",
                      src)


if __name__ == "__main__":
    unittest.main()
