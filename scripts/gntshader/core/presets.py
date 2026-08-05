"""Save and load shader looks as JSON."""

import json
import os

from maya import cmds

from . import env
from . import shader


def preset_files(directory=None):
    """All preset files, newest name order, as ``{name: path}``."""
    directory = directory or env.PRESET_DIR
    if not os.path.isdir(directory):
        return {}

    found = {}
    for filename in sorted(os.listdir(directory)):
        if filename.lower().endswith(".json"):
            found[os.path.splitext(filename)[0]] = os.path.join(directory, filename)
    return found


def load_file(path):
    with open(path, "r") as handle:
        return json.load(handle)


def apply(node, preset, skip_textures=False):
    """Apply a preset dict (or a preset name) to a shader node.

    Returns the list of uniforms that could not be applied.
    """
    if isinstance(preset, str):
        files = preset_files()
        if preset not in files:
            raise ValueError("Unknown preset: {0}".format(preset))
        preset = load_file(files[preset])

    technique = preset.get("technique")
    if technique:
        shader.set_technique(node, technique)

    params = dict(preset.get("parameters", {}))
    if skip_textures:
        params = {k: v for k, v in params.items() if not isinstance(v, str)}

    skipped = shader.set_params(node, params)
    if skipped:
        cmds.warning(
            "GNTShader: {0} preset value(s) skipped: {1}".format(
                len(skipped), ", ".join(sorted(skipped)))
        )
    return skipped


def capture(node, name, description="", directory=None, include_textures=False):
    """Write the current state of ``node`` out as a preset file."""
    directory = directory or env.PRESET_DIR
    if not os.path.isdir(directory):
        os.makedirs(directory)

    params = shader.dump_params(node)
    if not include_textures:
        params = {k: v for k, v in params.items() if not isinstance(v, str)}

    payload = {
        "name": name,
        "description": description,
        "technique": shader.technique(node),
        "parameters": params,
    }

    path = os.path.join(directory, "{0}.json".format(name))
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path
