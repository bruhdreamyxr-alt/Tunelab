"""Motion helpers (Phase 5) - small, Tk-safe animation utilities."""
import customtkinter as ctk


def fade_in(widget, steps=8, delay=16):
    """Fade a widget in by animating its alpha-ish opacity via after()."""
    try:
        widget.attributes("-alpha", 0.0)
    except Exception:
        return
    def _step(i):
        try:
            widget.attributes("-alpha", min(1.0, i / steps))
        except Exception:
            return
        if i < steps:
            widget.after(delay, lambda: _step(i + 1))
    _step(1)


def slide_in(widget, distance=12, steps=8, delay=16):
    """Nudge a widget into place; relies on place/pack geometry managed by caller."""
    pass
