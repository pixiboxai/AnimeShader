"""Mesh preparation for the anime shader.

The outline pass extrudes each vertex along its normal. On a hard edge one
position carries several normals, so the extruded hull splits open and the
outline shows gaps. The fix is the one GBFR uses in ``SmoothNormal.cs``:

    1. group vertices by *position*, not by index
    2. average their normals weighted by the corner angle of each face
    3. rotate that averaged normal into tangent space
    4. store it on the mesh

Unity can put a float3 in UV7. Maya UV sets are strictly 2D -- and Maya's
glslShader binds only ONE colour stream, so a second colour set is not an
option either (declaring COLOR1 compiles but the varying is silently dropped).

A unit vector octahedral-encodes into exactly 2 floats, which fits a UV set
perfectly, so the smooth normal goes into the mesh's **second UV set** and the
shader reads it as TEXCOORD1.
"""

import math

from maya import cmds
from maya.api import OpenMaya as om

from ..core import env

# Positions closer than this collapse into one group.
MERGE_TOLERANCE = 1e-5


def _dag_path(mesh):
    sel = om.MSelectionList()
    sel.add(mesh)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    return dag


def _position_key(point, tolerance=MERGE_TOLERANCE):
    inv = 1.0 / tolerance
    return (int(round(point.x * inv)), int(round(point.y * inv)), int(round(point.z * inv)))


def oct_encode(vector):
    """Map a unit vector onto the [0, 1] square (octahedral encoding).

    Inverse of ``octDecode`` in GNTAnime.ogsfx.
    """
    l1 = abs(vector.x) + abs(vector.y) + abs(vector.z)
    if l1 < 1e-12:
        return 0.5, 0.5

    x = vector.x / l1
    y = vector.y / l1
    z = vector.z / l1

    if z < 0.0:
        x, y = (
            (1.0 - abs(y)) * (1.0 if x >= 0.0 else -1.0),
            (1.0 - abs(x)) * (1.0 if y >= 0.0 else -1.0),
        )

    return x * 0.5 + 0.5, y * 0.5 + 0.5


def _corner_angle(apex, a, b):
    """Angle of the polygon corner at ``apex`` between neighbours ``a`` and ``b``."""
    va = om.MVector(a - apex)
    vb = om.MVector(b - apex)
    la = va.length()
    lb = vb.length()
    if la < 1e-12 or lb < 1e-12:
        return 0.0
    cos_a = max(-1.0, min(1.0, (va * vb) / (la * lb)))
    return math.acos(cos_a)


def compute_smooth_normals(mesh):
    """Angle-weighted normals averaged across coincident vertices.

    Returns ``{position_key: MVector}`` in object space.
    """
    dag = _dag_path(mesh)
    fn = om.MFnMesh(dag)

    points = fn.getPoints(om.MSpace.kObject)
    counts, indices = fn.getVertices()

    accum = {}
    offset = 0
    for face_id, count in enumerate(counts):
        corner = indices[offset:offset + count]
        face_normals = fn.getFaceVertexNormals(face_id, om.MSpace.kObject)

        for i in range(count):
            vid = corner[i]
            prev_id = corner[(i - 1) % count]
            next_id = corner[(i + 1) % count]

            weight = _corner_angle(points[vid], points[prev_id], points[next_id])
            if weight <= 0.0:
                continue

            normal = om.MVector(face_normals[i]) * weight
            key = _position_key(points[vid])
            if key in accum:
                accum[key] += normal
            else:
                accum[key] = normal
        offset += count

    for key, vector in accum.items():
        if vector.length() > 1e-12:
            accum[key] = vector.normal()
        else:
            accum[key] = om.MVector(0.0, 0.0, 1.0)
    return accum


def bake_smooth_normals(mesh, uv_set=None):
    """Bake tangent-space smooth normals into the mesh's second UV set.

    Returns the UV set name.
    """
    uv_set = uv_set or env.SMOOTH_NORMAL_UV_SET

    dag = _dag_path(mesh)
    fn = om.MFnMesh(dag)

    if not fn.getUVSetNames():
        raise RuntimeError(
            "{0} has no UV set. Tangent-space smooth normals need UVs; "
            "unwrap the mesh first.".format(mesh)
        )

    smooth = compute_smooth_normals(mesh)
    points = fn.getPoints(om.MSpace.kObject)
    counts, indices = fn.getVertices()

    # Pull the whole tangent basis up front. MItMeshFaceVertex.getTangent()
    # raises "No element at given index" when Maya has not cached a tangent for
    # that face-vertex yet; these array calls compute the lot in one go.
    tangents = fn.getTangents(om.MSpace.kObject)
    binormals = fn.getBinormals(om.MSpace.kObject)

    total_fv = sum(counts)
    if len(tangents) < total_fv or len(binormals) < total_fv:
        raise RuntimeError(
            "{0}: Maya returned {1} tangents for {2} face-vertices. The UV set "
            "is probably incomplete -- every face needs UVs.".format(
                mesh, len(tangents), total_fv)
        )

    us = om.MFloatArray()
    vs = om.MFloatArray()

    # Walk polygons in the same order as getVertices() so the running counter
    # lines up with the tangent arrays and with a sequential UV id list.
    fv = 0
    offset = 0
    for face_id, count in enumerate(counts):
        face_normals = fn.getFaceVertexNormals(face_id, om.MSpace.kObject)
        for i in range(count):
            vertex_id = indices[offset + i]

            normal = om.MVector(face_normals[i])
            tangent = om.MVector(tangents[fv])
            binormal = om.MVector(binormals[fv])

            target = smooth.get(_position_key(points[vertex_id]), normal)

            # Object-space vector -> tangent space is a dot against each axis.
            ts = om.MVector(target * tangent, target * binormal, target * normal)
            if ts.length() > 1e-12:
                ts = ts.normal()

            u, v = oct_encode(ts)
            us.append(u)
            vs.append(v)
            fv += 1
        offset += count

    transform = cmds.listRelatives(mesh, parent=True, fullPath=True)
    target_node = transform[0] if transform else mesh

    existing = cmds.polyUVSet(target_node, query=True, allUVSets=True) or []
    if uv_set not in existing:
        cmds.polyUVSet(target_node, create=True, uvSet=uv_set)

    uv_ids = om.MIntArray(range(len(us)))

    fn.setUVs(us, vs, uv_set)
    fn.assignUVs(counts, uv_ids, uv_set)

    return uv_set


def ensure_paint_set(mesh, color_set=None, default=(1.0, 1.0, 1.0, 1.0)):
    """Create the artist paint colour set (outline width in R, AO in G).

    This is the only colour set the shader reads; it binds to COLOR0.
    """
    color_set = color_set or env.PAINT_COLOR_SET

    transform = cmds.listRelatives(mesh, parent=True, fullPath=True)
    target_node = transform[0] if transform else mesh

    existing = cmds.polyColorSet(target_node, query=True, allColorSets=True) or []
    if color_set in existing:
        return color_set

    cmds.polyColorSet(target_node, create=True, colorSet=color_set,
                      representation="RGBA")
    cmds.polyColorSet(target_node, currentColorSet=True, colorSet=color_set)
    cmds.polyColorPerVertex(target_node, rgb=default[:3], a=default[3],
                            colorDisplayOption=False)
    return color_set


def prepare(mesh):
    """Create the paint colour set and bake smooth normals into UV set 2.

    Returns ``(paint_colour_set, smooth_normal_uv_set)``.
    """
    paint = ensure_paint_set(mesh)
    smooth = bake_smooth_normals(mesh)
    return paint, smooth


def prepare_selection():
    """Run :func:`prepare` on every selected mesh."""
    from ..core import outline

    meshes = cmds.ls(selection=True, dag=True, type="mesh", long=True, noIntermediate=True)
    # Outline hulls are children of the meshes they wrap, so selecting a
    # prepared character picks them up too. Their mesh data is a plug from the
    # source and would overwrite anything baked here on the next evaluation.
    meshes = [item for item in meshes if not outline.is_hull(item)]
    if not meshes:
        raise ValueError("Select at least one polygon mesh.")

    done = []
    for mesh in meshes:
        prepare(mesh)
        done.append(mesh)
    return done


def color_set_order(mesh):
    """Colour sets in binding order. Only the first one reaches the shader."""
    transform = cmds.listRelatives(mesh, parent=True, fullPath=True)
    target_node = transform[0] if transform else mesh
    return cmds.polyColorSet(target_node, query=True, allColorSets=True) or []


def uv_set_order(mesh):
    """UV sets in binding order: index 0 -> TEXCOORD0, index 1 -> TEXCOORD1."""
    transform = cmds.listRelatives(mesh, parent=True, fullPath=True)
    target_node = transform[0] if transform else mesh
    return cmds.polyUVSet(target_node, query=True, allUVSets=True) or []
