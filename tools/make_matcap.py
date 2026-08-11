"""Generate metal MatCap textures.

A MatCap is a photograph of a sphere made of the material, looked at head-on.
The shader samples it by the view-space normal, so all the reflection detail a
cel shader cannot compute is simply painted in. It is how stylised renderers
get believable metal without an environment probe.

These are built rather than found: a studio environment is evaluated along the
reflection vector, so the same code makes gold, silver and rust by changing a
handful of numbers -- and you can re-render them at any size.

    python tools/make_matcap.py

Writes to textures/ next to this script's project root. Standard library only.
"""

import math
import os
import struct
import sys
import zlib

SIZE = 512
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "textures")


def write_png(path, width, height, pixels):
    """8-bit RGBA, filter 0 on every row."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        body = struct.pack(">I", len(data)) + tag + data
        return body + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(png)


def normalise(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / length for c in v)


def hash01(x, y, seed):
    """Deterministic value noise in [0, 1]."""
    n = math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453
    return n - math.floor(n)


def fbm(x, y, seed, octaves=4):
    total = 0.0
    amp = 0.5
    freq = 1.0
    for _ in range(octaves):
        ix, iy = math.floor(x * freq), math.floor(y * freq)
        fx, fy = x * freq - ix, y * freq - iy
        # smooth interpolation between lattice values
        sx = fx * fx * (3 - 2 * fx)
        sy = fy * fy * (3 - 2 * fy)
        a = hash01(ix, iy, seed)
        b = hash01(ix + 1, iy, seed)
        c = hash01(ix, iy + 1, seed)
        d = hash01(ix + 1, iy + 1, seed)
        total += amp * ((a * (1 - sx) + b * sx) * (1 - sy) +
                        (c * (1 - sx) + d * sx) * sy)
        amp *= 0.5
        freq *= 2.0
    return total


# Two lights and a sky/ground split -- a plain studio, evaluated along the
# reflection vector.
KEY = normalise((-0.45, 0.72, 0.53))
FILL = normalise((0.65, 0.15, 0.60))


def environment(r, sky, ground, key_power, key_gain, fill_gain):
    horizon = r[1] * 0.5 + 0.5
    base = tuple(ground[i] + (sky[i] - ground[i]) * horizon for i in range(3))

    kd = max(0.0, sum(a * b for a, b in zip(r, KEY)))
    fd = max(0.0, sum(a * b for a, b in zip(r, FILL)))
    key = pow(kd, key_power) * key_gain
    fill = pow(fd, max(2.0, key_power * 0.2)) * fill_gain
    return tuple(base[i] + key + fill for i in range(3))


MATERIALS = {
    # tint,                  sky,               ground,            keyPow, keyGain, fillGain, fresnel, rough
    "gold":   dict(tint=(1.00, 0.76, 0.33), sky=(0.62, 0.55, 0.42), ground=(0.16, 0.10, 0.04),
                   key_power=90.0, key_gain=2.6, fill_gain=0.35, fresnel=0.35, rough=0.0),
    "silver": dict(tint=(0.96, 0.96, 0.99), sky=(0.72, 0.75, 0.82), ground=(0.14, 0.15, 0.19),
                   key_power=140.0, key_gain=3.0, fill_gain=0.30, fresnel=0.45, rough=0.0),
    "rust":   dict(tint=(0.40, 0.19, 0.11), sky=(0.31, 0.26, 0.23), ground=(0.09, 0.06, 0.04),
                   key_power=9.0, key_gain=0.28, fill_gain=0.10, fresnel=0.10, rough=0.80),
}


def build(name, spec):
    half = SIZE * 0.5
    pixels = bytearray(SIZE * SIZE * 4)

    for py in range(SIZE):
        for px in range(SIZE):
            # sphere normal across the disc
            nx = (px + 0.5 - half) / half
            ny = (half - py - 0.5) / half
            r2 = nx * nx + ny * ny
            i = (py * SIZE + px) * 4

            if r2 > 1.0:
                # Outside the sphere: keep the edge colour so bilinear filtering
                # at the rim does not fade to black.
                s = 1.0 / math.sqrt(r2)
                nx, ny = nx * s, ny * s
                nz = 0.0
                alpha = 255
            else:
                nz = math.sqrt(max(0.0, 1.0 - r2))
                alpha = 255

            n = (nx, ny, nz)

            if spec["rough"] > 0.0:
                # Rough metal: perturb the normal with noise before reflecting,
                # which scatters the highlight the way corroded surfaces do.
                amp = spec["rough"] * 0.35
                n = normalise((n[0] + (fbm(px / 42.0, py / 42.0, 1.0) - 0.5) * amp,
                               n[1] + (fbm(px / 42.0, py / 42.0, 2.0) - 0.5) * amp,
                               n[2] + (fbm(px / 42.0, py / 42.0, 3.0) - 0.5) * amp * 0.4))

            # reflect the view direction (0,0,1) about the normal
            ndv = n[2]
            refl = normalise((2.0 * n[0] * ndv, 2.0 * n[1] * ndv, 2.0 * n[2] * ndv - 1.0))

            env = environment(refl, spec["sky"], spec["ground"],
                              spec["key_power"], spec["key_gain"], spec["fill_gain"])

            colour = [env[c] * spec["tint"][c] for c in range(3)]

            # metal grazing-angle brightening
            fres = spec["fresnel"] * pow(1.0 - max(0.0, min(1.0, ndv)), 4.0)
            colour = [c + fres for c in colour]

            if spec["rough"] > 0.0:
                # pitting and colour drift across the surface
                # corrosion reads as pitting at two scales: fine grain for the
                # crust, broad patches for where it has eaten in deeper
                grain = fbm(px / 11.0, py / 11.0, 7.0)
                patch = fbm(px / 70.0, py / 70.0, 11.0)
                flake = fbm(px / 27.0, py / 27.0, 13.0)
                colour = [c * (0.35 + 1.15 * grain)
                            * (0.55 + 0.85 * patch)
                            * (0.70 + 0.55 * flake) for c in colour]

            for c in range(3):
                v = colour[c]
                v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
                pixels[i + c] = int(pow(v, 1.0 / 2.2) * 255.0 + 0.5)   # to sRGB
            pixels[i + 3] = alpha

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    path = os.path.join(OUT_DIR, "matcap_%s.png" % name)
    write_png(path, SIZE, SIZE, pixels)
    return path


def main():
    for name in sorted(MATERIALS):
        path = build(name, MATERIALS[name])
        print("%-8s -> %s  (%.0f KB)" % (name, path, os.path.getsize(path) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
