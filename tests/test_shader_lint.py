"""Static checks on the .ogsfx files -- catches typos before Maya does.

Pure Python, no Maya, no GPU::

    python tests/test_shader_lint.py

Maya only parses an effect once Viewport 2.0 has a live draw context, so a
freshly written shader stays unverified until someone opens the GUI. These
checks close part of that gap, and pin down the things that cost us time:

* sampler tokens Maya actually accepts (CLAMP_TO_BORDER compiles nowhere and
  OGSFX has no syntax for a border colour)
* varying members referenced through VS_OUT / PS_IN that the attribute block
  never declared
* vertex inputs referenced but missing from APPDATA
* passes wired to GLSLShader or attribute blocks that do not exist
* the pixel output actually being written
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHADER_DIR = os.path.join(ROOT, "shaders")

# Tokens proven to work: Maya ships the first three, and CLAMP_TO_EDGE is
# confirmed by GNTAnime.ogsfx compiling clean in Maya 2024.
SAMPLER_VALUES = {
    "REPEAT", "MIRRORED_REPEAT", "CLAMP_TO_EDGE",
    "LINEAR", "NEAREST", "LINEAR_MIPMAP_LINEAR", "NEAREST_MIPMAP_NEAREST",
    "LINEAR_MIPMAP_NEAREST", "NEAREST_MIPMAP_LINEAR",
}

FAILURES = []


def check(condition, label, detail=""):
    print("  [%s] %s%s" % ("PASS" if condition else "FAIL", label,
                           ("  -- " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def strip_comments(source):
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def block_body(source, start):
    """Text between the brace at/after ``start`` and its match."""
    depth = 0
    open_at = source.find("{", start)
    if open_at < 0:
        return "", start
    for i in range(open_at, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_at + 1:i], i
    return "", len(source)


def parse(source):
    """Attribute blocks, GLSLShader blocks and pass wiring."""
    attributes = {}
    for match in re.finditer(r"\battribute\s+(\w+)\s*\{", source):
        body, _end = block_body(source, match.end() - 1)
        members = set(re.findall(r"\b\w+\s+(\w+)\s*(?::\s*\w+\s*)?;", body))
        attributes[match.group(1)] = members

    stages = {}
    for match in re.finditer(r"\bGLSLShader\s+(\w+)\s*\{", source):
        body, _end = block_body(source, match.end() - 1)
        stages[match.group(1)] = body

    wiring = []
    pattern = re.compile(
        r"(\w+Shader)\s*\(\s*in\s+(\w+)(?:\s+(\w+))?\s*,\s*"
        r"out\s+(\w+)(?:\s+(\w+))?\s*\)\s*=\s*([^;]+);")
    for match in pattern.finditer(source):
        impls = re.findall(r"\w+", match.group(6))
        wiring.append({
            "stage": match.group(1),
            "in_block": match.group(2), "in_inst": match.group(3),
            "out_block": match.group(4), "out_inst": match.group(5),
            "impls": impls,
        })

    return attributes, stages, wiring


def lint(path):
    name = os.path.basename(path)
    print(name)
    source = strip_comments(read(path))
    attributes, stages, wiring = parse(source)

    check(source.count("{") == source.count("}"), "%s: braces balanced" % name,
          "%d open / %d close" % (source.count("{"), source.count("}")))

    # --- sampler tokens ---------------------------------------------------
    bad_tokens = set()
    for key, value in re.findall(r"(TEXTURE_\w+)\s*=\s*(\w+)", source):
        if value not in SAMPLER_VALUES:
            bad_tokens.add("%s = %s" % (key, value))
    check(not bad_tokens, "%s: sampler tokens are ones Maya accepts" % name,
          ", ".join(sorted(bad_tokens)))

    # --- every sampler points at a declared texture ------------------------
    textures = set(re.findall(r"uniform\s+texture\w*\s+(\w+)", source))
    missing = set()
    for target in re.findall(r"Texture\s*=\s*<\s*(\w+)\s*>", source):
        if target not in textures:
            missing.add(target)
    check(not missing, "%s: samplers reference declared textures" % name,
          ", ".join(sorted(missing)))

    # --- pass wiring ------------------------------------------------------
    unknown_blocks = set()
    unknown_impls = set()
    for entry in wiring:
        for block in (entry["in_block"], entry["out_block"]):
            if block not in attributes:
                unknown_blocks.add(block)
        for impl in entry["impls"]:
            if impl not in stages:
                unknown_impls.add(impl)
    check(not unknown_blocks, "%s: passes use declared attribute blocks" % name,
          ", ".join(sorted(unknown_blocks)))
    check(not unknown_impls, "%s: passes use declared GLSLShader blocks" % name,
          ", ".join(sorted(unknown_impls)))

    # --- varying members --------------------------------------------------
    bad_members = set()
    for entry in wiring:
        body = "\n".join(stages.get(impl, "") for impl in entry["impls"])
        for inst, block in ((entry["in_inst"], entry["in_block"]),
                            (entry["out_inst"], entry["out_block"])):
            if not inst or block not in attributes:
                continue
            for member in re.findall(re.escape(inst) + r"\.(\w+)", body):
                if member not in attributes[block]:
                    bad_members.add("%s.%s (not in %s)" % (inst, member, block))
    check(not bad_members, "%s: varying members exist" % name,
          "; ".join(sorted(bad_members)))

    # --- vertex inputs (naming convention: inSomething) -------------------
    appdata = attributes.get("APPDATA", set())
    bad_inputs = set()
    for entry in wiring:
        if entry["in_block"] != "APPDATA":
            continue
        body = "\n".join(stages.get(impl, "") for impl in entry["impls"])
        for ident in re.findall(r"\b(in[A-Z]\w*)\b", body):
            if ident not in appdata:
                bad_inputs.add(ident)
    check(not bad_inputs, "%s: vertex inputs declared in APPDATA" % name,
          ", ".join(sorted(bad_inputs)))

    # --- pixel outputs get written ----------------------------------------
    unwritten = set()
    for entry in wiring:
        if entry["stage"] != "PixelShader":
            continue
        members = attributes.get(entry["out_block"], set())
        body = "\n".join(stages.get(impl, "") for impl in entry["impls"])
        for member in members:
            if not re.search(r"\b" + re.escape(member) + r"\s*=", body):
                unwritten.add("%s.%s" % (entry["out_block"], member))
    check(not unwritten, "%s: pixel outputs are written" % name,
          ", ".join(sorted(unwritten)))


def main():
    files = sorted(name for name in os.listdir(SHADER_DIR)
                   if name.endswith(".ogsfx"))
    if not files:
        print("no .ogsfx found in %s" % SHADER_DIR)
        return 1

    for name in files:
        lint(os.path.join(SHADER_DIR, name))

    print("-" * 60)
    if FAILURES:
        print("%d FAILED: %s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
