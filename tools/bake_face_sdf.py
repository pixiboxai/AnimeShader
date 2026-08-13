"""Bake a face shadow threshold map (the Genshin-style face SDF).

A cel band on a face is unstable: as the light swings round, the terminator
crawls over the nose and cheek and breaks the drawing. The fix the industry
settled on is to stop computing the face shadow and look it up instead.

Each texel stores *the moment it goes dark* -- not a distance, despite the
name. The shader turns the light's horizontal angle into the same number and
compares:

    threshold = (1 - dot(headForward, lightHorizontal)) * 0.5
    lit       = sdf > threshold

so 0 means "in shadow even with the light dead ahead" and 1 means "still lit
with the light directly behind".

Method
------
The usual pipeline (see akasaki1211/sdf_shadow_threshold_map) renders a stack
of binary shadow masks at stepped light angles and blends between consecutive
pairs through their signed distance fields, which recovers a smooth threshold
from a handful of discrete steps.

This bakes the same map, but splits the problem in two rather than stepping the
whole thing:

  * the N-dot-L term is solved *analytically*, per texel. Sweeping a light and
    interpolating between steps is a way of approximating a crossing that can
    simply be computed:  N.L(t) = Nf.cos(t) + Nr.sin(t)  is zero at
    t = atan2(Nf, -Nr), exactly, at any angle. No steps, so nothing to blend
    away, and no quantisation left to filter out.

  * occlusion -- the nose casting onto the cheek, which no analytic form gives
    -- is swept with rays, and takes the earlier of the two angles.

Geometry is rasterised into UV space as position and normal maps first, so both
terms are evaluated per texel. The earlier version of this file interpolated a
per-vertex answer across each triangle, which pinned the shadow edge to the
mesh density: 4582 vertices spread over a 2K map is roughly one sample per
thirty texels, and the boundary showed it.

    import bake_face_sdf
    bake_face_sdf.bake("Head", "H:/.../T_Hiro_Face_SDF.png", size=2048)
"""

import math
import os
import struct
import zlib

from maya import cmds
import maya.api.OpenMaya as om


# --------------------------------------------------------------------------
# image io
# --------------------------------------------------------------------------

def write_png(path, size, pixels, bitdepth=8):
    """Greyscale written as RGB so any loader shows it correctly."""
    raw = bytearray()
    stride = size * 3 * (2 if bitdepth == 16 else 1)
    for y in range(size):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size,
                                                  bitdepth, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
                     + chunk(b"IEND", b""))


def _dag(mesh):
    sel = om.MSelectionList()
    sel.add(mesh)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    return dag


# --------------------------------------------------------------------------
# geometry -> UV space
# --------------------------------------------------------------------------

def rasterise_attributes(mesh, size, uv_set):
    """Position and normal per texel.

    Returns ``(pos, nrm, filled)`` where pos and nrm are flat lists of 3-tuples
    and filled is a byte mask of covered texels.
    """
    dag = _dag(mesh)
    fn = om.MFnMesh(dag)
    points = fn.getPoints(om.MSpace.kWorld)
    normals = fn.getVertexNormals(False, om.MSpace.kWorld)

    n = size * size
    pos = [None] * n
    nrm = [None] * n
    filled = bytearray(n)

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

            pa, pb, pc = (points[tri[0]], points[tri[1]], points[tri[2]])
            na, nb, nc = (normals[tri[0]], normals[tri[1]], normals[tri[2]])

            for py in range(miny, maxy + 1):
                for px in range(minx, maxx + 1):
                    a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
                    b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
                    c = 1.0 - a - b
                    if a < -0.001 or b < -0.001 or c < -0.001:
                        continue
                    idx = py * size + px
                    pos[idx] = (a * pa.x + b * pb.x + c * pc.x,
                                a * pa.y + b * pb.y + c * pc.y,
                                a * pa.z + b * pb.z + c * pc.z)
                    nx = a * na.x + b * nb.x + c * nc.x
                    ny = a * na.y + b * nb.y + c * nc.y
                    nz = a * na.z + b * nb.z + c * nc.z
                    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                    nrm[idx] = (nx / length, ny / length, nz / length)
                    filled[idx] = 1
        it.next()
    return pos, nrm, filled


# --------------------------------------------------------------------------
# the two terms
# --------------------------------------------------------------------------

def analytic_threshold(nrm, filled, forward, right):
    """Exact angle at which N.L crosses zero, per texel, as an sdf value.

    With L(t) = F.cos(t) + R.sin(t):

        N.L(t) = Nf.cos(t) + Nr.sin(t) = A.cos(t - phase)

    which first reaches zero, sweeping t upward from 0, at t = phase + pi/2.
    A texel already facing away at t = 0 gets 0; one that never turns away
    within the half sweep gets 1.
    """
    F, R = forward, right
    out = [0.0] * len(nrm)
    for i, n in enumerate(nrm):
        if not filled[i] or n is None:
            continue
        nf = n[0] * F[0] + n[1] * F[1] + n[2] * F[2]
        nr = n[0] * R[0] + n[1] * R[1] + n[2] * R[2]
        if nf <= 0.0:
            out[i] = 0.0                    # already dark with the light ahead
            continue
        phase = math.atan2(nr, nf)
        theta = phase + math.pi * 0.5       # first zero crossing above t = 0
        if theta >= math.pi:
            out[i] = 1.0
        else:
            out[i] = (1.0 - math.cos(theta)) * 0.5
    return out


def occlusion_threshold(mesh, pos, nrm, filled, forward, right, size,
                        steps=32, bias=0.05):
    """Angle at which something else gets in the way, per texel.

    No closed form for this one -- it depends on the whole head -- so it is
    swept. Texels already dark by N.L are skipped: they cannot be occluded
    into shadow twice.
    """
    dag = _dag(mesh)
    fn = om.MFnMesh(dag)
    accel = fn.autoUniformGridParams()
    box = fn.boundingBox
    reach = (box.width + box.height + box.depth) * 0.6

    F = om.MVector(*forward).normal()
    R = om.MVector(*right).normal()
    lights = []
    for s in range(1, steps + 1):
        theta = math.pi * s / float(steps)
        L = (F * math.cos(theta) + R * math.sin(theta)).normal()
        lights.append(((1.0 - math.cos(theta)) * 0.5,
                       om.MFloatVector(L.x, L.y, L.z), (L.x, L.y, L.z)))

    out = [1.0] * len(pos)
    tested = 0
    for i in range(len(pos)):
        if not filled[i] or pos[i] is None:
            continue
        p, n = pos[i], nrm[i]
        origin = om.MFloatPoint(p[0] + n[0] * bias,
                                p[1] + n[1] * bias,
                                p[2] + n[2] * bias)
        tested += 1
        for level, Lf, Lt in lights:
            if n[0] * Lt[0] + n[1] * Lt[1] + n[2] * Lt[2] <= 0.0:
                break                        # N.L already handles it from here
            hit = fn.anyIntersection(origin, Lf, om.MSpace.kWorld, reach,
                                     False, accelParams=accel, tolerance=1e-4)
            if hit and hit[0] is not None:
                out[i] = level
                break
    return out, tested


# --------------------------------------------------------------------------
# post
# --------------------------------------------------------------------------

def dilate(field, filled, size, rounds=4):
    """Bleed outwards so UV seams do not sample empty space.

    Only the frontier is visited each round. Scanning the whole image costs the
    same on round twenty as on round one, which at 2K is four million pixels of
    long-decided territory per pass.
    """
    frontier = set()
    for y in range(size):
        row = y * size
        for x in range(size):
            if filled[row + x]:
                continue
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1),
                           (-1, -1), (-1, 1), (1, -1), (1, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= nx < size and 0 <= ny < size and filled[ny * size + nx]:
                    frontier.add(row + x)
                    break

    for _ in range(rounds):
        if not frontier:
            break
        additions = []
        for i in frontier:
            y, x = divmod(i, size)
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
        nxt = set()
        for i, _v in additions:
            y, x = divmod(i, size)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < size and 0 <= ny < size:
                        j = ny * size + nx
                        if not filled[j]:
                            nxt.add(j)
        frontier = nxt
    return field


def blur(field, size, radius=1):
    """Box blur run separably: rows, then columns.

    A square kernel costs (2r+1)^2 samples per pixel; two 1D passes cost
    2*(2r+1) for the same result.
    """
    if radius < 1:
        return list(field)

    tmp = [0.0] * (size * size)
    for y in range(size):
        row = y * size
        for x in range(size):
            total = 0.0
            count = 0
            for dx in range(-radius, radius + 1):
                nx = x + dx
                if 0 <= nx < size:
                    total += field[row + nx]
                    count += 1
            tmp[row + x] = total / count

    out = [0.0] * (size * size)
    for x in range(size):
        for y in range(size):
            total = 0.0
            count = 0
            for dy in range(-radius, radius + 1):
                ny = y + dy
                if 0 <= ny < size:
                    total += tmp[ny * size + x]
                    count += 1
            out[y * size + x] = total / count
    return out


# --------------------------------------------------------------------------

def bake(mesh="Head", output=None, size=2048, uv_set=None, forward=None,
         right=None, occlusion_steps=32, occlusion_size=None,
         blur_radius=None, dilate_rounds=None, bitdepth=8):
    """Bake and write the threshold map. Returns a dict of what happened.

    ``occlusion_size`` renders the cast-shadow term at a lower resolution and
    upsamples it: a ray per texel per angle at 2K is tens of millions of casts,
    and cast shadow edges are soft anyway. The N-dot-L term, which carries the
    crisp boundary, always runs at full resolution.
    """
    uv_set = uv_set or (cmds.polyUVSet(mesh, q=True, currentUVSet=True)
                        or ["map1"])[0]
    forward = tuple(forward or (0.0, 0.0, 1.0))
    right = tuple(right or (1.0, 0.0, 0.0))
    scale = size / 512.0
    if blur_radius is None:
        blur_radius = max(1, int(round(scale)))
    if dilate_rounds is None:
        dilate_rounds = max(4, int(round(4 * scale)))
    if occlusion_size is None:
        occlusion_size = min(size, 512)

    pos, nrm, filled = rasterise_attributes(mesh, size, uv_set)
    covered = sum(filled)
    field = analytic_threshold(nrm, filled, forward, right)

    # cast shadows, at their own resolution, then upsampled
    if occlusion_size == size:
        occ, tested = occlusion_threshold(mesh, pos, nrm, filled, forward,
                                          right, size, steps=occlusion_steps)
        for i in range(len(field)):
            if filled[i] and occ[i] < field[i]:
                field[i] = occ[i]
    else:
        opos, onrm, ofilled = rasterise_attributes(mesh, occlusion_size, uv_set)
        occ, tested = occlusion_threshold(mesh, opos, onrm, ofilled, forward,
                                          right, occlusion_size,
                                          steps=occlusion_steps)
        ratio = occlusion_size / float(size)
        for y in range(size):
            oy = min(occlusion_size - 1, int(y * ratio))
            row = y * size
            orow = oy * occlusion_size
            for x in range(size):
                i = row + x
                if not filled[i]:
                    continue
                j = orow + min(occlusion_size - 1, int(x * ratio))
                if ofilled[j] and occ[j] < field[i]:
                    field[i] = occ[j]

    field = dilate(field, bytearray(filled), size, rounds=dilate_rounds)
    if blur_radius:
        field = blur(field, size, blur_radius)

    if bitdepth == 16:
        pixels = bytearray(size * size * 6)
        for i, v in enumerate(field):
            w = int(max(0.0, min(1.0, v)) * 65535.0 + 0.5)
            hi, lo = w >> 8, w & 255
            o = i * 6
            pixels[o] = pixels[o + 2] = pixels[o + 4] = hi
            pixels[o + 1] = pixels[o + 3] = pixels[o + 5] = lo
    else:
        pixels = bytearray(size * size * 3)
        for i, v in enumerate(field):
            b = int(max(0.0, min(1.0, v)) * 255.0 + 0.5)
            pixels[i * 3] = pixels[i * 3 + 1] = pixels[i * 3 + 2] = b
    if output:
        write_png(output, size, pixels, bitdepth)

    inside = [field[i] for i in range(len(field)) if filled[i]]
    inside.sort()
    n = max(1, len(inside))
    return {"output": output, "size": size, "uv_set": uv_set,
            "bitdepth": bitdepth,
            "texels_covered": covered,
            "coverage": covered / float(size * size),
            "occlusion_size": occlusion_size,
            "occlusion_steps": occlusion_steps,
            "occlusion_texels_tested": tested,
            "blur_radius": blur_radius, "dilate_rounds": dilate_rounds,
            "p10": inside[n // 10], "p50": inside[n // 2],
            "p90": inside[9 * n // 10],
            "distinct_values": len(set(int(v * 255) for v in inside))}
