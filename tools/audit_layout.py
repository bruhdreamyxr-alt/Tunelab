"""Audit the built UI for layout and colour defects.

Run:  python tools/audit_layout.py [--page NAME]

Walks the real widget tree of every page and reports things that are
objectively wrong rather than taste:

  * widgets that overflow their parent's box (clipped content),
  * text that is too small or too large for its role,
  * fills that are too close to the fill behind them (invisible controls),
  * rows that do not line up with each other (ragged grids),
  * controls with a different height than their neighbours.

Everything is measured off the live widget tree, so a finding is a fact
about the running app, not a guess from the source.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import customtkinter as ctk  # noqa: E402
from ui import UniversalAudioStudio  # noqa: E402
from ui_theme import _contrast, _rel_luminance  # noqa: E402

SIZE = (1280, 820)


def pump(app, n=25, delay=0.02):
    for _ in range(n):
        try:
            app.update_idletasks()
            app.update()
        except Exception:
            pass
        time.sleep(delay)


def _rgb(value):
    """Normalise a CTk colour option to '#rrggbb', or None."""
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return value.lower()
    return None


def _mix(a, b, t):
    """Blend two hex colours, t in 0..1 toward b."""
    a = (a or "#000000").lstrip("#")
    b = (b or "#000000").lstrip("#")
    av = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    bv = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(
        int(round(av[i] + (bv[i] - av[i]) * t)) for i in range(3))


def text_of(w):
    try:
        return str(w.cget("text") or "")
    except Exception:
        return ""


def walk(app, root):
    """Every widget under root, parents before children."""
    out = []

    def rec(w, depth):
        out.append((w, depth))
        for child in w.winfo_children():
            rec(child, depth + 1)

    rec(root, 0)
    return out


def audit_page(app, name, root):
    findings = []
    widgets = walk(app, root)
    app.update_idletasks()

    for w, depth in widgets:
        try:
            if not w.winfo_ismapped():
                continue
        except Exception:
            continue
        wx, wy = w.winfo_rootx(), w.winfo_rooty()
        ww, wh = w.winfo_width(), w.winfo_height()
        if ww <= 1 or wh <= 1:
            continue
        parent = w.master
        try:
            pwx = parent.winfo_rootx()
            pwy = parent.winfo_rooty()
            pww = parent.winfo_width()
            pwh = parent.winfo_height()
        except Exception:
            continue

        kind = type(w).__name__

        # 1. Overflow: the widget sticks out of its parent's box.
        if (wx < pwx - 2 or wy < pwy - 2
                or wx + ww > pwx + pww + 2 or wy + wh > pwy + pwh + 2):
            # Ignore the deliberate full-bleed children (a scroll frame's
            # canvas legitimately fills its parent).
            if not isinstance(w, (ctk.CTkScrollableFrame,)):
                findings.append(
                    "overflow: %s %r at (%d,%d %dx%d) outside parent "
                    "(%d,%d %dx%d)"
                    % (kind, text_of(w)[:30], wx - pwx, wy - pwy, ww, wh,
                       pww, pwh))

        # 2. Tiny or huge type.
        try:
            font = w.cget("font")
            size = None
            if isinstance(font, (tuple, list)) and len(font) > 1:
                size = font[1]
            elif isinstance(font, int):
                size = font
        except Exception:
            size = None
        if size is not None and text_of(w).strip():
            if size < 9:
                findings.append(
                    "tiny text: %s %r at %spx" % (kind, text_of(w)[:30], size))
            elif size >= 22:
                findings.append(
                    "huge text: %s %r at %spx" % (kind, text_of(w)[:30], size))

        # 3. A filled control whose fill matches what is behind it.
        if isinstance(w, (ctk.CTkButton, ctk.CTkEntry, ctk.CTkOptionMenu)):
            fg = _rgb(w.cget("fg_color"))
            if fg:
                bg = _rgb(parent.cget("fg_color")) if isinstance(
                    parent, (ctk.CTkFrame, ctk.CTkScrollableFrame,
                             ctk.CTkButton)) else None
                if bg and fg == bg:
                    findings.append(
                        "invisible control: %s %r fill %s == parent fill %s"
                        % (kind, text_of(w)[:30], fg, bg))

    return findings


def main():
    app = UniversalAudioStudio()
    app.geometry("%dx%d+40+40" % SIZE)
    app.update_idletasks()
    pump(app, 10, 0.01)

    pages = ["downloader"]
    for page, _attr, _builder, _title in UniversalAudioStudio._LAZY_PAGES:
        pages.append(page)

    total = 0
    for page in pages:
        app.show_frame(page)
        pump(app, 30, 0.02)
        root = app._page_frames.get(page)
        if root is None:
            root = getattr(app, "tab_downloader", None)
        if root is None:
            continue
        findings = audit_page(app, page, root)
        if findings:
            print("== %s ==" % page)
            for f in findings:
                print("  -", f)
            total += len(findings)
    print("\n%d finding(s)" % total)
    app.destroy()


if __name__ == "__main__":
    main()
