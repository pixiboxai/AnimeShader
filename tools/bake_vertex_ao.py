"""Bake ambient occlusion into the paint colour set's green channel.

What this buys: the soft contact shading a cel shader cannot derive -- under a
jacket, between thighs, in the hollow of a collar. Those are the shadows that
separate a flat texture read from a rendered character, and no amount of
terminator tuning produces them, because they are not about where the light is.

The shader reads it as ``UseVertexAO`` (``vcol.g``), alongside outline width in
red, so both live in one colour set -- Maya's GLSL shader binds only one.

Rays are cast against every piece at once, not each mesh alone: the jacket has
to occlude the arm, or the effect is pointless.

    import bake_vertex_ao
    bake_vertex_ao.bake(["Lucy_body", "Lucy_face", ...])
"""

import math

from maya import cmds
import maya.api.OpenMaya as om


def _hemisphere(count):
    """Cosine-weighted directions around +Z, via a Fibonacci spiral.

    Deterministic on purpose: rerunning the bake must not shuffle the noise,
    or every rebake shows up as a diff.
    """
    golden = math.pi * (3.0 - math.sqrt(5.0))
    out = []
    for i in range(count):
        # cosine weighting: more samples near the normal, which is where the
        # occlusion integral actually has weight
        z = math.sqrt((i + 0.5) / count)
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = i * golden
        out.append((r * math.cos(theta), r * math.sin(theta), z))
    return out


def _basis(normal):
    n = om.MVector(normal).normal()
    helper = om.MVector(0.0, 0.0, 1.0)
    if abs(n.z) > 0.9:
        helper = om.MVector(1.0, 0.0, 0.0)
    t = (helper ^ n).normal()
    b = n ^ t
    return t, b, n


def _combined(meshes):
    """One throwaway mesh holding every piece, for the ray casts."""
    copies = [cmds.duplicate(m, name=m + "_aoTmp")[0] for m in meshes]
    for c in copies:
        try:
            cmds.parent(c, world=True)
        except RuntimeError:
            pass
    if len(copies) == 1:
        merged = copies[0]
    else:
        merged = cmds.polyUnite(copies, constructionHistory=False,
                                name="GNT_aoTarget")[0]
    cmds.delete(merged, constructionHistory=True)
    return merged


def bake(meshes, samples=24, max_distance=None, intensity=1.0, bias=0.05,
         color_set="GNT_paint"):
    """Write AO into ``color_set``'s green for each mesh. Returns per-mesh stats."""
    meshes = [m for m in meshes if cmds.objExists(m)]
    if not meshes:
        return {}

    bb = cmds.exactWorldBoundingBox(*meshes)
    size = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    if max_distance is None:
        # Long rays turn AO into a global shadow and the character goes muddy;
        # a fraction of its height keeps it to contact shading.
        max_distance = size * 0.08

    target = _combined(meshes)
    sel = om.MSelectionList()
    sel.add(target)
    target_dag = sel.getDagPath(0)
    target_dag.extendToShape()
    target_fn = om.MFnMesh(target_dag)
    accel = target_fn.autoUniformGridParams()

    directions = _hemisphere(samples)
    report = {}

    for mesh in meshes:
        msel = om.MSelectionList()
        msel.add(mesh)
        dag = msel.getDagPath(0)
        dag.extendToShape()
        fn = om.MFnMesh(dag)

        points = fn.getPoints(om.MSpace.kWorld)
        normals = fn.getVertexNormals(False, om.MSpace.kWorld)

        previous = fn.currentColorSetName()
        fn.setCurrentColorSetName(color_set)
        existing = fn.getVertexColors(color_set)

        colours = om.MColorArray()
        indices = om.MIntArray()
        total = 0.0

        for i, point in enumerate(points):
            t, b, n = _basis(normals[i])
            origin = om.MFloatPoint(point.x + n.x * bias,
                                    point.y + n.y * bias,
                                    point.z + n.z * bias)
            hits = 0
            for dx, dy, dz in directions:
                d = t * dx + b * dy + n * dz
                hit = target_fn.anyIntersection(
                    origin, om.MFloatVector(d.x, d.y, d.z),
                    om.MSpace.kWorld, max_distance, False,
                    accelParams=accel, tolerance=1e-4)
                if hit and hit[0] is not None:
                    hits += 1
            ao = 1.0 - (hits / float(samples)) * intensity
            ao = max(0.0, min(1.0, ao))
            total += ao

            old = existing[i] if i < len(existing) else om.MColor((1.0, 1.0, 1.0, 1.0))
            colours.append(om.MColor((old.r, ao, old.b, old.a)))
            indices.append(i)

        fn.setVertexColors(colours, indices)
        if previous:
            try:
                fn.setCurrentColorSetName(previous)
            except RuntimeError:
                pass

        report[mesh] = {"vertices": len(points), "mean": total / max(1, len(points))}

    cmds.delete(target)
    report["_settings"] = {"samples": samples, "max_distance": max_distance,
                           "model_size": size}
    return report


if __name__ == "__main__":
    import pprint
    pprint.pprint(bake(cmds.ls(selection=True)))
