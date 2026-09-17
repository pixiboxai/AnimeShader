"""Put the GNT anime shader on Sora without moving a single colour.

Sora is not textured the way Hiro or the ArcSys samples are. Almost all of her
colour lives in fifteen flat phong materials assigned *per face* -- the body
alone carries six, the jacket eight -- and only the face and the shoes have a
map. So the usual "one shader per mesh" pass is exactly wrong here: it would
collapse eight colours into one and there would be no way back.

Instead every source material gets its own GNT shader carrying that material's
own colour, and the new shading group is assigned to precisely the faces the old
one held. Fifteen in, fifteen out, same faces, same colours.

Two settings decide whether the colours survive, and both were wrong on the
earlier attempt left in this scene:

    AlbedoIsSRGB   OFF. Colour management is enabled here, so the file nodes
                   linearise and the viewport applies a display transform. The
                   old GNT_Sora_Body had it ON, which de-gammas a second time.

    stream binding map1. Sora's meshes have one UV set called map1; the old
                   node was still pointing at UV1, left over from the Lucy
                   setup, so it sampled a UV set that does not exist.

The skin is a third trap: the earlier pass had already replaced it, leaving the
original phong6 (1.0, 0.675, 0.651) orphaned in the scene. That value is the
one restored here, not the 1.2-red the broken node had drifted to.

    import sys; sys.path.insert(0, r"Z:/RD/GNTShader/tools")
    import setup_sora; setup_sora.run()
"""

import os
import sys

from maya import cmds, mel

PROJECT = r"Z:/RD/GNTShader"
if os.path.join(PROJECT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT, "scripts"))

MESHES = ("belt", "body", "face", "hair", "shoes", "skirt", "suit")
UV_SET = "map1"

# The skin material the earlier pass displaced. Its faces now sit under a GNT
# node, so the colour has to come from the orphan rather than from the mesh.
SKIN_SOURCE = "phong6"
SKIN_FALLBACK = (1.0, 0.675, 0.651)

BASE_PRESET = "genshin_like"


def _log(out, *a):
    line = " ".join(str(x) for x in a)
    out.append(line)
    print(line)


def source_colour(mat):
    """The material's own colour and albedo map, whatever kind of node it is."""
    for attr in ("color", "baseColor"):
        full = "{0}.{1}".format(mat, attr)
        if not cmds.objExists(full):
            continue
        texture = ""
        files = cmds.listConnections(full, source=True, destination=False,
                                     type="file") or []
        if files:
            texture = cmds.getAttr(files[0] + ".fileTextureName") or ""
        try:
            value = cmds.getAttr(full)[0]
        except (RuntimeError, ValueError):
            value = (1.0, 1.0, 1.0)
        return tuple(value), texture
    return (1.0, 1.0, 1.0), ""


def survey():
    """Which shading group owns which faces, and what colour it is.

    Read before anything is touched: reassigning the first material would
    otherwise change the answer for the rest.
    """
    plan = []
    for mesh in MESHES:
        if not cmds.objExists(mesh):
            continue
        shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True,
                                   fullPath=True)[0]
        short = shape.split("|")[-1]
        for sg in sorted(set(cmds.listConnections(shape,
                                                  type="shadingEngine") or [])):
            members = [m for m in (cmds.sets(sg, q=True) or [])
                       if m.split(".")[0].split("|")[-1] in (mesh, short)]
            if not members:
                continue
            mats = cmds.listConnections(sg + ".surfaceShader") or []
            if not mats:
                continue
            plan.append({"mesh": mesh, "sg": sg, "material": mats[0],
                         "members": members})
    return plan


# Sora has no specular map and no ILM, so a single highlight setting has to
# serve every surface -- and the preset's default (intensity 1.4, softness 0.01)
# lands on flat colour as scattered hard white blobs rather than an anime
# highlight. These classes give each kind of surface a highlight that suits it.
# None of them touches BaseColor: the colours are already exact and stay that
# way.
SPEC_CLASS = {
    "skin": dict(members=("GNT_Sora_Body", "GNT_Sora_M_Sora_Face1"), params={
        "SpecMode": 1.0, "SpecIntensity": 0.10, "SpecGloss": 12.0,
        "SpecThreshold": 0.62, "SpecSoftness": 0.22,
        # the preset's cool violet shadow turns skin grey-magenta; flesh in
        # shade goes warm, and measuring the leg showed a 33 degree hue swing
        # off the albedo until this was changed
        "ShadowColor": [0.80, 0.63, 0.60], "HalfLambert": 0.70,
        "RimIntensity": 0.30, "RimColor": [1.0, 0.86, 0.80],
        "AmbientColor": [0.16, 0.14, 0.15]}),

    "hair": dict(members=("GNT_Sora_phong5_Hair",), params={
        "SpecMode": 3.0,               # Kajiya-Kay: one coherent strand band
        "AnisoExponent": 40.0, "AnisoShiftIntensity": 0.30, "AnisoBias": 0.18,
        "SpecIntensity": 0.70, "SpecColor": [1.0, 0.92, 0.92],
        "ShadowColor": [0.62, 0.42, 0.50], "HalfLambert": 0.85,
        "RimIntensity": 0.45}),

    "metal": dict(members=("GNT_Sora_Gold1",), params={
        "SpecMode": 1.0, "SpecIntensity": 1.10, "SpecGloss": 90.0,
        "SpecThreshold": 0.62, "SpecSoftness": 0.03,
        "SpecColor": [1.0, 0.95, 0.80], "RimIntensity": 0.60}),

    # Near-black surfaces: a bright highlight on them reads as noise, not shine.
    "dark": dict(members=("GNT_Sora_Base5", "GNT_Sora_Base6",
                          "GNT_Sora_phong22"), params={
        "SpecMode": 1.0, "SpecIntensity": 0.12, "SpecGloss": 25.0,
        "SpecThreshold": 0.66, "SpecSoftness": 0.12, "RimIntensity": 0.25}),
}

CLOTH = dict(params={
    "SpecMode": 1.0, "SpecIntensity": 0.28, "SpecGloss": 22.0,
    "SpecThreshold": 0.60, "SpecSoftness": 0.16,
    "ShadowColor": [0.58, 0.54, 0.66], "HalfLambert": 0.90,
    "RimIntensity": 0.35})


def tune_specular(log=None):
    """Give each class of surface a highlight that suits it. Colours untouched."""
    from gntshader.core import shader as gshader
    out = log if log is not None else []
    classed = set()
    for name, spec in SPEC_CLASS.items():
        for node in spec["members"]:
            if not cmds.objExists(node):
                continue
            before = cmds.getAttr(node + ".BaseColor")[0]
            gshader.set_params(node, spec["params"])
            after = cmds.getAttr(node + ".BaseColor")[0]
            drift = max(abs(before[i] - after[i]) for i in range(3))
            classed.add(node)
            _log(out, "  %-24s %-6s  BaseColor drift %.6f" % (node, name, drift))
    for node in sorted(cmds.ls("GNT_Sora_*", type="GLSLShader") or []):
        if node in classed:
            continue
        before = cmds.getAttr(node + ".BaseColor")[0]
        gshader.set_params(node, CLOTH["params"])
        after = cmds.getAttr(node + ".BaseColor")[0]
        _log(out, "  %-24s %-6s  BaseColor drift %.6f"
             % (node, "cloth", max(abs(before[i] - after[i]) for i in range(3))))
    return out


def split_hair(log=None):
    """Give the hair its own shader.

    phong5 is the crimson used on the hair, the skirt, the belt and parts of
    the jacket, so an anisotropic strand highlight applied to it would streak
    across the skirt too. Same colour, separate node.
    """
    from gntshader.core import shader as gshader
    from gntshader.core import presets as gpresets
    out = log if log is not None else []
    source = "GNT_Sora_phong5"
    name = "GNT_Sora_phong5_Hair"
    if not cmds.objExists(source) or not cmds.objExists("hair"):
        return out
    for stale in cmds.ls(name, name + "SG") or []:
        if cmds.objExists(stale):
            cmds.delete(stale)
    node, sg = gshader.create(name=name)
    gpresets.apply(node, BASE_PRESET)
    rgb = cmds.getAttr(source + ".BaseColor")[0]
    gshader.set_params(node, {"BaseColor": list(rgb), "AlbedoIsSRGB": 0,
                              "UseAlbedoMap": 0, "UseLightMap": 0,
                              "UseSSSMap": 0, "ILMAoStrength": 0.0,
                              "OutlineUseVertexColor": 1, "OutlineWidth": 0.10})
    cmds.sets("hair", edit=True, forceElement=sg)
    gshader.bind_streams(node, "hair", uv_set=UV_SET)
    _log(out, "hair split onto %s, colour copied exactly: %s"
         % (node, [round(c, 4) for c in cmds.getAttr(node + ".BaseColor")[0]]))
    return out


def run(log_path=os.path.join(PROJECT, "sora_setup.txt")):
    from gntshader.core import shader as gshader
    from gntshader.core import presets as gpresets
    from gntshader.utils import mesh as gmesh

    out = []
    plan = survey()
    _log(out, "found %d material assignments across %d meshes"
         % (len(plan), len(set(p["mesh"] for p in plan))))

    # ---- colours, captured before anything moves -------------------------
    colours = {}
    for entry in plan:
        mat = entry["material"]
        if mat in colours:
            continue
        if cmds.nodeType(mat) == "GLSLShader":
            # left over from the earlier pass; its colour is not trustworthy
            if cmds.objExists(SKIN_SOURCE):
                colours[mat] = source_colour(SKIN_SOURCE)
                _log(out, "  %s: colour taken from the orphaned %s"
                     % (mat, SKIN_SOURCE))
            else:
                colours[mat] = (SKIN_FALLBACK, "")
                _log(out, "  %s: %s is gone, using the recorded skin value"
                     % (mat, SKIN_SOURCE))
        else:
            colours[mat] = source_colour(mat)

    _log(out, "\n--- source colours ---")
    for mat in sorted(colours):
        rgb, tex = colours[mat]
        _log(out, "  %-16s %-26s %s" % (mat, [round(c, 4) for c in rgb],
                                        os.path.basename(tex) or "-"))

    # ---- mesh prep --------------------------------------------------------
    _log(out, "\n--- preparing meshes ---")
    meshes = sorted(set(p["mesh"] for p in plan))
    for mesh in meshes:
        paint, smooth = gmesh.prepare(mesh)
        _log(out, "  %-8s paint=%s smooth=%s" % (mesh, paint, smooth))

    reference = gmesh.character_reference(meshes, percentile=0.50)
    for mesh in meshes:
        gmesh.bake_outline_width(mesh, min_scale=0.45, reference=reference)
    _log(out, "shared thickness reference %.3f, outline width baked on %d meshes"
         % (reference, len(meshes)))

    # ---- one shader per source material -----------------------------------
    _log(out, "\n--- shaders ---")
    made = {}
    for mat in sorted(colours):
        name = "GNT_Sora_" + mat.replace("GNT_Sora_", "")
        for stale in cmds.ls(name, name + "SG") or []:
            if cmds.objExists(stale):
                cmds.delete(stale)
        node, sg = gshader.create(name=name)
        made[mat] = (node, sg)

        rgb, texture = colours[mat]
        # A phong whose .color has a texture plugged in ignores the attribute
        # value, and Maya leaves that value at whatever it happened to be --
        # black, on both of Sora's textured materials. Multiplying the map by it
        # would render the face and the shoes as silhouettes. The map carries
        # the colour; the tint has to be white.
        if texture:
            rgb = (1.0, 1.0, 1.0)
        params = {
            # Colour management is on in this scene: the file node linearises
            # and the viewport applies the display transform, so the shader
            # must not de-gamma as well.
            "AlbedoIsSRGB": 0,
            "BaseColor": [max(0.0, min(1.0, c)) for c in rgb],
            "UseAlbedoMap": 1 if texture else 0,
            "OutlineUseVertexColor": 1,
            "OutlineWidth": 0.10,
            "ILMAoStrength": 0.0,
            "ILMShadowBias": 0.0,
            "UseLightMap": 0,
            "UseSSSMap": 0,
        }
        gpresets.apply(node, BASE_PRESET)
        if texture and os.path.isfile(texture):
            gshader.set_texture(node, "AlbedoMap", texture)
        skipped = gshader.set_params(node, params)
        if skipped:
            _log(out, "  !! %s skipped %s" % (node, sorted(skipped)))
        _log(out, "  %-22s <- %-14s %s%s"
             % (node, mat, [round(c, 3) for c in params["BaseColor"]],
                "  +" + os.path.basename(texture) if texture else ""))

    # ---- reassign, face for face ------------------------------------------
    _log(out, "\n--- assignment ---")
    for entry in plan:
        node, sg = made[entry["material"]]
        cmds.sets(entry["members"], edit=True, forceElement=sg)
        gshader.bind_streams(node, entry["mesh"], uv_set=UV_SET)
        _log(out, "  %-8s %-16s -> %-22s (%d component groups)"
             % (entry["mesh"], entry["material"], node, len(entry["members"])))

    # ---- a light, because the scene has none ------------------------------
    lights = cmds.ls(type="directionalLight") or []
    if lights:
        key = cmds.listRelatives(lights[0], parent=True)[0]
        _log(out, "\nusing the existing light: %s" % key)
    else:
        shape = cmds.directionalLight(name="GNT_Sora_key", intensity=1.0)
        key = cmds.listRelatives(shape, parent=True)[0] or shape
        cmds.xform(key, ws=True, rotation=(-30, 25, 0))
        _log(out, "\nscene had no light; created %s" % key)

    for node, _sg in made.values():
        try:
            mel.eval('GLSLShader %s -cl "Light_0" "%s"' % (node, key))
        except RuntimeError:
            pass

    for panel in cmds.getPanel(type="modelPanel") or []:
        cmds.modelEditor(panel, e=True, displayLights="all")
    _log(out, "viewport displayLights set to 'all'")

    _log(out, "")
    _log(out, "--- hair ---")
    split_hair(out)
    _log(out, "")
    _log(out, "--- specular by surface class ---")
    tune_specular(out)
    for node in sorted(cmds.ls("GNT_Sora_*", type="GLSLShader") or []):
        try:
            mel.eval('GLSLShader %s -cl "Light_0" "%s"' % (node, key))
        except RuntimeError:
            pass

    with open(log_path, "w") as handle:
        handle.write("\n".join(out))
    return {mat: node for mat, (node, _sg) in made.items()}


if __name__ == "__main__":
    run()
