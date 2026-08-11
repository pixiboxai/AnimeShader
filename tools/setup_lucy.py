"""Assign the GNT anime shader to the Guilty Gear Strive Lucy sample.

Run inside Maya with GGSLucy.mb (or GGSLucy_quad.mb) open::

    import sys; sys.path.insert(0, r"Z:/RD/GNTShader/tools")
    import setup_lucy; setup_lucy.run()

Why this sample is worth wiring by hand: it ships the real Arc System Works
texture set, and the packing is exactly what the shader already reads --
measured on LUC_ilm.png rather than assumed:

    R  specular intensity     p50 80,  71 distinct values
    G  shadow map             clustered at 127, the neutral value
    B  specular size          near 0 -- tight highlights
    A  interior lines         only 2 distinct values, i.e. a binary mask

The scene has colour management switched off, so Maya's file nodes hand the
shader sRGB-encoded values untouched. AlbedoIsSRGB therefore has to be ON here
and the file nodes pinned to Raw, otherwise the maps come out washed out. That
is a property of the scene, not of the textures -- check it before copying
these settings elsewhere.
"""

import os
import sys

from maya import cmds, mel

PROJECT = r"Z:/RD/GNTShader"
TEX = r"Z:/RD/GNTShader/Sample/Guilty Gear Strive - Lucy"

if os.path.join(PROJECT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT, "scripts"))


# Solid character pieces: albedo + ILM + SSS from one of the two atlases.
SOLID = {
    "GNT_Lucy_Body":   dict(meshes=["Lucy_body", "Lucy_eyewhite"], atlas="LUC"),
    "GNT_Lucy_Face":   dict(meshes=["Lucy_face"], atlas="LUC", face=True),
    "GNT_Lucy_Hair":   dict(meshes=["Lucy_hair"], atlas="LUC", hair=True),
    "GNT_Lucy_Weapon": dict(meshes=["Lucy_gun", "Lucy_bag"], atlas="LUCW"),
}

# Transparent sheets laid over the body: cutout, no outline, no ILM.
OVERLAY = {
    "GNT_Lucy_Detail": dict(meshes=["Lucy_detail"], map="LUC_detailX.png"),
    "GNT_Lucy_Decal":  dict(meshes=["Lucy_decalBody", "Lucy_decalFace",
                                    "Lucy_gunTrim"], map="LUC_decalX.png"),
}

UV_SET = "UV1"

# What reaches the screen is OutlineWidth * the baked per-vertex multiplier, and
# that multiplier settles at a different average on each piece (body 0.93, hair
# 0.81, face 0.62, props 0.55) because the pieces are genuinely different
# thicknesses. Left alone the head draws a lighter line than the torso, which is
# the first thing that reads as wrong. These widths cancel the difference so the
# ink weighs the same everywhere.
OUTLINE_WIDTH = {
    "GNT_Lucy_Body":   0.80,
    "GNT_Lucy_Face":   1.21,
    "GNT_Lucy_Hair":   0.92,
    "GNT_Lucy_Weapon": 1.20,
}
TARGET_WEIGHT = 0.75             # OutlineWidth * mean multiplier
BASE_PRESET = "genshin_like"     # Arc System Works sits close to a hard two-tone


def _log(out, *a):
    line = " ".join(str(x) for x in a)
    out.append(line)
    print(line)


def _clean(out):
    """Remove debris left by earlier verification runs."""
    junk = []
    for pattern in ("gntVerify*", "GNT_metalProbe*", "GNT_metalTest*",
                    "GNT_probe*", "GNT_csProbe*"):
        junk += cmds.ls(pattern) or []
    for node in sorted(set(junk)):
        if cmds.objExists(node):
            try:
                cmds.delete(node)
            except RuntimeError:
                pass
    if junk:
        _log(out, "removed leftovers:", sorted(set(junk)))


def run(base_preset=BASE_PRESET, log_path=os.path.join(PROJECT, "lucy_setup.txt")):
    from gntshader.core import shader as gshader
    from gntshader.core import presets as gpresets
    from gntshader.utils import mesh as gmesh

    out = []
    _clean(out)

    all_meshes = []
    for spec in list(SOLID.values()) + list(OVERLAY.values()):
        all_meshes += [m for m in spec["meshes"] if cmds.objExists(m)]
    missing = [m for spec in list(SOLID.values()) + list(OVERLAY.values())
               for m in spec["meshes"] if not cmds.objExists(m)]
    if missing:
        _log(out, "WARNING missing meshes:", missing)

    # ---- mesh prep -----------------------------------------------------
    _log(out, "\n--- preparing %d meshes ---" % len(all_meshes))
    for mesh in all_meshes:
        paint, smooth = gmesh.prepare(mesh)
        _log(out, "  %-16s paint=%s smooth=%s" % (mesh, paint, smooth))

    # One thickness reference for the whole character, so the outline weighs
    # the same on the body, the head and the hair.
    solid_meshes = [m for spec in SOLID.values() for m in spec["meshes"]
                    if cmds.objExists(m)]
    # The 0.80 quantile is the body's own ceiling on this character -- 3.76
    # against the face's 0.55 -- so every other piece floors at min_scale and
    # the head ends up with a visibly lighter line than the torso. Take the
    # median instead, which sits between the pieces rather than on top of the
    # thickest one.
    reference = gmesh.character_reference(solid_meshes, percentile=0.50)
    _log(out, "\nshared thickness reference: %.3f" % reference)
    for mesh in solid_meshes:
        gmesh.bake_outline_width(mesh, min_scale=0.45, reference=reference)
    _log(out, "outline width baked on %d meshes" % len(solid_meshes))

    # ---- shaders -------------------------------------------------------
    made = {}
    _log(out, "\n--- shaders ---")
    for name, spec in sorted(SOLID.items()):
        meshes = [m for m in spec["meshes"] if cmds.objExists(m)]
        if not meshes:
            continue
        node, sg = gshader.create(name=name)
        made[name] = node
        gshader.assign(node, meshes)
        for mesh in meshes:
            gshader.bind_streams(node, mesh, uv_set=UV_SET)
        gpresets.apply(node, base_preset)

        atlas = spec["atlas"]
        gshader.set_texture(node, "AlbedoMap",
                            "%s/%s_baseX.png" % (TEX, atlas), colour_space="Raw")
        gshader.set_texture(node, "LightMap",
                            "%s/%s_ilm.png" % (TEX, atlas), colour_space="Raw")
        gshader.set_texture(node, "SSSMap",
                            "%s/%s_Sss.png" % (TEX, atlas), colour_space="Raw")

        skipped = gshader.set_params(node, {
            "UseAlbedoMap": 1,
            "AlbedoIsSRGB": 1,          # colour management is off in this scene
            "UseLightMap": 1,           # ILM: spec / shadow / size / lines

            # ILM green is NOT occlusion. GGXrd paints the terminator position
            # into it: 0.5 means "wherever the light puts it", brighter means
            # "stay lit", darker means "stay in shadow". Multiplying it into AO
            # instead -- which is what this script did first -- darkens the
            # whole model by about a third, because the neutral value is 0.5,
            # and throws away the authored shadow shapes entirely.
            "ILMAoStrength": 0.0,
            "ILMShadowBias": 1.0,
            "ILMBiasUseVertexColor": 0,   # our vcol.r carries outline width

            "UseSSSMap": 1,
            "ShadowColorMode": 1.0,     # shadow colour comes from the map
            "SSSStrength": 1.0,
            "UseInteriorLines": 1,      # ilm.a is a binary line mask
            "InteriorLineOpacity": 0.85,
            "InteriorLineThreshold": 0.5,
            "InteriorLineSoftness": 0.05,
            "OutlineTintFromAlbedo": 1,
            "OutlineTintAmount": 0.60,
            "OutlineUseVertexColor": 1,
            "OutlineWidth": OUTLINE_WIDTH.get(name, 0.80),
        })
        if skipped:
            _log(out, "  !! %s skipped: %s" % (name, sorted(skipped)))

        if spec.get("hair"):
            # The ILM already says where the hair highlight goes (R intensity,
            # B size), which is how the game does it. SpecMode 3 (Kajiya-Kay)
            # is available and looks good, but it is a different look, not the
            # authored one.
            gshader.set_params(node, {
                "SpecMode": 1.0,
                "SpecIntensity": 1.2,
                "SpecThreshold": 0.50,
                "SpecSoftness": 0.02,
            })
        if spec.get("face"):
            gshader.set_params(node, {
                "ShadowSoftness": 0.05,   # a hard band reads as dirt on a face
                "SpecIntensity": 0.35,
            })

        _log(out, "  %-16s -> %s  (%s atlas)" % (node, ", ".join(meshes), atlas))

    for name, spec in sorted(OVERLAY.items()):
        meshes = [m for m in spec["meshes"] if cmds.objExists(m)]
        if not meshes:
            continue
        node, sg = gshader.create(name=name)
        made[name] = node
        gshader.assign(node, meshes)
        for mesh in meshes:
            gshader.bind_streams(node, mesh, uv_set=UV_SET)
        gpresets.apply(node, base_preset)
        gshader.set_texture(node, "AlbedoMap", "%s/%s" % (TEX, spec["map"]),
                            colour_space="Raw")
        gshader.set_params(node, {
            "UseAlbedoMap": 1,
            "AlbedoIsSRGB": 1,
            "UseAlphaClip": 1,
            "AlphaCutoff": 0.30,
            "UseLightMap": 0,
            "UseSSSMap": 0,
            "UseInteriorLines": 0,
            "SpecIntensity": 0.0,
            "RimIntensity": 0.0,
            # these sheets sit on the skin; an outline round each one reads as
            # a smear rather than ink
            "OutlineWidth": 0.0,
        })
        _log(out, "  %-16s -> %s  (%s, alpha clip)"
             % (node, ", ".join(meshes), spec["map"]))

    # ---- light ---------------------------------------------------------
    lights = [l for l in (cmds.ls(type="directionalLight") or [])]
    if not lights:
        key = cmds.directionalLight(name="GNT_Lucy_key", intensity=1.0)
        keyT = cmds.listRelatives(key, parent=True)[0] or key
        cmds.xform(keyT, ws=True, rotation=(-30, 35, 0))
        _log(out, "\ncreated key light:", keyT)
    else:
        keyT = cmds.listRelatives(lights[0], parent=True)[0] or lights[0]
        _log(out, "\nusing existing light:", keyT)

    for node in made.values():
        try:
            mel.eval('GLSLShader %s -cl "Light_0" "%s"' % (node, keyT))
        except RuntimeError as exc:
            _log(out, "  light bind failed on %s: %s" % (node, exc))

    # Without this the viewport lights everything with a camera headlight and
    # the cel band never appears.
    for panel in cmds.getPanel(type="modelPanel") or []:
        cmds.modelEditor(panel, e=True, displayLights="all")
    _log(out, "viewport displayLights set to 'all'")

    # ---- report --------------------------------------------------------
    _log(out, "\n--- check ---")
    for name, node in sorted(made.items()):
        diag = gshader.diagnostics(node) or ""
        _log(out, "  %-16s uniforms=%-4d diagnostics=%s"
             % (node, len(cmds.getAttr(node + ".uniformParameters") or []),
                diag[:80] or "<empty>"))

    with open(log_path, "w") as handle:
        handle.write("\n".join(out))
    return made


if __name__ == "__main__":
    run()
