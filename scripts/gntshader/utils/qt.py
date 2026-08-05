"""Qt binding shim.

Maya 2024 ships PySide2, Maya 2025+ ships PySide6. Import from here so the
rest of the package does not care which one is present.
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
    QT_BINDING = "PySide6"
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance
    QT_BINDING = "PySide2"

from maya import OpenMayaUI


def maya_main_window():
    """Maya's main window as a QWidget, for parenting tool windows."""
    pointer = OpenMayaUI.MQtUtil.mainWindow()
    if pointer is None:
        return None
    return wrapInstance(int(pointer), QtWidgets.QWidget)


def delete_existing(object_name):
    """Close any previous instance of a window with this object name."""
    parent = maya_main_window()
    if parent is None:
        return
    for child in parent.findChildren(QtWidgets.QWidget, object_name):
        child.setParent(None)
        child.deleteLater()


__all__ = [
    "QtCore", "QtGui", "QtWidgets", "wrapInstance",
    "QT_BINDING", "maya_main_window", "delete_existing",
]
