"""Generate FinGuard PWA icons.

The mark is the app's signature: three payoff bars of decreasing length,
each one ending sooner than the last. Reads as a small ledger at 40px.
"""
from PIL import Image, ImageDraw

INK    = (15, 23, 32)
JADE   = (14, 122, 95)
VIOLET = (70, 59, 150)
AMBER  = (176, 122, 12)
ALARM  = (178, 58, 46)

BARS = [(ALARM, 0.86), (JADE, 0.62), (VIOLET, 0.40), (AMBER, 0.24)]


def draw(size, pad_ratio, radius_ratio, bg=INK):
    """pad_ratio: safe-area inset. maskable icons need a fat one."""
    s = size * 4  # supersample, then downscale for clean edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    r = int(s * radius_ratio)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=bg)

    pad = s * pad_ratio
    inner = s - pad * 2
    bar_h = inner * 0.115
    gap = (inner - bar_h * len(BARS)) / (len(BARS) - 1)
    br = bar_h / 2

    for i, (color, frac) in enumerate(BARS):
        y0 = pad + i * (bar_h + gap)
        x1 = pad + inner * frac
        d.rounded_rectangle([pad, y0, x1, y0 + bar_h], radius=br, fill=color)

    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = "./icons"
    # standard icons: tight padding, iOS-ish squircle radius
    for n in (180, 192, 512):
        draw(n, 0.20, 0.22).save(f"{out}/icon-{n}.png")
    # maskable: content must survive a 20% circular crop on Android
    draw(512, 0.28, 0.5).save(f"{out}/icon-maskable-512.png")
    # favicon
    draw(64, 0.20, 0.22).save(f"{out}/favicon.png")
    print("icons written")
