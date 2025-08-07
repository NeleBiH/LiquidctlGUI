import sys
import os
import time
import logging
import subprocess
import shutil
import threading
import re
import json
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QGroupBox, QComboBox,
    QSystemTrayIcon, QMenu, QMessageBox, QDialog,
    QFormLayout, QDialogButtonBox, QLineEdit, QInputDialog, QStyle, QSizePolicy, QStatusBar
)
from PyQt6.QtGui import QIcon, QAction, QFont
from PyQt6.QtCore import Qt, QTimer

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".LIquidctl_settings.json")

if not shutil.which("liquidctl"):
    app = QApplication(sys.argv)
    QMessageBox.critical(None, "Error", "liquidctl is not installed! Please install it and try again.")
    sys.exit(1)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

def get_linux_distribution():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.strip().split("=")[1].strip('"')
    except FileNotFoundError:
        return None

def install_lm_sensors(password):
    distro = get_linux_distribution()
    if not distro:
        return False

    install_commands = {
        "ubuntu": "apt-get install -y lm-sensors",
        "debian": "apt-get install -y lm-sensors",
        "fedora": "dnf install -y lm_sensors",
        "arch": "pacman -S --noconfirm lm-sensors",
        "manjaro": "pacman -S --noconfirm lm-sensors",
    }

    command = install_commands.get(distro)
    if not command:
        return False

    full_command = f'echo "{password}" | sudo -S {command}'
    try:
        subprocess.run(full_command, shell=True, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install lm-sensors: {e.stderr}")
        return False

def run_sensors_detect(password):
    full_command = f'echo "{password}" | sudo -S sensors-detect --auto'
    try:
        subprocess.run(full_command, shell=True, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to run sensors-detect: {e.stderr}")
        return False

def check_device_access():
    try:
        result = subprocess.run(["liquidctl", "list"], capture_output=True, text=True)
        if "Permission denied" not in result.stderr:
            return True
        app = QApplication(sys.argv)
        reply = QMessageBox.question(
            None, 'Permissions required',
            'To run without sudo, udev rules must be configured.\n'
            'Do you want to automatically configure access rules?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            password, ok = QInputDialog.getText(
                None, 'Confirmation',
                'Enter sudo password for configuration:',
                QLineEdit.EchoMode.Password
            )
            if ok and password:
                udev_rule = '''SUBSYSTEM=="usb", ATTR{idVendor}=="1b1c", ATTR{idProduct}=="0c0a", MODE="0666", GROUP="plugdev"'''
                cmd = f'echo "{password}" | sudo -S bash -c \'echo "{udev_rule}" > /etc/udev/rules.d/99-liquidctl.rules && udevadm control --reload-rules && udevadm trigger\''
                subprocess.run(cmd, shell=True, capture_output=True, text=True)
                QMessageBox.information(None, 'Success', 'Udev rules have been set!\nPlease log out and log back in.')
                sys.exit(0)
    except Exception as e:
        logger.error(f"Error checking access: {str(e)}")
    return False

def run_with_sudo():
    app = QApplication(sys.argv)
    password, ok = QInputDialog.getText(
        None, 'Confirmation required',
        'The application requires root privileges.\nEnter your sudo password:',
        QLineEdit.EchoMode.Password
    )
    if ok and password:
        cmd = f'echo "{password}" | sudo -S python3 {" ".join(sys.argv)}'
        subprocess.run(cmd, shell=True)
    sys.exit(0)

def load_json_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                conf = json.load(f)
            if not isinstance(conf, dict):
                raise Exception("Malformed config")
            return conf
        except Exception:
            pass
    return {
        "global": {"run_on_start": False, "last_profile": None},
        "profiles": {},
        "last_sliders": {"fan_speeds": [], "pump_speed": 0}
    }

def save_json_config(conf):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(conf, f, indent=2)
        logger.debug("Config saved.")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

# CPU temp — pokušava najčešće pattern-e
def get_cpu_temp():
    try:
        out = subprocess.run(['sensors'], capture_output=True, text=True)
        for line in out.stdout.splitlines():
            # Intel: Package id 0, Core 0, Core 1, AMD: Tctl, k10temp
            m = re.search(r'(Package id \d+|Tctl|Core \d+|k10temp|CPU Temperature|Physical id \d+):\s*\+?([\d.]+)', line)
            if m:
                return float(m.group(2))
            # fallback za temp1, temp2 ali bez GPU
            m2 = re.search(r'temp\d+:\s*\+?([\d.]+)', line)
            if m2:
                return float(m2.group(1))
    except Exception as e:
        logger.error(f"CPU temp error: {e}")
    return None

# GPU temp — nvidia-smi i sensors fallback
def get_gpu_temp():
    # Nvidia
    try:
        out = subprocess.run(
            ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=3
        )
        lines = out.stdout.strip().splitlines()
        for l in lines:
            try:
                temp = float(l.strip())
                if temp > 0:
                    return temp
            except:
                continue
    except Exception:
        pass
    # AMD/Intel sensors
    try:
        out = subprocess.run(['sensors'], capture_output=True, text=True, timeout=3)
        for line in out.stdout.splitlines():
            # AMD: edge, junction, temp1/2
            m = re.search(r'(edge|junction):\s*\+?([\d.]+)', line, re.I)
            if m:
                return float(m.group(2))
            # Intel: temp1, GPU Temp, itd.
            m2 = re.search(r'(GPU.*Temp|temp\d+):\s*\+?([\d.]+)', line, re.I)
            if m2 and float(m2.group(2)) < 120:  # GPU temp obično ispod 100C, CPU često gore
                return float(m2.group(2))
    except Exception:
        pass
    return None

if not check_device_access():
    run_with_sudo()

fan_slider_style = """
QSlider::groove:horizontal {
    border: 1px solid #999999;
    height: 8px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #B1B1B1, stop:1 #c4c4c4);
    margin: 2px 0;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #0080ff);
    border: 1px solid #313755;
    width: 30px;
    margin: -2px 0;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0099FF, stop:1 #0067B1);
}
QSlider::tick-mark:horizontal {
    background: #ffffff;
    height: 2px;
    width: 2px;
    margin: 0px 0;
}
"""
pump_slider_style = """
QSlider::groove:horizontal {
    border: 1px solid #999999;
    height: 8px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #B1B1B1, stop:1 #c4c4c4);
    margin: 2px 0;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
    border: 1px solid #5c5c5c;
    width: 30px;
    margin: -2px 0;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #800080, stop:1 #BA55D3);
}
QSlider::tick-mark:horizontal {
    background: #ffffff;
    height: 2px;
    width: 2px;
    margin: 0px 0;
}
"""

class ProfileDialog(QDialog):
    def __init__(self, parent=None, existing_name="", fan_speeds=None, pump_speed=0, fan_count=6):
        super().__init__(parent)
        self.setWindowTitle("Create/Edit Profile")
        self.setGeometry(200, 200, 340, 250 + (fan_count - 1) * 36)
        layout = QFormLayout()
        font = QFont()
        font.setPointSize(16)
        self.name_input = QLineEdit()
        self.name_input.setFont(font)
        self.name_input.setText(existing_name)
        layout.addRow("Profile Name:", self.name_input)
        self.fan_speed_labels = []
        self.fan_speed_sliders = []
        for i in range(fan_count):
            label = QLabel(f"Fan {i+1} Speed: {fan_speeds[i] if fan_speeds else 0}%")
            label.setFont(font)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(100)
            slider.setTickInterval(10)
            slider.setSingleStep(10)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setMinimumHeight(48)
            slider.setValue(fan_speeds[i] if fan_speeds else 0)
            slider.setStyleSheet(fan_slider_style)
            slider.valueChanged.connect(lambda value, idx=i: self.update_fan_speed_label(idx))
            layout.addRow(label)
            layout.addWidget(slider)
            self.fan_speed_labels.append(label)
            self.fan_speed_sliders.append(slider)
        self.pump_speed_label = QLabel(f"Pump Speed: {pump_speed}%")
        self.pump_speed_label.setFont(font)
        self.pump_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.pump_speed_slider.setMinimum(0)
        self.pump_speed_slider.setMaximum(100)
        self.pump_speed_slider.setTickInterval(10)
        self.pump_speed_slider.setSingleStep(10)
        self.pump_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.pump_speed_slider.setMinimumHeight(48)
        self.pump_speed_slider.setValue(pump_speed)
        self.pump_speed_slider.setStyleSheet(pump_slider_style)
        self.pump_speed_slider.valueChanged.connect(self.update_pump_speed_label)
        layout.addRow(self.pump_speed_label)
        layout.addWidget(self.pump_speed_slider)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.setMinimumHeight(48)
        self.button_box.setFont(font)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)
        self.setLayout(layout)
    def update_fan_speed_label(self, idx):
        speed = self.fan_speed_sliders[idx].value()
        speed = round(speed / 10) * 10
        self.fan_speed_sliders[idx].setValue(speed)
        self.fan_speed_labels[idx].setText(f"Fan {idx+1} Speed: {speed}%")
    def update_pump_speed_label(self):
        speed = self.pump_speed_slider.value()
        speed = round(speed / 10) * 10
        self.pump_speed_slider.setValue(speed)
        self.pump_speed_label.setText(f"Pump Speed: {speed}%")
    def get_values(self):
        name = self.name_input.text().strip()
        if not name:
            name = f"Pump {self.pump_speed_slider.value()} Fan {','.join(str(slider.value()) for slider in self.fan_speed_sliders)}"
        fan_speeds = [slider.value() for slider in self.fan_speed_sliders]
        pump_speed = self.pump_speed_slider.value()
        return {"name": name, "fan_speeds": fan_speeds, "pump_speed": pump_speed}

class LiquidCtlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mini Corsair iCUE for Linux")
        self.setGeometry(100, 100, 700, 520)

        self.conf = load_json_config()
        self.fan_count = 6
        self.devices = []
        self.selected_device = None
        self.fan_speeds = {}
        self.pump_speed = None
        self.water_temp = None
        self.user_set_fan_speeds = {}
        self.user_set_pump_speed = None
        self.min_fan_rpm = 200
        self.max_fan_rpm = 2000
        self.min_pump_rpm = 1000
        self.max_pump_rpm = 2700

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(2000)

        self.fan_apply_timer = QTimer()
        self.fan_apply_timer.setSingleShot(True)
        self.fan_apply_timer.timeout.connect(self.apply_all_fan_speeds)
        self.pump_apply_timer = QTimer()
        self.pump_apply_timer.setSingleShot(True)
        self.pump_apply_timer.timeout.connect(self.apply_pump_speed)

        icon_paths = [
            os.path.join(os.path.dirname(__file__), "icon.png"),
            "/usr/share/icons/liquidctl-gui.png",
            "/usr/local/share/icons/liquidctl-gui.png"
        ]
        app_icon = None
        for path in icon_paths:
            if os.path.exists(path):
                app_icon = QIcon(path)
                break
        else:
            app_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(app_icon)
        self.tray_menu = QMenu()
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        self.check_and_install_lm_sensors()
        self.init_ui()
        self.load_devices()
        self.update_status()
        self.rebuild_tray_menu(selected_profile=self.conf["global"].get("last_profile", None))

    def save_conf(self):
        save_json_config(self.conf)

    def check_and_install_lm_sensors(self):
        if not shutil.which("sensors"):
            reply = QMessageBox.question(
                self, 'lm-sensors not found',
                'The `sensors` command is not found. This is required to display CPU/GPU temperature.\n'
                'Do you want to automatically install `lm-sensors`?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                password, ok = QInputDialog.getText(
                    self, 'Sudo password',
                    'Enter your sudo password to install `lm-sensors`:',
                    QLineEdit.EchoMode.Password
                )
                if ok and password:
                    if install_lm_sensors(password):
                        QMessageBox.information(self, 'Success', '`lm-sensors` installed successfully.')
                        if run_sensors_detect(password):
                            QMessageBox.information(self, 'Success', '`sensors-detect` ran successfully.')
                        else:
                            QMessageBox.warning(self, 'Warning', 'Failed to run `sensors-detect`.')
                    else:
                        QMessageBox.warning(self, 'Error', 'Failed to install `lm-sensors`.')

    def show_status_message(self, message, timeout=5000):
        self.statusBar.showMessage(message, timeout)

    def init_ui(self):
        self.main_widget = QWidget()
        main_layout = QVBoxLayout()
        font = QFont()
        font.setPointSize(16)

        device_group = QGroupBox("Device")
        device_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setFont(font)
        self.device_combo.setMinimumHeight(48)
        self.device_combo.currentIndexChanged.connect(self.select_device)
        device_layout.addWidget(QLabel("Select Device:"))
        device_layout.addWidget(self.device_combo)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMinimumHeight(48)
        self.refresh_button.setFont(font)
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.clicked.connect(self.load_devices)
        device_layout.addWidget(self.refresh_button)
        device_group.setLayout(device_layout)
        main_layout.addWidget(device_group)

        profiles_group = QGroupBox("Profiles")
        profiles_layout = QHBoxLayout()
        profiles_label = QLabel("Profiles:")
        profiles_label.setFont(font)
        self.profile_combo = QComboBox()
        self.profile_combo.setFont(font)
        self.profile_combo.setMinimumHeight(48)
        self.update_profile_combo()
        self.profile_combo.currentIndexChanged.connect(self.profile_combo_selected)
        create_profile_button = QPushButton("Create Profile")
        create_profile_button.setFont(font)
        create_profile_button.setMinimumHeight(48)
        create_profile_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        create_profile_button.clicked.connect(self.create_profile)
        edit_profile_button = QPushButton("Edit Profile")
        edit_profile_button.setFont(font)
        edit_profile_button.setMinimumHeight(48)
        edit_profile_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        edit_profile_button.clicked.connect(self.edit_profile)
        delete_profile_button = QPushButton("Delete Profile")
        delete_profile_button.setFont(font)
        delete_profile_button.setMinimumHeight(48)
        delete_profile_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        delete_profile_button.clicked.connect(self.delete_profile)
        profiles_layout.addWidget(profiles_label)
        profiles_layout.addWidget(self.profile_combo)
        profiles_layout.addWidget(create_profile_button)
        profiles_layout.addWidget(edit_profile_button)
        profiles_layout.addWidget(delete_profile_button)
        profiles_group.setLayout(profiles_layout)
        main_layout.addWidget(profiles_group)

        self.control_group = QGroupBox("Fan & Pump Control")
        self.control_layout = QVBoxLayout()
        self.pump_label = QLabel("Pump Speed: N/A")
        self.pump_label.setFont(font)
        self.pump_slider = QSlider(Qt.Orientation.Horizontal)
        self.pump_slider.setMinimum(0)
        self.pump_slider.setMaximum(100)
        self.pump_slider.setTickInterval(10)
        self.pump_slider.setSingleStep(10)
        self.pump_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.pump_slider.setMinimumHeight(48)
        self.pump_slider.setStyleSheet(pump_slider_style)
        self.pump_slider.valueChanged.connect(self.adjust_pump_speed)
        self.control_layout.addWidget(self.pump_label)
        self.control_layout.addWidget(self.pump_slider)
        self.fan_labels = []
        self.fan_sliders = []
        self.fan_status_labels = []
        self.fan_status_layout = QVBoxLayout()
        self.add_fan_controls(6, font)  # initial default 6
        self.control_group.setLayout(self.control_layout)
        main_layout.addWidget(self.control_group)

        status_layout = QHBoxLayout()
        self.fan_status_group = QGroupBox("Fan Speeds")
        self.fan_status_layout = QVBoxLayout()
        self.fan_status_labels = []
        for i in range(6):
            label = QLabel(f"Fan {i+1}: N/A")
            label.setFont(font)
            self.fan_status_layout.addWidget(label)
            self.fan_status_labels.append(label)
        self.fan_status_group.setLayout(self.fan_status_layout)
        status_layout.addWidget(self.fan_status_group)

        self.pump_temp_group = QGroupBox("Temperature")
        pump_temp_layout = QVBoxLayout()
        self.temp_label = QLabel("Water Temperature: N/A")
        self.temp_label.setFont(font)
        self.pump_speed_label = QLabel("Pump Speed: N/A")
        self.pump_speed_label.setFont(font)
        pump_temp_layout.addWidget(self.temp_label)
        pump_temp_layout.addWidget(self.pump_speed_label)
        self.cpu_temp_label = QLabel("CPU Temperature: N/A")
        self.cpu_temp_label.setFont(font)
        pump_temp_layout.addWidget(self.cpu_temp_label)
        self.gpu_temp_label = QLabel("GPU Temperature: N/A")
        self.gpu_temp_label.setFont(font)
        pump_temp_layout.addWidget(self.gpu_temp_label)
        self.pump_temp_group.setLayout(pump_temp_layout)
        status_layout.addWidget(self.pump_temp_group)
        main_layout.addLayout(status_layout)

        self.main_widget.setLayout(main_layout)
        self.setCentralWidget(self.main_widget)
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.rebuild_tray_menu(selected_profile=self.conf["global"].get("last_profile", None))

    def add_fan_controls(self, count, font):
        # Clean old
        for l in getattr(self, "fan_labels", []):
            self.control_layout.removeWidget(l)
            l.deleteLater()
        for s in getattr(self, "fan_sliders", []):
            self.control_layout.removeWidget(s)
            s.deleteLater()
        self.fan_labels = []
        self.fan_sliders = []
        for i in range(count):
            label = QLabel(f"Fan {i+1} Speed: N/A")
            label.setFont(font)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(100)
            slider.setTickInterval(10)
            slider.setSingleStep(10)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setMinimumHeight(48)
            slider.setStyleSheet(fan_slider_style)
            slider.valueChanged.connect(lambda value, fan_id=i+1: self.adjust_fan_speed(fan_id, value))
            self.control_layout.addWidget(label)
            self.control_layout.addWidget(slider)
            self.fan_labels.append(label)
            self.fan_sliders.append(slider)

    def save_sliders_to_conf(self):
        fan_speeds = [s.value() for s in self.fan_sliders]
        pump_speed = self.pump_slider.value()
        self.conf["last_sliders"] = {"fan_speeds": fan_speeds, "pump_speed": pump_speed}
        self.save_conf()

    def rebuild_tray_menu(self, selected_profile=None):
        self.tray_menu.clear()
        if selected_profile:
            tr = f"Current profile: {selected_profile}"
        else:
            tr = "Current profile: (none)"
        current_item = QAction(tr, self)
        current_item.setEnabled(False)
        font = QFont()
        font.setBold(True)
        current_item.setFont(font)
        self.tray_menu.addAction(current_item)
        self.tray_menu.addSeparator()
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        run_on_start_action = QAction("Run on start", self)
        run_on_start_action.setCheckable(True)
        run_on_start_action.setChecked(self.conf["global"].get("run_on_start", False))
        run_on_start_action.toggled.connect(self.toggle_run_on_start)
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        profiles_menu = QMenu("Select Profile", self)
        for pname, pdata in self.conf.get("profiles", {}).items():
            fan_speeds = pdata.get("fan_speeds", [])
            pump_speed = pdata.get("pump_speed", 0)
            display_name = f"{pname} (Pump {pump_speed} Fan {','.join(map(str, fan_speeds))})"
            profile_action = QAction(display_name, self)
            profile_action.triggered.connect(partial(self.apply_profile_and_update_ui, pname, "tray"))
            profiles_menu.addAction(profile_action)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(QApplication.quit)
        self.tray_menu.addAction(about_action)
        self.tray_menu.addAction(run_on_start_action)
        self.tray_menu.addAction(show_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addMenu(profiles_menu)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(exit_action)

    def toggle_run_on_start(self, checked):
        self.conf["global"]["run_on_start"] = checked
        self.save_conf()

    def show_about(self):
        QMessageBox.information(self, "About", """
Mini Corsair iCUE for Linux
Saves data and profiles in ~/.LIquidctl_settings.json
Creator: Nele
""")

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Mini Corsair iCUE",
            "The application has been minimized to the system tray. Use 'Exit' to close.",
            QSystemTrayIcon.MessageIcon.Information, 2000
        )

    def update_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for pname in self.conf.get("profiles", {}):
            pdata = self.conf["profiles"][pname]
            fan_speeds = pdata.get("fan_speeds", [])
            pump_speed = pdata.get("pump_speed", 0)
            display_name = f"{pname} (Pump {pump_speed} Fan {','.join(map(str, fan_speeds))})"
            self.profile_combo.addItem(display_name, pname)
        if self.conf["global"].get("last_profile"):
            idx = self.profile_combo.findData(self.conf["global"]["last_profile"])
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    def profile_combo_selected(self, idx):
        pname = self.profile_combo.itemData(idx)
        if pname:
            self.apply_profile_and_update_ui(pname, source="dropdown")

    def create_profile(self):
        current_fans = [s.value() for s in self.fan_sliders]
        current_pump = self.pump_slider.value()
        dialog = ProfileDialog(self, fan_count=self.fan_count, fan_speeds=current_fans, pump_speed=current_pump)
        if dialog.exec():
            values = dialog.get_values()
            pname = values["name"]
            data = {"fan_speeds": values["fan_speeds"], "pump_speed": values["pump_speed"]}
            self.conf.setdefault("profiles", {})
            self.conf["profiles"][pname] = data
            self._update_profiles_ui(selected_profile=pname)

    def edit_profile(self):
        pname = self.profile_combo.currentData()
        if not pname or pname not in self.conf.get("profiles", {}):
            QMessageBox.warning(self, "Warning", "Please select a profile to edit.")
            return
        pdata = self.conf["profiles"][pname]
        fan_speeds = pdata.get("fan_speeds", [0]*self.fan_count)
        pump_speed = pdata.get("pump_speed", 0)
        dialog = ProfileDialog(self, pname, fan_speeds=fan_speeds, pump_speed=pump_speed, fan_count=self.fan_count)
        if dialog.exec():
            values = dialog.get_values()
            new_name = values["name"]
            self.conf["profiles"][new_name] = {
                "fan_speeds": values["fan_speeds"],
                "pump_speed": values["pump_speed"]
            }
            if new_name != pname:
                del self.conf["profiles"][pname]
            self._update_profiles_ui(selected_profile=new_name)
            if pname == self.conf["global"].get("last_profile"):
                self.apply_profile_and_update_ui(new_name)

    def delete_profile(self):
        pname = self.profile_combo.currentData()
        if not pname or pname not in self.conf.get("profiles", {}):
            QMessageBox.warning(self, "Warning", "Please select a profile to delete.")
            return
        reply = QMessageBox.question(self, "Confirmation", "Are you sure you want to delete the profile?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if pname == self.conf["global"].get("last_profile"):
                self.conf["global"]["last_profile"] = None
            del self.conf["profiles"][pname]
            self._update_profiles_ui(selected_profile=self.conf["global"].get("last_profile"))

    def _update_profiles_ui(self, selected_profile=None):
        self.save_conf()
        self.update_profile_combo()
        self.rebuild_tray_menu(selected_profile=selected_profile)

    def apply_profile_and_update_ui(self, pname, source="dropdown"):
        conf_profiles = self.conf.get("profiles", {})
        if not (isinstance(pname, str) and pname in conf_profiles):
            return
        values = conf_profiles[pname]
        fan_speeds = values.get("fan_speeds", [0]*self.fan_count)
        pump_speed = values.get("pump_speed", 0)
        self.block_slider_signals(True)
        for i in range(min(self.fan_count, len(fan_speeds))):
            self.fan_sliders[i].setValue(fan_speeds[i])
            self.user_set_fan_speeds[i+1] = (fan_speeds[i], time.time())
            self.fan_labels[i].setText(f"Fan {i+1} Speed: {self.percent_to_rpm(fan_speeds[i])} RPM")
        self.pump_slider.setValue(pump_speed)
        self.user_set_pump_speed = (pump_speed, time.time())
        self.pump_label.setText(f"Pump Speed: {self.percent_to_rpm(pump_speed, is_pump=True)} RPM")
        if source == "tray":
            idx = self.profile_combo.findData(pname)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.conf["global"]["last_profile"] = pname
        self.save_sliders_to_conf()
        self.block_slider_signals(False)
        self.fan_apply_timer.start(1500)
        self.pump_apply_timer.start(1500)
        self.update_profile_combo()
        self.rebuild_tray_menu(selected_profile=pname)

    def block_slider_signals(self, block):
        for s in self.fan_sliders:
            s.blockSignals(block)
        self.pump_slider.blockSignals(block)

    def update_tray_tooltip(self):
        tooltip_lines = []
        tooltip_lines.append(self.temp_label.text())
        tooltip_lines.append(self.cpu_temp_label.text())
        tooltip_lines.append(self.gpu_temp_label.text())
        for i, lbl in enumerate(self.fan_status_labels):
            tooltip_lines.append(lbl.text())
        tooltip_lines.append(self.pump_speed_label.text())
        self.tray_icon.setToolTip('\n'.join(tooltip_lines))

    def update_status(self):
        if not self.selected_device:
            return
        try:
            cmd = ["liquidctl", "-m", self.selected_device["description"], "status", "--json"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
            try:
                data = json.loads(result.stdout)
                self.parse_json_status(data)
            except Exception:
                self.parse_text_status(result.stdout)
        except Exception as e:
            self.show_status_message(f"Error updating status: {e}")

        cpu_temp = get_cpu_temp()
        if cpu_temp is not None:
            self.cpu_temp_label.setText(f"CPU Temperature: {cpu_temp:.1f} °C")
        else:
            self.cpu_temp_label.setText("CPU Temperature: N/A")

        gpu_temp = get_gpu_temp()
        if gpu_temp is not None:
            self.gpu_temp_label.setText(f"GPU Temperature: {gpu_temp:.1f} °C")
        else:
            self.gpu_temp_label.setText("GPU Temperature: N/A")

        self.update_tray_tooltip()

    def parse_json_status(self, status_data):
        if not status_data or not isinstance(status_data, list) or "status" not in status_data[0]:
            self.update_ui_with_status({}, None, None)
            return
        fan_speeds = {}
        pump_speed = None
        water_temp = None
        device_status = status_data[0].get("status", [])
        for item in device_status:
            key = item.get("key", "").lower()
            value = item.get("value", 0)
            if "fan speed" in key:
                m = re.search(r"fan speed (\d+)", key)
                if m:
                    fan_num = m.group(1)
                    rpm = int(value) if isinstance(value, (int, float)) else 0
                    percent = self.rpm_to_percent(rpm)
                    fan_speeds[f"Fan {fan_num}"] = (percent, rpm)
            elif "pump speed" in key:
                rpm = int(value) if isinstance(value, (int, float)) else 0
                percent = self.rpm_to_percent(rpm, is_pump=True)
                pump_speed = (percent, rpm)
            elif "water temperature" in key:
                water_temp = float(value) if isinstance(value, (int, float)) else None
        self.update_ui_with_status(fan_speeds, pump_speed, water_temp)

    def parse_text_status(self, output):
        # fallback, not needed for most devices
        pass

    def update_ui_with_status(self, fan_speeds, pump_speed, water_temp):
        now = time.time()
        for i in range(self.fan_count):
            fan_key = f"Fan {i+1}"
            if fan_key in fan_speeds:
                percent, rpm = fan_speeds[fan_key]
                u_speed = self.user_set_fan_speeds.get(i+1, (None, 0))
                if u_speed[0] is None or now - u_speed[1] > 3:
                    self.fan_sliders[i].blockSignals(True)
                    self.fan_sliders[i].setValue(percent)
                    self.fan_sliders[i].blockSignals(False)
                self.fan_labels[i].setText(f"Fan {i+1} Speed: {rpm} RPM")
                if i < len(self.fan_status_labels):
                    self.fan_status_labels[i].setText(f"Fan {i+1}: {rpm} RPM")
            else:
                self.fan_labels[i].setText(f"Fan {i+1} Speed: N/A")
                if i < len(self.fan_status_labels):
                    self.fan_status_labels[i].setText(f"Fan {i+1}: N/A")
        if pump_speed:
            pump_percent, pump_rpm = pump_speed
            p = self.user_set_pump_speed if self.user_set_pump_speed else (None, 0)
            if p[0] is None or now - p[1] > 3:
                self.pump_slider.blockSignals(True)
                self.pump_slider.setValue(pump_percent)
                self.pump_slider.blockSignals(False)
            self.pump_label.setText(f"Pump Speed: {pump_rpm} RPM")
            self.pump_speed_label.setText(f"Pump Speed: {pump_rpm} RPM")
        else:
            self.pump_label.setText("Pump Speed: N/A")
            self.pump_speed_label.setText("Pump Speed: N/A")
        if water_temp is not None:
            self.temp_label.setText(f"Water Temperature: {water_temp} °C")
        else:
            self.temp_label.setText("Water Temperature: N/A")
        self.save_sliders_to_conf()
        self.update_tray_tooltip()

    def load_devices(self):
        try:
            result = subprocess.run(["liquidctl", "list", "--json"], capture_output=True, text=True, check=True)
            self.devices = json.loads(result.stdout)
            self.device_combo.clear()
            for dev in self.devices:
                desc = dev.get("description", "Unknown Device")
                self.device_combo.addItem(desc, dev)
            if self.devices:
                self.select_device(0)
                self.initialize_device()
        except Exception as e:
            self.show_status_message(f"Failed to load devices: {e}")

    def select_device(self, index):
        if 0 <= index < len(self.devices):
            self.selected_device = self.device_combo.itemData(index)
            self.detect_fan_count()
            self.update_status()
            self.initialize_device()

    def initialize_device(self):
        if not self.selected_device:
            return
        try:
            cmd = ["liquidctl", "-m", self.selected_device["description"], "initialize"]
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except Exception as e:
            self.show_status_message(f"Failed to initialize device: {e}")

    def detect_fan_count(self):
        if not self.selected_device:
            self.fan_count = 0
            return
        try:
            cmd = ["liquidctl", "-m", self.selected_device["description"], "status", "--json"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            status_data = json.loads(result.stdout)
            count = 0
            for item in status_data[0].get("status", []):
                if "fan speed" in item.get("key", "").lower():
                    count += 1
            if count == 0:
                count = 6
            self.fan_count = count
            logger.debug(f"Detected {self.fan_count} fans!")
        except Exception as e:
            self.show_status_message(f"Error detecting fan count: {e}")
            self.fan_count = 6
        font = QFont()
        font.setPointSize(16)
        self.add_fan_controls(self.fan_count, font)
        for l in getattr(self, "fan_status_labels", []):
            self.fan_status_layout.removeWidget(l)
            l.deleteLater()
        self.fan_status_labels = []
        for i in range(self.fan_count):
            label = QLabel(f"Fan {i+1}: N/A")
            label.setFont(font)
            self.fan_status_layout.addWidget(label)
            self.fan_status_labels.append(label)
        self.main_widget.adjustSize()

    def update_controls(self):
        dev = self.selected_device
        if not dev:
            return
        desc = dev["description"].lower()
        if "corsair commander core" in desc:
            for slider in self.fan_sliders:
                slider.setEnabled(True)
            self.pump_slider.setEnabled(True)

    def adjust_fan_speed(self, fan_id, value):
        speed_percent = round(value / 10) * 10
        self.fan_sliders[fan_id-1].blockSignals(True)
        self.fan_sliders[fan_id-1].setValue(speed_percent)
        self.fan_sliders[fan_id-1].blockSignals(False)
        rpm = self.percent_to_rpm(speed_percent)
        self.fan_labels[fan_id-1].setText(f"Fan {fan_id} Speed: {rpm} RPM")
        now = time.time()
        self.user_set_fan_speeds[fan_id] = (speed_percent, now)
        self.fan_apply_timer.start(1500)
        self.save_sliders_to_conf()

    def apply_all_fan_speeds(self):
        speeds = [self.fan_sliders[i].value() for i in range(self.fan_count)]
        def worker():
            for fan_id, speed_percent in enumerate(speeds, 1):
                try:
                    cmd = [
                        "liquidctl", "-m", self.selected_device["description"],
                        "set", f"fan{fan_id}", "speed", str(speed_percent)
                    ]
                    subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
                    logger.debug(f"Fan {fan_id} set to {speed_percent}% ({' '.join(cmd)})")
                except Exception as e:
                    self.show_status_message(f"Failed to set fan {fan_id} speed: {e}")
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def adjust_pump_speed(self):
        speed_percent = self.pump_slider.value()
        speed_percent = round(speed_percent / 10) * 10
        self.pump_slider.blockSignals(True)
        self.pump_slider.setValue(speed_percent)
        self.pump_slider.blockSignals(False)
        rpm = self.percent_to_rpm(speed_percent, is_pump=True)
        self.pump_label.setText(f"Pump Speed: {rpm} RPM")
        now = time.time()
        self.user_set_pump_speed = (speed_percent, now)
        self.pump_apply_timer.start(1500)
        self.save_sliders_to_conf()

    def apply_pump_speed(self):
        speed_percent, _ = self.user_set_pump_speed
        def worker():
            try:
                cmd = [
                    "liquidctl", "-m", self.selected_device["description"],
                    "set", "pump", "speed", str(speed_percent)
                ]
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
                logger.debug(f"Pump set to {speed_percent}% ({' '.join(cmd)})")
            except Exception as e:
                self.show_status_message(f"Failed to set pump speed: {e}")
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def percent_to_rpm(self, percent, is_pump=False):
        if is_pump:
            min_rpm = self.min_pump_rpm
            max_rpm = self.max_pump_rpm
        else:
            min_rpm = self.min_fan_rpm
            max_rpm = self.max_fan_rpm
        if percent <= 20:
            return min_rpm
        elif percent >= 100:
            return max_rpm
        else:
            rpm_range = max_rpm - min_rpm
            percent_range = 100 - 20
            rpm = min_rpm + (rpm_range * (percent - 20) / percent_range)
            return int(round(rpm / 100) * 100)

    def rpm_to_percent(self, rpm, is_pump=False):
        if is_pump:
            min_rpm = self.min_pump_rpm
            max_rpm = self.max_pump_rpm
        else:
            min_rpm = self.min_fan_rpm
            max_rpm = self.max_fan_rpm
        if rpm <= min_rpm:
            return 20
        if rpm >= max_rpm:
            return 100
        percent_range = 100 - 20
        rpm_range = max_rpm - min_rpm
        percent = 20 + ((rpm - min_rpm) / rpm_range) * percent_range
        return int(round(percent / 10) * 10)

def main():
    app = QApplication(sys.argv)
    icon_paths = [
        os.path.join(os.path.dirname(__file__), "icon.png"),
        "/usr/share/icons/liquidctl-gui.png",
        "/usr/local/share/icons/liquidctl-gui.png"
    ]
    for path in icon_paths:
        if os.path.exists(path):
            app.setWindowIcon(QIcon(path))
            break
    gui = LiquidCtlGUI()
    gui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
