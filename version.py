"""Application version metadata for self-update checks."""
# 2.1.0 retired Google Drive: copies of 2.0.0 and earlier only accepted an
# update whose version is *strictly greater* than their own, so the release that
# hands them the GitHub-based updater had to be a higher number than 2.0.0.
#
# 2.1.1 carries the hardened updater (see updater_cli.py): a locked file no longer
# aborts the install partway, and the package writes the updater first so a
# partial update still leaves the fixed one behind.
#
# 2.6.0 is the AEP Version Converter release (projects and presets,
# 2022-2026), lazy page builds, the inline update banner, and an update
# confirmation that only promises the admin prompt when this machine
# actually needs it.
#
# 2.6.1 is a fix release: 2.6.0's startup banner rendered as an empty strip
# (the builder moved to ui_widgets.py and left the frame's pack() behind).
# It also adds "Skip this version" to the banner and shows the release
# notes inline, so an update can be judged before it is taken.
#
# 2.7.0 is the Update Center release: a dedicated Updates page that is the
# only place the app updates from (the Speed tab's duplicate button is
# gone), "Skip this version" undone from there, release notes browsable on
# the page, and download history moved onto a SQLite database that
# imports the old JSON entries itself.
#
# 2.8.0 puts every updater on that one surface and makes the app keep
# itself working. The downloader engine (yt-dlp) gets its own card on the
# Update Center with a live version line - it used to sit on the Speed tab
# with a startup note pointing users at the wrong page. Packaged builds
# now also install an available engine update on startup (opt-out, once a
# day) instead of only warning, since extractor rot is the operational
# risk this app exists to survive. Downloads are final on disk:
# VIDEO_FORMAT_SORT_FIELDS now ranks the codec first (H.264, AAC) so a
# finished file plays everywhere, and the old After Effects re-encode step
# is gone entirely - there is nothing left to fix up after the download.

__version__ = "2.9.7"