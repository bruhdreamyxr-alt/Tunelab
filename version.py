"""Application version metadata for self-update checks."""
# 2.1.0 retired Google Drive: copies of 2.0.0 and earlier only accepted an
# update whose version is *strictly greater* than their own, so the release that
# hands them the GitHub-based updater had to be a higher number than 2.0.0.
#
# 2.1.1 carries the hardened updater (see updater_cli.py): a locked file no longer
# aborts the install partway, and the package writes the updater first so a
# partial update still leaves the fixed one behind.
#
# 2.6.0 is the current release: the AEP Version Converter tab (projects and
# presets, 2022-2026), lazy page builds, the inline update banner, and an
# update confirmation that only promises the admin prompt when this machine
# actually needs it.

__version__ = "2.6.0"