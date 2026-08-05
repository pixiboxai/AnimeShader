"""Headless checks for the smooth-normal bake.

The shader itself cannot be tested without a GPU viewport, but everything
feeding it can. Run with mayapy, no Maya GUI needed::

    "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" tests/test_mesh_roundtrip.py

Exits non-zero if anything fails, so it drops straight into CI.

What it covers:

1. octahedral encode/decode agrees with the GLSL in GNTAnime.ogsfx
2. bake -> read back off the mesh -> decode the way the shader does
   reproduces the original smooth normal
3. the smooth-normal UV set lands at index 1, i.e. TEXCOORD1
4. the paint colour set lands at index 0, i.e. COLOR0
"""

import math
import os
import sys

import maya.standalone

maya.standalone.initialize("Python")

from maya import cmds                                    # noqa: E402
from maya.api import OpenMaya as om                      # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from gntshader.core import env                           # noqa: E402
from gntshader.utils import mesh as mu                    # noqa: E402

FAILURES = []


def check(condition, label, detail=""):
    status = "PASS" if condition else "FAIL"
    print("  [%s] %s%s" % (status, label, ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


def oct_decode(u, v):
    """Mirror of octDecode() in GNTAnime.ogsfx."""
    fx, fy = u * 2.0 - 1.0, v * 2.0 - 1.0
    nz = 1.0 - abs(fx) - abs(fy)
    t = max(-nz, 0.0)
    nx = fx + (-t if fx >= 0.0 else t)
    ny = fy + (-t if fy >= 0.0 else t)
    return om.MVector(nx, ny, nz).normal()


def test_oct_roundtrip():
    print("octahedral encode/decode")
    import random
    random.seed(7)

    worst = 0.0
    for _ in range(20000):
        v = om.MVector(random.uniform(-1, 1),
                       random.uniform(-1, 1),
                       random.uniform(-1, 1))
        if v.length() < 1e-6:
            continue
        v = v.normal()
        worst = max(worst, (oct_decode(*mu.oct_encode(v)) - v).length())

    check(worst < 0.01, "unit vectors survive the trip", "worst %.6f" % worst)


def test_mesh(maker, name):
    print(name)
    cmds.file(new=True, force=True)
    transform = maker()[0]

    targets = mu.compute_smooth_normals(transform)
    paint, uv_set = mu.prepare(transform)

    uv_sets = mu.uv_set_order(transform)
    colour_sets = mu.color_set_order(transform)

    check(uv_sets.index(uv_set) == 1 if uv_set in uv_sets else False,
          "smooth-normal UV set binds to TEXCOORD1", str(uv_sets))
    check(bool(colour_sets) and colour_sets[0] == env.PAINT_COLOR_SET,
          "paint colour set binds to COLOR0", str(colour_sets))

    fn = om.MFnMesh(mu._dag_path(transform))
    points = fn.getPoints(om.MSpace.kObject)
    counts, indices = fn.getVertices()
    tangents = fn.getTangents(om.MSpace.kObject)
    binormals = fn.getBinormals(om.MSpace.kObject)

    us, vs = fn.getUVs(uv_set)
    _uv_counts, uv_ids = fn.getAssignedUVs(uv_set)

    worst = 0.0
    skew = 0.0
    fv = 0
    offset = 0
    for face_id, count in enumerate(counts):
        face_normals = fn.getFaceVertexNormals(face_id, om.MSpace.kObject)
        for i in range(count):
            vertex_id = indices[offset + i]

            raw_n = om.MVector(face_normals[i]).normal()
            raw_t = om.MVector(tangents[fv])
            if raw_t.length() > 1e-9:
                skew = max(skew, abs(raw_n * raw_t.normal()))

            t, b, n = mu.orthonormal_basis(om.MVector(face_normals[i]),
                                           raw_t,
                                           om.MVector(binormals[fv]))

            decoded = oct_decode(us[uv_ids[fv]], vs[uv_ids[fv]])
            # what VS_Outline computes: mat3(T, B, N) * ts
            world = (t * decoded.x + b * decoded.y + n * decoded.z).normal()

            target = targets.get(mu._position_key(points[vertex_id]), n)
            worst = max(worst, (world - target).length())
            fv += 1
        offset += count

    check(worst < 0.02, "bake -> decode reproduces the smooth normal",
          "%d face-verts, worst %.6f" % (fv, worst))
    print("       Maya tangent off-perpendicular by up to %.4f deg"
          % math.degrees(math.asin(min(1.0, skew))))


def main():
    test_oct_roundtrip()
    for maker, name in (
        (lambda: cmds.polyCube(w=4, h=4, d=4, sx=2, sy=2, sz=2), "cube (all hard edges)"),
        (lambda: cmds.polySphere(r=3), "sphere"),
        (lambda: cmds.polyTorus(), "torus"),
        (lambda: cmds.polyCylinder(r=2, h=5), "cylinder (mixed hard/soft)"),
        (lambda: cmds.polyCone(r=2, h=4), "cone (degenerate apex)"),
    ):
        test_mesh(maker, name)

    print("-" * 60)
    if FAILURES:
        print("%d FAILED: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
