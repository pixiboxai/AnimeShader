"""GNTShader tool window.

Deliberately does *not* rebuild the uniform editor: Maya's Attribute Editor
already generates one from the UIGroup / UIName annotations in the .ogsfx.
This window covers the parts Maya has no answer for -- creating and assigning
the shader, preparing meshes for the outline, presets, linking the head basis,
and surfacing compile errors.
"""

import os

from maya import cmds

from ..core import env, plugin, presets, shader
from ..utils import mesh as mesh_utils
from ..utils.qt import QtCore, QtWidgets, delete_existing, maya_main_window

WINDOW_NAME = "GNTShaderWindow"
WINDOW_TITLE = "GNT Anime Shader"

QUICK_PARAMS = [
    ("OutlineWidth", "Outline Width", 0.0, 5.0),
    ("ShadowThreshold", "Shadow Threshold", 0.0, 1.0),
    ("ShadowSoftness", "Shadow Softness", 0.001, 0.5),
    ("RimIntensity", "Rim Intensity", 0.0, 5.0),
    ("SpecIntensity", "Specular Intensity", 0.0, 5.0),
]


class _Slider(QtWidgets.QWidget):
    """Float slider + spin box bound to one shader uniform."""

    def __init__(self, attr, label, minimum, maximum, parent=None):
        super(_Slider, self).__init__(parent)
        self.attr = attr
        self._minimum = minimum
        self._maximum = maximum
        self._node = None
        self._updating = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel(label)
        self.label.setMinimumWidth(120)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 1000)

        self.spin = QtWidgets.QDoubleSpinBox()
        self.spin.setDecimals(3)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep((maximum - minimum) / 100.0)
        self.spin.setMaximumWidth(80)

        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)

    def _to_value(self, tick):
        return self._minimum + (self._maximum - self._minimum) * (tick / 1000.0)

    def _to_tick(self, value):
        span = self._maximum - self._minimum
        if span <= 0:
            return 0
        return int(round((value - self._minimum) / span * 1000.0))

    def set_node(self, node):
        self._node = node
        self.setEnabled(False)
        if not node:
            return
        try:
            value = shader.get_param(node, self.attr)
        except (ValueError, RuntimeError):
            return

        self._updating = True
        self.spin.setValue(float(value))
        self.slider.setValue(self._to_tick(float(value)))
        self._updating = False
        self.setEnabled(True)

    def _push(self, value):
        if not self._node:
            return
        try:
            shader.set_param(self._node, self.attr, float(value))
        except (ValueError, RuntimeError):
            pass

    def _on_slider(self, tick):
        if self._updating:
            return
        value = self._to_value(tick)
        self._updating = True
        self.spin.setValue(value)
        self._updating = False
        self._push(value)

    def _on_spin(self, value):
        if self._updating:
            return
        self._updating = True
        self.slider.setValue(self._to_tick(value))
        self._updating = False
        self._push(value)


class GNTShaderWindow(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(GNTShaderWindow, self).__init__(parent or maya_main_window())
        self.setObjectName(WINDOW_NAME)
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFlags(QtCore.Qt.Window)
        self.resize(430, 720)

        self._sliders = []
        self._build()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(self._build_shader_group())
        root.addWidget(self._build_mesh_group())
        root.addWidget(self._build_quick_group())
        root.addWidget(self._build_preset_group())
        root.addWidget(self._build_face_group())
        root.addWidget(self._build_diagnostics_group(), 1)

    def _build_shader_group(self):
        box = QtWidgets.QGroupBox("Shader")
        layout = QtWidgets.QVBoxLayout(box)

        row = QtWidgets.QHBoxLayout()
        self.shader_combo = QtWidgets.QComboBox()
        self.shader_combo.currentIndexChanged.connect(self._on_shader_changed)
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.setMaximumWidth(70)
        refresh_btn.clicked.connect(self.refresh)
        row.addWidget(QtWidgets.QLabel("Node"))
        row.addWidget(self.shader_combo, 1)
        row.addWidget(refresh_btn)
        layout.addLayout(row)

        row = QtWidgets.QHBoxLayout()
        self.effect_combo = QtWidgets.QComboBox()
        self.effect_combo.setToolTip("Which .ogsfx a new shader node will use")
        row.addWidget(QtWidgets.QLabel("Effect"))
        row.addWidget(self.effect_combo, 1)
        layout.addLayout(row)

        row = QtWidgets.QHBoxLayout()
        self.technique_combo = QtWidgets.QComboBox()
        self.technique_combo.currentIndexChanged.connect(self._on_technique_changed)
        row.addWidget(QtWidgets.QLabel("Technique"))
        row.addWidget(self.technique_combo, 1)
        layout.addLayout(row)

        row = QtWidgets.QHBoxLayout()
        for label, slot in (
            ("Create", self.on_create),
            ("Assign to Selection", self.on_assign),
            ("Reload", self.on_reload),
            ("Attr Editor", self.on_show_attr_editor),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)

        return box

    def _build_mesh_group(self):
        box = QtWidgets.QGroupBox("Mesh Preparation")
        layout = QtWidgets.QVBoxLayout(box)

        note = QtWidgets.QLabel(
            "Bakes angle-weighted smooth normals into a colour set so the\n"
            "outline hull does not split at hard edges."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QtWidgets.QHBoxLayout()
        prep_btn = QtWidgets.QPushButton("Prepare Selected Meshes")
        prep_btn.clicked.connect(self.on_prepare_mesh)
        check_btn = QtWidgets.QPushButton("Check Colour Sets")
        check_btn.clicked.connect(self.on_check_color_sets)
        row.addWidget(prep_btn)
        row.addWidget(check_btn)
        layout.addLayout(row)

        return box

    def _build_quick_group(self):
        box = QtWidgets.QGroupBox("Quick Controls")
        layout = QtWidgets.QVBoxLayout(box)
        for attr, label, low, high in QUICK_PARAMS:
            widget = _Slider(attr, label, low, high)
            self._sliders.append(widget)
            layout.addWidget(widget)
        return box

    def _build_preset_group(self):
        box = QtWidgets.QGroupBox("Presets")
        layout = QtWidgets.QVBoxLayout(box)

        row = QtWidgets.QHBoxLayout()
        self.preset_combo = QtWidgets.QComboBox()
        row.addWidget(self.preset_combo, 1)
        apply_btn = QtWidgets.QPushButton("Apply")
        apply_btn.clicked.connect(self.on_apply_preset)
        save_btn = QtWidgets.QPushButton("Save As...")
        save_btn.clicked.connect(self.on_save_preset)
        row.addWidget(apply_btn)
        row.addWidget(save_btn)
        layout.addLayout(row)

        self.preset_textures = QtWidgets.QCheckBox("Also apply texture paths")
        layout.addWidget(self.preset_textures)

        return box

    def _build_face_group(self):
        box = QtWidgets.QGroupBox("Face Basis")
        layout = QtWidgets.QVBoxLayout(box)

        note = QtWidgets.QLabel(
            "Face rim and SDF shadow need the head's world axes. Select the\n"
            "head joint or control, then link it."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QtWidgets.QHBoxLayout()
        bake_btn = QtWidgets.QPushButton("Bake From Selection")
        bake_btn.clicked.connect(self.on_bake_head)
        link_btn = QtWidgets.QPushButton("Link (live)")
        link_btn.clicked.connect(self.on_link_head)
        row.addWidget(bake_btn)
        row.addWidget(link_btn)
        layout.addLayout(row)

        return box

    def _build_diagnostics_group(self):
        box = QtWidgets.QGroupBox("Diagnostics")
        layout = QtWidgets.QVBoxLayout(box)

        self.diagnostics = QtWidgets.QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        layout.addWidget(self.diagnostics)

        row = QtWidgets.QHBoxLayout()
        check_btn = QtWidgets.QPushButton("Run Validation")
        check_btn.clicked.connect(self.on_validate)
        row.addStretch(1)
        row.addWidget(check_btn)
        layout.addLayout(row)

        return box

    # -- state -------------------------------------------------------------
    def current_node(self):
        name = self.shader_combo.currentText()
        return name if name and cmds.objExists(name) else None

    def refresh(self):
        current = self.shader_combo.currentText()

        self.shader_combo.blockSignals(True)
        self.shader_combo.clear()
        self.shader_combo.addItems(shader.list_shaders())
        if current:
            index = self.shader_combo.findText(current)
            if index >= 0:
                self.shader_combo.setCurrentIndex(index)
        self.shader_combo.blockSignals(False)

        effect = self.effect_combo.currentText()
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        if os.path.isdir(env.SHADER_DIR):
            self.effect_combo.addItems(
                sorted(name for name in os.listdir(env.SHADER_DIR)
                       if name.endswith(".ogsfx")))
        if effect:
            index = self.effect_combo.findText(effect)
            if index >= 0:
                self.effect_combo.setCurrentIndex(index)
        self.effect_combo.blockSignals(False)

        self._sync_node()

    def _sync_node(self):
        node = self.current_node()

        self.technique_combo.blockSignals(True)
        self.technique_combo.clear()
        if node:
            self.technique_combo.addItems(shader.list_techniques(node))
            active = shader.technique(node)
            if active:
                index = self.technique_combo.findText(active)
                if index >= 0:
                    self.technique_combo.setCurrentIndex(index)
        self.technique_combo.blockSignals(False)

        # Only offer presets built for whatever effect this node is running --
        # applying an eye preset to the body shader skips every key silently.
        wanted = self.preset_combo.currentText()
        self.preset_combo.clear()
        if node:
            effect = os.path.basename(cmds.getAttr(node + ".shader") or "")
            names = presets.presets_for(effect) if effect else []
        else:
            names = sorted(presets.preset_files().keys())
        self.preset_combo.addItems(names)
        if wanted in names:
            self.preset_combo.setCurrentIndex(names.index(wanted))

        for widget in self._sliders:
            widget.set_node(node)

        self._show_diagnostics(node)

    def _show_diagnostics(self, node):
        if not node:
            self.diagnostics.setPlainText("No shader node selected.")
            return
        text = shader.diagnostics(node)
        self.diagnostics.setPlainText(text or "Effect compiled with no errors.")

    def _log(self, message):
        self.diagnostics.setPlainText(message)

    # -- slots -------------------------------------------------------------
    def _on_shader_changed(self, _index):
        self._sync_node()

    def _on_technique_changed(self, _index):
        node = self.current_node()
        name = self.technique_combo.currentText()
        if node and name:
            shader.set_technique(node, name)
            self._show_diagnostics(node)

    def on_create(self):
        effect = self.effect_combo.currentText() or "GNTAnime.ogsfx"
        path = os.path.join(env.SHADER_DIR, effect)
        name = os.path.splitext(effect)[0]

        try:
            node, _sg = shader.create(name=name, shader_file=path, technique=None)
        except (RuntimeError, IOError) as exc:
            self._log("Create failed: {0}".format(exc))
            return

        # The effect is only parsed once the viewport draws it, so the
        # technique list is empty until after a refresh.
        cmds.refresh(force=True)

        # Pick the technique the effect actually advertises. Which one is the
        # sensible default differs per effect, so ask rather than assume.
        available = shader.list_techniques(node)
        for preferred in ("AnimeOutline", "AnimeEye"):
            if preferred in available:
                shader.set_technique(node, preferred)
                break
        else:
            if available:
                shader.set_technique(node, available[0])
        self.refresh()
        index = self.shader_combo.findText(node)
        if index >= 0:
            self.shader_combo.setCurrentIndex(index)

    def on_assign(self):
        node = self.current_node()
        if not node:
            self._log("Select a shader node first.")
            return
        try:
            shader.assign(node)
        except ValueError as exc:
            self._log("Assign failed: {0}".format(exc))
            return
        self._log("Assigned {0} to selection.".format(node))

    def on_reload(self):
        node = self.current_node()
        if not node:
            return
        text = shader.reload_shader(node)
        self._sync_node()
        self._log(text or "Reloaded, no errors.")

    def on_show_attr_editor(self):
        node = self.current_node()
        if node:
            cmds.select(node, replace=True)
            import maya.mel as mel
            mel.eval("openAEWindow;")

    def on_prepare_mesh(self):
        try:
            done = mesh_utils.prepare_selection()
        except (ValueError, RuntimeError) as exc:
            self._log("Mesh prep failed: {0}".format(exc))
            return
        self._log("Prepared {0} mesh(es):\n{1}".format(len(done), "\n".join(done)))

    def on_check_color_sets(self):
        meshes = cmds.ls(selection=True, dag=True, type="mesh",
                         long=True, noIntermediate=True)
        if not meshes:
            self._log("Select at least one mesh.")
            return

        lines = []
        for item in meshes:
            colours = mesh_utils.color_set_order(item)
            uvs = mesh_utils.uv_set_order(item)
            lines.append(item.split("|")[-1])
            lines.append("  COLOR0    : {0}".format(
                colours[0] if colours else "(none)"))
            lines.append("  TEXCOORD1 : {0}".format(
                uvs[1] if len(uvs) > 1 else "(none)"))

            if not colours or colours[0] != env.PAINT_COLOR_SET:
                lines.append("  ! COLOR0 should be '{0}'".format(env.PAINT_COLOR_SET))
            if len(uvs) < 2 or uvs[1] != env.SMOOTH_NORMAL_UV_SET:
                lines.append("  ! UV set 2 should be '{0}' -- run Prepare".format(
                    env.SMOOTH_NORMAL_UV_SET))
        self._log("\n".join(lines))

    def on_apply_preset(self):
        node = self.current_node()
        name = self.preset_combo.currentText()
        if not node or not name:
            self._log("Need both a shader node and a preset.")
            return
        try:
            presets.apply(node, name,
                          skip_textures=not self.preset_textures.isChecked())
        except (ValueError, IOError) as exc:
            self._log("Preset failed: {0}".format(exc))
            return
        self._sync_node()
        self._log("Applied preset '{0}'.".format(name))

    def on_save_preset(self):
        node = self.current_node()
        if not node:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        path = presets.capture(node, name.strip(),
                               include_textures=self.preset_textures.isChecked())
        self.refresh()
        self._log("Saved: {0}".format(path))

    def _selected_transform(self):
        selection = cmds.ls(selection=True, type="transform", long=True)
        if not selection:
            selection = cmds.ls(selection=True, type="joint", long=True)
        return selection[0] if selection else None

    def on_bake_head(self):
        node = self.current_node()
        head = self._selected_transform()
        if not node or not head:
            self._log("Select the head transform, and pick a shader node.")
            return
        right, forward = shader.bake_head_basis(node, head)
        self._log("Head basis baked from {0}\n  right   {1}\n  forward {2}".format(
            head.split("|")[-1],
            [round(v, 3) for v in right],
            [round(v, 3) for v in forward]))

    def on_link_head(self):
        node = self.current_node()
        head = self._selected_transform()
        if not node or not head:
            self._log("Select the head transform, and pick a shader node.")
            return
        job = shader.live_head_basis(node, head)
        self._log("Live link created (scriptJob {0}).".format(job))

    def on_validate(self):
        lines = []

        ok = plugin.ensure_glsl_plugin()
        lines.append("glslShader plugin: {0}".format("loaded" if ok else "MISSING"))

        gl_ok, renderer = plugin.viewport_is_opengl_core()
        lines.append("viewport renderer: {0}{1}".format(
            renderer, "" if gl_ok else "   <- glslShader needs OpenGL Core Profile"))

        for problem in env.check_layout():
            lines.append("layout: {0}".format(problem))

        node = self.current_node()
        if node:
            lines.append("shader file: {0}".format(cmds.getAttr(node + ".shader")))
            lines.append("techniques: {0}".format(", ".join(shader.list_techniques(node))))
            lines.append("uniforms: {0}".format(len(shader.list_uniforms(node))))
            text = shader.diagnostics(node)
            lines.append("")
            lines.append(text or "compile: no errors")
        else:
            lines.append("no shader node selected")

        self._log("\n".join(lines))


def show():
    """Open the tool window."""
    delete_existing(WINDOW_NAME)
    window = GNTShaderWindow()
    window.show()
    return window
