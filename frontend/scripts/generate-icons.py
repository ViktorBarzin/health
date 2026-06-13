#!/usr/bin/env python3
"""Generate the PWA icon set for the Health fitness platform.

Draws a clean dumbbell + heart-rate-pulse motif on the brand green and emits
every size the web manifest / iOS / favicon need. Deterministic: re-running
produces byte-stable PNGs so the committed assets stay reproducible.

Two motif framings are produced:
  * "any"      — motif fills ~78% of the canvas (normal launcher/favicon use).
  * "maskable" — motif confined to the inner 80% safe zone on a full-bleed
                 background, so Android's adaptive-icon mask never clips it.

Requires Pillow (`pip install pillow`); no SVG rasterizer needed.

Usage:  python3 scripts/generate-icons.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "static"

# Brand palette (mirrors app.css --color-primary / --color-heart).
GREEN_DARK = (4, 120, 87)      # primary-700
GREEN = (16, 185, 129)         # primary-500
WHITE = (255, 255, 255)
HEART = (239, 68, 68)          # --color-heart

# Supersample factor for crisp anti-aliased edges, then downscale (Lanczos).
SS = 4


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """A vertical two-stop gradient background, fully opaque."""
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        grad.putpixel(
            (0, y),
            tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    return grad.resize((size, size)).convert("RGBA")


def _rounded_rect_mask(size: int, radius_frac: float) -> Image.Image:
    """An alpha mask with rounded corners (radius as a fraction of size)."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_frac)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return mask


def _draw_motif(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float) -> None:
    """Draw the dumbbell + heart-rate pulse centered at (cx, cy).

    `scale` is the motif half-extent in pixels (the motif spans ~2*scale wide).
    """
    # ---- Heart-rate pulse line behind the bar ----
    line_w = max(2, int(scale * 0.10))
    pulse_y = cy
    span = scale * 0.95
    # Classic ECG zig-zag: flat, up spike, deep dip, recover, flat.
    pts = [
        (cx - span, pulse_y),
        (cx - span * 0.45, pulse_y),
        (cx - span * 0.22, pulse_y - scale * 0.45),
        (cx - span * 0.02, pulse_y + scale * 0.55),
        (cx + span * 0.18, pulse_y - scale * 0.20),
        (cx + span * 0.40, pulse_y),
        (cx + span, pulse_y),
    ]
    draw.line(pts, fill=HEART, width=line_w, joint="curve")

    # ---- Dumbbell ----
    bar_h = scale * 0.18
    bar_half_w = scale * 0.32
    # Center bar.
    draw.rounded_rectangle(
        [cx - bar_half_w, cy - bar_h / 2, cx + bar_half_w, cy + bar_h / 2],
        radius=bar_h / 2,
        fill=WHITE,
    )

    plate_outer_h = scale * 0.92
    plate_inner_h = scale * 0.64
    plate_w = scale * 0.20
    gap = bar_half_w  # plates sit at the bar ends

    for side in (-1, 1):
        # Inner (smaller) plate.
        ix = cx + side * gap
        draw.rounded_rectangle(
            [ix - plate_w / 2, cy - plate_inner_h / 2, ix + plate_w / 2, cy + plate_inner_h / 2],
            radius=plate_w * 0.35,
            fill=WHITE,
        )
        # Outer (taller) plate + end cap.
        ox = cx + side * (gap + plate_w * 1.15)
        draw.rounded_rectangle(
            [ox - plate_w / 2, cy - plate_outer_h / 2, ox + plate_w / 2, cy + plate_outer_h / 2],
            radius=plate_w * 0.35,
            fill=WHITE,
        )
        # End knob.
        kx = cx + side * (gap + plate_w * 1.15 + plate_w * 0.55)
        knob_h = scale * 0.34
        draw.rounded_rectangle(
            [kx - plate_w * 0.45, cy - knob_h / 2, kx + plate_w * 0.45, cy + knob_h / 2],
            radius=plate_w * 0.3,
            fill=WHITE,
        )


def render(size: int, *, maskable: bool, rounded: bool) -> Image.Image:
    """Render one icon at `size` px."""
    s = size * SS
    bg = _vertical_gradient(s, GREEN, GREEN_DARK)

    if rounded and not maskable:
        # Favicon/touch icons look better with a soft rounded square.
        mask = _rounded_rect_mask(s, 0.22)
        out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        out.paste(bg, (0, 0), mask)
    else:
        out = bg.copy()

    draw = ImageDraw.Draw(out)
    cx = cy = s / 2
    # Maskable: keep motif inside the inner 80% safe zone (so half-extent smaller).
    half_extent = s * (0.30 if maskable else 0.39)
    _draw_motif(draw, cx, cy, half_extent)

    return out.resize((size, size), Image.LANCZOS)


def save(img: Image.Image, name: str) -> None:
    path = STATIC / name
    img.save(path, format="PNG", optimize=True)
    print(f"  wrote {name} ({img.size[0]}x{img.size[1]})")


def main() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    print(f"Generating PWA icons into {STATIC}")

    # Standard manifest icons ("any" purpose) — full square, no rounding so the
    # platform can apply its own masking consistently.
    save(render(192, maskable=False, rounded=False), "pwa-192x192.png")
    save(render(512, maskable=False, rounded=False), "pwa-512x512.png")

    # Maskable icon (Android adaptive) — safe-zone framed, full-bleed bg.
    save(render(512, maskable=True, rounded=False), "pwa-maskable-512x512.png")
    save(render(192, maskable=True, rounded=False), "pwa-maskable-192x192.png")

    # iOS apple-touch-icon — rounded square, no transparency (iOS adds its own
    # corner mask but a 180px PNG is the documented size).
    save(render(180, maskable=False, rounded=True), "apple-touch-icon.png")

    # Favicons.
    save(render(64, maskable=False, rounded=True), "favicon.png")
    fav = render(48, maskable=False, rounded=True)
    fav.save(STATIC / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    print("  wrote favicon.ico (16/32/48)")


if __name__ == "__main__":
    main()
