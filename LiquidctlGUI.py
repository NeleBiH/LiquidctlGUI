#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LiquidctlGUI for Linux – Liquidctl GUI (Qt/PyQt6)

What you get:
- Universal liquidctl front-end (no hard-coded devices).
- Auto-detect fan count + pump presence from `liquidctl status`.
- Manual fan & pump control with per-fan sliders and "All fans".
- Profiles (save/edit/delete) + tray menu quick switch.
- Safety (Emergency Boost) with hysteresis.
- Simple auto curves (optional) via small dialog.
- Inline rename of fans (double-click).
- Export/Import settings JSON.
- Debug log in a separate window.
- Adaptive layout for 1080p (compact mode), splitter + scroll area.
- Rolling graph with proper margins/grid so axes are readable.
- Clean GPU model string (NVIDIA/AMD/Intel).

Removed by request:
- “Enter raw liquidctl command” and “Run” button.
"""

import sys, os, time, logging, subprocess, shutil, threading, re, json
from functools import partial
from collections import deque

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QGroupBox, QComboBox,
    QSystemTrayIcon, QMenu, QMessageBox, QDialog,
    QFormLayout, QDialogButtonBox, QLineEdit, QInputDialog, QStyle, QStatusBar,
    QCheckBox, QSpinBox, QSizePolicy, QToolButton, QSpacerItem,
    QFileDialog, QPlainTextEdit, QSplitter, QScrollArea, QFrame
)
from PyQt6.QtGui import QIcon, QAction, QFont
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

# Try to import the liquidctl Python library.  If available we can talk
# directly to supported devices instead of spawning the external
# `liquidctl` command.  This improves performance and avoids the need
# for a separate CLI installation.  If the import fails we silently
# fall back to invoking the command line tool.
HAVE_LIQUIDCTL_LIB = False
try:
    import liquidctl  # type: ignore
    from liquidctl import find_liquidctl_devices  # type: ignore
    HAVE_LIQUIDCTL_LIB = True
except Exception:
    # Attempt to load a local copy of the library from a sibling
    # directory (e.g. when running from an extracted release).
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        here = os.getcwd()
    local_lib = os.path.join(here, "liquidctl-main")
    if os.path.isdir(os.path.join(local_lib, "liquidctl")):
        sys.path.insert(0, local_lib)
        try:
            import liquidctl  # type: ignore
            from liquidctl import find_liquidctl_devices  # type: ignore
            HAVE_LIQUIDCTL_LIB = True
        except Exception:
            HAVE_LIQUIDCTL_LIB = False

# ====== Adaptive UI defaults; shrinks on 1080p in _apply_compact_if_needed ======
FONT_PT   = 13
BTN_H     = 36
SLIDER_H  = 36
ROW_SP    = 6
MARGINS   = (8,6,8,6)

NAME_COL_W = 150
RPM_COL_W  = 140
PCT_COL_W  = 70

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".liquidctl_gui.json")
LEGACY_CONFIG_PATH = os.path.join(HOME, ".LIquidctl_settings.json")
AUTOSTART_DIR = os.path.join(HOME, ".config", "autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "liquidctl-gui.desktop")

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("liquidctl-gui")

def run_cmd(args, **kw):
    """Run a subprocess with sane defaults."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(args, **kw)

def compactify(layout):
    """Apply tighter margins/spacing to a layout."""
    layout.setSpacing(ROW_SP)
    layout.setContentsMargins(*MARGINS)

# ---------- Styles ----------
fan_slider_style = """
QSlider::groove:horizontal { border:1px solid #999; height:8px; background:#c4c4c4; margin:2px 0; }
QSlider::handle:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #b4b4b4, stop:1 #0080ff); border:1px solid #313755; width:26px; margin:-2px 0; border-radius:3px; }
QSlider::sub-page:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0099FF, stop:1 #0067B1); }
"""
pump_slider_style = """
QSlider::groove:horizontal { border:1px solid #999; height:8px; background:#c4c4c4; margin:2px 0; }
QSlider::handle:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #b4b4b4, stop:1 #8f8f8f); border:1px solid #5c5c5c; width:26px; margin:-2px 0; border-radius:3px; }
QSlider::sub-page:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #800080, stop:1 #BA55D3); }
"""

# ---------- Config I/O ----------
def load_json_config():
    """Load settings; keep backward compatibility with legacy path."""
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else (LEGACY_CONFIG_PATH if os.path.exists(LEGACY_CONFIG_PATH) else CONFIG_PATH)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("global", {})
                g = data["global"]
                g.setdefault("run_on_start", False)
                g.setdefault("last_profile", None)
                g.setdefault("link_fans", False)
                g.setdefault("language", "English")
                g.setdefault("show_graph", True)  # may get toggled off on first 1080p run

                data.setdefault("safety", {"enabled": False, "cpu_crit": 85, "water_crit": 45, "hysteresis": 5})
                data.setdefault("curves", {
                    "enabled": False,
                    "apply_pump": True,
                    "cpu": {"p1":[30,20], "p2":[60,60], "p3":[80,100]},
                    "water": {"p1":[30,20], "p2":[40,60], "p3":[50,100]}
                })
                data.setdefault("profiles", {})
                data.setdefault("last_sliders", {"fan_speeds": [], "pump_speed": 0})
                data.setdefault("fan_names", {})
                data.setdefault("debug_keep", 5000)
                return data
        except Exception:
            pass
    return {
        "global": {"run_on_start": False, "last_profile": None, "link_fans": False, "language": "English", "show_graph": True},
        "safety": {"enabled": False, "cpu_crit": 85, "water_crit": 45, "hysteresis": 5},
        "curves": {
            "enabled": False, "apply_pump": True,
            "cpu": {"p1":[30,20], "p2":[60,60], "p3":[80,100]},
            "water": {"p1":[30,20], "p2":[40,60], "p3":[50,100]}
        },
        "profiles": {},
        "last_sliders": {"fan_speeds": [], "pump_speed": 0},
        "fan_names": {},
        "debug_keep": 5000
    }

def save_json_config(conf):
    """Write settings to disk."""
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(conf, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save config: {e}")

# ---------- Temperature helpers ----------
def get_cpu_temp():
    """Try sensors -j; fallback to parsing sensors. Take the hottest sane CPU reading."""
    try:
        out = run_cmd(['sensors', '-j'], timeout=3)
        data = json.loads(out.stdout)
        best = None
        for chip, sections in data.items():
            chip_l = str(chip).lower()
            chip_is_cpu = any(x in chip_l for x in ('k10temp', 'coretemp', 'zenpower'))
            if not isinstance(sections, dict): continue
            for sec in sections.values():
                if not isinstance(sec, dict): continue
                for k, v in sec.items():
                    if not (isinstance(k, str) and k.startswith('temp') and k.endswith('_input')): continue
                    try: val = float(v)
                    except: continue
                    label = sec.get(k.replace('_input','_label'), '')
                    if chip_is_cpu or re.search(r'(tctl|tdie|package|core|cpu)', str(label).lower() or ''):
                        if 5.0 <= val <= 120.0:
                            best = val if best is None else max(best, val)
        if best is not None: return best
    except Exception:
        pass
    try:
        out = run_cmd(['sensors'], timeout=3)
        best=None
        for line in out.stdout.splitlines():
            ll=line.lower()
            if not re.search(r'(tctl|tdie|package|cpu|core)', ll): continue
            m=re.search(r'(\+?\d+(?:\.\d+)?)\s*°?c', line, re.I)
            if m:
                val=float(m.group(1))
                if 5.0 <= val <= 120.0: best = val if best is None else max(best, val)
        return best
    except Exception:
        return None

def get_gpu_temp():
    """Prefer nvidia-smi; fallback to sensors for AMD/Intel."""
    try:
        if shutil.which("nvidia-smi"):
            out = run_cmd(['nvidia-smi','--query-gpu=temperature.gpu','--format=csv,noheader'], timeout=3)
            for l in out.stdout.strip().splitlines():
                try:
                    t=float(l.strip())
                    if t>0: return t
                except: pass
    except Exception:
        pass
    try:
        out = run_cmd(['sensors'], timeout=3)
        for line in out.stdout.splitlines():
            m = re.search(r'(edge|junction):\s*\+?([\d.]+)', line, re.I)
            if m: return float(m.group(2))
            m2 = re.search(r'(gpu.*temp|temp\d+):\s*\+?([\d.]+)', line, re.I)
            if m2 and float(m2.group(2))<120: return float(m2.group(2))
    except Exception:
        pass
    return None

# ---------- Inline-rename label ----------
class RenamableLabel(QLabel):
    """Clickable label that requests inline editing on double-click."""
    requestEdit = pyqtSignal()
    def mouseDoubleClickEvent(self, ev):
        self.requestEdit.emit()
        super().mouseDoubleClickEvent(ev)

# ---------- Profile dialog ----------
class ProfileDialog(QDialog):
    """Small dialog to create/edit a profile (fan % per channel + pump %)."""
    def __init__(self, parent=None, existing_name="", fan_speeds=None, pump_speed=0, fan_count=6):
        super().__init__(parent)
        self.setWindowTitle("Create/Edit Profile")
        self.resize(360, 180 + (fan_count - 1) * 32)

        layout = QFormLayout()
        font = QFont(); font.setPointSize(FONT_PT)

        self.name_input = QLineEdit(); self.name_input.setFont(font)
        self.name_input.setText(existing_name)
        layout.addRow("Profile Name:", self.name_input)

        self.fan_speed_labels, self.fan_speed_sliders = [], []
        for i in range(fan_count):
            cur = fan_speeds[i] if fan_speeds and i < len(fan_speeds) else 0
            lbl = QLabel(f"Fan {i+1} Speed: {cur}%"); lbl.setFont(font)
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(0,100); s.setTickInterval(10); s.setSingleStep(10)
            s.setTickPosition(QSlider.TickPosition.TicksBelow); s.setMinimumHeight(SLIDER_H); s.setStyleSheet(fan_slider_style); s.setValue(cur)
            s.valueChanged.connect(lambda v, idx=i: self._upd_fan_label(idx))
            layout.addRow(lbl); layout.addWidget(s)
            self.fan_speed_labels.append(lbl); self.fan_speed_sliders.append(s)

        self.pump_speed_label = QLabel(f"Pump Speed: {pump_speed}%"); self.pump_speed_label.setFont(font)
        self.pump_speed_slider = QSlider(Qt.Orientation.Horizontal); self.pump_speed_slider.setRange(0,100)
        self.pump_speed_slider.setTickInterval(10); self.pump_speed_slider.setSingleStep(10)
        self.pump_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow); self.pump_speed_slider.setMinimumHeight(SLIDER_H)
        self.pump_speed_slider.setStyleSheet(pump_slider_style); self.pump_speed_slider.setValue(pump_speed)
        self.pump_speed_slider.valueChanged.connect(self._upd_pump_label)
        layout.addRow(self.pump_speed_label); layout.addWidget(self.pump_speed_slider)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.setMinimumHeight(BTN_H); bb.setFont(font); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        layout.addRow(bb); self.setLayout(layout)

    def _upd_fan_label(self, idx):
        val = round(self.fan_speed_sliders[idx].value()/10)*10
        self.fan_speed_sliders[idx].setValue(val)
        self.fan_speed_labels[idx].setText(f"Fan {idx+1} Speed: {val}%")

    def _upd_pump_label(self):
        val = round(self.pump_speed_slider.value()/10)*10
        self.pump_speed_slider.setValue(val)
        self.pump_speed_label.setText(f"Pump Speed: {val}%")

    def get_values(self):
        name = self.name_input.text().strip() or f"Pump {self.pump_speed_slider.value()} Fan {','.join(str(s.value()) for s in self.fan_speed_sliders)}"
        return {"name": name,
                "fan_speeds": [s.value() for s in self.fan_speed_sliders],
                "pump_speed": self.pump_speed_slider.value()}

# ---------- Curves dialog ----------
class CurvesDialog(QDialog):
    """Minimal curves editor (3 points for CPU and Water)."""
    def __init__(self, parent, curves):
        super().__init__(parent)
        self.setWindowTitle("Auto Control (Curves)")
        self.resize(600, 240)
        self.curves = curves
        v = QVBoxLayout(); compactify(v)

        top = QHBoxLayout(); compactify(top)
        self.enable = QCheckBox("Enable"); self.enable.setChecked(curves.get("enabled", False))
        self.apply_pump = QCheckBox("Apply to pump"); self.apply_pump.setChecked(curves.get("apply_pump", True))
        top.addWidget(self.enable); top.addWidget(self.apply_pump)
        v.addLayout(top)

        def make_row(title, cur):
            row = QHBoxLayout(); compactify(row)
            row.addWidget(QLabel(title))
            sp=[]
            for key in ["p1","p2","p3"]:
                t,p = cur.get(key,[30,20])
                ts = QSpinBox(); ts.setRange(0,110); ts.setSuffix(" °C"); ts.setValue(int(t))
                ps = QSpinBox(); ps.setRange(0,100); ps.setSuffix(" %"); ps.setValue(int(p))
                row.addWidget(ts); row.addWidget(ps); sp.append((ts,ps))
            return row, sp

        self.cpu_row, self.cpu_spins = make_row("CPU:  T1/P1  T2/P2  T3/P3", curves.get("cpu",{}))
        self.wat_row, self.wat_spins = make_row("Water: T1/P1 T2/P2 T3/P3", curves.get("water",{}))
        v.addLayout(self.cpu_row); v.addLayout(self.wat_row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.setLayout(v)

    def get_curves(self):
        def read(spins):
            return {"p1":[spins[0][0].value(), spins[0][1].value()],
                    "p2":[spins[1][0].value(), spins[1][1].value()],
                    "p3":[spins[2][0].value(), spins[2][1].value()]}
        return {
            "enabled": self.enable.isChecked(),
            "apply_pump": self.apply_pump.isChecked(),
            "cpu": read(self.cpu_spins),
            "water": read(self.wat_spins),
        }

# ---------- Debug dialog ----------
class DebugDialog(QDialog):
    """Small separate window for live debug log."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Debug Log")
        self.resize(900, 480)
        v = QVBoxLayout(); compactify(v)
        self.out = QPlainTextEdit(); self.out.setReadOnly(True)
        v.addWidget(self.out)
        h = QHBoxLayout(); compactify(h)
        btn_copy = QPushButton("Copy"); btn_copy.clicked.connect(self.copy_all)
        btn_clear = QPushButton("Clear"); btn_clear.clicked.connect(self.clear_all)
        btn_close = QPushButton("Close"); btn_close.clicked.connect(self.close)
        for b in (btn_copy, btn_clear, btn_close): b.setMinimumHeight(BTN_H)
        h.addWidget(btn_copy); h.addWidget(btn_clear); h.addStretch(1); h.addWidget(btn_close)
        v.addLayout(h); self.setLayout(v)
    def set_lines(self, lines): self.out.setPlainText("\n".join(lines))
    def append_line(self, line): self.out.appendPlainText(line)
    def copy_all(self): QApplication.clipboard().setText(self.out.toPlainText())
    def clear_all(self):
        self.out.clear()
        if isinstance(self.parent(), LiquidCtlGUI):
            self.parent().debug_lines.clear()

# ---------- Optional rolling graphs ----------
HAVE_MPL = False
try:
    import matplotlib
    matplotlib.use("agg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False

# ---------- Main GUI ----------
class LiquidCtlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self._apply_compact_if_needed()
        self.setWindowTitle("LiquidctlGUI for Linux")
        self.setGeometry(80, 80, 1100, 720)

        # State
        self.conf = load_json_config()
        if getattr(self, "compact", False) and "show_graph" not in self.conf["global"]:
            self.conf["global"]["show_graph"] = False

        self.safety = self.conf.get("safety")
        self.curves = self.conf.get("curves")
        self.devices = []
        self.selected_device = None
        self.fan_count = 6
        self.have_pump = False
        self.pump_supported = False

        self.user_set_fan_speeds = {}      # {index: (pct, timestamp)}
        self.user_set_pump_speed = None     # (pct, timestamp)
        self.min_fan_rpm, self.max_fan_rpm = 200, 2000
        self.min_pump_rpm, self.max_pump_rpm = 1000, 2700
        self._last_water_temp = None

        # Determine if we should use the Python library or fall back to the CLI.
        # When HAVE_LIQUIDCTL_LIB is true we can talk to devices directly via
        # the liquidctl API; otherwise we spawn the `liquidctl` command as
        # before.  Storing this in an instance variable allows other methods
        # to conditionally branch without repeatedly checking the global.
        self.use_cli = not HAVE_LIQUIDCTL_LIB

        # Rename state
        self.fan_name_edits = {}
        self.fan_name_labels = []

        # Debug
        self.debug_lines = []
        self.debug_dlg = None

        # Safety boost
        self._boost_active = False
        self._preboost = None

        # Graph history
        self._hist_t = deque(maxlen=180)
        self._hist_cpu = deque(maxlen=180)
        self._hist_water = deque(maxlen=180)
        self._t0 = None  # time origin for x-axis in seconds

        # Timers
        self.status_timer = QTimer(); self.status_timer.timeout.connect(self.update_status); self.status_timer.start(2500)
        self.fan_apply_timer = QTimer(); self.fan_apply_timer.setSingleShot(True); self.fan_apply_timer.timeout.connect(self.apply_all_fan_speeds)
        self.pump_apply_timer = QTimer(); self.pump_apply_timer.setSingleShot(True); self.pump_apply_timer.timeout.connect(self.apply_pump_speed)

        # Tray + statusbar
        self._statusbar = QStatusBar(self); self.setStatusBar(self._statusbar)
        icon_paths = [os.path.join(os.path.dirname(__file__), "icon.png"),
                      "/usr/share/icons/liquidctl-gui.png", "/usr/local/share/icons/liquidctl-gui.png"]
        app_icon = None
        for p in icon_paths:
            if os.path.exists(p): app_icon = QIcon(p); break
        if app_icon is None: app_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon = QSystemTrayIcon(self); self.tray_icon.setIcon(app_icon)
        self.tray_menu = QMenu(); self.tray_icon.setContextMenu(self.tray_menu); self.tray_icon.show()

        self.init_ui()
        self.safe_refresh_devices(select_first=True)
        self.update_status()
        self.rebuild_tray_menu(selected_profile=self.conf["global"].get("last_profile"))

    # ---------- Adaptive sizing ----------
    def _apply_compact_if_needed(self):
        try:
            scr_h = QApplication.primaryScreen().availableGeometry().height()
        except Exception:
            scr_h = 1080
        self.compact = scr_h <= 1080
        if self.compact:
            global FONT_PT, BTN_H, SLIDER_H, ROW_SP, MARGINS, NAME_COL_W, RPM_COL_W, PCT_COL_W
            FONT_PT = 11
            BTN_H = 28
            SLIDER_H = 26
            ROW_SP = 4
            MARGINS = (6,4,6,4)
            NAME_COL_W = 120
            RPM_COL_W = 110
            PCT_COL_W = 50

    # ---------- Helpers ----------
    def show_status_message(self, msg, ms=2500):
        try: self._statusbar.showMessage(msg, ms)
        except: pass

    def _append_debug(self, line):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {line}"
        self.debug_lines.append(line)
        keep = int(self.conf.get("debug_keep", 5000))
        if keep and len(self.debug_lines) > keep:
            self.debug_lines = self.debug_lines[-keep:]
        if self.debug_dlg and self.debug_dlg.isVisible():
            self.debug_dlg.append_line(line)

    def run_logged(self, args, **kw):
        self._append_debug(f"$ {' '.join(args)}")
        r = run_cmd(args, **kw)
        if r.returncode != 0:
            self._append_debug(f"ERR {r.returncode}: {(r.stderr or '').strip()}")
        else:
            if r.stdout:
                s = r.stdout.strip()
                self._append_debug(s[:500] + ("..." if len(s) > 500 else ""))
        return r

    def _info_button(self, tip, title="Info"):
        btn = QToolButton(); btn.setText("?"); btn.setFixedWidth(24)
        btn.setToolTip(tip.replace("\n\n","\n"))
        btn.clicked.connect(lambda: QMessageBox.information(self, title, tip))
        return btn

    def _mk_btn(self, text, cb):
        b = QPushButton(text); b.setMinimumHeight(BTN_H); b.clicked.connect(cb); return b

    def _vsep(self):
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine); sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep

    # ---------- UI ----------
    def init_ui(self):
        container = QWidget()
        root_v = QVBoxLayout(); compactify(root_v)

        top_panel = QWidget(); top_v = QVBoxLayout(); compactify(top_v)
        bottom_panel = QWidget(); bottom_v = QVBoxLayout(); compactify(bottom_v)

        font = QFont(); font.setPointSize(FONT_PT)

        # Device row
        dev_group = QGroupBox("Device"); dev_layout = QHBoxLayout(); compactify(dev_layout)
        self.device_combo = QComboBox(); self.device_combo.setFont(font); self.device_combo.setMinimumHeight(BTN_H)
        self.device_combo.currentIndexChanged.connect(self.select_device)
        dev_layout.addWidget(QLabel("Select Device:")); dev_layout.addWidget(self.device_combo)
        btn_refresh = self._mk_btn("Refresh", lambda: self.safe_refresh_devices(select_first=False))
        btn_refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        dev_layout.addWidget(btn_refresh)
        btn_perm = self._mk_btn("Fix permissions", self.install_udev_rule_for_selected); dev_layout.addWidget(btn_perm)
        dev_layout.addWidget(self._info_button(
            "Fix permissions: adds an udev rule so this device works without sudo.\n"
            "• Grants user access to USB/HIDRAW via TAG+=\"uaccess\".\n"
            "• After installing: replug device or relogin.", "Fix permissions – help"))
        dev_group.setLayout(dev_layout); top_v.addWidget(dev_group)

        # Profiles row
        prof_group = QGroupBox("Profiles"); prof_layout = QHBoxLayout(); compactify(prof_layout)
        self.profile_combo = QComboBox(); self.profile_combo.setFont(font); self.profile_combo.setMinimumHeight(BTN_H)
        self.profile_combo.currentIndexChanged.connect(self.profile_combo_selected)
        btn_edit = self._mk_btn("Edit Profile", self.edit_profile)
        btn_del  = self._mk_btn("Delete Profile", self.delete_profile)
        btn_save = self._mk_btn("Save Current Profile", self.save_current_profile)
        for w in (QLabel("Profiles:"), self.profile_combo, btn_edit, btn_del, btn_save):
            prof_layout.addWidget(w)
        prof_group.setLayout(prof_layout); top_v.addWidget(prof_group)
        self.update_profile_combo()

        # Quick controls
        quick_group = QGroupBox("Quick Controls"); quick_layout = QHBoxLayout(); compactify(quick_layout)
        self.allfans_label = QLabel("All Fans"); self.allfans_label.setFont(font); self.allfans_label.setFixedWidth(NAME_COL_W)
        self.allfans_pct = QLabel("0 %"); self.allfans_pct.setFont(font); self.allfans_pct.setFixedWidth(PCT_COL_W)
        self.allfans_slider = QSlider(Qt.Orientation.Horizontal); self.allfans_slider.setRange(0,100)
        self.allfans_slider.setTickInterval(10); self.allfans_slider.setSingleStep(10)
        self.allfans_slider.setTickPosition(QSlider.TickPosition.TicksBelow); self.allfans_slider.setMinimumHeight(SLIDER_H)
        self.allfans_slider.setStyleSheet(fan_slider_style)
        self.allfans_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.allfans_slider.valueChanged.connect(self.adjust_all_fans)
        self.link_chk = QCheckBox("Link fans")
        self.link_chk.setChecked(bool(self.conf["global"].get("link_fans", False)))
        self.link_chk.toggled.connect(lambda ch: (self.conf["global"].__setitem__("link_fans", bool(ch)), save_json_config(self.conf)))
        quick_layout.addWidget(self.allfans_label); quick_layout.addWidget(QLabel(""))
        quick_layout.addWidget(self.allfans_pct); quick_layout.addWidget(self.allfans_slider)
        quick_layout.addWidget(self.link_chk)
        quick_layout.addWidget(self._info_button("All Fans: set all fan sliders.\nLink fans: moving one moves all.", "Quick – help"))
        quick_group.setLayout(quick_layout); top_v.addWidget(quick_group)

        # Safety
        safety_group = QGroupBox("Safety (Emergency Boost)"); s_layout = QHBoxLayout(); compactify(s_layout)
        self.safety_enable = QCheckBox("Enable"); self.safety_enable.setChecked(self.safety.get("enabled", False))
        self.safety_enable.toggled.connect(self._save_safety)
        self.cpu_crit = QSpinBox(); self.cpu_crit.setRange(40, 110); self.cpu_crit.setSuffix(" °C"); self.cpu_crit.setValue(int(self.safety.get("cpu_crit",85)))
        self.cpu_crit.valueChanged.connect(self._save_safety)
        self.water_crit = QSpinBox(); self.water_crit.setRange(20, 90); self.water_crit.setSuffix(" °C"); self.water_crit.setValue(int(self.safety.get("water_crit",45)))
        self.water_crit.valueChanged.connect(self._save_safety)
        self.hyst = QSpinBox(); self.hyst.setRange(0, 20); self.hyst.setSuffix(" °C"); self.hyst.setValue(int(self.safety.get("hysteresis",5)))
        self.hyst.valueChanged.connect(self._save_safety)
        for w in (self.safety_enable, QLabel("CPU ≥"), self.cpu_crit, QLabel("Water ≥"), self.water_crit, QLabel("Hysteresis"), self.hyst):
            s_layout.addWidget(w)
        s_layout.addWidget(self._info_button("Boost 100% when above thresholds. Turns off below (threshold − hysteresis).", "Safety – help"))
        safety_group.setLayout(s_layout); top_v.addWidget(safety_group)

        # Fan & Pump Control
        self.control_group = QGroupBox("Fan & Pump Control"); self.control_layout = QVBoxLayout(); compactify(self.control_layout)
        header = QHBoxLayout(); compactify(header)
        Hname = QLabel("Name"); Hname.setFont(font); Hname.setFixedWidth(NAME_COL_W)
        Hrpm  = QLabel("RPM");  Hrpm.setFont(font);  Hrpm.setFixedWidth(RPM_COL_W)
        Hpct  = QLabel("%");    Hpct.setFont(font);   Hpct.setFixedWidth(PCT_COL_W)
        Hsl   = QLabel("Slider"); Hsl.setFont(font)
        for w in (Hname, Hrpm, Hpct, Hsl): header.addWidget(w)
        self.control_layout.addLayout(header)

        # Pump row (visible only if pump + supported)
        self.pump_row = QHBoxLayout(); compactify(self.pump_row)
        self.pump_name_inline = QLabel("Pump"); self.pump_name_inline.setFont(font); self.pump_name_inline.setFixedWidth(NAME_COL_W)
        self.pump_rpm_inline = QLabel("N/A");    self.pump_rpm_inline.setFont(font);  self.pump_rpm_inline.setFixedWidth(RPM_COL_W)
        self.pump_percent_inline = QLabel("0 %");self.pump_percent_inline.setFont(font); self.pump_percent_inline.setFixedWidth(PCT_COL_W)
        self.pump_slider = QSlider(Qt.Orientation.Horizontal); self.pump_slider.setRange(0,100)
        self.pump_slider.setTickInterval(10); self.pump_slider.setSingleStep(10)
        self.pump_slider.setTickPosition(QSlider.TickPosition.TicksBelow); self.pump_slider.setMinimumHeight(SLIDER_H)
        self.pump_slider.setStyleSheet(pump_slider_style)
        self.pump_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pump_slider.valueChanged.connect(self.adjust_pump_speed)
        for w in (self.pump_name_inline, self.pump_rpm_inline, self.pump_percent_inline, self.pump_slider):
            self.pump_row.addWidget(w)
        self.control_layout.addLayout(self.pump_row)

        # Fan rows
        self.fan_rows_layouts=[]; self.fan_rpm_inline_labels=[]; self.fan_percent_inline_labels=[]; self.fan_sliders=[]; self.fan_name_labels=[]
        self.fan_name_edits={}
        self.add_fan_controls(6, font)
        self.control_group.setLayout(self.control_layout); top_v.addWidget(self.control_group)

        # ---- bottom panel ----
        status_layout = QHBoxLayout(); compactify(status_layout)
        sys_group = QGroupBox("System Info"); sys_v = QVBoxLayout(); compactify(sys_v)
        self.sys_os_label   = QLabel("OS: N/A")
        self.sys_cpu_label  = QLabel("CPU: N/A")
        self.sys_gpu_label  = QLabel("GPU: N/A")
        self.sys_ram_label  = QLabel("RAM: N/A")
        self.sys_disk_label = QLabel("Disk: N/A")
        for L in (self.sys_os_label,self.sys_cpu_label,self.sys_gpu_label,self.sys_ram_label,self.sys_disk_label):
            L.setWordWrap(True); L.setFont(font); sys_v.addWidget(L)
        sys_group.setLayout(sys_v); status_layout.addWidget(sys_group, 1)

        temp_group = QGroupBox("Temperature"); temp_v = QVBoxLayout(); compactify(temp_v)
        top_t = QHBoxLayout(); compactify(top_t)
        self.temp_label = QLabel("Water Temperature: N/A"); self.temp_label.setFont(font)
        self.cpu_temp_label = QLabel("CPU Temperature: N/A"); self.cpu_temp_label.setFont(font)
        self.gpu_temp_label = QLabel("GPU Temperature: N/A"); self.gpu_temp_label.setFont(font)
        top_t.addWidget(self.temp_label); top_t.addWidget(self._vsep())
        top_t.addWidget(self.cpu_temp_label); top_t.addWidget(self._vsep())
        top_t.addWidget(self.gpu_temp_label)
        top_t.addStretch(1)
        self.show_graph_chk = QCheckBox("Show graph")
        self.show_graph_chk.setChecked(bool(self.conf["global"].get("show_graph", not self.compact)))
        self.show_graph_chk.toggled.connect(self._toggle_graph)
        btn_curves = self._mk_btn("Curves…", self.open_curves_dialog)
        top_t.addWidget(self.show_graph_chk); top_t.addWidget(btn_curves)
        temp_v.addLayout(top_t)

        self.canvas = None
        if HAVE_MPL:
            self.fig = Figure(figsize=(5, 1.8 if self.compact else 2.1), dpi=100)
            self.ax = self.fig.add_subplot(111)
            # Better margins so tick labels are visible
            self.fig.subplots_adjust(left=0.09, right=0.98, top=0.93, bottom=0.28)
            self.ax.set_xlabel("seconds"); self.ax.set_ylabel("°C")
            self.ax.grid(True, which='both', axis='both', linestyle='--', alpha=0.3)
            self._graph_cpu_line, = self.ax.plot([], [], label="CPU")
            self._graph_water_line, = self.ax.plot([], [], label="Water")
            self.ax.legend(loc="upper left")
            self.canvas = FigureCanvas(self.fig)
            temp_v.addWidget(self.canvas)
            self.canvas.setVisible(self.show_graph_chk.isChecked())
        else:
            temp_v.addWidget(QLabel("Install matplotlib for rolling graphs."))
        temp_group.setLayout(temp_v); status_layout.addWidget(temp_group, 2)
        bottom_v.addLayout(status_layout)

        # Tools row (no raw command)
        tools_row = QHBoxLayout(); compactify(tools_row)
        btn_debug   = self._mk_btn("Debug…", self.open_debug_dialog)
        btn_exp_settings = self._mk_btn("Export Settings", self.export_settings)
        btn_imp_settings = self._mk_btn("Import Settings", self.import_settings)
        tools_row.addStretch(1); tools_row.addWidget(btn_debug); tools_row.addWidget(btn_exp_settings); tools_row.addWidget(btn_imp_settings)
        bottom_v.addLayout(tools_row)

        # Language
        bottom = QHBoxLayout(); compactify(bottom)
        bottom.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        bottom.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox(); self.lang_combo.addItems(["English", "Bosanski/Hrvatski/Srpski"])
        self.lang_combo.setCurrentText(self.conf["global"].get("language","English"))
        self.lang_combo.currentTextChanged.connect(lambda s: (self.conf["global"].__setitem__("language", s), save_json_config(self.conf)))
        bottom.addWidget(self.lang_combo)
        bottom.addWidget(self._info_button("Language: placeholder. Real translations later.", "Language – info"))
        bottom_panel.setLayout(bottom_v)

        # Splitter + scroll wrapper
        splitter = QSplitter(Qt.Orientation.Vertical)
        top_panel.setLayout(top_v); splitter.addWidget(top_panel)
        splitter.addWidget(bottom_panel)
        splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 2)

        root_v.addWidget(splitter)
        container.setLayout(root_v)

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)

    def _toggle_graph(self, on):
        self.conf["global"]["show_graph"] = bool(on)
        save_json_config(self.conf)
        if self.canvas:
            self.canvas.setVisible(bool(on))

    # ---------- Save handlers ----------
    def _save_safety(self, *_):
        self.safety = {
            "enabled": bool(self.safety_enable.isChecked()),
            "cpu_crit": int(self.cpu_crit.value()),
            "water_crit": int(self.water_crit.value()),
            "hysteresis": int(self.hyst.value())
        }
        self.conf["safety"] = self.safety
        save_json_config(self.conf)

    # ---------- Curves dialog open ----------
    def open_curves_dialog(self):
        dlg = CurvesDialog(self, self.curves)
        if dlg.exec():
            self.curves = dlg.get_curves()
            self.conf["curves"] = self.curves
            save_json_config(self.conf)

    # ---------- Export/Import settings ----------
    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export settings",
                                              os.path.join(HOME, "liquidctl-settings.json"),
                                              "JSON (*.json)")
        if not path: return
        try:
            with open(path, "w") as f: json.dump(self.conf, f, indent=2)
            self.show_status_message(f"Settings exported to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", HOME, "JSON (*.json)")
        if not path: return
        try:
            with open(path, "r") as f: data = json.load(f)
            if not isinstance(data, dict): raise ValueError("Invalid settings file")
            self.conf = data
            self.safety = self.conf.get("safety", self.safety)
            self.curves = self.conf.get("curves", self.curves)
            save_json_config(self.conf)
            self.update_profile_combo()
            font = QFont(); font.setPointSize(FONT_PT)
            self.add_fan_controls(self.fan_count, font)
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentText(self.conf.get("global", {}).get("language", "English"))
            self.lang_combo.blockSignals(False)
            self.show_status_message(f"Settings imported from {path}")
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))

    # ---------- Profiles ----------
    def update_profile_combo(self):
        self.profile_combo.blockSignals(True); self.profile_combo.clear()
        for pname,p in self.conf.get("profiles", {}).items():
            fs=p.get("fan_speeds",[]); ps=p.get("pump_speed",0)
            self.profile_combo.addItem(f"{pname} (Pump {ps} Fan {','.join(map(str,fs))})", pname)
        last=self.conf["global"].get("last_profile")
        if last is not None:
            idx=self.profile_combo.findData(last)
            if idx>=0: self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    def profile_combo_selected(self, idx):
        pname = self.profile_combo.itemData(idx)
        if pname: self.apply_profile_and_update_ui(pname, source="dropdown")

    def edit_profile(self):
        pname=self.profile_combo.currentData()
        if not pname or pname not in self.conf.get("profiles",{}):
            QMessageBox.warning(self,"Warning","Select a profile to edit."); return
        p=self.conf["profiles"][pname]
        d=ProfileDialog(self, pname, fan_speeds=p.get("fan_speeds",[0]*self.fan_count), pump_speed=p.get("pump_speed",0), fan_count=self.fan_count)
        if d.exec():
            v=d.get_values(); self.conf["profiles"][v["name"]]={"fan_speeds":v["fan_speeds"],"pump_speed":v["pump_speed"]}
            if v["name"]!=pname: del self.conf["profiles"][pname]
            save_json_config(self.conf); self.update_profile_combo(); self.rebuild_tray_menu(selected_profile=v["name"])
            if pname==self.conf["global"].get("last_profile"): self.apply_profile_and_update_ui(v["name"])

    def delete_profile(self):
        pname=self.profile_combo.currentData()
        if not pname or pname not in self.conf.get("profiles", {}):
            QMessageBox.warning(self,"Warning","Select a profile to delete."); return
        if QMessageBox.question(self, "Confirmation", "Delete profile?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            if pname==self.conf["global"].get("last_profile"): self.conf["global"]["last_profile"]=None
            del self.conf["profiles"][pname]; self._update_profiles_ui(selected_profile=self.conf["global"].get("last_profile"))

    def save_current_profile(self):
        fan_speeds=[s.value() for s in self.fan_sliders]; pump_speed=self.pump_slider.value()
        default=f"Custom_P{pump_speed}_F{','.join(map(str,fan_speeds))}"
        name,ok=QInputDialog.getText(self,"Save Current Profile","Profile name:",QLineEdit.EchoMode.Normal,default)
        if not ok: return
        name=(name or default).strip()
        if not name: QMessageBox.warning(self,"Invalid name","Profile name cannot be empty."); return
        if name in self.conf.setdefault("profiles", {}): QMessageBox.warning(self,"Exists","Profile with that name already exists."); return
        self.conf["profiles"][name]={"fan_speeds":fan_speeds,"pump_speed":pump_speed}; self.conf["global"]["last_profile"]=name
        save_json_config(self.conf); self._update_profiles_ui(selected_profile=name); self.show_status_message(f"Saved profile '{name}'", 3000)

    def _update_profiles_ui(self, selected_profile=None):
        save_json_config(self.conf); self.update_profile_combo(); self.rebuild_tray_menu(selected_profile=selected_profile)

    def apply_profile_and_update_ui(self, pname, source="dropdown"):
        profs=self.conf.get("profiles",{});
        if pname not in profs: return
        vals=profs[pname]
        fan_speeds=vals.get("fan_speeds",[0]*self.fan_count); pump_speed=vals.get("pump_speed",0)
        self.block_slider_signals(True)
        for i in range(min(self.fan_count, len(fan_speeds))):
            self.fan_sliders[i].setValue(fan_speeds[i]); self.user_set_fan_speeds[i+1]=(fan_speeds[i], time.time())
            if i<len(self.fan_percent_inline_labels): self.fan_percent_inline_labels[i].setText(f"{fan_speeds[i]} %")
            if i<len(self.fan_rpm_inline_labels): self.fan_rpm_inline_labels[i].setText(f"{self.percent_to_rpm(fan_speeds[i])} RPM")
        self.pump_slider.setValue(pump_speed); self.pump_percent_inline.setText(f"{pump_speed} %")
        self.pump_rpm_inline.setText(f"{self.percent_to_rpm(pump_speed, True)} RPM")
        self.user_set_pump_speed=(pump_speed, time.time())
        if source=="tray":
            idx=self.profile_combo.findData(pname)
            if idx>=0: self.profile_combo.setCurrentIndex(idx)
        self.conf["global"]["last_profile"]=pname
        self.save_sliders_to_conf()
        self.block_slider_signals(False)
        self.fan_apply_timer.start(800);
        if self.have_pump and self.pump_supported: self.pump_apply_timer.start(800)
        self.update_profile_combo(); self.rebuild_tray_menu(selected_profile=pname)
        self._sync_all_fans_slider()

    # ---------- Device / permissions ----------
    def safe_refresh_devices(self, select_first=False):
        prev_desc = self.selected_device["description"] if self.selected_device else None
        # When using the Python library we query connected devices directly; otherwise we
        # fall back to invoking the liquidctl CLI.  The resulting list of
        # dictionaries always contains at least a human readable description and,
        # for the library case, a reference to the driver instance under the
        # ``device`` key.
        if not self.use_cli:
            try:
                devices = list(find_liquidctl_devices())
            except Exception as e:
                self.show_status_message(f"Refresh failed: {e}")
                return
            if not devices:
                self.show_status_message("No devices found."); return
            new_list = []
            for dev in devices:
                try:
                    desc = getattr(dev, 'description', 'Unknown Device')
                except Exception:
                    desc = 'Unknown Device'
                entry = {
                    'description': desc,
                    'vendor_id': getattr(dev, 'vendor_id', None),
                    'product_id': getattr(dev, 'product_id', None),
                    'device': dev
                }
                new_list.append(entry)
        else:
            try:
                r = self.run_logged(["liquidctl","list","--json"], timeout=6)
                new_list = json.loads(r.stdout) if r.stdout else []
            except Exception as e:
                self.show_status_message(f"Refresh failed: {e}")
                return
            if not new_list:
                self.show_status_message("No devices found."); return
        # Populate the combo box and preserve the previously selected device if possible
        self.devices = new_list
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        keep_idx = 0
        for i, dev in enumerate(self.devices):
            desc = dev.get("description","Unknown Device")
            self.device_combo.addItem(desc, dev)
            if prev_desc and desc == prev_desc:
                keep_idx = i
        self.device_combo.blockSignals(False)
        if select_first:
            self.select_device(0)
        else:
            self.device_combo.setCurrentIndex(keep_idx)
            self.select_device(keep_idx)

    def select_device(self, index):
        if 0<=index<len(self.devices):
            self.selected_device = self.device_combo.itemData(index)
            self.detect_features_from_status()
            self.initialize_device()
            self.update_status()

    def initialize_device(self):
        if not self.selected_device:
            return
        # For library-backed devices we initialize via the API; otherwise we
        # fall back to the CLI.  Always probe for pump capability afterwards.
        if self.use_cli:
            try:
                self.run_logged(["liquidctl","-m", self.selected_device["description"], "initialize"], timeout=8)
            except Exception as e:
                self.show_status_message(f"Failed to initialize device: {e}")
        else:
            dev = self.selected_device.get("device")
            if dev is None:
                return
            try:
                # Connect and initialize the device.  The context manager
                # ensures disconnect() is called even if initialization
                # fails.
                with dev.connect():
                    # Some drivers return additional status information; we
                    # intentionally ignore the return value here.
                    dev.initialize()
            except Exception as e:
                self.show_status_message(f"Failed to initialize device: {e}")
        self.probe_pump_capability()

    def install_udev_rule_for_selected(self):
        if not self.selected_device:
            QMessageBox.information(self,"No device","Select a device first."); return
        vid = int(self.selected_device.get("vendor_id",0)); pid = int(self.selected_device.get("product_id",0))
        vidhex=f"{vid:04x}"; pidhex=f"{pid:04x}"
        rule = (
            f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vidhex}", ATTR{{idProduct}}=="{pidhex}", TAG+="uaccess"\n'
            f'SUBSYSTEM=="hidraw", ATTRS{{idVendor}}=="{vidhex}", ATTRS{{idProduct}}=="{pidhex}", TAG+="uaccess"'
        )
        cmd = f'pkexec bash -lc \'printf "%s\\n" "{rule}" > /etc/udev/rules.d/99-liquidctl.rules; udevadm control --reload-rules; udevadm trigger\''
        try:
            subprocess.run(cmd, shell=True, check=True)
            QMessageBox.information(self, "Done", "Udev rules installed. Replug device or relogin.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to install udev rules:\n{e}")

    # ---------- Status / parsing ----------
    def _iter_status_entries(self, status_data):
        if not isinstance(status_data, list): return
        for block in status_data:
            if isinstance(block, dict):
                for it in block.get("status", []):
                    yield it

    def detect_features_from_status(self):
        # Reset feature flags before probing.
        self.fan_count = 0
        self.have_pump = False
        if not self.selected_device:
            return
        if self.use_cli:
            try:
                res = self.run_logged(["liquidctl","-m", self.selected_device["description"], "status","--json"], timeout=8)
                status_data = json.loads(res.stdout) if res.stdout else []
                max_fan_idx = 0
                for it in self._iter_status_entries(status_data):
                    k = (it.get("key","") or "").lower()
                    if k.startswith("fan speed"):
                        m = re.search(r'fan speed\s+(\d+)', k)
                        if m:
                            max_fan_idx = max(max_fan_idx, int(m.group(1)))
                    elif k.startswith("pump speed"):
                        self.have_pump = True
                self.fan_count = max_fan_idx or 6
            except Exception as e:
                self.show_status_message(f"Error detecting features: {e}")
                self.fan_count = 6
        else:
            dev = self.selected_device.get("device")
            if dev is None:
                self.fan_count = 6
            else:
                try:
                    with dev.connect():
                        status = dev.get_status()
                    max_fan_idx = 0
                    for key, value, unit in status:
                        k = (key or '').lower()
                        if 'fan' in k and 'speed' in k:
                            m = re.search(r'fan\s*(\d+)', k)
                            if m:
                                idx = int(m.group(1))
                                max_fan_idx = max(max_fan_idx, idx)
                        elif 'pump' in k and 'speed' in k:
                            self.have_pump = True
                    self.fan_count = max_fan_idx or 6
                except Exception as e:
                    self.show_status_message(f"Error detecting features: {e}")
                    self.fan_count = 6
        font = QFont(); font.setPointSize(FONT_PT)
        self.add_fan_controls(self.fan_count, font)
        self.update_pump_row_visibility()
        self._sync_all_fans_slider()

    def update_pump_row_visibility(self):
        visible = (self.have_pump and self.pump_supported)
        for i in range(self.pump_row.count()):
            w = self.pump_row.itemAt(i).widget()
            if w: w.setVisible(visible)

    def probe_pump_capability(self):
        if not self.have_pump:
            # No pump present, so nothing to probe.
            self.pump_supported = False
            self.update_pump_row_visibility()
            return
        if self.use_cli:
            ok = self._try_cmds(self._candidate_set_cmds("pump", None, 50), timeout=5)
            self.pump_supported = bool(ok)
            self.update_pump_row_visibility()
            if not self.pump_supported:
                self.show_status_message("Pump control not supported by this driver/device.")
        else:
            # Use the API to probe if setting the pump speed raises.
            ok = False
            dev = self.selected_device.get("device")
            if dev is not None:
                try:
                    with dev.connect():
                        dev.set_fixed_speed('pump', 50)
                    ok = True
                except Exception:
                    ok = False
            self.pump_supported = ok
            self.update_pump_row_visibility()
            if not self.pump_supported:
                self.show_status_message("Pump control not supported by this driver/device.")

    def update_status(self):
        if not self.selected_device: return
        self.update_system_info()

        status_parsed = False
        if not self.use_cli:
            # Read status via the Python API
            dev = self.selected_device.get("device") if isinstance(self.selected_device, dict) else None
            if dev is not None:
                try:
                    with dev.connect():
                        data = dev.get_status()
                    # Parse the (key, value, unit) tuples
                    self._parse_devstatus_and_update(data)
                    status_parsed = True
                except Exception as e:
                    self.show_status_message(f"Error updating status: {e}")
            else:
                # If no device object, we can't update via library
                status_parsed = False
        else:
            # Read status by invoking the CLI
            try:
                res = self.run_logged(["liquidctl","-m", self.selected_device["description"], "status","--json"], timeout=8)
                data = json.loads(res.stdout) if res.stdout else []
                self._parse_json_and_update(data)
                status_parsed = True
            except Exception:
                try:
                    res2 = self.run_logged(["liquidctl","-m", self.selected_device["description"], "status"], timeout=8)
                    self._parse_text_and_update(res2.stdout)
                    status_parsed = True
                except Exception as e2:
                    self.show_status_message(f"Error updating status: {e2}")

        ct=get_cpu_temp(); self.cpu_temp_label.setText(f"CPU Temperature: {ct:.1f} °C" if ct is not None else "CPU Temperature: N/A")
        gt=get_gpu_temp(); self.gpu_temp_label.setText(f"GPU Temperature: {gt:.1f} °C" if gt is not None else "GPU Temperature: N/A")

        if status_parsed: self.check_safety_boost(ct, self._last_water_temp)

        if self.curves.get("enabled", False) and not self._boost_active:
            target = 0
            cpts = [tuple(self.curves["cpu"][k]) for k in ("p1","p2","p3")]
            wpts = [tuple(self.curves["water"][k]) for k in ("p1","p2","p3")]
            if ct is not None: target = max(target, self._curve_value(cpts, ct))
            if self._last_water_temp is not None: target = max(target, self._curve_value(wpts, self._last_water_temp))
            target = max(0, min(100, int(target)))
            self.adjust_all_fans(target)
            if self.have_pump and self.pump_supported and self.curves.get("apply_pump", True):
                self.pump_slider.setValue(target); self.pump_percent_inline.setText(f"{target} %"); self.pump_apply_timer.start(200)

        self.update_graph(ct, self._last_water_temp)
        self.update_tray_tooltip()

    @staticmethod
    def _curve_value(points, temp):
        pts = sorted(points, key=lambda x: x[0])
        if not pts: return 0
        if temp <= pts[0][0]: return pts[0][1]
        if temp >= pts[-1][0]: return pts[-1][1]
        for (t1,p1),(t2,p2) in zip(pts, pts[1:]):
            if t1 <= temp <= t2:
                if t2==t1: return p2
                ratio = (temp - t1)/(t2 - t1)
                return int(round(p1 + ratio*(p2-p1)))
        return pts[-1][1]

    def _parse_json_and_update(self, status_data):
        fan_map = {}; pump=None; wtemp=None
        for it in self._iter_status_entries(status_data):
            key = (it.get("key","") or "").lower()
            val = it.get("value", 0)
            if key.startswith("fan speed"):
                m = re.search(r'fan speed\s+(\d+)', key)
                if m:
                    idx=int(m.group(1)); rpm=int(val) if isinstance(val,(int,float)) else 0
                    fan_map[idx]=(self.rpm_to_percent(rpm), rpm)
            elif key.startswith("pump speed"):
                rpm=int(val) if isinstance(val,(int,float)) else 0
                pump=(self.rpm_to_percent(rpm, True), rpm)
            elif "water temperature" in key or "liquid temperature" in key or "coolant temperature" in key:
                try: wtemp=float(val)
                except: pass
        self._update_ui_from_maps(fan_map, pump, wtemp)

    def _parse_text_and_update(self, txt):
        fan_map = {}; pump=None; wtemp=None
        for line in txt.splitlines():
            l=line.strip().lower()
            m=re.search(r'fan speed\s+(\d+)\s+(\d+)\s*rpm', l)
            if m:
                idx=int(m.group(1)); rpm=int(m.group(2)); fan_map[idx]=(self.rpm_to_percent(rpm), rpm); continue
            m=re.search(r'pump speed\s+(\d+)\s*rpm', l)
            if m:
                rpm=int(m.group(1)); pump=(self.rpm_to_percent(rpm, True), rpm); continue
            m=re.search(r'(water|liquid|coolant)\s*temperature\s+([\d.]+)\s*°?c', l)
            if m:
                try: wtemp=float(m.group(2))
                except: pass
        self._update_ui_from_maps(fan_map, pump, wtemp)

    def _parse_devstatus_and_update(self, status):
        """Parse a status returned by the liquidctl Python API.

        The API returns a list of (key, value, unit) tuples.  Keys are human
        readable strings like ``Fan 1 speed``, ``Pump speed`` or
        ``Liquid temperature``.  Values are numeric when appropriate, but may
        come in different types (int, float, None).  Units are present for
        compatibility with the CLI but not used here.

        This method normalizes the information into the internal fan_map and
        pump/water variables before delegating to `_update_ui_from_maps`.
        """
        fan_map = {}
        pump = None
        wtemp = None
        for key, value, unit in status:
            k = (key or '').lower()
            # Detect fan speed entries.  Some drivers expose "fan speed 1"
            # while others use "fan 1 speed"; use a loose regex to match both.
            if 'fan' in k and 'speed' in k:
                m = re.search(r'fan\s*(\d+)', k)
                if m:
                    idx = int(m.group(1))
                    try:
                        rpm = int(value)
                    except Exception:
                        try:
                            rpm = int(float(value))
                        except Exception:
                            rpm = 0
                    fan_map[idx] = (self.rpm_to_percent(rpm), rpm)
                continue
            # Detect pump speed entries
            if 'pump' in k and 'speed' in k:
                try:
                    rpm = int(value)
                except Exception:
                    try:
                        rpm = int(float(value))
                    except Exception:
                        rpm = 0
                pump = (self.rpm_to_percent(rpm, True), rpm)
                continue
            # Detect water/liquid/coolant temperature entries
            if any(word in k for word in ('water', 'liquid', 'coolant')) and 'temperature' in k:
                try:
                    wtemp = float(value)
                except Exception:
                    wtemp = None
                continue
        self._update_ui_from_maps(fan_map, pump, wtemp)

    def _update_ui_from_maps(self, fan_map, pump, water_temp):
        now=time.time()
        if fan_map:
            max_idx = max(fan_map.keys())
            if max_idx != self.fan_count:
                self.fan_count = max_idx
                font = QFont(); font.setPointSize(FONT_PT)
                self.add_fan_controls(self.fan_count, font)

        for i in range(1, self.fan_count+1):
            if i in fan_map:
                pct, rpm = fan_map[i]
                u=self.user_set_fan_speeds.get(i,(None,0))
                if u[0] is None or now-u[1] > 3:
                    self.fan_sliders[i-1].blockSignals(True)
                    self.fan_sliders[i-1].setValue(pct)
                    self.fan_sliders[i-1].blockSignals(False)
                    if i-1 < len(self.fan_percent_inline_labels): self.fan_percent_inline_labels[i-1].setText(f"{pct} %")
                if i-1 < len(self.fan_rpm_inline_labels): self.fan_rpm_inline_labels[i-1].setText(f"{rpm} RPM")
            else:
                if i-1 < len(self.fan_rpm_inline_labels): self.fan_rpm_inline_labels[i-1].setText("N/A")

        if self.have_pump and self.pump_supported and pump:
            ppct, prpm = pump
            p = self.user_set_pump_speed if self.user_set_pump_speed else (None,0)
            if p[0] is None or now - p[1] > 3:
                self.pump_slider.blockSignals(True); self.pump_slider.setValue(ppct); self.pump_slider.blockSignals(False)
                self.pump_percent_inline.setText(f"{ppct} %")
            self.pump_rpm_inline.setText(f"{prpm} RPM")
        else:
            self.pump_rpm_inline.setText("N/A")

        self._last_water_temp = water_temp
        self.temp_label.setText(f"Water Temperature: {water_temp:.1f} °C" if water_temp is not None else "Water Temperature: N/A")

        self.save_sliders_to_conf()
        self._sync_all_fans_slider()

    # ---------- Safety boost ----------
    def check_safety_boost(self, cpu_temp, water_temp):
        if not self.safety.get("enabled", False):
            if self._boost_active: self._restore_from_boost()
            return
        over = False
        if cpu_temp is not None and cpu_temp >= float(self.safety.get("cpu_crit", 85)): over = True
        if water_temp is not None and water_temp >= float(self.safety.get("water_crit", 45)): over = True
        if over and not self._boost_active:
            self._preboost = {"fans": [s.value() for s in self.fan_sliders], "pump": self.pump_slider.value()}
            self.adjust_all_fans(100)
            if self.have_pump and self.pump_supported:
                self.pump_slider.setValue(100); self.pump_percent_inline.setText("100 %"); self.pump_apply_timer.start(100)
            self._boost_active = True
            self._append_debug("EMERGENCY BOOST ON")
            self.show_status_message("Emergency boost: temps over threshold → all 100%", 4000)
            return
        if self._boost_active and not over:
            h = float(self.safety.get("hysteresis", 5))
            below_cpu = (cpu_temp is None) or (cpu_temp <= float(self.safety.get("cpu_crit",85)) - h)
            below_wat = (water_temp is None) or (water_temp <= float(self.safety.get("water_crit",45)) - h)
            if below_cpu and below_wat: self._restore_from_boost()

    def _restore_from_boost(self):
        if not self._preboost:
            self._boost_active = False; return
        self.block_slider_signals(True)
        for i, val in enumerate(self._preboost.get("fans", [])):
            if i < len(self.fan_sliders):
                self.fan_sliders[i].setValue(val)
                if i < len(self.fan_percent_inline_labels): self.fan_percent_inline_labels[i].setText(f"{val} %")
        self.block_slider_signals(False)
        self.fan_apply_timer.start(200)
        if self.have_pump and self.pump_supported:
            pv = int(self._preboost.get("pump", 100))
            self.pump_slider.setValue(pv); self.pump_percent_inline.setText(f"{pv} %"); self.pump_apply_timer.start(200)
        self._boost_active = False; self._preboost = None
        self._append_debug("EMERGENCY BOOST OFF")
        self.show_status_message("Emergency boost ended: restored previous speeds", 4000)

    # ---------- Apply speeds ----------
    def _candidate_set_cmds(self, kind, index=None, percent=0):
        m = self.selected_device["description"] if self.selected_device else None
        p=str(int(percent))
        cmds=[]
        if kind=="fan":
            if index is not None:
                cmds.append(["liquidctl","-m",m,"set",f"fan{index}","speed",p])
                cmds.append(["liquidctl","-m",m,"set",f"fan{index}","duty",p])
            cmds.append(["liquidctl","-m",m,"set","fan","speed",p])
            cmds.append(["liquidctl","-m",m,"set","fan","duty",p])
        elif kind=="pump":
            cmds.append(["liquidctl","-m",m,"set","pump","speed",p])
            cmds.append(["liquidctl","-m",m,"set","pump","duty",p])
        return cmds

    def _try_cmds(self, cmds, timeout=6):
        """Attempt to execute one of several candidate commands.

        When using the CLI backend this will iterate through all provided
        commands, running each until one succeeds.  When using the Python
        library we instead parse the command structure to call the
        appropriate API methods.  Only the first candidate is attempted when
        using the API, since either the operation will succeed or it will
        raise.
        """
        if self.use_cli:
            for c in cmds:
                try:
                    self.run_logged(c, check=True, timeout=timeout)
                    return True
                except Exception as e:
                    log.debug(f"command failed: {' '.join(c)} -> {e}")
            return False
        # API backend: parse the command parameters and dispatch to the
        # appropriate set speed call.  The expected format is
        # ["liquidctl", "-m", <model>, "set", <channel>, <mode>, <percent>].
        for c in cmds:
            try:
                if len(c) < 7:
                    continue
                channel = c[4]
                # percent is always the last element
                pct_str = c[-1]
                try:
                    pct = int(pct_str)
                except Exception:
                    pct = int(float(pct_str))
                if channel.startswith('fan'):
                    if channel == 'fan':
                        self._lib_set_speed('fan', None, pct)
                    else:
                        try:
                            idx = int(channel[3:])
                        except Exception:
                            idx = None
                        self._lib_set_speed('fan', idx, pct)
                    return True
                elif channel == 'pump':
                    self._lib_set_speed('pump', None, pct)
                    return True
            except Exception as e:
                log.debug(f"API command failed: {c} -> {e}")
        return False

    def _lib_set_speed(self, kind, index, percent):
        """Set a fan or pump speed using the liquidctl Python API.

        Parameters
        ----------
        kind: str
            Either 'fan' or 'pump'.
        index: int or None
            For fans, the 1-based channel index.  If None, all fans will be
            targeted when supported by the driver.  Ignored for pumps.
        percent: int
            The desired duty percentage (0–100).

        Returns
        -------
        bool
            True if the operation appears to have succeeded, False otherwise.
        """
        dev = None
        if isinstance(self.selected_device, dict):
            dev = self.selected_device.get('device')
        if dev is None:
            return False
        try:
            with dev.connect():
                if kind == 'pump':
                    # Set pump speed; some drivers may not implement pump control
                    dev.set_fixed_speed('pump', percent)
                elif kind == 'fan':
                    if index is None:
                        # Try to set all fans at once; if unsupported, fall back
                        try:
                            dev.set_fixed_speed('fan', percent)
                        except Exception:
                            # Fall back to per-channel update for each fan
                            for chan in range(1, self.fan_count + 1):
                                try:
                                    dev.set_fixed_speed(f'fan{chan}', percent)
                                except Exception:
                                    pass
                    else:
                        # Specific fan channel
                        dev.set_fixed_speed(f'fan{index}', percent)
            return True
        except Exception as e:
            # Log and surface the error through the status bar; avoid crashing.
            try:
                self.show_status_message(f"Failed to set {kind} speed: {e}")
            except Exception:
                pass
            return False

    def adjust_all_fans(self, value):
        pct = round(value/10)*10
        self.allfans_pct.setText(f"{pct} %")
        self.block_slider_signals(True)
        now=time.time()
        for i,s in enumerate(self.fan_sliders):
            s.setValue(pct)
            if i < len(self.fan_percent_inline_labels): self.fan_percent_inline_labels[i].setText(f"{pct} %")
            if i < len(self.fan_rpm_inline_labels): self.fan_rpm_inline_labels[i].setText(f"{self.percent_to_rpm(pct)} RPM")
            self.user_set_fan_speeds[i+1]=(pct, now)
        self.block_slider_signals(False)
        self.fan_apply_timer.start(400)
        self.save_sliders_to_conf()

    def adjust_fan_speed(self, fan_id, value):
        pct = round(value/10)*10
        if self.link_chk.isChecked():
            self.adjust_all_fans(pct); return
        s=self.fan_sliders[fan_id-1]; s.blockSignals(True); s.setValue(pct); s.blockSignals(False)
        rpm=self.percent_to_rpm(pct)
        if fan_id-1 < len(self.fan_percent_inline_labels): self.fan_percent_inline_labels[fan_id-1].setText(f"{pct} %")
        if fan_id-1 < len(self.fan_rpm_inline_labels): self.fan_rpm_inline_labels[fan_id-1].setText(f"{rpm} RPM")
        self.user_set_fan_speeds[fan_id]=(pct, time.time())
        self.fan_apply_timer.start(400); self.save_sliders_to_conf()

    def apply_all_fan_speeds(self):
        speeds=[s.value() for s in self.fan_sliders]
        # Apply all fan speeds asynchronously.  When using the CLI backend the
        # commands are executed via the CLI; when using the Python API we call
        # the library directly.  The per-channel loop ensures that drivers
        # lacking an all-fan command still receive the correct duty per fan.
        def worker():
            if self.use_cli:
                for fan_id, pct in enumerate(speeds, 1):
                    self._try_cmds(self._candidate_set_cmds("fan", fan_id, pct))
            else:
                for fan_id, pct in enumerate(speeds, 1):
                    self._lib_set_speed('fan', fan_id, pct)
        threading.Thread(target=worker, daemon=True).start()

    def adjust_pump_speed(self, value):
        pct = round(value/10)*10
        self.pump_slider.blockSignals(True); self.pump_slider.setValue(pct); self.pump_slider.blockSignals(False)
        rpm=self.percent_to_rpm(pct, True)
        self.pump_percent_inline.setText(f"{pct} %"); self.pump_rpm_inline.setText(f"{rpm} RPM")
        self.user_set_pump_speed=(pct, time.time())
        if self.have_pump and self.pump_supported: self.pump_apply_timer.start(400)
        self.save_sliders_to_conf()

    def apply_pump_speed(self):
        if not (self.user_set_pump_speed and self.have_pump and self.pump_supported): return
        pct,_=self.user_set_pump_speed
        def worker():
            if self.use_cli:
                self._try_cmds(self._candidate_set_cmds("pump", None, pct))
            else:
                self._lib_set_speed('pump', None, pct)
        threading.Thread(target=worker, daemon=True).start()

    # ---------- % <-> RPM ----------
    def percent_to_rpm(self, percent, is_pump=False):
        mn=self.min_pump_rpm if is_pump else self.min_fan_rpm
        mx=self.max_pump_rpm if is_pump else self.max_fan_rpm
        if percent<=20: return mn
        if percent>=100: return mx
        return int(round((mn + (mx-mn)*(percent-20)/80)/100)*100)

    def rpm_to_percent(self, rpm, is_pump=False):
        mn=self.min_pump_rpm if is_pump else self.min_fan_rpm
        mx=self.max_pump_rpm if is_pump else self.max_fan_rpm
        if rpm<=mn: return 20
        if rpm>=mx: return 100
        pct = 20 + ((rpm-mn)/(mx-mn))*80
        return int(round(pct/10)*10)

    def _sync_all_fans_slider(self):
        pcts = [s.value() for s in self.fan_sliders]
        if not pcts: return
        pcts_sorted = sorted(pcts)
        median = pcts_sorted[len(pcts_sorted)//2]
        self.allfans_slider.blockSignals(True)
        self.allfans_slider.setValue(median)
        self.allfans_slider.blockSignals(False)
        self.allfans_pct.setText(f"{median} %" if len(set(pcts))==1 else f"~{median} %")

    # ---------- System info ----------
    def read_cpu_model(self):
        try:
            env=os.environ.copy(); env["LC_ALL"]="C"
            out=run_cmd(["lscpu"], env=env)
            for line in out.stdout.splitlines():
                if line.lower().startswith("model name:"):
                    return line.split(":",1)[1].strip()
        except Exception:
            pass
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line.lower():
                        return line.split(":",1)[1].strip()
        except Exception:
            pass
        return "N/A"

    def read_gpu_model(self):
        """Return a short, human GPU name (NVIDIA/AMD/Intel) without lspci noise."""
        try:
            if shutil.which("nvidia-smi"):
                out = run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=3)
                line = out.stdout.strip().splitlines()[0].strip()
                if line:
                    return f"NVIDIA {line}" if not line.lower().startswith(("nvidia", "geforce", "quadro", "rtx", "gtx")) else line
        except Exception:
            pass
        try:
            if shutil.which("glxinfo"):
                out = run_cmd(["glxinfo", "-B"], timeout=3)
                for ln in out.stdout.splitlines():
                    if ln.lower().startswith("device:"):
                        val = ln.split(":", 1)[1].strip()
                        val = re.sub(r"\s*\(.*?\)\s*", "", val)
                        return self._pretty_gpu_name(val)
        except Exception:
            pass
        try:
            out = run_cmd("lspci -nn | egrep -i 'VGA|3D|Display' | head -n1", shell=True, timeout=3)
            line = out.stdout.strip()
            if line:
                line = re.sub(r".*?(controller:|display:)\s*", "", line, flags=re.I)
                return self._pretty_gpu_name(line)
        except Exception:
            pass
        return "N/A"

    def _pretty_gpu_name(self, raw):
        s = raw.strip()
        s = re.sub(r"\(rev\s*[0-9a-fA-F]+\)", "", s, flags=re.I).strip()
        s = re.sub(r"\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]", "", s).strip()
        low = s.lower()
        m = re.search(r"(geforce\s+[^\(\[]+|rtx\s+[^\(\[]+|gtx\s+[^\(\[]+|quadro\s+[^\(\[]+|tesla\s+[^\(\[]+)", low)
        if m:
            name = m.group(1).strip()
            return "NVIDIA " + name.upper().replace("  ", " ")
        m = re.search(r"(iris\s+xe\s*[^\(\[]*|uhd\s+graphics\s*\d+\w*|arc\s+[^\(\[]+)", low)
        if m:
            name = m.group(1).strip()
            pretty = " ".join(w.capitalize() if w.lower() not in ("xe", "uhd") else w.upper() for w in name.split())
            return "Intel " + pretty
        br = re.search(r"\[(Radeon[^\]]+)\]", s, flags=re.I)
        if br:
            inside = br.group(1)
            parts = [p.strip() for p in inside.split("/") if p.strip()]
            cand = None
            for p in parts:
                if "rx " in p.lower() and (" xt" in p.lower() or "xtx" in p.lower()):
                    cand = p; break
            if not cand:
                for p in parts:
                    if "rx " in p.lower():
                        cand = p; break
            if not cand:
                cand = max(parts, key=len)
            return "AMD " + cand
        m = re.search(r"(radeon\s+[^\(\[]+)", low)
        if m:
            token = m.group(1).strip()
            token = re.sub(r"\brx\b", "RX", token, flags=re.I)
            token = re.sub(r"\bxtx?\b", lambda x: x.group(0).upper(), token, flags=re.I)
            return "AMD " + token.capitalize()
        s = re.sub(r"Advanced Micro Devices, Inc\.\s*\[AMD/ATI\]\s*", "AMD ", s, flags=re.I)
        s = re.sub(r"NVIDIA Corporation\s*", "NVIDIA ", s, flags=re.I)
        s = re.sub(r"Intel Corporation\s*", "Intel ", s, flags=re.I)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return s or "N/A"

    def read_os_pretty(self):
        name=""
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        name=line.split("=",1)[1].strip().strip('"'); break
        except Exception:
            pass
        if not name:
            try:
                out=run_cmd(["uname","-sr"])
                name=out.stdout.strip()
            except:
                name="Unknown OS"
        return name

    def read_ram_info(self):
        total=avail=None
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"): total=int(line.split()[1])*1024
                    elif line.startswith("MemAvailable:"): avail=int(line.split()[1])*1024
                    if total and avail: break
        except Exception:
            pass
        fmt=lambda b: f"{b/1024/1024/1024:.1f} GB"
        return f"{fmt(total)} total / {fmt(avail)} free" if total and avail else "N/A"

    def read_disk_info(self):
        try:
            du=shutil.disk_usage("/")
            fmt=lambda b: f"{b/1024/1024/1024:.1f} GB"
            return f"{fmt(du.total)} total / {fmt(du.free)} free"
        except Exception:
            return "N/A"

    def update_system_info(self):
        self.sys_os_label.setText(f"OS: {self.read_os_pretty()}")
        self.sys_cpu_label.setText(f"CPU: {self.read_cpu_model()}")
        self.sys_gpu_label.setText(f"GPU: {self.read_gpu_model()}")
        self.sys_ram_label.setText(f"RAM: {self.read_ram_info()}")
        self.sys_disk_label.setText(f"Disk: {self.read_disk_info()}")

    # ---------- Fans UI + rename ----------
    def _start_edit_name(self, idx):
        edit = self.fan_name_edits.get(idx)
        if not edit: return
        label = self.fan_name_labels[idx-1]; label.hide()
        edit.setText(label.text()); edit.show(); edit.setFocus(); edit.selectAll()

    def _finish_edit_name(self, idx):
        edit = self.fan_name_edits.get(idx)
        if not edit: return
        txt = edit.text().strip() or f"Fan {idx}"
        self.conf.setdefault("fan_names", {})[str(idx)] = txt
        save_json_config(self.conf)
        label = self.fan_name_labels[idx-1]
        label.setText(txt); edit.hide(); label.show()

    def add_fan_controls(self, count, font):
        # Clear existing
        for lay in getattr(self, "fan_rows_layouts", []):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w: w.setParent(None)
        self.fan_rows_layouts=[]
        for l in getattr(self,"fan_rpm_inline_labels",[]): l.deleteLater()
        for l in getattr(self,"fan_percent_inline_labels",[]): l.deleteLater()
        for s in getattr(self,"fan_sliders",[]): s.deleteLater()
        for l in getattr(self,"fan_name_labels",[]): l.deleteLater()
        for e in getattr(self, "fan_name_edits", {}).values(): e.deleteLater()
        self.fan_name_edits={}; self.fan_name_labels=[]
        self.fan_rpm_inline_labels=[]; self.fan_percent_inline_labels=[]; self.fan_sliders=[]

        # Build rows
        for i in range(count):
            row = QHBoxLayout(); compactify(row)
            name_lbl = RenamableLabel(self.conf.get("fan_names", {}).get(str(i+1), f"Fan {i+1}"))
            name_lbl.setFont(font); name_lbl.setFixedWidth(NAME_COL_W)
            name_lbl.requestEdit.connect(lambda idx=i+1: self._start_edit_name(idx))
            name_edit = QLineEdit(); name_edit.setFont(font); name_edit.setFixedWidth(NAME_COL_W); name_edit.setVisible(False)
            name_edit.editingFinished.connect(lambda idx=i+1: self._finish_edit_name(idx))

            rpm_lbl  = QLabel("N/A"); rpm_lbl.setFont(font); rpm_lbl.setFixedWidth(RPM_COL_W)
            perc_lbl = QLabel("0 %");  perc_lbl.setFont(font); perc_lbl.setFixedWidth(PCT_COL_W)

            s = QSlider(Qt.Orientation.Horizontal); s.setRange(0,100); s.setTickInterval(10); s.setSingleStep(10)
            s.setTickPosition(QSlider.TickPosition.TicksBelow); s.setMinimumHeight(SLIDER_H); s.setStyleSheet(fan_slider_style)
            s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            s.valueChanged.connect(lambda v, fid=i+1: self.adjust_fan_speed(fid, v))

            for w in (name_lbl, name_edit, rpm_lbl, perc_lbl, s): row.addWidget(w)
            self.control_layout.addLayout(row)
            self.fan_rows_layouts.append(row)
            self.fan_name_labels.append(name_lbl); self.fan_name_edits[i+1]=name_edit
            self.fan_rpm_inline_labels.append(rpm_lbl); self.fan_percent_inline_labels.append(perc_lbl); self.fan_sliders.append(s)

    # ---------- Misc ----------
    def save_sliders_to_conf(self):
        self.conf["last_sliders"]={"fan_speeds":[s.value() for s in self.fan_sliders], "pump_speed": self.pump_slider.value()}
        save_json_config(self.conf)

    def update_tray_tooltip(self):
        lines=[self.temp_label.text(), self.cpu_temp_label.text(), self.gpu_temp_label.text()]
        for i,lbl in enumerate(self.fan_rpm_inline_labels,1):
            name = self.conf.get("fan_names", {}).get(str(i), f"Fan {i}")
            lines.append(f"{name}: {lbl.text()}")
        lines.append(f"Pump: {self.pump_rpm_inline.text()}")
        self.tray_icon.setToolTip("\n".join(lines))

    def open_debug_dialog(self):
        if not self.debug_dlg:
            self.debug_dlg = DebugDialog(self)
        self.debug_dlg.set_lines(self.debug_lines)
        self.debug_dlg.show(); self.debug_dlg.raise_(); self.debug_dlg.activateWindow()

    def update_graph(self, cpu_t, water_t):
        """Update rolling graph; x-axis in seconds, with readable ticks."""
        if not HAVE_MPL or not self.canvas or not self.canvas.isVisible(): return
        now = time.time()
        if self._t0 is None: self._t0 = now
        self._hist_t.append(now - self._t0)
        self._hist_cpu.append(cpu_t if cpu_t is not None else float("nan"))
        self._hist_water.append(water_t if water_t is not None else float("nan"))

        x = list(self._hist_t)
        self._graph_cpu_line.set_data(x, list(self._hist_cpu))
        self._graph_water_line.set_data(x, list(self._hist_water))

        vals = [v for v in list(self._hist_cpu)+list(self._hist_water) if v==v]
        ymin = min(vals, default=0); ymax = max(vals, default=100)
        if ymin == ymax: ymin -= 1; ymax += 1

        # show last 60–120 seconds nicely
        xmax = max(60, int(x[-1]) if x else 60)
        self.ax.set_xlim(max(0, xmax-120), xmax)
        self.ax.set_ylim(max(0, ymin-2), min(120, ymax+2))
        self.ax.set_xticks(range(max(0, xmax-120), xmax+1, 10))

        # keep margins so labels are visible even when resized
        self.fig.subplots_adjust(left=0.09, right=0.98, top=0.93, bottom=0.28)
        self.canvas.draw_idle()

    def rebuild_tray_menu(self, selected_profile=None):
        self.tray_menu.clear()
        cur = QAction(f"Current profile: {selected_profile or '(none)'}", self); f=QFont(); f.setBold(True); cur.setFont(f); cur.setEnabled(False)
        self.tray_menu.addAction(cur); self.tray_menu.addSeparator()

        about_action = QAction("About", self); about_action.triggered.connect(self.show_about)
        run_on_start_action = QAction("Run on start", self); run_on_start_action.setCheckable(True)
        run_on_start_action.setChecked(self.conf["global"].get("run_on_start", False))
        run_on_start_action.toggled.connect(self.set_autostart)
        show_action = QAction("Show", self); show_action.triggered.connect(self.show)
        self.tray_menu.addAction(about_action); self.tray_menu.addAction(run_on_start_action); self.tray_menu.addAction(show_action)
        self.tray_menu.addSeparator()

        profiles_menu = QMenu("Select Profile", self)
        for pname,p in self.conf.get("profiles", {}).items():
            act = QAction(f"{pname} (P {p.get('pump_speed',0)} F {','.join(map(str,p.get('fan_speeds',[])))})", self)
            act.triggered.connect(partial(self.apply_profile_and_update_ui, pname, "tray"))
            profiles_menu.addAction(act)
        self.tray_menu.addMenu(profiles_menu)

        self.tray_menu.addSeparator()
        for pct in (30,50,70,100):
            a = QAction(f"All fans {pct}%", self); a.triggered.connect(partial(self.adjust_all_fans, pct)); self.tray_menu.addAction(a)
        self.tray_menu.addSeparator()
        exit_action = QAction("Exit", self); exit_action.triggered.connect(QApplication.quit); self.tray_menu.addAction(exit_action)

    def set_autostart(self, enabled):
        enabled = bool(enabled)
        self.conf["global"]["run_on_start"] = enabled
        save_json_config(self.conf)
        try:
            if enabled:
                os.makedirs(AUTOSTART_DIR, exist_ok=True)
                exe = sys.argv[0];
                if not os.path.isabs(exe): exe = os.path.abspath(exe)
                desktop = f"""[Desktop Entry]
Type=Application
Name=Liquidctl GUI
Exec="{exe}"
X-GNOME-Autostart-enabled=true
"""
                with open(AUTOSTART_FILE, "w") as f: f.write(desktop)
            else:
                if os.path.exists(AUTOSTART_FILE): os.remove(AUTOSTART_FILE)
        except Exception as e:
            self._append_debug(f"Autostart error: {e}")

    def show_about(self):
        QMessageBox.information(self, "About",
"""LiquidctlGUI for Linux
Profiles: ~/.liquidctl_gui.json (reads legacy ~/.LIquidctl_settings.json)
Creator: Nele
""")

    def block_slider_signals(self, block):
        for s in self.fan_sliders: s.blockSignals(block)
        self.pump_slider.blockSignals(block)

    def closeEvent(self, event):
        event.ignore(); self.hide()
        self.tray_icon.showMessage("LiquidctlGUI","Minimized to tray. Use 'Exit' to close.",
                                   QSystemTrayIcon.MessageIcon.Information, 2000)

# ---------- main ----------
def main():
    if not shutil.which("liquidctl"):
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Error", "liquidctl is not installed! Please install it and try again.")
        sys.exit(1)
    app = QApplication(sys.argv)
    for p in [os.path.join(os.path.dirname(__file__), "icon.png"),
              "/usr/share/icons/liquidctl-gui.png","/usr/local/share/icons/liquidctl-gui.png"]:
        if os.path.exists(p): app.setWindowIcon(QIcon(p)); break
    gui = LiquidCtlGUI(); gui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
