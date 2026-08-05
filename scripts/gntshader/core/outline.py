"""Duplicated-hull fallback for the outline.

The ``AnimeOutline`` technique asks Maya to run two passes that both declare
``drawContext = "colorPass"``. Autodesk does not document that as supported, so
if Maya draws only the first one the outline just is not there -- no error, no
diagnostic. This module is the route around that failure mode.

The hull is a second mesh node parented under the source transform and fed by
``sourceShape.outMesh -> hullShape.inMesh``, shaded with the ``OutlineOnly``
technique. One colorPass per effect, nothing left to assume.

Two choices worth spelling out:

*Driven by a plug, not duplicated.* Deformation, UV sets and colour sets all
travel along ``outMesh``, so skinning and the baked smooth normals arrive on
the hull for free, with no scriptJob keeping a copy in step.

*Parented under the source transform, not the world.* The hull's world matrix
is then the source's, so ``gWorldXf`` and the object-space position the
triplanar outline noise samples are exactly what the multi-pass technique
sees -- the fallback looks the same, it does not merely look similar. It also
means hiding or deleting the character takes the outline with it.
"""

from maya import cmds

from . import shader

HULL_SUFFIX = "_GNThull"

# Message attribute on the hull transform, connected from the source shape.
# It is what makes a hull findable and, just as importantly, recognisable --
# nothing here keys off the name.
LINK_ATTR = "gntOutlineSource"

SHADER_NAME = "GNTOutline"

# Uniforms the hull shader needs to match the shading shader. Everything
# starting with "Outline" is included automatically; these are the strays the
# outline pass also reads (PS_Outline tints from the albedo map).
SHARED_PARAMS = (
    "UseOutlineNoise",
    "UseAlbedoMap",
    "AlbedoMap",
    "AlbedoIsSRGB",
)


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------
def _mesh_shape(node):
    """Resolve a transform or shape to its renderable mesh shape (long name)."""
    if not cmds.objExists(node):
        raise ValueError("No such node: {0}".format(node))

    if cmds.objectType(node) == "mesh":
        return cmds.ls(node, long=True)[0]

    shapes = cmds.listRelatives(node, shapes=True, fullPath=True,
                                noIntermediate=True, type="mesh") or []
    return shapes[0] if shapes else None


def is_hull(node):
    """True when ``node`` is an outline hull, or the shape of one."""
    if not cmds.objExists(node):
        return False
    if cmds.objectType(node) == "mesh":
        parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        node = parents[0] if parents else node
    return cmds.objExists("{0}.{1}".format(node, LINK_ATTR))


def find_hull(mesh):
    """The hull transform driven by ``mesh``, or None."""
    src = _mesh_shape(mesh)
    if src is None:
        return None

    plugs = cmds.listConnections(src + ".message", source=False,
                                 destination=True, plugs=True) or []
    for plug in plugs:
        node, _, attr = plug.rpartition(".")
        if attr == LINK_ATTR:
            return cmds.ls(node, long=True)[0]
    return None


def source_of(hull):
    """The mesh shape a hull is driven by, or None."""
    connections = cmds.listConnections("{0}.{1}".format(hull, LINK_ATTR),
                                       source=True, destination=False,
                                       shapes=True) or []
    return cmds.ls(connections[0], long=True)[0] if connections else None


def list_hulls():
    """Every outline hull in the scene."""
    return [node for node in cmds.ls(type="transform", long=True)
            if cmds.objExists("{0}.{1}".format(node, LINK_ATTR))]


# ---------------------------------------------------------------------------
# the hull shader
# ---------------------------------------------------------------------------
def find_shader():
    """An existing GLSLShader set to the outline technique, or None."""
    fallback = None
    for node in shader.list_shaders():
        if shader.technique(node) == shader.OUTLINE_TECHNIQUE:
            return node
        # Before the effect has compiled once, `.technique` reads back empty;
        # the name is all there is to go on.
        if fallback is None and node.startswith(SHADER_NAME):
            fallback = node
    return fallback


def ensure_shader():
    """Return the shared outline shader node, creating it if need be."""
    node = find_shader()
    if node:
        return node
    node, _sg = shader.create(name=SHADER_NAME,
                              technique=shader.OUTLINE_TECHNIQUE)
    return node


def outline_params(node):
    """Uniforms on ``node`` that drive the outline."""
    return [name for name in shader.list_uniforms(node)
            if name.startswith("Outline") or name in SHARED_PARAMS]


def sync_params(source_node, outline_node=None):
    """Copy the outline uniforms from the shading shader onto the hull shader.

    The two live on separate nodes, so a change to OutlineWidth on one does not
    reach the other until this runs. Returns the names that were applied.
    """
    outline_node = outline_node or find_shader()
    if not outline_node:
        raise ValueError("No outline shader node in the scene.")
    if outline_node == source_node:
        raise ValueError(
            "{0} is the outline shader -- pick the shading shader to copy "
            "from.".format(source_node))

    values = {}
    for name in outline_params(source_node):
        try:
            values[name] = shader.get_param(source_node, name)
        except (ValueError, RuntimeError):
            continue

    skipped = shader.set_params(outline_node, values)
    return sorted(set(values) - set(skipped))


# ---------------------------------------------------------------------------
# build / remove
# ---------------------------------------------------------------------------
def build(mesh, outline_node=None):
    """Give ``mesh`` an outline hull. Returns the hull transform.

    Idempotent: a mesh that already has one gets it back untouched.
    """
    src = _mesh_shape(mesh)
    if src is None:
        raise ValueError("{0} has no renderable mesh shape.".format(mesh))
    if is_hull(src):
        raise ValueError("{0} is itself an outline hull.".format(mesh))

    existing = find_hull(src)
    if existing:
        return existing

    parent = cmds.listRelatives(src, parent=True, fullPath=True)[0]
    base = parent.split("|")[-1] + HULL_SUFFIX

    hull = cmds.ls(cmds.createNode("transform", name=base, parent=parent),
                   long=True)[0]
    hull_shape = cmds.ls(cmds.createNode("mesh", name=base + "Shape",
                                         parent=hull), long=True)[0]

    cmds.connectAttr(src + ".outMesh", hull_shape + ".inMesh")

    # The hull is wider than the mesh it wraps, so anything it contributes to
    # besides the beauty pass is wrong by construction.
    for attr, value in (("castsShadows", 0), ("receiveShadows", 0)):
        cmds.setAttr("{0}.{1}".format(hull_shape, attr), value)

    # Reference display: drawn normally, never picked in the viewport.
    cmds.setAttr(hull_shape + ".overrideEnabled", 1)
    cmds.setAttr(hull_shape + ".overrideDisplayType", 2)

    cmds.addAttr(hull, longName=LINK_ATTR, attributeType="message")
    cmds.connectAttr(src + ".message", "{0}.{1}".format(hull, LINK_ATTR))

    # Offsetting the hull would break the alignment the whole effect rests on.
    for attr in ("translate", "rotate", "scale"):
        for axis in "XYZ":
            cmds.setAttr("{0}.{1}{2}".format(hull, attr, axis), lock=True)

    node = outline_node or ensure_shader()
    sg = shader.shading_group(node)
    if not sg:
        raise RuntimeError("Outline shader {0} has no shading group.".format(node))
    cmds.sets(hull_shape, edit=True, forceElement=sg)

    return hull


def build_selection(outline_node=None):
    """Build hulls for every selected mesh. Returns the hull transforms."""
    meshes = cmds.ls(selection=True, dag=True, type="mesh",
                     long=True, noIntermediate=True)
    meshes = [item for item in meshes if not is_hull(item)]
    if not meshes:
        raise ValueError("Select at least one polygon mesh.")

    # One shader for the lot, so the outline stays one set of knobs.
    outline_node = outline_node or ensure_shader()
    return [build(item, outline_node) for item in meshes]


def remove(mesh):
    """Delete the hull belonging to ``mesh`` (or the hull itself). True if one went."""
    hull = mesh if is_hull(mesh) else find_hull(mesh)
    if not hull:
        return False

    if cmds.objectType(hull) == "mesh":
        hull = cmds.listRelatives(hull, parent=True, fullPath=True)[0]

    for attr in ("translate", "rotate", "scale"):
        for axis in "XYZ":
            cmds.setAttr("{0}.{1}{2}".format(hull, attr, axis), lock=False)
    cmds.delete(hull)
    return True


def remove_selection():
    """Remove hulls for the selection. Returns how many went."""
    nodes = cmds.ls(selection=True, dag=True, long=True) or []
    removed = 0
    for node in nodes:
        try:
            if remove(node):
                removed += 1
        except ValueError:
            continue
    return removed


def remove_all():
    """Remove every outline hull in the scene. Returns how many went."""
    hulls = list_hulls()
    for hull in hulls:
        remove(hull)
    return len(hulls)
