"""Loading the Maya plugins this toolset depends on."""

from maya import cmds

GLSL_PLUGIN = "glslShader"


def ensure_glsl_plugin():
    """Load glslShader if needed.

    Returns True when the plugin is available.
    """
    if cmds.pluginInfo(GLSL_PLUGIN, query=True, loaded=True):
        return True
    try:
        cmds.loadPlugin(GLSL_PLUGIN, quiet=True)
    except RuntimeError as exc:
        cmds.warning("GNTShader: could not load {0}: {1}".format(GLSL_PLUGIN, exc))
        return False
    return cmds.pluginInfo(GLSL_PLUGIN, query=True, loaded=True)


def viewport_is_opengl_core():
    """glslShader only renders under the OpenGL Core Profile renderer.

    Returns (ok, current_renderer).
    """
    try:
        renderer = cmds.optionVar(query="vp2RenderingEngine")
    except RuntimeError:
        return True, "unknown"

    if not isinstance(renderer, str):
        return True, "unknown"

    ok = "OpenGLCoreProfile" in renderer or "OpenGL" in renderer
    return ok, renderer
