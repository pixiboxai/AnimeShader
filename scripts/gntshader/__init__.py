"""GNTShader -- real-time anime shading for Maya Viewport 2.0.

Quick start inside Maya::

    import gntshader
    gntshader.show()

Or without the UI::

    from gntshader.core import shader
    node, sg = shader.create()
    shader.assign(node)
"""

__version__ = "0.1.0"


def show():
    """Open the tool window."""
    from .ui import main_window
    return main_window.show()


def reload_package():
    """Re-import every submodule. Handy while developing the tool."""
    import importlib
    import sys

    prefix = __name__ + "."
    names = sorted(
        (name for name in sys.modules if name.startswith(prefix)),
        key=lambda item: item.count("."),
        reverse=True,
    )
    for name in names:
        module = sys.modules.get(name)
        if module is not None:
            importlib.reload(module)
    importlib.reload(sys.modules[__name__])
