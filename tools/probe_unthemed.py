"""Probe the widget kinds the theme walks do not reach.

Run:  python tools/probe_unthemed.py

Reports, off the live tree:

  * CTkSegmentedButton - its segment buttons keep CustomTkinter's own
    greys, and the *selected* segment is the same colour as the
    unselected one, so the toggle shows no state at all;
  * CTkRadioButton - the same, for the AEP year picker;
  * CTkEntry - the field fill is CTk's white, not the palette's;
  * card frames that were filled from the wrong palette role.

A theme switch must repaint every one of these, or a palette change
leaves grey furniture behind.
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
from ui import UniversalAudioStudio  # noqa: E402
from ui_theme import COLOR_THEMES  # noqa: E402


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


def main():
    app = UniversalAudioStudio()
    app.geometry("1280x820+40+40")
    app.update_idletasks()
    pump(app, 10, 0.01)

    # --- The selection bug, checked by clicking rather than by reading ----
    print("=== downloader mode toggle ===")
    app.show_frame("downloader")
    pump(app, 20, 0.02)
    toggle = app.dl_mode_toggle
    print("values            %r" % (toggle.cget("values"),))
    print("variable value    %r" % (app.dl_mode_var.get(),))
    print("selected segment  %r" % (toggle.get(),))
    for name, btn in toggle._buttons_dict.items():
        print("  segment %-8r fill=%s" % (name, _rgb(btn.cget("fg_color"))))
    print("-> clicking 'Video'")
    toggle._buttons_dict["Video"].invoke()
    pump(app, 6, 0.02)
    print("variable value    %r" % (app.dl_mode_var.get(),))
    print("selected segment  %r" % (toggle.get(),))
    print("_start_download routes on %r" % ("mode == 'video'",))
    print("-> would take the video branch? %s"
          % (app.dl_mode_var.get() == "video"))

    print("\n=== entry fill in a dark palette ===")
    print("url_entry fg      %s" % _rgb(app.url_entry.cget("fg_color")))
    print("url_entry text    %s" % _rgb(app.url_entry.cget("text_color")))
    print("palette bg        %s" % COLOR_THEMES["TuneLab Dark"]["bg"])

    print("\n=== AEP radio buttons ===")
    app.show_frame("aep")
    pump(app, 20, 0.02)
    for w in app._iter_widgets():
        if isinstance(w, ctk.CTkRadioButton):
            print("radio %-6r fg=%s text=%s hover=%s border=%s roles=%s" % (
                w.cget("text"), _rgb(w.cget("fg_color")),
                _rgb(w.cget("text_color")), _rgb(w.cget("hover_color")),
                _rgb(w.cget("border_color")),
                getattr(w, "_theme_roles", None)))
            break

    print("\n=== segmented buttons, all pages ===")
    pages = ["downloader"]
    for page, _attr, _builder, _title in UniversalAudioStudio._LAZY_PAGES:
        pages.append(page)
    for page in pages:
        app.show_frame(page)
        pump(app, 20, 0.02)
        for w in app._iter_widgets():
            if not isinstance(w, ctk.CTkSegmentedButton):
                continue
            var = getattr(w, "_variable", None)
            print("  %-11s values=%r var=%r selected=%r fg=%s unsel=%s" % (
                page, w.cget("values"), var.get() if var else None,
                w.get(), _rgb(w.cget("fg_color")),
                _rgb(w.cget("unselected_color"))))

    print("\n--- palette reference ---")
    print("TuneLab Dark", COLOR_THEMES["TuneLab Dark"])
    app.destroy()


if __name__ == "__main__":
    main()
