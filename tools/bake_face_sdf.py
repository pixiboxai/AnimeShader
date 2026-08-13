"""Bake a face shadow SDF the way Genshin Impact does it.

A cel band on a face is unstable: as the light swings round, the terminator
crawls over the nose and cheek and breaks the drawing. The fix the industry
settled on is to stop computing the face shadow at all and look it up instead.

Each texel stores *the moment it goes dark* -- not a distance, despite the name.
The shader turns the light's horizontal angle into the same number and compares:

    threshold = (1 - dot(headForward, lightHorizontal)) * 0.5
    lit       = sdf > threshold

so 0 means "in shadow even with the light dead ahead" and 1 means "still lit
with the light directly behind". The shadow then sweeps across the face in the
shapes an artist would draw, and never wobbles.

The value is found by actually sweeping a light around the head and watching
each vertex, including self-shadowing -- the nose casting onto the cheek is the
whole point, and a plain N·L test would miss it. Per-vertex results are then
rasterised into UV space.

Only one side needs baking: the shader mirrors U when the light crosses to the
other side of the head.

    import bake_face_sdf
    bake_face_sdf.bake("Head", "H:/.../T_Hiro_Face_SDF.png")
"""

import math
import os
import struct
import zlib

from maya import cmds
import maya.api.OpenMaya as om


def write_png(path, size, pixels):
    """8-bit greyscale written as RGB, so any loader shows it correctly."""
    raw = bytearray()
    stride = size * 3
    for y in range(size):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size,
                                                  8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
                     + chunk(b"IEND", b""))


def _dag(mesh):
    sel = om.MSelectionList()
    sel.add(mesh)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    return dag


def sweep(mesh, forward, right, steps=60, bias=0.05, reach=None):
    """Per-vertex angle at which the light stops reaching it.

    Returns a list of sdf values in [0, 1], one per vertex.
    """
    dag = _dag(mesh)
    fn = om.MFnMesh(dag)
    points = fn.getPoints(om.MSpace.kWorld)
    normals = fn.getVertexNormals(False, om.MSpace.kWorld)
    accel = fn.autoUniformGridParams()

    box = fn.boundingBox
    if reach is None:
        reach = (box.width + box.height + box.depth) * 0.6

    F = om.MVector(*forward).normal()
    R = om.MVector(*right).normal()

    # Precompute the light directions once; they do not depend on the vertex.
    lights = []
    for s in range(steps + 1):
        theta = math.pi * s / float(steps)          # 0 .. 180 degrees
        lights.append((theta, (F * math.cos(theta) + R * math.sin(theta)).normal()))

    out = []
    for i in range(len(points)):
        n = om.MVector(normals[i])
        origin = om.MFloatPoint(points[i] + n * bias)
        value = 1.0                                  # never goes dark
        for theta, L in lights:
            if (n * L) <= 0.0:
                value = (1.0 - math.cos(theta)) * 0.5
                break
            hit = fn.anyIntersection(origin, om.MFloatVector(L.x, L.y, L.z),
                                     om.MSpace.kWorld, reach, False,
                                     accelParams=accel, tolerance=1e-4)
            if hit and hit[0] is not None:
                value = (1.0 - math.cos(theta)) * 0.5
                break
        out.append(max(0.0, min(1.0, value)))
    return out


def rasterise(mesh, values, size, uv_set):
    """Draw the per-vertex field into UV space. Returns (buffer, coverage)."""
    dag = _dag(mesh)
    field = [0.0] * (size * size)
    filled = bytearray(size * size)

    it = om.MItMeshPolygon(dag)
    while not it.isDone():
        verts = it.getVertices()
        uvs = {}
        for local, vid in enumerate(verts):
            try:
                uvs[vid] = it.getUV(local, uv_set)
            except RuntimeError:
                uvs[vid] = None
        _, ids = it.getTriangles(om.MSpace.kWorld)

        for t in range(0, len(ids), 3):
            tri = [ids[t], ids[t + 1], ids[t + 2]]
            if any(uvs.get(v) is None for v in tri):
                continue
            p = [(uvs[v][0] * (size - 1), (1.0 - uvs[v][1]) * (size - 1))
                 for v in tri]
            w = [values[v] for v in tri]

            minx = max(0, int(math.floor(min(q[0] for q in p))))
            maxx = min(size - 1, int(math.ceil(max(q[0] for q in p))))
            miny = max(0, int(math.floor(min(q[1] for q in p))))
            maxy = min(size - 1, int(math.ceil(max(q[1] for q in p))))
            if maxx < minx or maxy < miny:
                continue

            (x0, y0), (x1, y1), (x2, y2) = p
            denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(denom) < 1e-12:
                continue

            for py in range(miny, maxy + 1):
                for px in range(minx, maxx + 1):
                    a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
                    b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
                    c = 1.0 - a - b
                    if a < -0.001 or b < -0.001 or c < -0.001:
                        continue
                    idx = py * size + px
                    field[idx] = a * w[0] + b * w[1] + c * w[2]
                    filled[idx] = 1
        it.next()
    return field, filled


def dilate(field, filled, size, rounds=4):
    """Bleed the field outwards so UV seams do not sample empty space."""
    for _ in range(rounds):
        additions = []
        for y in range(size):
            for x in range(size):
                i = y * size + x
                if filled[i]:
                    continue
                total = 0.0
                count = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < size and 0 <= ny < size:
                            j = ny * size + nx
                            if filled[j]:
                                total += field[j]
                                count += 1
                if count:
                    additions.append((i, total / count))
        if not additions:
            break
        for i, v in additions:
            field[i] = v
            filled[i] = 1
    return field


def blur(field, size, radius=1):
    """A light box blur: the SDF is meant to be smooth, and rasterising
    per-vertex values leaves faceting along the triangle edges."""
    out = list(field)
    for y in range(size):
        for x in range(size):
            total = 0.0
            count = 0
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < size and 0 <= ny < size:
                        total += field[ny * size + nx]
                        count += 1
            out[y * size + x] = total / count
    return out


def bake(mesh="Head", output=None, size=512, steps=60, uv_set=None,
         forward=None, right=None, blur_radius=1):
    """Bake and write the SDF. Returns a dict of what happened."""
    uv_set = uv_set or (cmds.polyUVSet(mesh, q=True, currentUVSet=True)
                        or ["map1"])[0]
    forward = forward or (0.0, 0.0, 1.0)
    right = right or (1.0, 0.0, 0.0)

    values = sweep(mesh, forward, right, steps=steps)
    field, filled = rasterise(mesh, values, size, uv_set)
    covered = sum(filled)
    field = dilate(field, filled, size)
    if blur_radius:
        field = blur(field, size, blur_radius)

    pixels = bytearray(size * size * 3)
    for i, v in enumerate(field):
        b = int(max(0.0, min(1.0, v)) * 255.0 + 0.5)
        pixels[i * 3] = pixels[i * 3 + 1] = pixels[i * 3 + 2] = b
    if output:
        write_png(output, size, pixels)

    ordered = sorted(values)
    n = len(ordered)
    return {"output": output, "size": size, "uv_set": uv_set,
            "vertices": n, "steps": steps,
            "coverage": covered / float(size * size),
            "p10": ordered[n // 10], "p50": ordered[n // 2],
            "p90": ordered[9 * n // 10],
            "always_lit": sum(1 for v in values if v >= 0.999),
            "always_dark": sum(1 for v in values if v <= 0.001)}
