"""Keep the .ogsfx, the presets and the UI talking about the same names.

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

SHADER = os.path.join(ROOT, "shaders", "GNTAnime.ogsfx")
PRESET_DIR = os.path.join(ROOT, "presets")
MAIN_WINDOW = os.path.join(ROOT, "scripts", "gntshader", "ui", "main_window.py")
ENV_MODULE = os.path.join(ROOT, "scripts", "gntshader", "core", "env.py")

FAILURES = []


def check(condition, label, detail=""):
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", label,
                           ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def shader_uniforms(source):
    """Uniform names the effect exposes as Maya attributes."""
    names = set()
    for match in re.finditer(
            r"^\s*uniform\s+\w+\s+(\w+)", source, re.MULTILINE):
        names.add(match.group(1))
    return names


def shader_techniques(source):
    return set(re.findall(r"^technique\s+(\w+)", source, re.MULTILINE))


def vertex_attributes(source):
    """Semantics declared in the APPDATA block."""
    block = re.search(r"attribute\s+APPDATA\s*\{(.*?)\}", source, re.DOTALL)
    if not block:
        return set()
    return set(re.findall(r":\s*(\w+)\s*;", block.group(1)))


def main():
    source = read(SHADER)

    uniforms = shader_uniforms(source)
    techniques = shader_techniques(source)
    semantics = vertex_attributes(source)

    print("shader")
    check(len(uniforms) > 50, "uniforms parsed", "%d found" % len(uniforms))
    check(techniques == {"Anime", "AnimeOutline"}, "techniques",
          ", ".join(sorted(techniques)))

    # Regression guard. Maya's glslShader binds exactly one colour stream;
    # a second COLOR semantic compiles but the varying is dropped in silence.
    print("vertex streams")
    check("COLOR1" not in semantics,
          "no COLOR1 (glslShader would drop it silently)", ", ".join(sorted(semantics)))
    check("COLOR0" in semantics, "COLOR0 present for artist paint")
    check("TEXCOORD1" in semantics, "TEXCOORD1 present for the smooth normal")

    print("presets")
    preset_files = sorted(name for name in os.listdir(PRESET_DIR)
                          if name.endswith(".json"))
    check(bool(preset_files), "presets found", "%d files" % len(preset_files))

    for name in preset_files:
        data = json.loads(read(os.path.join(PRESET_DIR, name)))

        unknown = sorted(set(data.get("parameters", {})) - uniforms)
        check(not unknown, "%s: every key is a real uniform" % name,
              ("unknown: " + ", ".join(unknown)) if unknown else "")

        technique = data.get("technique")
        check(technique in techniques, "%s: technique exists" % name,
              str(technique))

    print("tool window")
    ui = read(MAIN_WINDOW)
    quick = re.search(r"QUICK_PARAMS\s*=\s*\[(.*?)\]", ui, re.DOTALL)
    if quick:
        attrs = re.findall(r'\(\s*"(\w+)"', quick.group(1))
        unknown = sorted(set(attrs) - uniforms)
        check(not unknown, "quick sliders map to real uniforms",
              ("unknown: " + ", ".join(unknown)) if unknown
              else "%d sliders" % len(attrs))
    else:
        check(False, "QUICK_PARAMS found in main_window.py")

    # Uniforms the Python side pokes by name must exist too.
    print("code references")
    env_src = read(ENV_MODULE)
    check("SMOOTH_NORMAL_UV_SET" in env_src and
          "SMOOTH_NORMAL_COLOR_SET" not in env_src,
          "env.py uses the UV-set name, not the old colour-set one")

    for path in (os.path.join(ROOT, "verify_outline.py"),
                 os.path.join(ROOT, "scripts", "gntshader", "core", "shader.py")):
        src = read(path)
        referenced = set(re.findall(r'"(Outline\w+|Head\w+|Base\w+|Rim\w+|Spec\w+'
                                    r'|Shadow\w+|Ambient\w+|Emission\w+)"', src))
        unknown = sorted(referenced - uniforms)
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
