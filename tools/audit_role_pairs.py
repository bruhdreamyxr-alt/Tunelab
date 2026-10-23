"""Report, per theme, the contrast of the role pairs the UI actually uses.

Run:  python tools/audit_role_pairs.py

The UI paints a secondary button with ``sidebar_active`` and a card with
``sidebar``, but the page behind them is ``surface``. This prints the
contrast of exactly those pairs, so a role that is unreadable on a
surface is a number rather than an opinion.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ui_theme import COLOR_THEMES, _contrast  # noqa: E402

# (foreground role, background role, what it is in the UI, needed)
PAIRS = (
    ("text", "surface", "body text on a page", 4.5),
    ("text", "sidebar", "body text on a card", 4.5),
    ("text", "sidebar_active", "text on a secondary button", 4.5),
    ("sub", "surface", "muted text on a page", 4.5),
    ("sub", "sidebar", "muted text on a card", 4.5),
    ("sub", "sidebar_active", "muted text on a secondary button", 4.5),
    ("accent", "surface", "accent on a page", 3.0),
    ("accent", "sidebar", "accent on a card", 3.0),
    ("accent", "sidebar_active", "accent on a secondary button", 3.0),
    ("sidebar_active", "surface", "secondary button fill vs the page", 1.2),
    ("sidebar", "surface", "card fill vs the page", 1.2),
    ("hover", "surface", "control border vs the page", 1.2),
    ("success", "surface", "success text on a page", 3.0),
    ("danger", "surface", "danger text on a page", 3.0),
    ("warning", "surface", "warning text on a page", 3.0),
)


def main():
    worst = {}
    for name, pal in COLOR_THEMES.items():
        if pal.get("mode") != "dark":
            continue
        for fg, bg, what, need in PAIRS:
            if fg not in pal or bg not in pal:
                continue
            got = _contrast(pal[fg], pal[bg])
            if got >= need:
                continue
            worst.setdefault(what, []).append((got, name, fg, bg, need))

    for what, rows in sorted(worst.items()):
        rows.sort()
        print("\n%s:" % what)
        for got, name, fg, bg, need in rows:
            print("   %-16s %s on %s = %.2f (need %.1f)"
                  % (name, fg, bg, got, need))


if __name__ == "__main__":
    main()
