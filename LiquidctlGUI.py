#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, time, logging, subprocess, shutil, threading, re, json
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QGroupBox, QComboBox,
    QSystemTrayIcon, QMenu, QMessageBox, QDialog,
    QFormLayout, QDialogButtonBox, QLineEdit, QInputDialog, QStyle, QStatusBar,
    QCheckBox, QSpinBox, QSizePolicy
)
from PyQt6.QtGui import QIcon, QAction, QFont
from PyQt6.QtCore import Qt, QTimer

# ---------------------- Column widths (keep alignment) ----------------------
NAME_COL_W = 140
RPM_COL_W  = 160
PCT_COL_W  = 80

# ---------------------- Setup / paths ----------------------
HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".liquidctl_gui.json")
LEGACY_CONFIG_PATH = os.path.join(HOME, ".LIquidctl_settings.json")  # backward-compat read only

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("liquidctl-gui")

def run_cmd(args, **kw):
    """subprocess.run with sane defaults."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(args, **kw)

# ---------------------- Config I/O ----------------------
def load_json_config():
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else (LEGACY_CONFIG_PATH if os.path.exists(LEGACY_CONFIG_PATH) else CONFIG_PATH)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # fill defaults where missing
                data.setdefault("global", {}).setdefault("run_on_start", False)
                data["global"].setdefault("last_profile", None)
                data["global"].setdefault("link_fans", False)
                data.setdefault("safety", {"enabled": False, "cpu_crit": 85, "water_crit": 45, "hysteresis": 5})
                data.setdefault("profiles", {})
                data.setdefault("last_sliders", {"fan_speeds": [], "pump_speed": 0})
                return data
        except Exception:
            pass
    return {
        "global": {"run_on_start": False, "last_profile": None, "link_fans": False},
        "safety": {"enabled": False, "cpu_crit": 85, "water_crit": 45, "hysteresis": 5},
        "profiles": {},
        "last_sliders": {"fan_speeds": [], "pump_speed": 0}
    }

def save_json_config(conf):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(conf, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save config: {e}")

# ---------------------- Temperature helpers ----------------------
def get_cpu_temp():
    """
    Prefer `sensors -j` and take the hottest CPU-related reading:
    chips: k10temp/coretemp/zenpower; labels: Tctl/Tdie/Package/Core/CPU.
    Fallback to text parsing if JSON not available.
    """
    try:
        out = run_cmd(['sensors', '-j'], timeout=3)
        data = json.loads(out.stdout)
        best = None
        for chip, sections in data.items():
            chip_l = str(chip).lower()
            chip_is_cpu = any(x in chip_l for x in ('k10temp', 'coretemp', 'zenpower'))
            if not isinstance(sections, dict):
                continue
            for sec in sections.values():
                if not isinstance(sec, dict):
                    continue
                for k, v in sec.items():
                    if not (isinstance(k, str) and k.startswith('temp') and k.endswith('_input')):
                        continue
                    try:
                        val = float(v)
                    except Exception:
                        continue
                    label = sec.get(k.replace('_input', '_label'), '')
                    if chip_is_cpu or re.search(r'(tctl|tdie|package|core|cpu)', str(label).lower() or ''):
                        if 5.0 <= val <= 120.0:
                            best = val if best is None else max(best, val)
        if best is not None:
            return best
    except Exception:
        pass
    try:
        out = run_cmd(['sensors'], timeout=3)
        best = None
        for line in out.stdout.splitlines():
            ll = line.lower()
            if not re.search(r'(tctl|tdie|package|cpu|core)', ll):
                continue
            m = re.search(r'(\+?\d+(?:\.\d+)?)\s*°?c', line, re.I)
            if m:
                val = float(m.group(1))
                if 5.0 <= val <= 120.0:
                    best = val if best is None else max(best, val)
        return best
    except Exception:
        return None

def get_gpu_temp():
    """nvidia-smi first; else sensors (edge/junction)."""
    try:
        if shutil.which("nvidia-smi"):
            out = run_cmd(['nvidia-smi','--query-gpu=temperature.gpu','--format=csv,noheader'], timeout=3)
            for l in out.stdout.strip().splitlines():
                try:
                    t=float(l.strip())
                    if t>0: return t
                except: pass
    except Exception: pass
    try:
        out = run_cmd(['sensors'], timeout=3)
        for line in out.stdout.splitlines():
            m = re.search(r'(edge|junction):\s*\+?([\d.]+)', line, re.I)
            if m: return float(m.group(2))
            m2 = re.search(r'(gpu.*temp|temp\d+):\s*\+?([\d.]+)', line, re.I)
            if m2 and float(m2.group(2))<120: return float(m2.group(2))
    except Exception: pass
    return None

# ---------------------- UI styles ----------------------
fan_slider_style = """
QSlider::groove:horizontal { border:1px solid #999; height:8px; background:#c4c4c4; margin:2px 0; }
QSlider::handle:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #b4b4b4, stop:1 #0080ff); border:1px solid #313755; width:30px; margin:-2px 0; border-radius:3px; }
QSlider::sub-page:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0099FF, stop:1 #0067B1); }
"""
pump_slider_style = """
QSlider::groove:horizontal { border:1px solid #999; height:8px; background:#c4c4c4; margin:2px 0; }
QSlider::handle:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #b4b4b4, stop:1 #8f8f8f); border:1px solid #5c5c5c; width:30px; margin:-2px 0; border-radius:3px; }
QSlider::sub-page:horizontal { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #800080, stop:1 #BA55D3); }
"""

# ---------------------- Profile dialog ----------------------
class ProfileDialog(QDialog):
    """Simple profile editor based on current slider values."""
    def __init__(self, parent=None, existing_name="", fan_speeds=None, pump_speed=0, fan_count=6):
        super().__init__(parent)
        self.setWindowTitle("Create/Edit Profile")
        self.setGeometry(200, 200, 360, 250 + (fan_count - 1) * 36)
        layout = QFormLayout()
        font = QFont(); font.setPointSize(16)

        self.name_input = QLineEdit(); self.name_input.setFont(font); self.name_input.setText(existing_name)
        layout.addRow("Profile Name:", self.name_input)

        self.fan_speed_labels, self.fan_speed_sliders = [], []
        for i in range(fan_count):
            cur = fan_speeds[i] if fan_speeds and i < len(fan_speeds) else 0
            lbl = QLabel(f"Fan {i+1} Speed: {cur}%"); lbl.setFont(font)
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(0,100); s.setTickInterval(10); s.setSingleStep(10)
            s.setTickPosition(QSlider.TickPosition.TicksBelow); s.setMinimumHeight(48); s.setStyleSheet(fan_slider_style); s.setValue(cur)
            s.valueChanged.connect(lambda v, idx=i: self._upd_fan_label(idx))
            layout.addRow(lbl); layout.addWidget(s)
            self.fan_speed_labels.append(lbl); self.fan_speed_sliders.append(s)

        self.pump_speed_label = QLabel(f"Pump Speed: {pump_speed}%"); self.pump_speed_label.setFont(font)
        self.pump_speed_slider = QSlider(Qt.Orientation.Horizontal); self.pump_speed_slider.setRange(0,100)
        self.pump_speed_slider.setTickInterval(10); self.pump_speed_slider.setSingleStep(10)
        self.pump_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow); self.pump_speed_slider.setMinimumHeight(48)
        self.pump_speed_slider.setStyleSheet(pump_slider_style); self.pump_speed_slider.setValue(pump_speed)
        self.pump_speed_slider.valueChanged.connect(self._upd_pump_label)
        layout.addRow(self.pump_speed_label); layout.addWidget(self.pump_speed_slider)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.setMinimumHeight(48); bb.setFont(font); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
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

# ---------------------- Main GUI ----------------------
class LiquidCtlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mini Corsair iCUE for Linux")
        self.setGeometry(100, 100, 1000, 680)

        # State
        self.conf = load_json_config()
        self.safety = self.conf.get("safety", {"enabled": False, "cpu_crit": 85, "water_crit": 45, "hysteresis": 5})
        self.devices = []
        self.selected_device = None
        self.fan_count = 6
        self.have_pump = False
        self.pump_supported = False
        self.user_set_fan_speeds = {}
        self.user_set_pump_speed = None
        self.min_fan_rpm, self.max_fan_rpm = 200, 2000
        self.min_pump_rpm, self.max_pump_rpm = 1000, 2700
        self._last_water_temp = None

        # Emergency boost state
        self._boost_active = False
        self._preboost = None  # {"fans":[...], "pump":int}

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
        self.load_devices()
        self.update_status()
        self.rebuild_tray_menu(selected_profile=self.conf["global"].get("last_profile"))

    # ---------------------- UI skeleton ----------------------
    def init_ui(self):
        self.main_widget = QWidget(); self.setCentralWidget(self.main_widget)
        main_layout = QVBoxLayout()
        font = QFont(); font.setPointSize(16)

        # Device row
        dev_group = QGroupBox("Device"); dev_layout = QHBoxLayout()
        self.device_combo = QComboBox(); self.device_combo.setFont(font); self.device_combo.setMinimumHeight(48)
        self.device_combo.currentIndexChanged.connect(self.select_device)
        dev_layout.addWidget(QLabel("Select Device:"))
        dev_layout.addWidget(self.device_combo)

        btn_refresh = QPushButton("Refresh"); btn_refresh.setFont(font); btn_refresh.setMinimumHeight(48)
        btn_refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        btn_refresh.clicked.connect(self.load_devices); dev_layout.addWidget(btn_refresh)

        btn_perm = QPushButton("Fix permissions"); btn_perm.setFont(font); btn_perm.setMinimumHeight(48)
        btn_perm.clicked.connect(self.install_udev_rule_for_selected); dev_layout.addWidget(btn_perm)

        btn_help = QPushButton("?"); btn_help.setFixedWidth(36); btn_help.setMinimumHeight(48); btn_help.setFont(font)
        btn_help.clicked.connect(self.show_permissions_help); dev_layout.addWidget(btn_help)

        dev_group.setLayout(dev_layout); main_layout.addWidget(dev_group)

        # Profiles
        prof_group = QGroupBox("Profiles"); prof_layout = QHBoxLayout()
        lblp = QLabel("Profiles:"); lblp.setFont(font)
        self.profile_combo = QComboBox(); self.profile_combo.setFont(font); self.profile_combo.setMinimumHeight(48)
        self.profile_combo.currentIndexChanged.connect(self.profile_combo_selected)
        btn_edit = QPushButton("Edit Profile"); btn_edit.setFont(font); btn_edit.setMinimumHeight(48); btn_edit.clicked.connect(self.edit_profile)
        btn_del = QPushButton("Delete Profile"); btn_del.setFont(font); btn_del.setMinimumHeight(48); btn_del.clicked.connect(self.delete_profile)
        btn_save = QPushButton("Save Current Profile"); btn_save.setFont(font); btn_save.setMinimumHeight(48); btn_save.clicked.connect(self.save_current_profile)
        for w in (lblp, self.profile_combo, btn_edit, btn_del, btn_save): prof_layout.addWidget(w)
        prof_group.setLayout(prof_layout); main_layout.addWidget(prof_group)
        self.update_profile_combo()

        # Quick controls
        quick_group = QGroupBox("Quick Controls"); quick_layout = QHBoxLayout()
        self.allfans_label = QLabel("All Fans"); self.allfans_label.setFont(font); self.allfans_label.setFixedWidth(NAME_COL_W)
        self.allfans_pct = QLabel("0 %"); self.allfans_pct.setFont(font); self.allfans_pct.setFixedWidth(PCT_COL_W)
        self.allfans_slider = QSlider(Qt.Orientation.Horizontal); self.allfans_slider.setRange(0,100)
        self.allfans_slider.setTickInterval(10); self.allfans_slider.setSingleStep(10)
        self.allfans_slider.setTickPosition(QSlider.TickPosition.TicksBelow); self.allfans_slider.setMinimumHeight(36)
        self.allfans_slider.setStyleSheet(fan_slider_style)
        self.allfans_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.allfans_slider.valueChanged.connect(self.adjust_all_fans)

        # Link fans checkbox
        self.link_chk = QCheckBox("Link fans")
        self.link_chk.setChecked(bool(self.conf["global"].get("link_fans", False)))
        self.link_chk.toggled.connect(lambda ch: (self.conf["global"].__setitem__("link_fans", bool(ch)), save_json_config(self.conf)))

        for w in (self.allfans_label, QLabel(""), self.allfans_pct, self.allfans_slider, self.link_chk):
            quick_layout.addWidget(w)
        quick_group.setLayout(quick_layout); main_layout.addWidget(quick_group)

        # Safety group (emergency boost)
        safety_group = QGroupBox("Safety (Emergency Boost)"); s_layout = QHBoxLayout()
        self.safety_enable = QCheckBox("Enable"); self.safety_enable.setChecked(self.safety.get("enabled", False))
        self.safety_enable.toggled.connect(self._save_safety)

        self.cpu_crit = QSpinBox(); self.cpu_crit.setRange(40, 110); self.cpu_crit.setSuffix(" °C"); self.cpu_crit.setValue(int(self.safety.get("cpu_crit",85)))
        self.cpu_crit.valueChanged.connect(self._save_safety)
        self.water_crit = QSpinBox(); self.water_crit.setRange(20, 90); self.water_crit.setSuffix(" °C"); self.water_crit.setValue(int(self.safety.get("water_crit",45)))
        self.water_crit.valueChanged.connect(self._save_safety)
        self.hyst = QSpinBox(); self.hyst.setRange(0, 20); self.hyst.setSuffix(" °C"); self.hyst.setValue(int(self.safety.get("hysteresis",5)))
        self.hyst.valueChanged.connect(self._save_safety)

        for w in (self.safety_enable,
                  QLabel("CPU ≥"), self.cpu_crit,
                  QLabel("Water ≥"), self.water_crit,
                  QLabel("Hysteresis"), self.hyst):
            s_layout.addWidget(w)
        safety_group.setLayout(s_layout); main_layout.addWidget(safety_group)

        # Control header
        self.control_group = QGroupBox("Fan & Pump Control"); self.control_layout = QVBoxLayout()
        header = QHBoxLayout()
        Hname = QLabel("Name"); Hname.setFont(font); Hname.setFixedWidth(NAME_COL_W)
        Hrpm  = QLabel("RPM");  Hrpm.setFont(font);  Hrpm.setFixedWidth(RPM_COL_W)
        Hpct  = QLabel("%");    Hpct.setFont(font);  Hpct.setFixedWidth(PCT_COL_W)
        Hsl   = QLabel("Slider"); Hsl.setFont(font)
        header.addWidget(Hname); header.addWidget(Hrpm); header.addWidget(Hpct); header.addWidget(Hsl)
        self.control_layout.addLayout(header)

        # Pump row (wrapped so it can be hidden when unsupported)
        self.pump_row = QHBoxLayout()
        self.pump_name_inline = QLabel("Pump"); self.pump_name_inline.setFont(font); self.pump_name_inline.setFixedWidth(NAME_COL_W)
        self.pump_rpm_inline = QLabel("N/A");    self.pump_rpm_inline.setFont(font);  self.pump_rpm_inline.setFixedWidth(RPM_COL_W)
        self.pump_percent_inline = QLabel("0 %");self.pump_percent_inline.setFont(font); self.pump_percent_inline.setFixedWidth(PCT_COL_W)
        self.pump_slider = QSlider(Qt.Orientation.Horizontal); self.pump_slider.setRange(0,100)
        self.pump_slider.setTickInterval(10); self.pump_slider.setSingleStep(10)
        self.pump_slider.setTickPosition(QSlider.TickPosition.TicksBelow); self.pump_slider.setMinimumHeight(48)
        self.pump_slider.setStyleSheet(pump_slider_style)
        self.pump_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pump_slider.valueChanged.connect(self.adjust_pump_speed)
        for w in (self.pump_name_inline, self.pump_rpm_inline, self.pump_percent_inline, self.pump_slider):
            self.pump_row.addWidget(w)
        self.control_layout.addLayout(self.pump_row)

        # legacy labels (for tooltip)
        self.pump_label = QLabel("Pump Speed: N/A"); self.pump_speed_label = QLabel("Pump Speed: N/A")

        # Fans (dynamic)
        self.fan_rows_layouts=[]; self.fan_name_labels=[]; self.fan_rpm_inline_labels=[]; self.fan_percent_inline_labels=[]; self.fan_sliders=[]
        self.add_fan_controls(6, font)
        self.control_group.setLayout(self.control_layout); main_layout.addWidget(self.control_group)

        # System info + Temps
        status_layout = QHBoxLayout()
        sys_group = QGroupBox("System Info"); sys_v = QVBoxLayout()
        self.sys_os_label = QLabel("OS: N/A"); self.sys_cpu_label = QLabel("CPU: N/A")
        self.sys_gpu_label = QLabel("GPU: N/A"); self.sys_ram_label = QLabel("RAM: N/A"); self.sys_disk_label = QLabel("Disk: N/A")
        for L in (self.sys_os_label,self.sys_cpu_label,self.sys_gpu_label,self.sys_ram_label,self.sys_disk_label):
            L.setFont(font); sys_v.addWidget(L)
        sys_group.setLayout(sys_v); status_layout.addWidget(sys_group)

        temp_group = QGroupBox("Temperature"); temp_v = QVBoxLayout()
        self.temp_label = QLabel("Water Temperature: N/A"); self.temp_label.setFont(font); temp_v.addWidget(self.temp_label)
        self.cpu_temp_label = QLabel("CPU Temperature: N/A"); self.cpu_temp_label.setFont(font); temp_v.addWidget(self.cpu_temp_label)
        self.gpu_temp_label = QLabel("GPU Temperature: N/A"); self.gpu_temp_label.setFont(font); temp_v.addWidget(self.gpu_temp_label)
        temp_group.setLayout(temp_v); status_layout.addWidget(temp_group)

        main_layout.addLayout(status_layout)
        self.main_widget.setLayout(main_layout)

    def _save_safety(self, *_):
        """Persist safety settings to config."""
        self.safety = {
            "enabled": bool(self.safety_enable.isChecked()),
            "cpu_crit": int(self.cpu_crit.value()),
            "water_crit": int(self.water_crit.value()),
            "hysteresis": int(self.hyst.value())
        }
        self.conf["safety"] = self.safety
        save_json_config(self.conf)

    def show_status_message(self, msg, timeout=5000):
        QTimer.singleShot(0, lambda: self._statusbar.showMessage(msg, timeout))

    # ---------------------- Profiles / Tray ----------------------
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

    def rebuild_tray_menu(self, selected_profile=None):
        self.tray_menu.clear()
        cur = QAction(f"Current profile: {selected_profile or '(none)'}", self); f=QFont(); f.setBold(True); cur.setFont(f); cur.setEnabled(False)
        self.tray_menu.addAction(cur); self.tray_menu.addSeparator()
        about_action = QAction("About", self); about_action.triggered.connect(self.show_about)
        run_on_start_action = QAction("Run on start", self); run_on_start_action.setCheckable(True)
        run_on_start_action.setChecked(self.conf["global"].get("run_on_start", False))
        run_on_start_action.toggled.connect(lambda ch: (self.conf["global"].__setitem__("run_on_start", ch), save_json_config(self.conf)))
        show_action = QAction("Show", self); show_action.triggered.connect(self.show)
        self.tray_menu.addAction(about_action); self.tray_menu.addAction(run_on_start_action); self.tray_menu.addAction(show_action)
        self.tray_menu.addSeparator()
        profiles_menu = QMenu("Select Profile", self)
        for pname,p in self.conf.get("profiles", {}).items():
            act = QAction(f"{pname} (Pump {p.get('pump_speed',0)} Fan {','.join(map(str,p.get('fan_speeds',[])))})", self)
            act.triggered.connect(partial(self.apply_profile_and_update_ui, pname, "tray"))
            profiles_menu.addAction(act)
        self.tray_menu.addMenu(profiles_menu); self.tray_menu.addSeparator()
        exit_action = QAction("Exit", self); exit_action.triggered.connect(QApplication.quit); self.tray_menu.addAction(exit_action)

    def show_about(self):
        QMessageBox.information(self, "About",
"""Mini Corsair iCUE for Linux
Profiles: ~/.liquidctl_gui.json (reads legacy ~/.LIquidctl_settings.json)
Creator: Nele
""")

    def profile_combo_selected(self, idx):
        pname = self.profile_combo.itemData(idx)
        if pname:
            self.apply_profile_and_update_ui(pname, source="dropdown")

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

    def block_slider_signals(self, block):
        for s in self.fan_sliders: s.blockSignals(block)
        self.pump_slider.blockSignals(block)

    # ---------------------- Device / permissions ----------------------
    def load_devices(self):
        try:
            r = run_cmd(["liquidctl","list","--json"], check=True)
            self.devices = json.loads(r.stdout)
            self.device_combo.clear()
            for dev in self.devices:
                self.device_combo.addItem(dev.get("description","Unknown Device"), dev)
            if self.devices:
                self.select_device(0)
                self.initialize_device()
        except Exception as e:
            self.show_status_message(f"Failed to load devices: {e}")

    def select_device(self, index):
        if 0<=index<len(self.devices):
            self.selected_device = self.device_combo.itemData(index)
            self.detect_features_from_status()
            self.initialize_device()
            self.update_status()

    def initialize_device(self):
        if not self.selected_device: return
        try:
            run_cmd(["liquidctl","-m", self.selected_device["description"], "initialize"], check=True)
        except Exception as e:
            self.show_status_message(f"Failed to initialize device: {e}")
        self.probe_pump_capability()

    def install_udev_rule_for_selected(self):
        """Install udev rules for the selected VID/PID with TAG+="uaccess" (no 0666)."""
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

    def show_permissions_help(self):
        QMessageBox.information(self, "Fix permissions – help",
"""This adds a rule so your device works without 'sudo'.

• Detects your device (Vendor ID and Product ID).
• Adds a rule that grants access to the logged-in user (TAG+="uaccess") for USB and HIDRAW.
• Safer than world-writable 0666.

After that, replug the USB device or relogin.
If you change device/brand later, click it again.""")

    # ---------------------- Status / parsing ----------------------
    def _iter_status_entries(self, status_data):
        """Yield all 'status' items across returned list (some drivers return multiple blocks)."""
        if not isinstance(status_data, list):
            return
        for block in status_data:
            if isinstance(block, dict):
                for it in block.get("status", []):
                    yield it

    def detect_features_from_status(self):
        """Detect fan count and pump presence from a single status read."""
        self.fan_count = 0; self.have_pump = False
        if not self.selected_device: return
        try:
            res = run_cmd(["liquidctl","-m", self.selected_device["description"], "status","--json"], check=True)
            status_data = json.loads(res.stdout)
            max_fan_idx = 0
            for it in self._iter_status_entries(status_data):
                k = (it.get("key","") or "").lower()
                if k.startswith("fan speed"):
                    m = re.search(r'fan speed\s+(\d+)', k)
                    if m:
                        max_fan_idx = max(max_fan_idx, int(m.group(1)))
                elif k.startswith("pump speed"):
                    self.have_pump = True
            self.fan_count = max_fan_idx or 6   # fallback to 6
        except Exception as e:
            self.show_status_message(f"Error detecting features: {e}")
            self.fan_count = 6
        font = QFont(); font.setPointSize(16)
        self.add_fan_controls(self.fan_count, font)
        self.update_pump_row_visibility()
        self._sync_all_fans_slider()

    def update_pump_row_visibility(self):
        visible = (self.have_pump and self.pump_supported)
        for i in range(self.pump_row.count()):
            w = self.pump_row.itemAt(i).widget()
            if w: w.setVisible(visible)

    def probe_pump_capability(self):
        """Try to set pump once; if not supported, hide the row."""
        if not self.have_pump:
            self.pump_supported = False
            self.update_pump_row_visibility()
            return
        ok = self._try_cmds(self._candidate_set_cmds("pump", None, 50), timeout=4)
        self.pump_supported = bool(ok)
        self.update_pump_row_visibility()
        if not self.pump_supported:
            self.show_status_message("Pump control not supported by this driver/device.")

    def update_status(self):
        if not self.selected_device: return
        self.update_system_info()
        status_parsed = False
        try:
            res = run_cmd(["liquidctl","-m", self.selected_device["description"], "status","--json"], check=True, timeout=6)
            data = json.loads(res.stdout)
            self._parse_json_and_update(data); status_parsed = True
        except Exception:
            # fallback to text
            try:
                res2 = run_cmd(["liquidctl","-m", self.selected_device["description"], "status"], check=True, timeout=6)
                self._parse_text_and_update(res2.stdout); status_parsed = True
            except Exception as e2:
                self.show_status_message(f"Error updating status: {e2}")

        # Temps (external) + safety check
        ct=get_cpu_temp(); self.cpu_temp_label.setText(f"CPU Temperature: {ct:.1f} °C" if ct is not None else "CPU Temperature: N/A")
        gt=get_gpu_temp(); self.gpu_temp_label.setText(f"GPU Temperature: {gt:.1f} °C" if gt is not None else "GPU Temperature: N/A")

        if status_parsed:
            self.check_safety_boost(ct, self._last_water_temp)

        self.update_tray_tooltip()

    def _parse_json_and_update(self, status_data):
        """Parse JSON exactly like the Commander Core output: 'Fan speed N', 'Pump speed', 'Water temperature'."""
        fan_map = {}          # idx -> (percent, rpm)
        pump = None
        wtemp = None
        for it in self._iter_status_entries(status_data):
            key = (it.get("key","") or "").lower()
            val = it.get("value", 0)
            if key.startswith("fan speed"):
                m = re.search(r'fan speed\s+(\d+)', key)
                if m:
                    idx = int(m.group(1))
                    rpm = int(val) if isinstance(val,(int,float)) else 0
                    fan_map[idx] = (self.rpm_to_percent(rpm), rpm)
            elif key.startswith("pump speed"):
                rpm = int(val) if isinstance(val,(int,float)) else 0
                pump = (self.rpm_to_percent(rpm, True), rpm)
            elif "water temperature" in key or "liquid temperature" in key or "coolant temperature" in key:
                try: wtemp = float(val)
                except: pass
        self._update_ui_from_maps(fan_map, pump, wtemp)

    def _parse_text_and_update(self, txt):
        """Fallback plain text parser."""
        fan_map = {}
        pump = None
        wtemp = None
        for line in txt.splitlines():
            l = line.strip().lower()
            # e.g. "Fan speed 3           292  rpm"
            m = re.search(r'fan speed\s+(\d+)\s+(\d+)\s*rpm', l)
            if m:
                idx=int(m.group(1)); rpm=int(m.group(2)); fan_map[idx]=(self.rpm_to_percent(rpm), rpm); continue
            m = re.search(r'pump speed\s+(\d+)\s*rpm', l)
            if m:
                rpm=int(m.group(1)); pump=(self.rpm_to_percent(rpm, True), rpm); continue
            m = re.search(r'(water|liquid|coolant)\s*temperature\s+([\d.]+)\s*°?c', l)
            if m:
                try: wtemp=float(m.group(2))
                except: pass
        self._update_ui_from_maps(fan_map, pump, wtemp)

    def _update_ui_from_maps(self, fan_map, pump, water_temp):
        """fan_map: {idx: (pct, rpm)} with idx starting at 1."""
        now=time.time()
        # ensure UI has rows for detected fans
        if fan_map:
            max_idx = max(fan_map.keys())
            if max_idx != self.fan_count:
                self.fan_count = max_idx
                font = QFont(); font.setPointSize(16)
                self.add_fan_controls(self.fan_count, font)

        # fans
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

        # pump
        if self.have_pump and self.pump_supported and pump:
            ppct, prpm = pump
            p = self.user_set_pump_speed if self.user_set_pump_speed else (None,0)
            if p[0] is None or now - p[1] > 3:
                self.pump_slider.blockSignals(True); self.pump_slider.setValue(ppct); self.pump_slider.blockSignals(False)
                self.pump_percent_inline.setText(f"{ppct} %")
            self.pump_label.setText(f"Pump Speed: {prpm} RPM"); self.pump_speed_label.setText(f"Pump Speed: {prpm} RPM"); self.pump_rpm_inline.setText(f"{prpm} RPM")
        else:
            self.pump_label.setText("Pump Speed: N/A"); self.pump_speed_label.setText("Pump Speed: N/A"); self.pump_rpm_inline.setText("N/A")

        # water temp
        self._last_water_temp = water_temp
        self.temp_label.setText(f"Water Temperature: {water_temp:.1f} °C" if water_temp is not None else "Water Temperature: N/A")
        self.save_sliders_to_conf()
        self._sync_all_fans_slider()

    # ---------------------- Safety (emergency boost) ----------------------
    def check_safety_boost(self, cpu_temp, water_temp):
        """If safety enabled and temp >= threshold, force 100% fans (+pump). Restore when cooled by hysteresis."""
        if not self.safety.get("enabled", False):
            if self._boost_active:
                self._restore_from_boost()
            return

        over = False
        if cpu_temp is not None and cpu_temp >= float(self.safety.get("cpu_crit", 85)):
            over = True
        if water_temp is not None and water_temp >= float(self.safety.get("water_crit", 45)):
            over = True

        if over and not self._boost_active:
            # store current values
            self._preboost = {
                "fans": [s.value() for s in self.fan_sliders],
                "pump": self.pump_slider.value()
            }
            # slam to 100%
            self.adjust_all_fans(100)
            if self.have_pump and self.pump_supported:
                self.pump_slider.setValue(100); self.pump_percent_inline.setText("100 %"); self.pump_apply_timer.start(100)
            self._boost_active = True
            self.show_status_message("Emergency boost: temps over threshold → all 100%", 4000)
            return

        if self._boost_active and not over:
            # cool-down: wait until both below threshold - hysteresis
            h = float(self.safety.get("hysteresis", 5))
            below_cpu = (cpu_temp is None) or (cpu_temp <= float(self.safety.get("cpu_crit",85)) - h)
            below_wat = (water_temp is None) or (water_temp <= float(self.safety.get("water_crit",45)) - h)
            if below_cpu and below_wat:
                self._restore_from_boost()

    def _restore_from_boost(self):
        if not self._preboost:
            self._boost_active = False
            return
        # restore previous sliders
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
        self._boost_active = False
        self._preboost = None
        self.show_status_message("Emergency boost ended: restored previous speeds", 4000)

    # ---------------------- Apply speeds ----------------------
    def _candidate_set_cmds(self, kind, index=None, percent=0):
        """Cross-driver set command candidates."""
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
        for c in cmds:
            try:
                run_cmd(c, check=True, timeout=timeout)
                return True
            except Exception as e:
                log.debug(f"command failed: {' '.join(c)} -> {e}")
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
        self.fan_apply_timer.start(800)
        self.save_sliders_to_conf()

    def adjust_fan_speed(self, fan_id, value):
        pct = round(value/10)*10
        if self.link_chk.isChecked():
            # when linked, moving any fan equals moving All Fans
            self.adjust_all_fans(pct)
            return
        s=self.fan_sliders[fan_id-1]; s.blockSignals(True); s.setValue(pct); s.blockSignals(False)
        rpm=self.percent_to_rpm(pct)
        if fan_id-1 < len(self.fan_percent_inline_labels): self.fan_percent_inline_labels[fan_id-1].setText(f"{pct} %")
        if fan_id-1 < len(self.fan_rpm_inline_labels): self.fan_rpm_inline_labels[fan_id-1].setText(f"{rpm} RPM")
        self.user_set_fan_speeds[fan_id]=(pct, time.time())
        self.fan_apply_timer.start(800); self.save_sliders_to_conf()

    def apply_all_fan_speeds(self):
        speeds=[s.value() for s in self.fan_sliders]
        def worker():
            for fan_id, pct in enumerate(speeds,1):
                self._try_cmds(self._candidate_set_cmds("fan", fan_id, pct))
        threading.Thread(target=worker, daemon=True).start()

    def adjust_pump_speed(self, value):
        pct = round(value/10)*10
        self.pump_slider.blockSignals(True); self.pump_slider.setValue(pct); self.pump_slider.blockSignals(False)
        rpm=self.percent_to_rpm(pct, True)
        self.pump_percent_inline.setText(f"{pct} %"); self.pump_rpm_inline.setText(f"{rpm} RPM")
        self.user_set_pump_speed=(pct, time.time())
        if self.have_pump and self.pump_supported: self.pump_apply_timer.start(800)
        self.save_sliders_to_conf()

    def apply_pump_speed(self):
        if not (self.user_set_pump_speed and self.have_pump and self.pump_supported): return
        pct,_=self.user_set_pump_speed
        def worker():
            self._try_cmds(self._candidate_set_cmds("pump", None, pct))
        threading.Thread(target=worker, daemon=True).start()

    # ---------------------- % <-> RPM mapping ----------------------
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

    # ---------------------- System info ----------------------
    def read_cpu_model(self):
        try:
            env=os.environ.copy(); env["LC_ALL"]="C"
            out=run_cmd(["lscpu"], check=True, env=env)
            for line in out.stdout.splitlines():
                if line.lower().startswith("model name:"):
                    return line.split(":",1)[1].strip()
        except Exception: pass
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line.lower():
                        return line.split(":",1)[1].strip()
        except Exception: pass
        return "N/A"

    def read_gpu_model(self):
        try:
            if shutil.which("nvidia-smi"):
                out=run_cmd(["nvidia-smi","--query-gpu=name","--format=csv,noheader"], check=True, timeout=2)
                line=out.stdout.strip().splitlines()[0].strip()
                if line: return line
        except Exception: pass
        try:
            out=run_cmd("lspci | grep -i ' vga ' -m1", shell=True, check=True, timeout=2)
            line=out.stdout.strip(); m=re.search(r'VGA compatible controller:\s*(.+)$', line, re.I)
            return m.group(1).strip() if m else (line or "N/A")
        except Exception: return "N/A"

    def read_os_pretty(self):
        name=""
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        name=line.split("=",1)[1].strip().strip('"'); break
        except Exception: pass
        if not name:
            try:
                out=run_cmd(["uname","-sr"], check=True)
                name=out.stdout.strip()
            except: name="Unknown OS"
        return name

    def read_ram_info(self):
        total=avail=None
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"): total=int(line.split()[1])*1024
                    elif line.startswith("MemAvailable:"): avail=int(line.split()[1])*1024
                    if total and avail: break
        except Exception: pass
        fmt=lambda b: f"{b/1024/1024/1024:.1f} GB"
        return f"{fmt(total)} total / {fmt(avail)} free" if total and avail else "N/A"

    def read_disk_info(self):
        try:
            du=shutil.disk_usage("/")
            fmt=lambda b: f"{b/1024/1024/1024:.1f} GB"
            return f"{fmt(du.total)} total / {fmt(du.free)} free"
        except Exception: return "N/A"

    def update_system_info(self):
        self.sys_os_label.setText(f"OS: {self.read_os_pretty()}")
        self.sys_cpu_label.setText(f"CPU: {self.read_cpu_model()}")
        self.sys_gpu_label.setText(f"GPU: {self.read_gpu_model()}")
        self.sys_ram_label.setText(f"RAM: {self.read_ram_info()}")
        self.sys_disk_label.setText(f"Disk: {self.read_disk_info()}")

    # ---------------------- Fans UI (dynamic) ----------------------
    def add_fan_controls(self, count, font):
        # clear
        for lay in getattr(self, "fan_rows_layouts", []):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w: w.setParent(None)
        self.fan_rows_layouts=[];
        for l in getattr(self,"fan_name_labels",[]): l.deleteLater()
        for l in getattr(self,"fan_rpm_inline_labels",[]): l.deleteLater()
        for l in getattr(self,"fan_percent_inline_labels",[]): l.deleteLater()
        for s in getattr(self,"fan_sliders",[]): s.deleteLater()
        self.fan_name_labels=[]; self.fan_rpm_inline_labels=[]; self.fan_percent_inline_labels=[]; self.fan_sliders=[]

        for i in range(count):
            row = QHBoxLayout()
            name_lbl = QLabel(f"Fan {i+1}"); name_lbl.setFont(font); name_lbl.setFixedWidth(NAME_COL_W)
            rpm_lbl  = QLabel("N/A");        rpm_lbl.setFont(font);  rpm_lbl.setFixedWidth(RPM_COL_W)
            perc_lbl = QLabel("0 %");        perc_lbl.setFont(font); perc_lbl.setFixedWidth(PCT_COL_W)
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(0,100); s.setTickInterval(10); s.setSingleStep(10)
            s.setTickPosition(QSlider.TickPosition.TicksBelow); s.setMinimumHeight(48); s.setStyleSheet(fan_slider_style)
            s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            s.valueChanged.connect(lambda v, fid=i+1: self.adjust_fan_speed(fid, v))
            for w in (name_lbl,rpm_lbl,perc_lbl,s): row.addWidget(w)
            self.control_layout.addLayout(row)
            self.fan_rows_layouts.append(row); self.fan_name_labels.append(name_lbl); self.fan_rpm_inline_labels.append(rpm_lbl); self.fan_percent_inline_labels.append(perc_lbl); self.fan_sliders.append(s)

    # ---------------------- Misc ----------------------
    def save_sliders_to_conf(self):
        self.conf["last_sliders"]={"fan_speeds":[s.value() for s in self.fan_sliders], "pump_speed": self.pump_slider.value()}
        save_json_config(self.conf)

    def update_tray_tooltip(self):
        lines=[self.temp_label.text(), self.cpu_temp_label.text(), self.gpu_temp_label.text()]
        for i,lbl in enumerate(self.fan_rpm_inline_labels,1): lines.append(f"Fan {i}: {lbl.text()}")
        lines.append(f"Pump: {self.pump_rpm_inline.text()}")
        self.tray_icon.setToolTip("\n".join(lines))

    def closeEvent(self, event):
        event.ignore(); self.hide()
        self.tray_icon.showMessage("Mini Corsair iCUE","Minimized to tray. Use 'Exit' to close.",
                                   QSystemTrayIcon.MessageIcon.Information, 2000)

# ---------------------- main ----------------------
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
