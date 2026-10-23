"""Check every text label's real rendered contrast, in every palette.

Run:  python tools/audit_contrast_all.py

For each theme: switch to it, walk the visible tree, and for every
label with text, work out the colour actually painted and the colour it
is actually painted on, then report the WCAG contrast ratio.

This is the check that catches a palette not being honoured: a label
that kept a hard-coded hex from a dark theme lands unreadable on a
light one, and a muted tone chosen for a dark surface washes out on a
light one.

WCAG AA wants 4.5:1 for body text and 3:1 for text that is large
(>=18px, or >=14px bold).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import customtkinter as ctk  # noqa: E402
from ui import COLOR_THEMES, UniversalAudioStudio  # noqa: E402
from ui_theme import _contrast  # noqa: E402

MIN_BODY = 4.5
MIN_LARGE = 3.0


def pump(app, n=20, delay=0.02):
    for _ in range(n):
        try:
            app.update_idletasks()
            app.update()
        except Exception:
            pass
        time.sleep(delay)


def _rgb(value):
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return value.lower()
    return None


def effective_bg(widget):
    """The colour a label is actually painted on, walking up the parents."""
    node = widget
    while node is not None:
        try:
            fg = _rgb(node.cget("fg_color"))
        except Exception:
            fg = None
        if fg:
            return fg
        node = getattr(node, "master", None)
    return "#000000"


def main():
    app = UniversalAudioStudio()
    app.geometry("1280x820+40+40")
    app.update_idletasks()
    pump(app, 10, 0.01)

    pages = ["downloader"]
    for page, _attr, _builder, _title in UniversalAudioStudio._LAZY_PAGES:
        pages.append(page)

    # Only the palettes the app ships; the custom one is user-made.
    themes = [t for t in COLOR_THEMES if t != "Custom"]
    report = {}

    for theme in themes:
        try:
            app.apply_color_theme(theme)
        except Exception as exc:
            print("skip %s: %s" % (theme, exc))
            continue
        app.update_idletasks()
        findings = []
        for page in pages:
            try:
                app.show_frame(page)
            except Exception:
                continue
            pump(app, 12, 0.01)
            for w in app._iter_widgets():
                if not isinstance(w, ctk.CTkLabel):
                    continue
                try:
                    if not w.winfo_ismapped():
                        continue
                    text = str(w.cget("text") or "").strip()
                except Exception:
                    continue
                if not text:
                    continue
                fg = _rgb(w.cget("text_color"))
                if not fg:
                    continue
                bg = effective_bg(w)
                try:
                    ratio = _contrast(fg, bg)
                except Exception:
                    continue
                font = w.cget("font")
                size = font[1] if isinstance(font, (tuple, list)) and len(font) > 1 else 13
                bold = "bold" in (font[2:] if isinstance(font, (tuple, list)) else ())
                large = size >= 18 or (size >= 14 and bold)
                need = MIN_LARGE if large else MIN_BODY
                if ratio < need:
                    findings.append("%s: %r %s on %s = %.2f (need %.1f)" % (
                        page, text[:34], fg, bg, ratio, need))
        report[theme] = findings

    for theme, findings in report.items():
        if findings:
            print("\n== %s ==" % theme)
            for f in findings:
                print("  -", f)

    total = sum(len(v) for v in report.values())
    print("\n%d contrast failure(s) across %d theme(s)" % (total, len(themes)))
    app.destroy()


if __name__ == "__main__":
    main()
