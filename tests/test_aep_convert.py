"""Unit tests for aep_convert: version parsing, naming, conversion guards.

py_aep is stubbed, so these run without After Effects files and without
the optional dependency installed - they pin the module's own logic
(paths, errors, refusals), not the parser's.
"""
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aep_convert


class _FakeApp:
    """Stand-in for py_aep's parsed application object."""

    def __init__(self, version="26.0x67"):
        self.version = version
        self.project = self

    def save(self, dest):
        with open(dest, "wb") as f:
            f.write(b"fake-aep")


def _install_fake_py_aep(version="26.0x67"):
    fake = types.ModuleType("py_aep")
    setattr(fake, "parse",
            lambda path: _FakeApp(version))  # noqa: B023 - test stub
    sys.modules["py_aep"] = fake
    return fake


class TargetVersionsTests(unittest.TestCase):
    def test_five_years_offered(self):
        self.assertEqual(sorted(aep_convert.TARGET_VERSIONS),
                         [2022, 2023, 2024, 2025, 2026])

    def test_years_are_distinct_releases(self):
        self.assertEqual(len(set(aep_convert.TARGET_VERSIONS.values())), 5)

    def test_describe_version_names_the_year(self):
        self.assertIn("2024", aep_convert.describe_version("24.0x42"))
        self.assertIn("2026", aep_convert.describe_version("26.0x67"))

    def test_describe_version_unknown_string(self):
        self.assertTrue(aep_convert.describe_version("99.0x99"))


class OutputPathTests(unittest.TestCase):
    def test_default_name_carries_the_year(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "shootout.aep")
            open(src, "wb").close()
            out = aep_convert.output_path_for(src, 2024)
            self.assertEqual(os.path.basename(out), "shootout_AE2024.aep")
            self.assertFalse(os.path.exists(out))

    def test_taken_name_gets_a_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "shootout.aep")
            open(src, "wb").close()
            open(os.path.join(d, "shootout_AE2024.aep"), "wb").close()
            out = aep_convert.output_path_for(src, 2024)
            self.assertEqual(os.path.basename(out), "shootout_AE2024_2.aep")


class _FakePyAepMixin:
    def _stub(self, version="26.0x67"):
        self._had_real = "py_aep" in sys.modules
        self._real = sys.modules.get("py_aep")
        _install_fake_py_aep(version)

    def _unstub(self):
        if self._had_real and self._real is not None:
            sys.modules["py_aep"] = self._real
        else:
            sys.modules.pop("py_aep", None)

    def _src(self, d, name="shootout.aep"):
        src = os.path.join(d, name)
        with open(src, "wb") as f:
            f.write(b"fake-aep")
        return src
class ConvertTests(_FakePyAepMixin, unittest.TestCase):
    def setUp(self):
        self._stub("26.0x67")

    def tearDown(self):
        self._unstub()

    def test_roundtrip_relabels_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d)
            res = aep_convert.convert(src, 2024)
            self.assertEqual(res["src_version"], "26.0x67")
            self.assertEqual(res["year"], 2024)
            self.assertEqual(res["target"], aep_convert.TARGET_VERSIONS[2024])
            self.assertTrue(os.path.isfile(res["out_path"]))

    def test_unknown_year_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d)
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(src, 2030)

    def test_missing_source_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(os.path.join(d, "ghost.aep"), 2024)

    def test_existing_destination_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d)
            dest = os.path.join(d, "taken.aep")
            open(dest, "wb").close()
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(src, 2024, out_path=dest)

    def test_destination_equal_to_source_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d)
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(src, 2024, out_path=src)

    def test_damaged_file_refused(self):
        def _bad(path):
            raise ValueError("bad riff")
        setattr(sys.modules["py_aep"], "parse", _bad)
        with tempfile.TemporaryDirectory() as d:
            src = self._src(d)
            with self.assertRaises(aep_convert.AepError) as cm:
                aep_convert.convert(src, 2024)
            self.assertIn("shootout.aep", str(cm.exception))

    def test_missing_dependency_names_the_interpreter(self):
        # Force the import inside aep_convert to fail, whatever is cached.
        import builtins
        real_import = builtins.__import__

        def _no_py_aep(name, *args, **kwargs):
            if name == "py_aep" or name.startswith("py_aep."):
                raise ImportError("No module named 'py_aep'")
            return real_import(name, *args, **kwargs)

        popped = sys.modules.pop("py_aep", None)
        builtins.__import__ = _no_py_aep
        try:
            with tempfile.TemporaryDirectory() as d:
                src = self._src(d)
                with self.assertRaises(aep_convert.AepMissingDependency) as cm:
                    aep_convert.convert(src, 2024)
                self.assertIn(sys.executable, str(cm.exception))
        finally:
            builtins.__import__ = real_import
            if popped is not None:
                sys.modules["py_aep"] = popped


class ReadVersionTests(_FakePyAepMixin, unittest.TestCase):
    def setUp(self):
        self._stub("25.0x42")

    def tearDown(self):
        self._unstub()

    def test_returns_the_raw_version_string(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "x.aep")
            open(src, "wb").close()
            self.assertEqual(aep_convert.read_version(src), "25.0x42")

    def test_missing_file_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(aep_convert.AepError):
                aep_convert.read_version(os.path.join(d, "ghost.aep"))


if __name__ == "__main__":
    unittest.main()
