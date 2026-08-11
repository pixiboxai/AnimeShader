"""Generate a tileable rusted-iron albedo texture.

A MatCap cannot give rust its character: it is locked to the camera, so any
grain painted into it swims across the surface as the object turns. Corrosion
has to live in UV space, on the model. This writes that map.

The look is built from three layers, which is roughly how rust actually forms:
bare iron underneath, an oxide bloom eating into it in patches, and a darker
crust where the bloom is thickest.

    python tools/make_rust.py [size]

Seamless: the noise lattice wraps, so the map tiles in both directions.
"""

import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "textures")

IRON = (0.20, 0.20, 0.21)
RUST = (0.46, 0.22, 0.10)
CRUST = (0.21, 0.11, 0.07)
BLOOM = (0.58, 0.31, 0.13)


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


def hash01(x, y, seed):
    n = math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453
    return n - math.floor(n)


def noise(x, y, period, seed):
    """Value noise on a lattice that wraps every ``period`` cells."""
    ix, iy = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - ix, y - iy
    sx = fx * fx * (3 - 2 * fx)
    sy = fy * fy * (3 - 2 * fy)
    x0, x1 = ix % period, (ix + 1) % period
    y0, y1 = iy % period, (iy + 1) % period
    a = hash01(x0, y0, seed)
    b = hash01(x1, y0, seed)
    c = hash01(x0, y1, seed)
    d = hash01(x1, y1, seed)
    return ((a * (1 - sx) + b * sx) * (1 - sy)
            + (c * (1 - sx) + d * sx) * sy)


def fbm(u, v, base_period, seed, octaves=5):
    total = 0.0
    amp = 0.5
    norm = 0.0
    period = base_period
    for _ in range(octaves):
        total += amp * noise(u * period, v * period, period, seed)
        norm += amp
        amp *= 0.5
        period *= 2
    return total / norm


def punch(value, amount):
    """Stretch a noise field around 0.5.

    Summing octaves and normalising drives the result towards the mean, so raw
    fbm is nearly flat -- the first version of this texture came out a uniform
    grey. Expanding the range afterwards is what gives rust its patchiness.
    """
    return max(0.0, min(1.0, (value - 0.5) * amount + 0.5))


def smoothstep(edge0, edge1, x):
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def build(size):
    pixels = bytearray(size * size * 3)
    for py in range(size):
        v = py / float(size)
        for px in range(size):
            u = px / float(size)

            bloom = punch(fbm(u, v, 4, 1.0), 3.4)          # where oxide spread
            grain = punch(fbm(u, v, 32, 2.0), 3.0)         # fine crust
            flake = punch(fbm(u, v, 12, 3.0), 3.2)         # flaking scale
            streak = punch(fbm(u, v * 0.25, 8, 4.0), 3.0)  # run-off

            # Rust dominates; bare iron shows only where the bloom is thin.
            oxide = smoothstep(0.18, 0.62, bloom)
            oxide = max(oxide, smoothstep(0.55, 0.85, streak))

            colour = mix(IRON, RUST, oxide)
            colour = mix(colour, BLOOM, smoothstep(0.55, 0.95, flake) * oxide)
            colour = mix(colour, CRUST, smoothstep(0.45, 0.05, grain) * 0.85)
            colour = tuple(c * (0.62 + 0.76 * grain) for c in colour)

            i = (py * size + px) * 3
            for c in range(3):
                x = colour[c]
                x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
                pixels[i + c] = int(pow(x, 1.0 / 2.2) * 255.0 + 0.5)
    return pixels


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 512
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    path = os.path.join(OUT_DIR, "rust_albedo.png")
    write_png(path, size, size, build(size))
    print("rust_albedo %dx%d -> %s  (%.0f KB)"
          % (size, size, path, os.path.getsize(path) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
