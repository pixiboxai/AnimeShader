"""Keep the .ogsfx files, the presets and the UI talking about the same names.

Pure Python -- no Maya, no GPU::

    python tests/test_shader_contract.py

Why this exists: a preset key that does not match a uniform is skipped at
runtime with a warning that is easy to miss, so the look silently comes out
wrong. Same for the quick-control sliders in the tool window. A typo here is
invisible until someone wonders why a preset "does nothing".
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SHADER_DIR = os.path.join(ROOT, "shaders")
PRESET_DIR = os.path.join(ROOT, "presets")
MAIN_WINDOW = os.path.join(ROOT, "scripts", "gntshader", "ui", "main_window.py")
ENV_MODULE = os.path.join(ROOT, "scripts", "gntshader", "core", "env.py")

MAIN_SHADER = "GNTAnime.ogsfx"
EYE_SHADER = "GNTAnimeEye.ogsfx"

FAILURES = []


def check(condition, label, detail=""):
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", label,
                           ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def parse_shader(source):
    """Uniform names, technique names and vertex semantics of an effect."""
    uniforms = set(re.findall(r"^\s*uniform\s+\w+\s+(\w+)", source, re.MULTILINE))
    techniques = set(re.findall(r"^technique\s+(\w+)", source, re.MULTILINE))

    semantics = set()
    block = re.search(r"attribute\s+APPDATA\s*\{(.*?)\}", source, re.DOTALL)
    if block:
        semantics = set(re.findall(r":\s*(\w+)\s*;", block.group(1)))

    return uniforms, techniques, semantics


def main():
    shaders = {}
    for name in sorted(os.listdir(SHADER_DIR)):
        if name.endswith(".ogsfx"):
            shaders[name] = parse_shader(read(os.path.join(SHADER_DIR, name)))

    print("shaders")
    check(MAIN_SHADER in shaders, "%s present" % MAIN_SHADER)
    check(EYE_SHADER in shaders, "%s present" % EYE_SHADER)

    for name, (uniforms, techniques, semantics) in shaders.items():
        check(len(uniforms) > 20, "%s: uniforms parsed" % name,
              "%d found" % len(uniforms))
        check(bool(techniques), "%s: techniques declared" % name,
              ", ".join(sorted(techniques)))
        # Maya's glslShader binds exactly one colour stream; a second COLOR
        # semantic compiles but the varying is dropped in silence.
        check("COLOR1" not in semantics, "%s: no COLOR1" % name,
              ", ".join(sorted(semantics)))

    main_uniforms, main_techniques, main_semantics = shaders[MAIN_SHADER]
    print("main shader streams")
    check("COLOR0" in main_semantics, "COLOR0 present for artist paint")
    check("TEXCOORD1" in main_semantics, "TEXCOORD1 present for the smooth normal")
    check(main_techniques == {"Anime", "AnimeOutline"}, "technique names",
          ", ".join(sorted(main_techniques)))

    print("presets")
    preset_files = sorted(name for name in os.listdir(PRESET_DIR)
                          if name.endswith(".json"))
    check(bool(preset_files), "presets found", "%d files" % len(preset_files))

    for name in preset_files:
        data = json.loads(read(os.path.join(PRESET_DIR, name)))
        target = data.get("shader", MAIN_SHADER)

        if target not in shaders:
            check(False, "%s: names a shader that exists" % name, target)
            continue

        uniforms, techniques, _semantics = shaders[target]

        unknown = sorted(set(data.get("parameters", {})) - uniforms)
        check(not unknown, "%s -> %s: every key is a real uniform" % (name, target),
              ("unknown: " + ", ".join(unknown)) if unknown else "")

        technique = data.get("technique")
        check(technique in techniques, "%s: technique exists" % name, str(technique))

    print("tool window")
    ui = read(MAIN_WINDOW)
    quick = re.search(r"QUICK_PARAMS\s*=\s*\[(.*?)\]", ui, re.DOTALL)
    if quick:
        attrs = re.findall(r'\(\s*"(\w+)"', quick.group(1))
        unknown = sorted(set(attrs) - main_uniforms)
        check(not unknown, "quick sliders map to real uniforms",
              ("unknown: " + ", ".join(unknown)) if unknown
              else "%d sliders" % len(attrs))
    else:
        check(False, "QUICK_PARAMS found in main_window.py")

    print("code references")
    env_src = read(ENV_MODULE)
    check("SMOOTH_NORMAL_UV_SET" in env_src and
          "SMOOTH_NORMAL_COLOR_SET" not in env_src,
          "env.py uses the UV-set name, not the old colour-set one")

    every_uniform = set()
    for uniforms, _t, _s in shaders.values():
        every_uniform |= uniforms

    for path in (os.path.join(ROOT, "verify_outline.py"),
                 os.path.join(ROOT, "scripts", "gntshader", "core", "shader.py")):
        src = read(path)
        referenced = set(re.findall(r'"(Outline\w+|Head\w+|Base\w+|Rim\w+|Spec\w+'
                                    r'|Shadow\w+|Ambient\w+|Emission\w+|Iris\w+'
                                    r'|Pupil\w+|Highlight\w+)"', src))
        unknown = sorted(referenced - every_uniform)
        check(not unknown, "%s: uniform names valid" % os.path.basename(path),
              ("unknown: " + ", ".join(unknown)) if unknown
              else "%d referenced" % len(referenced))

    print("-" * 60)
    if FAILURES:
        print("%d FAILED: %s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
