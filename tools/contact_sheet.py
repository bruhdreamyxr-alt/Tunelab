"""Stitch the per-page screenshots into one contact sheet.

Run:  python tools/contact_sheet.py _shots [out.png]

Eyeballing eight PNGs one at a time is slow and it hides the things that
matter most: a spacing rhythm that is off on every page, a header that
never lines up, a control that is the same size everywhere. One sheet
puts them side by side so those show up.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw  # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_shots")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "_shots", "_sheet.png")
COLS = int(sys.argv[3]) if len(sys.argv) > 3 else 2
THUMB_W = 620
GAP = 16
LABEL_H = 26


def main():
    names = sorted(n for n in os.listdir(SRC)
                   if n.lower().endswith(".png")
                   and not n.startswith("_"))
    if not names:
        raise SystemExit("no PNGs in %s" % SRC)

    thumbs = []
    for name in names:
        img = Image.open(os.path.join(SRC, name)).convert("RGB")
        scale = THUMB_W / img.width
        thumb = img.resize((THUMB_W, max(1, int(img.height * scale))),
                           Image.LANCZOS)
        thumbs.append((name, thumb))

    rows = (len(thumbs) + COLS - 1) // COLS
    cell_h = max(t.height for _n, t in thumbs) + LABEL_H
    sheet = Image.new("RGB",
                      (COLS * THUMB_W + (COLS + 1) * GAP,
                       rows * cell_h + (rows + 1) * GAP),
                      (24, 24, 30))
    draw = ImageDraw.Draw(sheet)

    for i, (name, thumb) in enumerate(thumbs):
        col, row = i % COLS, i // COLS
        x = GAP + col * (THUMB_W + GAP)
        y = GAP + row * cell_h
        draw.text((x + 2, y + 6), name, fill=(210, 210, 220))
        sheet.paste(thumb, (x, y + LABEL_H))

    sheet.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
