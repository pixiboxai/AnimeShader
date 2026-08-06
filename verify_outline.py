"""Prove -- without looking at the screen -- whether the outline pass runs.

The open question is whether Maya executes *both* passes of a technique that
declares two with ``drawContext = "colorPass"``. Watching the viewport answers
it, but so does counting pixels, and counting is repeatable.

Method: render the probe twice through Viewport 2.0, once on the ``Anime``
technique and once on ``AnimeOutline`` with the outline colour set to pure red
and every other red-producing term switched off. Any strongly red pixel can
then only have come from the outline pass.

Run in **Maya GUI** (the effect does not compile in mayapy)::

    PROJECT_ROOT = r"D:/path/to/GNTShader"
    exec(open(PROJECT_ROOT + "/verify_outline.py").read())

Writes the verdict to ``verify_outline_result.txt`` next to this file.
"""

import os
import struct
import sys
import traceback
import zlib

from maya import cmds

PROBE_PREFIX = "gntVerify"

_LINES = []


def log(*args):
    text = " ".join(str(a) for a in args)
    _LINES.append(text)
    print(text)


def _project_root():
    root = globals().get("PROJECT_ROOT")
    if root and os.path.isdir(root):
        return root.replace("\\", "/")
    if "__file__" in globals():
        return os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    try:
        from gntshader.core import env as _env
        return _env.PROJECT_ROOT.replace("\\", "/")
    except ImportError:
        pass
    raise RuntimeError('Define PROJECT_ROOT before the exec.')


ROOT = _project_root()
SHADER = ROOT + "/shaders/GNTAnime.ogsfx"
LOG_PATH = ROOT + "/verify_outline_result.txt"


# ---------------------------------------------------------------------------
# minimal PNG reader -- stdlib only, 8-bit RGB/RGBA, non-interlaced
# ---------------------------------------------------------------------------
def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path):
    """Return ``(width, height, channels, bytearray_of_pixels)``."""
    with open(path, "rb") as handle:
        data = handle.read()

    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: %s" % path)

    pos = 8
    width = height = depth = colour_type = None
    idat = bytearray()

    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length

        if ctype == b"IHDR":
            width, height, depth, colour_type = struct.unpack(">IIBB", chunk[:10])
            if chunk[12] != 0:
                raise ValueError("interlaced PNG not supported")
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break

    if depth != 8 or colour_type not in (2, 6):
        raise ValueError("need 8-bit RGB or RGBA, got depth=%s type=%s"
                         % (depth, colour_type))

    channels = 4 if colour_type == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = width * channels

    out = bytearray(height * stride)
    prev = bytearray(stride)
    src = 0
    for row in range(height):
        filt = raw[src]
        src += 1
        line = bytearray(raw[src:src + stride])
        src += stride

        if filt == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                upleft = prev[i - channels] if i >= channels else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        elif filt != 0:
            raise ValueError("bad PNG filter %d" % filt)

        out[row * stride:(row + 1) * stride] = line
        prev = line

    return width, height, channels, out


def classify(path, base_mask=None):
    """Split a render into background / red / covered.

    Returns ``(total, red_outside, red_inside, covered, mask)``.

    ``base_mask`` is the coverage of the same probe rendered *without* the
    outline. Red landing outside it is the outline ring doing its job; red
    landing inside it is the hull poking through the surface -- cracks at hard
    edges, or z-fighting. Total red area cannot tell those apart, which is why
    the first version of this comparison drew the wrong conclusion.
    """
    width, height, channels, px = read_png(path)

    mask = bytearray(width * height)
    red_inside = 0
    red_outside = 0
    covered = 0

    for index in range(width * height):
        i = index * channels
        r, g, b = px[i], px[i + 1], px[i + 2]
        alpha = px[i + 3] if channels == 4 else 255

        is_covered = alpha > 16
        if channels == 3:
            is_covered = (abs(r - 128) > 24 or abs(g - 128) > 24
                          or abs(b - 128) > 24)
        if not is_covered:
            continue

        covered += 1
        mask[index] = 1
        if r > 128 and g < 77 and b < 77:
            if base_mask is not None and base_mask[index]:
                red_inside += 1
            else:
                red_outside += 1

    return width * height, red_outside, red_inside, covered, mask


# ---------------------------------------------------------------------------
def _cleanup():
    for node in cmds.ls(PROBE_PREFIX + "*") or []:
        if cmds.objExists(node):
            try:
                cmds.delete(node)
            except RuntimeError:
                pass


def _render(tag):
    cmds.setAttr("defaultRenderGlobals.imageFilePrefix", tag, type="string")
    result = cmds.ogsRender(width=256, height=256, camera="persp")

    path = None
    if isinstance(result, (list, tuple)) and result:
        path = result[0]
    elif isinstance(result, str):
        path = result

    if not path or not os.path.isfile(path):
        images = cmds.workspace(expandName=cmds.workspace(
            fileRuleEntry="images") or "images")
        candidates = []
        for name in os.listdir(images):
            if name.startswith(tag) and name.lower().endswith(".png"):
                candidates.append(os.path.join(images, name))
        if candidates:
            path = max(candidates, key=os.path.getmtime)

    if not path or not os.path.isfile(path):
        raise RuntimeError("could not locate render output for '%s'" % tag)
    return path


def verify():
    log("=" * 68)
    log("GNTShader outline pass verification")
    log("=" * 68)

    if not cmds.pluginInfo("glslShader", query=True, loaded=True):
        cmds.loadPlugin("glslShader")

    sys.path.insert(0, ROOT + "/scripts")
    from gntshader.utils import mesh as mesh_utils

    _cleanup()

    cube = cmds.polyCube(name=PROBE_PREFIX + "Cube", width=6, height=6, depth=6,
                         subdivisionsX=2, subdivisionsY=2, subdivisionsZ=2)[0]
    mesh_utils.prepare(cube)
    if not cmds.ls(type="directionalLight"):
        cmds.directionalLight(name=PROBE_PREFIX + "Key")

    node = cmds.shadingNode("GLSLShader", asShader=True, name=PROBE_PREFIX + "Shader")
    sg = cmds.sets(name=node + "SG", empty=True, renderable=True, noSurfaceShader=True)
    cmds.connectAttr(node + ".outColor", sg + ".surfaceShader", force=True)
    cmds.setAttr(node + ".shader", SHADER, type="string")
    cmds.sets(cube, edit=True, forceElement=sg)
    cmds.refresh(force=True)

    techniques = cmds.getAttr(node + ".techniques") or []
    log("techniques  : %s" % ", ".join(techniques))
    if "AnimeOutline" not in techniques:
        log("FAIL  AnimeOutline technique missing.")
        return

    # Blue object, red outline, nothing else that can emit red.
    for attr, value in (("BaseColor", (0.0, 0.1, 1.0)),
                        ("AmbientColor", (0.0, 0.0, 0.2)),
                        ("ShadowColor", (0.0, 0.0, 0.4)),
                        ("RimIntensity", 0.0),
                        ("SpecIntensity", 0.0),
                        ("EmissionIntensity", 0.0),
                        ("OutlineColor", (1.0, 0.0, 0.0)),
                        ("OutlineWidth", 2.0),
                        ("OutlineUseSmoothNormal", 1),
                        ("OutlineUseVertexColor", 0),
                        ("UseOutlineNoise", 0)):
        full = "{0}.{1}".format(node, attr)
        if not cmds.objExists(full):
            log("  ! missing uniform: %s" % attr)
            continue
        if isinstance(value, tuple):
            cmds.setAttr(full, value[0], value[1], value[2], type="double3")
        else:
            cmds.setAttr(full, value)

    cmds.displayRGBColor("background", 0.5, 0.5, 0.5)

    # Place the camera by hand. viewFit depends on there being an active model
    # panel, which is not guaranteed when this runs over a command bridge --
    # and a probe that lands on one pixel produces a confident wrong verdict.
    try:
        cmds.xform("persp", worldSpace=True, translation=(9.0, 7.0, 9.0))
        cmds.viewLookAt("persp", position=(0.0, 0.0, 0.0))
    except RuntimeError as exc:
        log("  ! could not place the camera: %s" % exc)

    base_mask = [None]

    def measure(tag, technique, smooth_normal=None):
        cmds.setAttr(node + ".technique", technique, type="string")
        if smooth_normal is not None:
            full = node + ".OutlineUseSmoothNormal"
            if cmds.objExists(full):
                cmds.setAttr(full, smooth_normal)
        cmds.refresh(force=True)
        path = _render("gntVerify_" + tag)

        total, red_out, red_in, covered, mask = classify(path, base_mask[0])
        log("-" * 68)
        log("%s" % tag)
        log("  image      : %s" % path)
        log("  red outside: %d   (the outline ring)" % red_out)
        log("  red inside : %d   (cracks / z-fighting -- lower is better)" % red_in)
        log("  covered px : %d / %d" % (covered, total))
        return red_out, red_in, covered, mask

    # --- does the outline pass run at all? -------------------------------
    red_off, _in_off, cov_off, mask_off = measure("noOutline", "Anime")
    base_mask[0] = mask_off

    smooth_out, smooth_in, cov_on, _m = measure(
        "outline_smoothNormal", "AnimeOutline", smooth_normal=1)
    red_on = smooth_out + smooth_in

    log("=" * 68)

    # Refuse to judge the shader when the probe barely made it into frame.
    # A one-pixel cube produces numbers that look like a failure but say
    # nothing about the shader.
    MIN_COVERAGE = 500
    if cov_off < MIN_COVERAGE:
        log("INCONCLUSIVE  the probe covers only %d pixels." % cov_off)
        log("      The camera is not framing it, so these counts mean nothing.")
        log("      Check that 'persp' exists and is not parented or locked.")
        return

    if red_on > 50 and red_on > red_off * 10 + 50:
        log("PASS  outline pass RUNS.")
        log("      red pixels %d -> %d, coverage %d -> %d"
            % (red_off, red_on, cov_off, cov_on))
        log("      Multi-pass colorPass works; keep technique AnimeOutline.")
    else:
        log("FAIL  outline pass does NOT draw.")
        log("      red pixels %d -> %d (expected a large jump)" % (red_off, red_on))
        log("      Maya is running only the first colorPass. Switch to the")
        log("      duplicate-mesh outline instead.")
        return

    # --- is the baked smooth normal actually earning its keep? -----------
    # A cube is all hard edges. Extruding along the raw face normals pulls the
    # faces apart, so the outline ring breaks up at every edge and corner.
    # The baked smooth normal welds them, which should show up as a longer,
    # more continuous red ring.
    log("")
    log("=" * 68)
    log("Smooth-normal comparison (cube = worst case, every edge is hard)")
    log("")
    log("Extruding along raw face normals pulls the six faces apart, so red")
    log("leaks through the cracks *inside* the silhouette. Total red area")
    log("cannot see that -- it just goes up. Judge on inside-red instead.")

    raw_out, raw_in, _cov_raw, _m = measure(
        "outline_rawNormal", "AnimeOutline", smooth_normal=0)

    log("=" * 68)
    log("                     ring (outside)   cracks (inside)")
    log("  raw mesh normal  : %14d   %15d" % (raw_out, raw_in))
    log("  baked smooth norm: %14d   %15d" % (smooth_out, smooth_in))

    if raw_in == 0 and smooth_in == 0:
        log("INCONCLUSIVE  neither pass leaks red inside the silhouette, so")
        log("      this probe does not exercise the problem. Judge on a real")
        log("      character mesh with hard edges under skinning.")
    elif smooth_in < raw_in:
        drop = (raw_in - smooth_in) / float(raw_in) * 100.0
        log("PASS  smooth normals cut the leaking by %.1f%%." % drop)
    else:
        log("NOTE  smooth normals did not reduce the leaking here.")


try:
    verify()
except Exception:
    log("!! verify() raised:")
    log(traceback.format_exc())
finally:
    try:
        with open(LOG_PATH, "w") as handle:
            handle.write("\n".join(_LINES))
        print("\n[log written to %s]" % LOG_PATH)
    except IOError:
        pass
