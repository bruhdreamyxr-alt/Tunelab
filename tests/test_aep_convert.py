"""Unit tests for aep_convert: version parsing, naming, conversion guards.

py_aep is stubbed, so these run without After Effects files and without
the optional dependency installed - they pin the module's own logic
(paths, errors, refusals), not the parser's. The .ffx preset tests build
synthetic but structurally real preset bytes (RIFX/FaFX/16-byte head plus
an XMP tail, like the presets Adobe ships), so they also pin the FFX head
layout and the patch-only write path.
"""
import os
import struct
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


def _mk_ffx_bytes(fmt=95, sub=6, marker=3, form=b"FaFX", head_len=None):
    """Build a minimal but structurally real .ffx preset.

    Mirrors the layout measured from Adobe's shipped presets: RIFX header,
    'head' chunk (marker, format, subversion, flags - big-endian u32s), a
    LIST besc chunk, and an XMP packet tail after the container.
    """
    xmp = (b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
           b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>'
           b'<?xpacket end="w"?>')
    body = struct.pack(">IIII", marker, fmt, sub, 0x01020000)
    if head_len is not None:
        body = body.ljust(head_len, b"\x00")[:head_len]
    chunks = (b"head" + struct.pack(">I", len(body)) + body
              + b"LIST" + struct.pack(">I", 8) + b"besc" + b"\x00\x00\x00\x00")
    inner = form + chunks
    return b"RIFX" + struct.pack(">I", len(inner)) + inner + xmp


def _write_ffx(d, name="Fade In.ffx", **kw):
    path = os.path.join(d, name)
    with open(path, "wb") as f:
        f.write(_mk_ffx_bytes(**kw))
    return path


class TargetVersionsTests(unittest.TestCase):
    def test_five_years_offered(self):
        self.assertEqual(sorted(aep_convert.TARGET_VERSIONS),
                         [2020, 2021, 2022, 2023, 2024, 2025, 2026])

    def test_years_are_distinct_releases(self):
        self.assertEqual(len(set(aep_convert.TARGET_VERSIONS.values())), 7)

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


class FfxTests(unittest.TestCase):
    """Real-bytes preset tests: FFX head layout, patch-only write, guards.

    No py_aep stub needed - the preset path is dependency-free by design,
    and test_converts_without_py_aep pins exactly that.
    """

    def test_is_ffx_by_extension(self):
        self.assertTrue(aep_convert.is_ffx("Fade In.ffx"))
        self.assertTrue(aep_convert.is_ffx("Fade In.FFX"))
        self.assertFalse(aep_convert.is_ffx("shootout.aep"))
        self.assertFalse(aep_convert.is_ffx("shootout"))

    def test_read_version_reads_the_stamp(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d, fmt=95, sub=6)
            self.assertEqual(aep_convert.read_version(src), "ffx:95.6")

    def test_read_version_missing_file_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(aep_convert.AepError):
                aep_convert.read_version(os.path.join(d, "ghost.ffx"))

    def test_describe_names_the_year(self):
        label = aep_convert.describe_version("ffx:95.6")
        self.assertIn("2024", label)
        self.assertIn("preset", label)
        self.assertIn("2026", aep_convert.describe_version("ffx:97.2"))
        self.assertIn("2018", aep_convert.describe_version("ffx:92.14"))

    def test_describe_uses_subversion_for_the_shared_format(self):
        # 93 spans majors 16-22 (2019-2022); only the subversion pins them.
        self.assertIn("2022", aep_convert.describe_version("ffx:93.43"))
        self.assertIn("2020", aep_convert.describe_version("ffx:93.22"))
        self.assertIn("2019-2022",
                      aep_convert.describe_version("ffx:93.30"))

    def test_describe_old_format_claims_no_year(self):
        label = aep_convert.describe_version("ffx:68.0")
        self.assertIn("format 68", label)
        self.assertNotRegex(label, r"20\d\d")

    def test_describe_newer_format_is_honest(self):
        label = aep_convert.describe_version("ffx:98.1")
        self.assertIn("format 98", label)
        self.assertNotRegex(label, r"20\d\d")

    def test_output_path_keeps_the_preset_extension(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "Fade In.ffx")
            open(src, "wb").close()
            out = aep_convert.output_path_for(src, 2024)
            self.assertEqual(os.path.basename(out), "Fade In_AE2024.ffx")
            self.assertFalse(os.path.exists(out))

    def test_roundtrip_patches_only_the_stamp(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d, fmt=95, sub=1)  # a Beta-style stamp
            with open(src, "rb") as f:
                before = f.read()
            res = aep_convert.convert(src, 2024)
            self.assertEqual(res["src_version"], "ffx:95.1")
            self.assertEqual(res["year"], 2024)
            self.assertEqual(res["target"], "ffx:95.6")
            self.assertEqual(os.path.basename(res["out_path"]),
                             "Fade In_AE2024.ffx")
            with open(res["out_path"], "rb") as f:
                after = f.read()
            # The stamp (offsets 24-31) becomes the AE 2024 release pair...
            self.assertEqual(struct.unpack_from(">II", after, 24), (95, 6))
            # ...and every other byte, XMP tail included, is carried over.
            self.assertEqual(before[:24], after[:24])
            self.assertEqual(before[32:], after[32:])
            with open(src, "rb") as f:
                self.assertEqual(f.read(), before)  # original untouched


    def test_convert_to_2022_stamps_the_2022_pair(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d, fmt=97, sub=2)
            res = aep_convert.convert(src, 2022)
            with open(res["out_path"], "rb") as f:
                data = f.read()
            self.assertEqual(struct.unpack_from(">II", data, 24), (93, 43))

    def test_unknown_year_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d)
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(src, 2030)

    def test_missing_source_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(os.path.join(d, "ghost.ffx"), 2024)

    def test_existing_destination_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d)
            dest = os.path.join(d, "taken.ffx")
            open(dest, "wb").close()
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(src, 2024, out_path=dest)

    def test_destination_equal_to_source_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d)
            with self.assertRaises(aep_convert.AepError):
                aep_convert.convert(src, 2024, out_path=src)

    def test_not_rifx_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "junk.ffx")
            with open(src, "wb") as f:
                f.write(b"this is not a riff file at all")
            with self.assertRaises(aep_convert.AepError) as cm:
                aep_convert.read_version(src)
            self.assertIn("junk.ffx", str(cm.exception))

    def test_project_named_ffx_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d, form=b"Egg!")
            with self.assertRaises(aep_convert.AepError) as cm:
                aep_convert.read_version(src)
            self.assertIn("project", str(cm.exception))

    def test_wrong_form_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d, form=b"WAVE")
            with self.assertRaises(aep_convert.AepError) as cm:
                aep_convert.read_version(src)
            self.assertIn("WAVE", str(cm.exception))

    def test_short_head_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d, head_len=8)
            with self.assertRaises(aep_convert.AepError) as cm:
                aep_convert.read_version(src)
            self.assertIn("too short", str(cm.exception))

    def test_unknown_head_marker_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = _write_ffx(d, marker=4)
            with self.assertRaises(aep_convert.AepError) as cm:
                aep_convert.read_version(src)
            self.assertIn("marker 4", str(cm.exception))

    def test_converts_without_py_aep(self):
        # Presets must work with py-aep absent: block the import outright.
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
                src = _write_ffx(d, fmt=96, sub=9)
                self.assertEqual(aep_convert.read_version(src), "ffx:96.9")
                res = aep_convert.convert(src, 2024)
                self.assertEqual(res["target"], "ffx:95.6")
                self.assertTrue(os.path.isfile(res["out_path"]))
        finally:
            builtins.__import__ = real_import
            if popped is not None:
                sys.modules["py_aep"] = popped


if __name__ == "__main__":
    unittest.main()
