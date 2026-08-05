"""Validate GNTAnime.ogsfx inside Maya.

Must run in **Maya GUI**, not mayapy: the glslShader plugin only parses an
effect file once Viewport 2.0 has a live draw context. In `mayapy -c` every
query comes back empty -- including for Maya's own shipped shaders -- so a
clean result there means nothing.

Paste into the Script Editor (Python tab)::

    PROJECT_ROOT = r"D:/path/to/GNTShader"      # optional, see below
    exec(open(PROJECT_ROOT + "/validate.py").read())

It builds a probe cube, prepares it, assigns the shader, forces a viewport
refresh, then prints the compiler diagnostics and everything Maya managed to
introspect.

The project root is worked out automatically when the file has a ``__file__``
(normal import) or when you define ``PROJECT_ROOT`` before the exec. Otherwise
edit ``_FALLBACK_ROOT`` below.
"""

import os
import sys
import traceback

from maya import cmds, mel

def _project_root():
    # 1. caller set it explicitly
    root = globals().get("PROJECT_ROOT")
    if root and os.path.isdir(root):
        return root.replace("\\", "/")
    # 2. running as a real file
    if "__file__" in globals():
        return os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    # 3. the package is already installed and importable
    try:
        from gntshader.core import env as _env
        return _env.PROJECT_ROOT.replace("\\", "/")
    except ImportError:
        pass
    raise RuntimeError(
        "Cannot work out where GNTShader lives. Define PROJECT_ROOT before "
        "the exec:\n"
        '    PROJECT_ROOT = r"D:/path/to/GNTShader"\n'
        '    exec(open(PROJECT_ROOT + "/validate.py").read())'
    )


ROOT = _project_root()
SHADER = ROOT + "/shaders/GNTAnime.ogsfx"
LOG_PATH = ROOT + "/validate_result.txt"
PROBE_PREFIX = "gntProbe"

_LINES = []


def print(*args):  # noqa: A001 - deliberately shadowing, see _flush()
    """Collect output so it lands in both the Script Editor and the log file."""
    text = " ".join(str(a) for a in args)
    _LINES.append(text)
    import builtins
    builtins.print(text)


def _flush():
    try:
        with open(LOG_PATH, "w") as handle:
            handle.write("\n".join(_LINES))
    except IOError:
        pass


def _cleanup():
    for node in cmds.ls(PROBE_PREFIX + "*") or []:
        if cmds.objExists(node):
            try:
                cmds.delete(node)
            except RuntimeError:
                pass


def validate(shader_file=SHADER, keep=True):
    print("=" * 68)
    print("GNTShader validation")
    print("=" * 68)

    if not os.path.isfile(shader_file):
        print("FAIL  shader file not found: %s" % shader_file)
        return False
    print("shader file : %s" % shader_file)

    if not cmds.pluginInfo("glslShader", query=True, loaded=True):
        cmds.loadPlugin("glslShader")
    print("plugin      : glslShader loaded")

    renderer = cmds.optionVar(query="vp2RenderingEngine")
    print("VP2 renderer: %s" % renderer)
    if isinstance(renderer, str) and "OpenGL" not in renderer:
        print("   !! glslShader needs the OpenGL Core Profile renderer.")
        print("      Preferences > Display > Viewport 2.0 > Rendering engine")

    _cleanup()

    # A cube gives hard edges, which is exactly where a bad smooth-normal bake
    # shows up as gaps in the outline.
    sphere = cmds.polyCube(name=PROBE_PREFIX + "Cube", width=8, height=8, depth=8,
                           subdivisionsX=2, subdivisionsY=2, subdivisionsZ=2)[0]
    if not cmds.ls(type="directionalLight"):
        cmds.directionalLight(name=PROBE_PREFIX + "Key")

    # Exercise the real preparation path, not a hand-rolled stand-in.
    scripts_dir = ROOT + "/scripts"
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from gntshader.utils import mesh as mesh_utils
        try:
            import importlib
            importlib.reload(mesh_utils)
        except Exception:
            pass
        paint, uvset = mesh_utils.prepare(sphere)
        print("mesh prep   : colour set '%s', UV set '%s'" % (paint, uvset))
        print("UV sets     : %s" % mesh_utils.uv_set_order(sphere))
    except Exception:
        print("!! mesh prep FAILED:")
        print(traceback.format_exc())

    node = cmds.shadingNode("GLSLShader", asShader=True, name=PROBE_PREFIX + "Shader")
    sg = cmds.sets(name=node + "SG", empty=True, renderable=True, noSurfaceShader=True)
    cmds.connectAttr(node + ".outColor", sg + ".surfaceShader", force=True)
    cmds.setAttr(node + ".shader", shader_file.replace("\\", "/"), type="string")
    cmds.sets(sphere, edit=True, forceElement=sg)

    # The effect is parsed on the next draw.
    cmds.refresh(force=True)

    # Switch to the outline technique and turn the relevant knobs on so the
    # viewport actually shows whether the second pass runs.
    if "AnimeOutline" in (cmds.getAttr(node + ".techniques") or []):
        cmds.setAttr(node + ".technique", "AnimeOutline", type="string")
        for attr, value in (("OutlineWidth", 1.5),
                            ("OutlineUseSmoothNormal", 1),
                            ("OutlineUseVertexColor", 0)):
            full = "{0}.{1}".format(node, attr)
            if cmds.objExists(full):
                cmds.setAttr(full, value)
        cmds.refresh(force=True)

    techniques = cmds.getAttr(node + ".techniques") or []
    uniforms = cmds.getAttr(node + ".uniformParameters") or []
    varyings = cmds.getAttr(node + ".varyingParameters") or []
    diagnostics = cmds.getAttr(node + ".diagnostics") or ""

    print("-" * 68)
    print("techniques  : %s" % (", ".join(techniques) if techniques else "(none)"))
    print("active      : %s" % cmds.getAttr(node + ".technique"))
    print("uniforms    : %d" % len(uniforms))
    print("varyings    : %s" % (", ".join(varyings) if varyings else "(none)"))

    try:
        groups = mel.eval("GLSLShader %s -q -lg" % node)
        print("UI groups   : %s" % (groups if groups else "(none)"))
    except RuntimeError:
        pass

    try:
        lights = mel.eval("GLSLShader %s -q -li" % node)
        print("light slots : %s" % (lights if lights else "(none)"))
    except RuntimeError:
        pass

    print("-" * 68)
    if diagnostics.strip():
        print("DIAGNOSTICS:")
        print(diagnostics)
    else:
        print("DIAGNOSTICS: (empty)")

    missing = [name for name in ("Anime", "AnimeOutline", "OutlineOnly")
               if name not in techniques]
    if missing:
        print("!! techniques missing from the effect: %s" % ", ".join(missing))

    ok = bool(techniques) and not missing and not diagnostics.strip()
    print("-" * 68)
    if ok:
        print("PASS  effect compiled -- %d techniques, %d uniforms"
              % (len(techniques), len(uniforms)))
        print()
        print("Next: look through the persp viewport. You should see a shaded")
        print("cube. Switch technique to 'AnimeOutline' to check the outline")
        print("pass actually draws -- that is the one unverified assumption.")
        print("If no rim appears, run check_hull_fallback() for the one-pass")
        print("route that does not depend on it.")
    else:
        print("FAIL  effect did not compile. Read the diagnostics above.")
        if not techniques and not diagnostics.strip():
            print()
            print("Both empty usually means the viewport never drew the shader.")
            print("Make sure a modelPanel is visible and set to Viewport 2.0,")
            print("then run this again.")

    if not keep:
        _cleanup()
    return ok


def check_multipass_outline(node=None):
    """Report whether the two-pass outline technique is actually selectable."""
    node = node or (cmds.ls(type="GLSLShader") or [None])[0]
    if not node:
        print("No GLSLShader node in the scene.")
        return

    techniques = cmds.getAttr(node + ".techniques") or []
    print("techniques on %s: %s" % (node, techniques))
    if "AnimeOutline" not in techniques:
        print("!! AnimeOutline missing -- the effect did not expose it.")
        return

    cmds.setAttr(node + ".technique", "AnimeOutline", type="string")
    cmds.refresh(force=True)
    print("Switched to AnimeOutline.")
    print("Look at the viewport: if there is no dark rim around the silhouette,")
    print("Maya is only running the first colorPass. Run check_hull_fallback()")
    print("to switch to the duplicated-hull outline, which never needs two.")


def check_hull_fallback(mesh=None, node=None):
    """Put the probe mesh on the duplicated-hull outline and report.

    Leaves the scene in the fallback configuration: shading shader on the
    `Anime` technique, a hull child on the mesh carrying `OutlineOnly`.
    """
    scripts_dir = ROOT + "/scripts"
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from gntshader.core import outline as outline_utils

    mesh = mesh or (cmds.ls(PROBE_PREFIX + "Cube") or [None])[0]
    node = node or (cmds.ls(type="GLSLShader") or [None])[0]
    if not mesh or not node:
        print("Need a probe mesh and a GLSLShader node -- run validate() first.")
        return False

    try:
        hull = outline_utils.build(mesh)
    except (ValueError, RuntimeError) as exc:
        print("!! hull build FAILED: %s" % exc)
        return False

    hull_shader = outline_utils.find_shader()
    cmds.setAttr(node + ".technique", "Anime", type="string")
    for attr, value in (("OutlineWidth", 1.5), ("OutlineUseSmoothNormal", 1)):
        full = "{0}.{1}".format(hull_shader, attr)
        if cmds.objExists(full):
            cmds.setAttr(full, value)
    cmds.refresh(force=True)

    hull_shape = cmds.listRelatives(hull, shapes=True, fullPath=True)[0]
    diagnostics = cmds.getAttr(hull_shader + ".diagnostics") or ""

    print("-" * 68)
    print("hull        : %s" % hull)
    print("driven by   : %s" % outline_utils.source_of(hull))
    print("hull shader : %s (technique %s)"
          % (hull_shader, cmds.getAttr(hull_shader + ".technique")))
    print("hull faces  : %d" % cmds.polyEvaluate(hull_shape, face=True))
    if diagnostics.strip():
        print("DIAGNOSTICS:")
        print(diagnostics)
        return False

    print("PASS  hull built and shaded, no compile errors.")
    print()
    print("Look at the viewport: the cube should now have a rim even though the")
    print("shading shader is on 'Anime'. That rim comes from the hull, so it is")
    print("proof the fallback works whatever Maya does with multi-pass.")
    return True


try:
    validate()
except Exception:
    print("!! validate() raised:")
    print(traceback.format_exc())
finally:
    _flush()
    import builtins
    builtins.print("\n[log written to %s]" % LOG_PATH)
