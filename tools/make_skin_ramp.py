"""Generate the skin shading ramp.

Skin is the one material where a two-tone cel band always looks wrong. Light
enters the surface, scatters, and leaves again reddened, so the shadow does not
just get darker -- it gets *warmer*, and there is a red bloom sitting right at
the terminator where the path through the flesh is longest. A hard threshold
cannot produce that; a ramp can, because it lets the colour turn as the surface
falls away from the light rather than only dimming.

The shader multiplies albedo by this ramp (``celDiffuse`` with ``UseRampMap``),
so these are multipliers, not colours: white on the right means "leave the
texture alone in full light", and the left end tints towards blood.

Rows, selected with ``RampRowIndex``:

    0  neutral   general-purpose anime skin
    1  warm      stronger subsurface, for close-ups and bare torsos
    2  pale      restrained, cool-leaning -- porcelain characters
    3  tan       deeper and more saturated, for darker skin

    python tools/make_skin_ramp.py

Standard library only.
"""

import os
import struct
import sys
import zlib

WIDTH = 256
ROW_HEIGHT = 32

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "textures")

# (position along the ramp, multiplier). Position 0 = fully turned away from
# the light, 1 = facing it.
ROWS = [
    ("neutral", [
        (0.00, (0.40, 0.24, 0.22)),
        (0.25, (0.52, 0.31, 0.28)),
        (0.42, (0.78, 0.51, 0.46)),   # the terminator bloom
        (0.55, (0.95, 0.83, 0.79)),
        (0.72, (1.00, 0.97, 0.95)),
        (1.00, (1.00, 1.00, 1.00)),
    ]),
    ("warm", [
        (0.00, (0.44, 0.20, 0.17)),
        (0.22, (0.60, 0.28, 0.23)),
        (0.40, (0.88, 0.47, 0.39)),   # a wider, redder bloom
        (0.56, (0.98, 0.80, 0.74)),
        (0.74, (1.00, 0.96, 0.93)),
        (1.00, (1.00, 1.00, 1.00)),
    ]),
    ("pale", [
        (0.00, (0.46, 0.36, 0.38)),
        (0.28, (0.60, 0.47, 0.49)),
        (0.46, (0.82, 0.68, 0.68)),
        (0.58, (0.96, 0.89, 0.88)),
        (0.75, (1.00, 0.98, 0.98)),
        (1.00, (1.00, 1.00, 1.00)),
    ]),
    ("tan", [
        (0.00, (0.32, 0.17, 0.13)),
        (0.24, (0.46, 0.24, 0.18)),
        (0.42, (0.72, 0.42, 0.31)),
        (0.56, (0.92, 0.73, 0.62)),
        (0.74, (0.99, 0.94, 0.90)),
        (1.00, (1.00, 1.00, 1.00)),
    ]),
]


def write_png(path, width, height, pixels):
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                                  8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
                     + chunk(b"IEND", b""))


def sample(stops, t):
    """Piecewise-linear lookup, smoothed so no stop shows as a crease."""
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        if p0 <= t <= p1:
            u = (t - p0) / (p1 - p0)
            u = u * u * (3.0 - 2.0 * u)          # smoothstep between stops
            return tuple(c0[k] + (c1[k] - c0[k]) * u for k in range(3))
    return stops[-1][1]


def build():
    """Rows are written bottom-up.

    The shader flips V when it samples (``flipUV``), so a top-down image makes
    RampRowIndex 0 land on the last row -- measured, not assumed: index 1 came
    back with R/B 1.19 against the 'pale' row's 1.21. Reversing here keeps the
    index matching the documented order instead of pushing the surprise onto
    whoever reads the preset.
    """
    height = ROW_HEIGHT * len(ROWS)
    pixels = bytearray(WIDTH * height * 3)
    for row, (_, stops) in enumerate(reversed(ROWS)):
        line = bytearray(WIDTH * 3)
        for x in range(WIDTH):
            colour = sample(stops, x / float(WIDTH - 1))
            for c in range(3):
                v = max(0.0, min(1.0, colour[c]))
                line[x * 3 + c] = int(v * 255.0 + 0.5)
        for y in range(row * ROW_HEIGHT, (row + 1) * ROW_HEIGHT):
            pixels[y * WIDTH * 3:(y + 1) * WIDTH * 3] = line
    return WIDTH, height, pixels


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    width, height, pixels = build()
    path = os.path.join(OUT_DIR, "skin_ramp.png")
    write_png(path, width, height, pixels)
    print("skin_ramp %dx%d (%d rows) -> %s  (%.1f KB)"
          % (width, height, len(ROWS), path, os.path.getsize(path) / 1024.0))
    for i, (name, stops) in enumerate(ROWS):
        shadow = stops[0][1]
        print("  row %d  %-8s shadow multiplier R/B = %.2f"
              % (i, name, shadow[0] / max(1e-6, shadow[2])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
