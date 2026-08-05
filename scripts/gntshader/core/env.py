"""Filesystem layout and Maya version helpers."""

import os

try:
    from maya import cmds
except ImportError:  # allows importing outside Maya for tests
    cmds = None


# .../GNTShader/scripts/gntshader/core/env.py -> .../GNTShader
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(os.path.dirname(PACKAGE_ROOT))

SHADER_DIR = os.path.join(PROJECT_ROOT, "shaders")
PRESET_DIR = os.path.join(PROJECT_ROOT, "presets")
ICON_DIR = os.path.join(PROJECT_ROOT, "icons")

ANIME_SHADER = os.path.join(SHADER_DIR, "GNTAnime.ogsfx")
EYE_SHADER = os.path.join(SHADER_DIR, "GNTAnimeEye.ogsfx")

# Vertex streams the shader reads.
#   COLOR0    -> artist paint (R = outline width, G = AO)
#   TEXCOORD1 -> octahedral-encoded tangent-space smooth normal
#
# glslShader binds only ONE colour stream, so the smooth normal cannot live in
# a second colour set -- it goes in the second UV set instead.
PAINT_COLOR_SET = "GNT_paint"
SMOOTH_NORMAL_UV_SET = "GNT_smoothNormal"


def maya_version():
    """Return the running Maya version as an int, or 0 outside Maya."""
    if cmds is None:
        return 0
    return int(cmds.about(apiVersion=True) / 10000)


def shader_path(name="GNTAnime.ogsfx"):
    """Absolute path to a shader file shipped with this project."""
    return os.path.join(SHADER_DIR, name)


def check_layout():
    """Report missing pieces of the expected project layout."""
    problems = []
    for label, path in (
        ("shaders dir", SHADER_DIR),
        ("presets dir", PRESET_DIR),
        ("GNTAnime.ogsfx", ANIME_SHADER),
    ):
        if not os.path.exists(path):
            problems.append("{0} not found: {1}".format(label, path))
    return problems
