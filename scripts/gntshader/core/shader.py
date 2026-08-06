"""Create, assign and drive GLSLShader nodes.

Attribute contract on Maya's ``GLSLShader`` node (verified against
``AEGLSLShaderTemplate.mel`` in the Maya install):

    .shader             string   -- path to the .ogsfx effect file
    .technique          string   -- active technique name
    .techniques         string[] -- techniques found in the effect
    .uniformParameters  string[] -- names of the generated uniform attributes
    .<uniform>_Type     string   -- type tag for each uniform
    .diagnostics        string   -- compiler output, empty when the effect is fine
"""

import os

from maya import cmds
import maya.mel as mel

from . import env
from . import plugin

NODE_TYPE = "GLSLShader"

DEFAULT_TECHNIQUE = "AnimeOutline"

# Type tags that map onto a plain numeric setAttr.
_SCALAR_TYPES = {"bool", "int", "enum", "float"}

# Type tags carrying several floats; the count is the leading digit pair.
_VECTOR_TYPES = {
    "float2x1": 2, "float1x2": 2,
    "float3x1": 3, "float1x3": 3,
    "float4x1": 4, "float1x4": 4,
    "color3x1": 3, "color1x3": 3,
    "color4x1": 4, "color1x4": 4,
}


# ---------------------------------------------------------------------------
# creation / assignment
# ---------------------------------------------------------------------------
def create(name="GNTAnime", shader_file=None, technique=DEFAULT_TECHNIQUE):
    """Create a GLSLShader node wired to a shading group.

    Returns ``(shader_node, shading_group)``.
    """
    if not plugin.ensure_glsl_plugin():
        raise RuntimeError("glslShader plugin is not available.")

    shader_file = shader_file or env.ANIME_SHADER
    if not os.path.isfile(shader_file):
        raise IOError("Shader file not found: {0}".format(shader_file))

    node = cmds.shadingNode(NODE_TYPE, asShader=True, name=name)
    sg = cmds.sets(name=node + "SG", empty=True, renderable=True, noSurfaceShader=True)
    cmds.connectAttr(node + ".outColor", sg + ".surfaceShader", force=True)

    set_shader_file(node, shader_file)
    if technique:
        set_technique(node, technique)

    return node, sg


def set_shader_file(node, shader_file):
    """Point a GLSLShader node at an .ogsfx file and force a recompile.

    Maya caches the compiled effect against the file path, so assigning an
    edited .ogsfx -- even to a brand new node -- can hand you the previous
    build with no warning. Clearing the attribute first drops the cache entry.
    Skipping this once cost a whole measurement run: the shader under test was
    the old one, and the numbers looked like a sign error in the maths.
    """
    path = shader_file.replace("\\", "/")
    cmds.setAttr(node + ".shader", "", type="string")
    cmds.setAttr(node + ".shader", path, type="string")

    # Clearing the attribute alone is not enough -- measured: after editing an
    # .ogsfx, a cleared-and-reset node still reported the old uniform list.
    # The plugin's own reload flag is what actually drops the cached build.
    try:
        mel.eval("GLSLShader %s -r" % node)
    except RuntimeError:
        pass


def bind_streams(node, mesh, uv_set=None, smooth_uv_set=None, color_set=None):
    """Point each vertex stream at a named UV / colour set on ``mesh``.

    Maya exposes the mapping as ``<varying>_Source`` string attributes holding
    values like ``uv:map1``, ``color:colorSet`` or ``tangent:map1``. The
    defaults are those literal names, so on any mesh whose sets are called
    something else -- production meshes routinely use ``UV1`` / ``Col`` -- the
    shader silently reads the wrong stream or none at all.

    Relying on set *order* does not work either: the effect asks for
    TEXCOORD1, and which set that lands on depends on how many the mesh
    already had. Bind by name instead.

    Returns a dict of what was bound.
    """
    # Skip intermediate shapes: a skinned character carries a "...Orig" mesh
    # whose sets the viewport never reads.
    shape = mesh
    if cmds.objectType(shape) != "mesh" or cmds.getAttr(shape + ".intermediateObject"):
        shapes = cmds.listRelatives(mesh, shapes=True, fullPath=True,
                                    noIntermediate=True, type="mesh") or []
        if not shapes:
            raise ValueError("No renderable mesh shape under {0}".format(mesh))
        shape = shapes[0]

    uv_sets = cmds.polyUVSet(shape, query=True, allUVSets=True) or []
    colour_sets = cmds.polyColorSet(shape, query=True, allColorSets=True) or []

    if uv_set is None:
        # The texture UV set is whichever one is not ours.
        candidates = [s for s in uv_sets if s != env.SMOOTH_NORMAL_UV_SET]
        uv_set = candidates[0] if candidates else (uv_sets[0] if uv_sets else None)

    if smooth_uv_set is None and env.SMOOTH_NORMAL_UV_SET in uv_sets:
        smooth_uv_set = env.SMOOTH_NORMAL_UV_SET

    if color_set is None:
        if env.PAINT_COLOR_SET in colour_sets:
            color_set = env.PAINT_COLOR_SET
        elif colour_sets:
            color_set = colour_sets[0]

    wanted = {}
    if uv_set:
        wanted["TexCoord0"] = "uv:" + uv_set
        wanted["Tangent"] = "tangent:" + uv_set
        wanted["Binormal"] = "binormal:" + uv_set
    if smooth_uv_set:
        wanted["TexCoord1"] = "uv:" + smooth_uv_set
    if color_set:
        wanted["Color0"] = "color:" + color_set

    available = cmds.getAttr(node + ".varyingParameters") or []
    bound = {}
    for stream, value in wanted.items():
        if stream not in available:
            continue
        attr = "{0}.{1}_Source".format(node, stream)
        if not cmds.objExists(attr):
            continue
        cmds.setAttr(attr, value, type="string")
        bound[stream] = value

    return bound


def stream_bindings(node):
    """Current ``<varying>_Source`` values, for diagnosing wrong streams."""
    out = {}
    for stream in cmds.getAttr(node + ".varyingParameters") or []:
        attr = "{0}.{1}_Source".format(node, stream)
        if cmds.objExists(attr):
            out[stream] = cmds.getAttr(attr)
    return out


def reload_shader(node):
    """Recompile the effect from disk, dropping Maya's cached build.

    Returns the diagnostics string (empty when the effect compiled).
    """
    current = cmds.getAttr(node + ".shader")
    if current:
        set_shader_file(node, current)
    return diagnostics(node)


def assign(node_or_sg, objects=None, bind=True):
    """Assign the shader to ``objects`` (defaults to the current selection).

    Also binds the vertex streams to the first target's UV / colour sets by
    name, because the stream defaults (``map1``, ``colorSet``) do not exist on
    most production meshes.
    """
    objects = objects or cmds.ls(selection=True, long=True)
    if not objects:
        raise ValueError("Nothing to assign to.")

    node = node_or_sg
    sg = node_or_sg
    if cmds.objectType(node_or_sg) == NODE_TYPE:
        sg = shading_group(node_or_sg)
    else:
        node = None
    if not sg:
        raise ValueError("No shading group found for {0}".format(node_or_sg))

    cmds.sets(objects, edit=True, forceElement=sg)

    if bind and node:
        meshes = cmds.ls(objects, dag=True, type="mesh", long=True,
                         noIntermediate=True) or []
        if meshes:
            try:
                bind_streams(node, meshes[0])
            except (ValueError, RuntimeError) as exc:
                cmds.warning("GNTShader: could not bind streams: {0}".format(exc))

    return sg


def shading_group(node):
    """Return the shading group driven by a shader node, if any."""
    sets = cmds.listConnections(node + ".outColor", type="shadingEngine") or []
    return sets[0] if sets else None


def list_shaders():
    """All GLSLShader nodes in the scene."""
    return cmds.ls(type=NODE_TYPE) or []


# ---------------------------------------------------------------------------
# techniques
# ---------------------------------------------------------------------------
def list_techniques(node):
    return cmds.getAttr(node + ".techniques") or []


def technique(node):
    return cmds.getAttr(node + ".technique")


def set_technique(node, name):
    available = list_techniques(node)
    if available and name not in available:
        cmds.warning(
            "GNTShader: technique '{0}' not in effect (have: {1})".format(
                name, ", ".join(available))
        )
        return False
    cmds.setAttr(node + ".technique", name, type="string")
    return True


def diagnostics(node):
    """Compiler output for the effect. Empty string means it compiled."""
    try:
        return cmds.getAttr(node + ".diagnostics") or ""
    except (RuntimeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# uniforms
# ---------------------------------------------------------------------------
def list_uniforms(node):
    """Names of the uniform attributes generated from the effect file."""
    return cmds.getAttr(node + ".uniformParameters") or []


def uniform_type(node, attr):
    """Type tag for a uniform, or '' when Maya did not publish one."""
    type_attr = "{0}.{1}_Type".format(node, attr)
    if cmds.objExists(type_attr):
        return cmds.getAttr(type_attr) or ""
    return ""


def get_param(node, attr):
    value = cmds.getAttr("{0}.{1}".format(node, attr))
    # Maya returns [(x, y, z)] for compound attributes.
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], tuple):
        return list(value[0])
    return value


def set_param(node, attr, value):
    """Set a uniform, picking the right setAttr form from its type tag."""
    full = "{0}.{1}".format(node, attr)
    if not cmds.objExists(full):
        raise ValueError("No such attribute: {0}".format(full))

    tag = uniform_type(node, attr)

    if isinstance(value, str):
        # A path aimed at a texture uniform has to go through a file node.
        if tag == "texture" or cmds.attributeQuery(attr, node=node,
                                                   connectable=True) and \
                cmds.getAttr(full, type=True) == "float3":
            set_texture(node, attr, value)
            return
        cmds.setAttr(full, value, type="string")
        return

    if tag in _VECTOR_TYPES or isinstance(value, (list, tuple)):
        values = list(value)
        cmds.setAttr(full, *values, type="double{0}".format(len(values)))
        return

    if tag in _SCALAR_TYPES or isinstance(value, (int, float, bool)):
        cmds.setAttr(full, value)
        return

    cmds.setAttr(full, value)


def set_texture(node, attr, path, colour_space=None):
    """Plug an image file into a texture uniform.

    Texture uniforms are not strings. Maya generates them as connectable
    ``float3`` attributes tagged ``_Type = "texture"``, so the value arrives
    through a ``file`` node rather than a setAttr -- passing a path straight in
    fails with "does not accept data of type 'string'".

    Reuses an existing file node already wired to this attribute.
    """
    full = "{0}.{1}".format(node, attr)
    if not cmds.objExists(full):
        raise ValueError("No such attribute: {0}".format(full))

    existing = cmds.listConnections(full, source=True, destination=False,
                                    type="file") or []
    if existing:
        file_node = existing[0]
    else:
        file_node = cmds.shadingNode("file", asTexture=True,
                                     isColorManaged=True,
                                     name="{0}_{1}_file".format(node, attr))
        placer = cmds.shadingNode("place2dTexture", asUtility=True,
                                  name="{0}_{1}_p2d".format(node, attr))
        for src, dst in (("outUV", "uvCoord"),
                         ("outUvFilterSize", "uvFilterSize")):
            cmds.connectAttr("{0}.{1}".format(placer, src),
                             "{0}.{1}".format(file_node, dst), force=True)
        for name in ("coverage", "translateFrame", "rotateFrame", "mirrorU",
                     "mirrorV", "stagger", "wrapU", "wrapV", "repeatUV",
                     "offset", "rotateUV", "noiseUV", "vertexUvOne",
                     "vertexUvTwo", "vertexUvThree", "vertexCameraOne"):
            src = "{0}.{1}".format(placer, name)
            dst = "{0}.{1}".format(file_node, name)
            if cmds.objExists(src) and cmds.objExists(dst):
                cmds.connectAttr(src, dst, force=True)
        cmds.connectAttr(file_node + ".outColor", full, force=True)

    cmds.setAttr(file_node + ".fileTextureName", path.replace("\\", "/"),
                 type="string")
    if colour_space:
        try:
            cmds.setAttr(file_node + ".colorSpace", colour_space, type="string")
        except RuntimeError:
            pass
    return file_node


def texture_path(node, attr):
    """Path currently feeding a texture uniform, or '' when nothing is."""
    full = "{0}.{1}".format(node, attr)
    files = cmds.listConnections(full, source=True, destination=False,
                                 type="file") or []
    if not files:
        return ""
    return cmds.getAttr(files[0] + ".fileTextureName") or ""


def set_params(node, mapping):
    """Apply a dict of ``{uniform: value}``, skipping anything absent.

    Returns the list of names that could not be applied.
    """
    skipped = []
    for attr, value in mapping.items():
        try:
            set_param(node, attr, value)
        except (ValueError, RuntimeError):
            skipped.append(attr)
    return skipped


def dump_params(node):
    """Read every uniform back into a plain dict.

    Texture uniforms come back as the file path feeding them, so a captured
    preset can rebuild the connection later.
    """
    out = {}
    for attr in list_uniforms(node):
        try:
            if uniform_type(node, attr) == "texture":
                path = texture_path(node, attr)
                if path:
                    out[attr] = path
                continue
            out[attr] = get_param(node, attr)
        except (ValueError, RuntimeError):
            continue
    return out


# ---------------------------------------------------------------------------
# head basis (drives the GBFR face rim / SDF shadow)
# ---------------------------------------------------------------------------
def bake_head_basis(node, head_transform):
    """Write a head transform's world axes into HeadForward / HeadRight.

    Call again whenever the head moves; see ``live_head_basis`` for an
    automatic version.
    """
    matrix = cmds.xform(head_transform, query=True, matrix=True, worldSpace=True)
    right = [matrix[0], matrix[1], matrix[2]]
    forward = [matrix[8], matrix[9], matrix[10]]

    set_param(node, "HeadRight", right)
    set_param(node, "HeadForward", forward)
    return right, forward


def live_head_basis(node, head_transform):
    """Keep HeadForward / HeadRight in sync with a transform via a scriptJob.

    Returns the scriptJob id so the caller can kill it later.
    """
    cmd = (
        "import gntshader.core.shader as s; "
        "s.bake_head_basis('{0}', '{1}')".format(node, head_transform)
    )
    return cmds.scriptJob(attributeChange=[head_transform + ".matrix", cmd])
