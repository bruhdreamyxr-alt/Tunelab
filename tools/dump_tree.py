"""Dump the built widget tree of every page, with geometry and colour.

Run:  python tools/dump_tree.py [page]

For each widget: class, text, geometry, fill, text colour, font size.
This is the readable form of the UI - the screenshots cannot be read
directly, so the tree is how the layout is actually inspected.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# The console on Windows is cp1252 and cannot print the bullet the app
# uses as a status dot. Reconfigure stdout to utf-8 instead of crashing
# halfway through the dump.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import customtkinter as ctk  # noqa: E402
from ui import UniversalAudioStudio  # noqa: E402

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
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    if isinstance(value, str) and value.startswith("#") and len(value) == 7:
        return value.lower()
    return None


def _size(w):
    try:
        font = w.cget("font")
        if isinstance(font, (tuple, list)) and len(font) > 1:
            return font[1]
        if isinstance(font, int):
            return font
    except Exception:
        pass
    return None


def dump(app, w, depth=0):
    try:
        if not w.winfo_ismapped():
            return
    except Exception:
        return
    kind = type(w).__name__
    parts = ["  " * depth + kind]
    for opt, attr in (("text", "t"), ("fg_color", "f"), ("text_color", "tc")):
        try:
            v = w.cget(opt)
        except Exception:
            continue
        if opt == "text":
            v = str(v or "")
            if v:
                parts.append("%s=%r" % (attr, v[:44]))
        else:
            r = _rgb(v)
            if r:
                parts.append("%s=%s" % (attr, r))
    s = _size(w)
    if s:
        parts.append("fs=%s" % s)
    try:
        parts.append("@%d,%d %dx%d" % (w.winfo_x(), w.winfo_y(),
                                       w.winfo_width(), w.winfo_height()))
    except Exception:
        pass
    try:
        mgr = w.winfo_manager()
        if mgr:
            parts.append("[%s]" % mgr)
    except Exception:
        pass
    print(" ".join(parts))
    for child in w.winfo_children():
        dump(app, child, depth + 1)


def main():
    app = UniversalAudioStudio()
    app.geometry("%dx%d+40+40" % SIZE)
    app.update_idletasks()
    pump(app, 10, 0.01)

    pages = ["downloader"]
    for page, _attr, _builder, _title in UniversalAudioStudio._LAZY_PAGES:
        pages.append(page)

    only = sys.argv[1] if len(sys.argv) > 1 else None
    for page in pages:
        if only and page != only:
            continue
        app.show_frame(page)
        pump(app, 30, 0.02)
        print("\n########## %s ##########" % page)
        root = app._page_frames.get(page)
        if root is None:
            root = getattr(app, "tab_downloader", None)
        if root is not None:
            dump(app, root)
    app.destroy()


if __name__ == "__main__":
    main()
