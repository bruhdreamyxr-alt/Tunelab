"""After Effects project (.aep) and preset (.ffx) version inspection.

The honest shape of this problem, because it decides what the feature can be:
Adobe never documents the .aep format and never ships a downgrade tool. A
project saved by a newer After Effects carries chunks, feature flags and
layer records that older releases do not understand, and the only supported
way to make an old release open it is to open-and-resave inside every
intermediate version. No file-level rewrite can "convert project content"
that way - not this one, not the paid online services either; they relabel
the version header and hope the content is compatible, and say so in their
own fine print.

What we do instead is the same relabel done *carefully*, via ``py_aep``
(the reverse-engineered parser from Fortiche, the Arcane studio):

* Reading the version that saved a file is exact and always safe.
* Writing a target version rewrites the version field AND the file-format
  compatibility marker together, so the result is internally consistent.
* The two relabels After Effects itself would refuse - anything landing on
  the AE 2022 layer-record layout from a 2023+ source, and the AE 2020
  media-replacement folder id - raise instead of emitting a file that no
  release will open. We surface that refusal rather than bury it.

Animation presets (.ffx) share the RIFX container but not the head shape.
py_aep cannot parse them at all, so this module handles them itself, from
measurement rather than guesswork: across the presets Adobe ships with
After Effects 2025 (679 files, formats 68-97) the head is always a 16-byte
body ``marker=3, format, subversion, flags`` (big-endian u32s), and the
(format, subversion) pair is exactly what py_aep records for the projects
of that release - (95, 6) is AE 2024, (93, 43) is AE 2022. A preset
conversion therefore patches just those two fields of an otherwise
byte-identical copy; the LIST body, the XMP tail and the original file
stay untouched.

A converted file is always written to a NEW path; the caller decides where,
and the original is never opened for writing. This module owns no Tk and no
widget construction, so it stays unit-testable without a window.
"""
import os
import struct
import sys
from pathlib import Path
from typing import Optional

# Target releases offered in the UI, as the canonical version string py_aep
# writes for that year (``major.0xbuild``). The build numbers are the ones
# Adobe shipped as the year's baseline; picking the baseline keeps the
# converted file openable across that whole release train, not just one patch.
TARGET_VERSIONS = {
    2020: "17.0x53",
    2021: "18.0x53",
    2022: "22.0x53",
    2023: "23.0x53",
    2024: "24.0x42",
    2025: "25.0x42",
    2026: "26.0x67",
}

# The AE major that each release year corresponds to. Adobe jumped from a
# 2021 release (major 21) straight to a 2022 major, so the numbers are not
# simply the last two digits of the year.
_MAJOR_BY_YEAR = {2020: 17, 2021: 18, 2022: 22, 2023: 23, 2024: 24, 2025: 25, 2026: 26}
_YEAR_BY_MAJOR = {major: year for year, major in _MAJOR_BY_YEAR.items()}

# --- Animation presets (.ffx) ------------------------------------------------
# Container form of a preset; projects carry _PROJECT_FORM instead (that is
# the root list type py_aep itself writes, see py_aep/project.py).
_FFX_FORM = b"FaFX"
_PROJECT_FORM = b"Egg!"
# File offset of the format u32: 12 (RIFX header) + 8 (chunk header) + 4
# (the marker field that opens the 16-byte head body).
_FFX_STAMP_OFFSET = 24
_FFX_MARKER = 3
# The (format, subversion) pair each target release stamps into new files,
# from py_aep's FORMAT_VERSIONS - the same baselines TARGET_VERSIONS picks
# for projects. format is the AE major plus 71 for 2022+ (93 = 22 ... 97 = 26).
_FFX_STAMPS = {
    2020: (93, 22),
    2021: (93, 29),
    2022: (93, 43),
    2023: (94, 9),
    2024: (95, 6),
    2025: (96, 9),
    2026: (97, 2),
}
# Reading the year back: 94-97 each map to one major, 92 was only ever
# major 15 (CC 2018), and 93 spans majors 16-22 (2019-2022), so only its
# subversion can pick the year. Formats older than 92 have no verified
# table - the label shows the format number instead of a guessed year.
_FFX_YEAR_BY_FORMAT = {92: 2018, 94: 2023, 95: 2024, 96: 2025, 97: 2026}
_FFX_YEAR_BY_SUB_93 = {5: 2019, 22: 2020, 29: 2021, 43: 2022}


class AepError(Exception):
    """A conversion could not be done; ``str(e)`` is safe to show a user."""


class AepMissingDependency(AepError):
    """py_aep is not importable in the running interpreter."""


def _require_py_aep():
    """Import py_aep or explain, in user terms, why the tab is inert.

    The message names the interpreter that is actually running, because the
    usual cause is launching the app with the system Python instead of the
    project's venv (which is where ``py-aep`` is installed).
    """
    try:
        import py_aep  # local: optional until the converter is actually used
    except Exception as exc:  # pragma: no cover - depends on the install
        raise AepMissingDependency(
            "The project converter needs the 'py-aep' package, which this "
            "Python does not have (%s).\n\n"
            "You are running:\n%s\n\n"
            "Fix it one of these ways:\n"
            "1. Run the app with the project interpreter:\n"
            "   C:\\Users\\antho\\Downloads\\scripts\\path\\.venv\\Scripts\\python.exe main.py\n"
            "2. Or install the package into this Python:\n"
            "   python -m pip install py-aep"
            % (sys.executable, sys.executable)
        ) from exc
    return py_aep


def _version_tuple(version: str) -> tuple:
    """``'26.0x67'`` -> ``(26, 0, 67)``. Tolerates a missing build part."""
    core, _, build = str(version).partition("x")
    parts = core.split(".")
    major = int(parts[0]) if parts and parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return (major, minor, int(build) if build.isdigit() else 0)


def describe_version(version: str) -> str:
    """Human label for a version string: 'AE 2024 (24.0x42)' or a fallback.

    Falls back to the raw string for builds whose major we do not map, so an
    odd or pre-2022 file still shows something true rather than a wrong year.
    Preset stamps ('ffx:<format>.<subversion>') label the same way.
    """
    if str(version).startswith("ffx:"):
        return _describe_ffx_version(str(version))
    major, _minor, _build = _version_tuple(version)
    year = _YEAR_BY_MAJOR.get(major)
    if year is None:
        return "AE %s (unknown release)" % version
    return "AE %d (%s)" % (year, version)


def is_ffx(path: str) -> bool:
    """True when *path* names an animation preset by its extension."""
    return os.path.splitext(str(path))[1].lower() == ".ffx"


def _describe_ffx_version(stamp: str) -> str:
    """Label an ``ffx:<fmt>.<sub>`` stamp: 'AE 2024 (preset format 95.6)'.

    Years come from the measured tables above; formats with no verified
    year keep the format number rather than a guessed year.
    """
    fmt_s, dot, sub_s = stamp[4:].partition(".")
    fmt = int(fmt_s) if fmt_s.isdigit() else -1
    sub = int(sub_s) if dot and sub_s.isdigit() else -1
    if fmt < 0:
        return "preset (%s)" % stamp
    detail = ("preset format %d" % fmt if sub < 0
              else "preset format %d.%d" % (fmt, sub))
    if fmt == 93:
        year = _FFX_YEAR_BY_SUB_93.get(sub)
        if year is not None:
            return "AE %d (%s)" % (year, detail)
        return "AE 2019-2022 (%s)" % detail
    year = _FFX_YEAR_BY_FORMAT.get(fmt)
    if year is not None:
        return "AE %d (%s)" % (year, detail)
    if fmt > max(_FFX_YEAR_BY_FORMAT):
        return "newer After Effects than this tool knows (%s)" % detail
    return "old After Effects (%s)" % detail


def _read_file_bytes(path: str) -> bytes:
    """Read *path* fully, or raise :class:`AepError` a user can be shown."""
    if not os.path.isfile(path):
        raise AepError("No such file: %s" % path)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise AepError("Could not read %s (%s)."
                       % (os.path.basename(path), exc)) from exc


def _parse_ffx_head(data: bytes, name: str) -> tuple:
    """Validate preset bytes; return ``(format, subversion)`` from the head.

    ``name`` is the file's basename, for messages. Every failure raises
    :class:`AepError` rather than guessing at a header this converter does
    not actually understand.
    """
    if len(data) < 12 or data[:4] != b"RIFX":
        raise AepError(
            "Could not read %s as an After Effects preset. It may not be an "
            ".ffx file, or it may be damaged. (missing RIFX header)" % name)
    form = data[8:12]
    if form == _PROJECT_FORM:
        raise AepError("%s is an After Effects project, not a preset." % name)
    if form != _FFX_FORM:
        raise AepError(
            "Could not read %s as an After Effects preset. Its container is "
            "%r, not 'FaFX'. It may not be an .ffx file, or it may be "
            "damaged." % (name, form))
    if len(data) < 20 or data[12:16] != b"head":
        raise AepError(
            "Could not read %s as an After Effects preset. The file has no "
            "'head' chunk, so it may be damaged." % name)
    head_len = struct.unpack_from(">I", data, 16)[0]
    if head_len < 12:
        raise AepError(
            "Could not read %s as an After Effects preset. The 'head' chunk "
            "is too short (%d bytes)." % (name, head_len))
    if len(data) < 20 + head_len:
        raise AepError(
            "Could not read %s as an After Effects preset. The file ends "
            "inside its 'head' chunk, so it may be damaged." % name)
    marker, fmt, sub = struct.unpack_from(">III", data, 20)
    if marker != _FFX_MARKER:
        raise AepError(
            "%s has a preset header shape this converter does not know "
            "(marker %d, expected %d); refusing to guess where the version "
            "lives." % (name, marker, _FFX_MARKER))
    if fmt == 0:
        raise AepError(
            "Could not read %s as an After Effects preset. Its header "
            "reports format 0, which no After Effects has ever written."
            % name)
    return (fmt, sub)


def _read_ffx_version(path: str) -> str:
    """Return ``'ffx:<format>.<subversion>'`` for the preset at *path*."""
    fmt, sub = _parse_ffx_head(_read_file_bytes(path),
                               os.path.basename(path))
    return "ffx:%d.%d" % (fmt, sub)


def read_version(path: str) -> str:
    """Return the version that last saved *path*.

    Projects yield py_aep's raw string ('26.0x67'); presets yield the
    stamp form ``'ffx:<format>.<subversion>'``. Both label through
    :func:`describe_version`, and presets need no optional dependency.
    """
    if is_ffx(path):
        return _read_ffx_version(path)
    py_aep = _require_py_aep()
    if not os.path.isfile(path):
        raise AepError("No such file: %s" % path)
    try:
        app = py_aep.parse(path)
    except Exception as exc:
        raise AepError(
            "Could not read %s as an After Effects project. It may not be an "
            ".aep file, or it may be damaged. (%s)"
            % (os.path.basename(path), exc)
        ) from exc
    return str(app.version)


def output_path_for(src_path: str, year: int, out_dir: Optional[str] = None) -> str:
    """Default destination: ``<name>_AE<year><ext>`` next to the source.

    The source's own extension is kept, so a preset stays a .ffx (a name
    with no extension defaults to .aep). Nothing here exists yet: if the
    name is taken we append ``_2``, ``_3`` ... until it is free, because
    both writers refuse to overwrite.
    """
    base, ext = os.path.splitext(os.path.basename(src_path))
    folder = out_dir or os.path.dirname(os.path.abspath(src_path))
    ext = ext or ".aep"
    candidate = os.path.join(folder, "%s_AE%d%s" % (base, year, ext))
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, "%s_AE%d_%d%s" % (base, year, n, ext))
        n += 1
    return candidate


def _guard_destination(src_path: str, dest: str) -> None:
    """Refuse writing onto the source or onto anything that already exists."""
    if os.path.abspath(dest) == os.path.abspath(src_path):
        raise AepError(
            "The destination is the source file itself. Pick a different "
            "output name - the original is never overwritten."
        )
    if os.path.exists(dest):
        raise AepError(
            "Refusing to overwrite %s. Pick a different output name."
            % os.path.basename(dest)
        )


def convert(src_path: str, year: int,
            out_path: Optional[str] = None) -> dict:
    """Relabel *src_path* for AE *year*; return a result dict for the UI.

    The dict carries ``src_version`` (what the file said), ``year``,
    ``target`` (the version written) and ``out_path``. Anything going
    wrong raises :class:`AepError` with a user-showable message - including
    py_aep's own refusal to relabel across the AE 23 layer record or the AE
    17 folder id, which we deliberately let through unchanged. ``.ffx``
    presets dispatch to :func:`_convert_ffx`, which needs no py_aep.
    """
    if year not in TARGET_VERSIONS:
        raise AepError("No converter target for %r." % (year,))
    if is_ffx(src_path):
        return _convert_ffx(src_path, year, out_path)
    target = TARGET_VERSIONS[year]
    py_aep = _require_py_aep()
    if not os.path.isfile(src_path):
        raise AepError("No such file: %s" % src_path)
    try:
        app = py_aep.parse(src_path)
    except Exception as exc:
        raise AepError(
            "Could not read %s as an After Effects project. It may not be "
            "an .aep file, or it may be damaged. (%s)"
            % (os.path.basename(src_path), exc)
        ) from exc
    src_version = str(app.version)
    dest = out_path or output_path_for(src_path, year)
    _guard_destination(src_path, dest)
    try:
        app.version = target
    except ValueError as exc:
        # py_aep's own guard: a relabel no After Effects would open.
        raise AepError(
            "That conversion is not possible: %s" % exc
        ) from exc
    except Exception as exc:
        raise AepError("Could not re-stamp the project (%s)." % exc) from exc
    try:
        app.project.save(Path(dest))
    except Exception as exc:
        raise AepError("Could not write %s (%s)."
                       % (os.path.basename(dest), exc)) from exc
    return {"src_version": src_version, "year": year,
            "target": target, "out_path": dest}


def _convert_ffx(src_path: str, year: int,
                 out_path: Optional[str] = None) -> dict:
    """Relabel a preset: copy it, patch only format+subversion in the head.

    ``py_aep`` is deliberately not involved - it cannot parse presets, and
    the two stamp fields sit at a fixed offset in an otherwise opaque file,
    so the LIST body, the XMP tail and every other byte are carried across
    untouched. Result dict matches :func:`convert`'s; ``src_version`` and
    ``target`` use the ``ffx:<format>.<subversion>`` stamp form.
    """
    stamp = _FFX_STAMPS.get(year)
    if stamp is None:
        raise AepError("No converter target for %r." % (year,))
    name = os.path.basename(src_path)
    data = _read_file_bytes(src_path)
    fmt_src, sub_src = _parse_ffx_head(data, name)
    dest = out_path or output_path_for(src_path, year)
    _guard_destination(src_path, dest)
    patched = bytearray(data)
    struct.pack_into(">II", patched, _FFX_STAMP_OFFSET, stamp[0], stamp[1])
    try:
        with open(dest, "wb") as fh:
            fh.write(patched)
    except OSError as exc:
        raise AepError("Could not write %s (%s)."
                       % (os.path.basename(dest), exc)) from exc
    return {"src_version": "ffx:%d.%d" % (fmt_src, sub_src),
            "year": year, "target": "ffx:%d.%d" % stamp, "out_path": dest}
