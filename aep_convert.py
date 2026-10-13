"""After Effects project (.aep) version inspection and conversion.

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

A converted file is always written to a NEW path; the caller decides where,
and the original is never opened for writing. This module owns no Tk and no
widget construction, so it stays unit-testable without a window.
"""
import os
import sys
from typing import Optional

# Target releases offered in the UI, as the canonical version string py_aep
# writes for that year (``major.0xbuild``). The build numbers are the ones
# Adobe shipped as the year's baseline; picking the baseline keeps the
# converted file openable across that whole release train, not just one patch.
TARGET_VERSIONS = {
    2022: "22.0x53",
    2023: "23.0x53",
    2024: "24.0x42",
    2025: "25.0x42",
    2026: "26.0x67",
}

# The AE major that each release year corresponds to. Adobe jumped from a
# 2021 release (major 21) straight to a 2022 major, so the numbers are not
# simply the last two digits of the year.
_MAJOR_BY_YEAR = {2022: 22, 2023: 23, 2024: 24, 2025: 25, 2026: 26}
_YEAR_BY_MAJOR = {major: year for year, major in _MAJOR_BY_YEAR.items()}


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
    """
    major, _minor, _build = _version_tuple(version)
    year = _YEAR_BY_MAJOR.get(major)
    if year is None:
        return "AE %s (unknown release)" % version
    return "AE %d (%s)" % (year, version)


def read_version(path: str) -> str:
    """Return the raw version string ('26.0x67') that last saved *path*."""
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
    """Default destination: ``<name>_AE<year>.aep`` next to the source.

    ``save()`` refuses to overwrite, so if that name is taken we append
    ``_2``, ``_3`` ... until it is free. The returned path never exists,
    which is exactly what ``save()`` demands.
    """
    base = os.path.splitext(os.path.basename(src_path))[0]
    folder = out_dir or os.path.dirname(os.path.abspath(src_path))
    candidate = os.path.join(folder, "%s_AE%d.aep" % (base, year))
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, "%s_AE%d_%d.aep" % (base, year, n))
        n += 1
    return candidate


def convert(src_path: str, year: int,
            out_path: Optional[str] = None) -> dict:
    """Relabel *src_path* for AE *year*; return a result dict for the UI.

    The dict carries ``src_version`` (what the file said), ``year``,
    ``target`` (the version string written) and ``out_path``. Anything going
    wrong raises :class:`AepError` with a user-showable message - including
    py_aep's own refusal to relabel across the AE 23 layer record or the AE
    17 folder id, which we deliberately let through unchanged.
    """
    if year not in TARGET_VERSIONS:
        raise AepError("No converter target for %r." % (year,))
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
        app.project.save(dest)
    except Exception as exc:
        raise AepError("Could not write %s (%s)."
                       % (os.path.basename(dest), exc)) from exc
    return {"src_version": src_version, "year": year,
            "target": target, "out_path": dest}
