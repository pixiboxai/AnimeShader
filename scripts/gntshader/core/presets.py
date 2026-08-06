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


def presets_for(shader_filename, directory=None):
    """Preset names built for a given effect file.

    Presets without a ``shader`` field are treated as belonging to the body
    shader, which is what they were before the field existed.
    """
    matches = []
    for name, path in preset_files(directory).items():
        try:
            data = load_file(path)
        except (IOError, ValueError):
            continue
        if data.get("shader", "GNTAnime.ogsfx") == shader_filename:
            matches.append(name)
    return sorted(matches)


def apply(node, preset, skip_textures=False):
    """Apply a preset dict (or a preset name) to a shader node.

    Returns the list of uniforms that could not be applied.
    """
    if isinstance(preset, str):
        files = preset_files()
        if preset not in files:
            raise ValueError("Unknown preset: {0}".format(preset))
        preset = load_file(files[preset])

    # A preset built for the eye shader will silently do nothing on the body
    # shader (every key gets skipped), so say so up front.
    wanted = preset.get("shader")
    if wanted:
        current = os.path.basename(cmds.getAttr(node + ".shader") or "")
        if current and current != wanted:
            cmds.warning(
                "GNTShader: preset '{0}' is for {1}, but {2} is running {3}.".format(
                    preset.get("name", "?"), wanted, node, current)
            )

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
        "shader": os.path.basename(cmds.getAttr(node + ".shader") or ""),
        "technique": shader.technique(node),
        "parameters": params,
    }

    path = os.path.join(directory, "{0}.json".format(name))
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path
