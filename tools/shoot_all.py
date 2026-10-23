"""Grab screenshots of every page, for eyeballing a layout change.

Run:  python tools/shoot_all.py [outdir]

Builds the real window once and walks every page, saving a PNG per page.
One window for all of them, not one process per page: the queue and
history pages then render whatever the app really holds, and a page that
is built lazily is built in the same order a user would reach it.

The page list is read off the app's own _LAZY_PAGES so a page added
there is never missing from the gallery.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PIL import ImageGrab  # noqa: E402
import ui  # noqa: E402
from ui import UniversalAudioStudio  # noqa: E402

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_shots")
SIZE = (1280, 820)


def page_names():
    """Every page the app can show, in nav order."""
    names = ["downloader"]
    for page, _attr, _builder, _title in UniversalAudioStudio._LAZY_PAGES:
        names.append(page)
    return names


def pump(app, n=30, delay=0.02):
    for _ in range(n):
        try:
            app.update_idletasks()
            app.update()
        except Exception:
            pass
        time.sleep(delay)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    app = UniversalAudioStudio()
    app.geometry("%dx%d+40+40" % SIZE)
    app.update_idletasks()
    pump(app, 10, 0.01)

    # ImageGrab reads the screen at those coordinates, so the window has to
    # actually be in front.
    app.attributes("-topmost", True)
    app.deiconify()
    app.lift()
    pump(app, 20, 0.02)

    written = []
    for page in page_names():
        try:
            app.show_frame(page)
        except Exception as exc:
            print("skip %s: %s" % (page, exc))
            continue
        # The history/queue pages render asynchronously (worker thread ->
        # main thread), so give them a moment to land before the grab.
        pump(app, 40, 0.02)
        x, y = app.winfo_rootx(), app.winfo_rooty()
        w, h = app.winfo_width(), app.winfo_height()
        out = os.path.join(OUT_DIR, "%s.png" % page)
        try:
            ImageGrab.grab(bbox=(x, y, x + w, y + h),
                           all_screens=True).save(out)
            written.append(out)
            print(out)
        except Exception as exc:
            print("failed %s: %s" % (page, exc))
    app.destroy()
    print("%d page(s) captured in %s" % (len(written), OUT_DIR))


if __name__ == "__main__":
    main()
