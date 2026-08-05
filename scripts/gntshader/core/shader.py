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

from . import env
from . import plugin

NODE_TYPE = "GLSLShader"

DEFAULT_TECHNIQUE = "AnimeOutline"

# Shading with no outline pass. Pair it with the duplicated hull in
# ``core.outline`` when Maya will not run two colorPass passes at once.
SHADING_TECHNIQUE = "Anime"

# Outline with no shading pass -- what the hull mesh gets.
OUTLINE_TECHNIQUE = "OutlineOnly"

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
    """Point a GLSLShader node at an .ogsfx file and recompile."""
    # Maya wants forward slashes here.
    cmds.setAttr(node + ".shader", shader_file.replace("\\", "/"), type="string")


def reload_shader(node):
    """Force a recompile by re-setting the shader path.

    Returns the diagnostics string (empty when the effect compiled).
    """
    current = cmds.getAttr(node + ".shader")
    cmds.setAttr(node + ".shader", "", type="string")
    cmds.setAttr(node + ".shader", current, type="string")
    return diagnostics(node)


def assign(node_or_sg, objects=None):
    """Assign the shader to ``objects`` (defaults to the current selection)."""
    objects = objects or cmds.ls(selection=True, long=True)
    if not objects:
        raise ValueError("Nothing to assign to.")

    sg = node_or_sg
    if cmds.objectType(node_or_sg) == NODE_TYPE:
        sg = shading_group(node_or_sg)
    if not sg:
        raise ValueError("No shading group found for {0}".format(node_or_sg))

    cmds.sets(objects, edit=True, forceElement=sg)
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
    """Read every uniform back into a plain dict."""
    out = {}
    for attr in list_uniforms(node):
        try:
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
