#!/usr/bin/env python3
"""Cut the Micetil brand assets out of the identity board.

Source of truth: assets/MICETIL_brand_identity.jpg (2752x1536, light board).

Every file is a crop of that board.  The board's background is a flat near
white, so it is keyed out: neutral pixels that are almost white become
transparent, everything else (the mark, its warm speculars, its shadow)
stays.  The result works on light and on dark surfaces.

Writes, into assets/ :
    emblem.png            the prismatic mark (the big glass X)
    logo-horizontal.png   the mark + the MICETIL wordmark
    mark-mono.png         the flat copper monogram

Run:  python3 tools/crop_brand.py
"""

from __future__ import annotations

import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
BOARD = ASSETS / "MICETIL_brand_identity.jpg"

# name -> (search region, brightness threshold, margin, shadow cut)
# The shadow cut is the luminance at which a neutral (grey) pixel becomes
# transparent: a low cut keeps the soft drop shadow, a high cut drops it.
REGIONS = {
    "emblem.png": ((280, 380, 1100, 1300), 200, 6, 205),
    "logo-horizontal.png": ((1250, 690, 2200, 1010), 200, 6, 205),
    "mark-mono.png": ((2300, 670, 2600, 970), 200, 4, 190),
}


def tight_box(im: Image.Image, box, threshold=200, margin=6):
    """Bounding box of the object inside `box` (the board background is white)."""
    reg = im.crop(box).convert("L")
    px = reg.load()
    w, h = reg.size
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            if px[x, y] < threshold:
                xs.append(x)
                ys.append(y)
    x0 = max(0, min(xs) - margin)
    y0 = max(0, min(ys) - margin)
    x1 = min(w, max(xs) + margin)
    y1 = min(h, max(ys) + margin)
    return (box[0] + x0, box[1] + y0, box[0] + x1, box[1] + y1)


def key_white(im: Image.Image, cut: float = 238.0) -> Image.Image:
    """Make the white board background transparent.

    A pixel is background when it is bright and neutral.  Warm highlights of
    the mark are bright but saturated, so they survive.
    """
    out = im.convert("RGBA")
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            sat = max(r, g, b) - min(r, g, b)
            if sat <= 18:
                if lum >= cut:
                    a = 0.0
                elif lum >= cut - 8:
                    a = (cut - lum) / 8.0
                else:
                    a = 1.0
            else:
                a = 1.0
            px[x, y] = (r, g, b, int(round(a * 255)))
    return out


def main() -> None:
    board = Image.open(BOARD)
    for name, (box, threshold, margin, cut) in REGIONS.items():
        crop = board.crop(tight_box(board, box, threshold, margin))
        key_white(crop, cut).save(ASSETS / name)
        print(f"wrote assets/{name}  {crop.size[0]}x{crop.size[1]}")


if __name__ == "__main__":
    main()
