"""Install GNTShader as a Maya module.

Run inside Maya's script editor::

    PROJECT_ROOT = r"D:/path/to/GNTShader"
    exec(open(PROJECT_ROOT + "/install.py").read())

It writes a .mod file into your Maya modules folder so `import gntshader`
works on the next launch. To use it immediately in the current session it also
extends sys.path.

``PROJECT_ROOT`` is picked up from the calling scope; when this file is run
normally it is derived from ``__file__`` instead.
"""

import os
import sys

if "__file__" in globals():
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
elif not globals().get("PROJECT_ROOT"):
    raise RuntimeError(
        "Define PROJECT_ROOT before the exec:\n"
        '    PROJECT_ROOT = r"D:/path/to/GNTShader"\n'
        '    exec(open(PROJECT_ROOT + "/install.py").read())'
    )

MOD_TEMPLATE = """+ GNTShader 0.1.0 {root}
scripts: scripts
icons: icons
PYTHONPATH +:= scripts
"""


def maya_app_dir():
    from maya import cmds
    return cmds.internalVar(userAppDir=True)


def install(root=None):
    root = (root or PROJECT_ROOT).replace("\\", "/")
    app_dir = maya_app_dir()

    written = []
    # Version-specific folders plus the shared one; the shared folder is what
    # makes the module load for every Maya on this machine.
    modules_dir = os.path.join(app_dir, "modules")
    if not os.path.isdir(modules_dir):
        os.makedirs(modules_dir)

    mod_path = os.path.join(modules_dir, "GNTShader.mod")
    with open(mod_path, "w") as handle:
        handle.write(MOD_TEMPLATE.format(root=root))
    written.append(mod_path)

    # Make it usable right now, without restarting.
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    print("GNTShader installed:")
    for path in written:
        print("   " + path)
    print("   sys.path += " + scripts_dir)
    print("\nNow run:\n    import gntshader\n    gntshader.show()")
    return written


if __name__ == "__main__" or True:
    try:
        install()
    except ImportError:
        print("Run this from inside Maya.")
