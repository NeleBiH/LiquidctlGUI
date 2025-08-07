import subprocess
import types
import sys
from types import SimpleNamespace

import pytest
from unittest.mock import patch


def load_module():
    """Load LiquidctlGUI with stubbed PyQt6 and without running device checks."""
    # Stub PyQt6 modules
    pyqt6 = types.ModuleType("PyQt6")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtcore = types.ModuleType("PyQt6.QtCore")

    class DummyMeta(type):
        def __getattr__(cls, name):
            return Dummy

    class Dummy(metaclass=DummyMeta):
        def __init__(self, *a, **k):
            pass
        def __getattr__(self, name):
            return Dummy()
        def __call__(self, *a, **k):
            return Dummy()
        def setText(self, *a, **k):
            pass
        def show(self):
            pass
        def setIcon(self, *a, **k):
            pass
        def setContextMenu(self, *a, **k):
            pass
        def start(self, *a, **k):
            pass
        def timeout(self, *a, **k):
            return Dummy()
        def connect(self, *a, **k):
            pass
        def blockSignals(self, *a, **k):
            pass
        def setValue(self, *a, **k):
            pass

    widget_names = [
        "QApplication", "QMainWindow", "QWidget", "QVBoxLayout", "QHBoxLayout",
        "QPushButton", "QLabel", "QSlider", "QGroupBox", "QComboBox",
        "QSystemTrayIcon", "QMenu", "QMessageBox", "QDialog",
        "QFormLayout", "QDialogButtonBox", "QLineEdit", "QInputDialog",
        "QStyle", "QSpacerItem", "QSizePolicy", "QStatusBar"
    ]
    for name in widget_names:
        setattr(qtwidgets, name, Dummy)
    for name in ["QIcon", "QAction", "QFont"]:
        setattr(qtgui, name, Dummy)
    qtcore.Qt = SimpleNamespace(Orientation=SimpleNamespace(Horizontal=0))
    qtcore.QTimer = Dummy

    sys.modules.setdefault("PyQt6", pyqt6)
    sys.modules.setdefault("PyQt6.QtWidgets", qtwidgets)
    sys.modules.setdefault("PyQt6.QtGui", qtgui)
    sys.modules.setdefault("PyQt6.QtCore", qtcore)

    # Load module with device access check removed
    with open("LiquidctlGUI.py", "r") as f:
        lines = f.readlines()
    filtered = []
    skip = {23, 24, 25, 26, 162, 163}
    for idx, line in enumerate(lines, start=1):
        if idx in skip:
            continue
        filtered.append(line)
    module = types.ModuleType("LiquidctlGUI")
    exec("".join(filtered), module.__dict__)
    return module


# Load LiquidctlGUI module
LiquidctlModule = load_module()
LiquidCtlGUI = LiquidctlModule.LiquidCtlGUI


class DummyLabel:
    def setText(self, text):
        self.text = text


def make_dummy_gui():
    gui = SimpleNamespace(
        selected_device={"description": "test"},
        parse_json_status=lambda data: None,
        parse_text_status=lambda text: None,
        show_status_message=lambda msg: None,
        cpu_temp_label=DummyLabel(),
    )
    return gui


def test_update_status_falls_back_on_json_parse_error():
    gui = make_dummy_gui()
    sample_text = "Fan 1 Speed: 800\nPump Speed: 2500\nWater Temperature: 31.5"
    error_cp = subprocess.CompletedProcess(["liquidctl"], 0, stdout="{", stderr="")
    text_cp = subprocess.CompletedProcess(["liquidctl"], 0, stdout=sample_text, stderr="")
    gui.parse_text_status = lambda text: setattr(gui, "text_output", text)
    with patch.object(LiquidctlModule.subprocess, "run", side_effect=[error_cp, text_cp]):
        with patch.object(LiquidctlModule, "get_cpu_temp", return_value=None):
            LiquidCtlGUI.update_status(gui)
    assert getattr(gui, "text_output", None) == sample_text


def test_update_status_falls_back_on_json_command_error():
    gui = make_dummy_gui()
    sample_text = "Fan 1 Speed: 800\nPump Speed: 2500\nWater Temperature: 31.5"
    error_cp = subprocess.CompletedProcess(["liquidctl"], 1, stdout="", stderr="boom")
    text_cp = subprocess.CompletedProcess(["liquidctl"], 0, stdout=sample_text, stderr="")
    gui.parse_text_status = lambda text: setattr(gui, "text_output", text)
    with patch.object(LiquidctlModule.subprocess, "run", side_effect=[error_cp, text_cp]):
        with patch.object(LiquidctlModule, "get_cpu_temp", return_value=None):
            LiquidCtlGUI.update_status(gui)
    assert getattr(gui, "text_output", None) == sample_text


def test_parse_text_status_extracts_values():
    class Dummy:
        min_fan_rpm = 200
        max_fan_rpm = 2000
        min_pump_rpm = 1000
        max_pump_rpm = 2700

        def rpm_to_percent(self, rpm, is_pump=False):
            return LiquidCtlGUI.rpm_to_percent(self, rpm, is_pump)

        def update_ui_with_status(self, fan_speeds, pump_speed, water_temp):
            self.fan_speeds = fan_speeds
            self.pump_speed = pump_speed
            self.water_temp = water_temp

    dummy = Dummy()
    sample_text = (
        "Fan 1 Speed: 800\n"
        "Fan 2 Speed: 1000\n"
        "Pump Speed: 2500\n"
        "Water Temperature: 31.5"
    )
    LiquidCtlGUI.parse_text_status(dummy, sample_text)
    assert dummy.fan_speeds == {"Fan 1": (50, 800), "Fan 2": (60, 1000)}
    assert dummy.pump_speed == (90, 2500)
    assert dummy.water_temp == 31.5
