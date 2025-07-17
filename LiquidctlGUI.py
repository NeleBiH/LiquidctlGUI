import sys
import json
import subprocess
import logging
import time
import configparser
import os
import re
from getpass import getpass
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QSlider, QGroupBox, QComboBox,
                             QSystemTrayIcon, QMenu, QCheckBox, QMessageBox, QDialog,
                             QFormLayout, QDialogButtonBox, QLineEdit, QInputDialog, QStyle)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QTimer

# Postavljanje logginga
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("liquidctl_gui_debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def check_device_access():
    """Provjeri da li korisnik ima pristup uređajima bez sudo-a"""
    try:
        result = subprocess.run(["liquidctl", "list"],
                                capture_output=True,
                                text=True)
        if "Permission denied" not in result.stderr:
            return True

        app = QApplication(sys.argv)
        reply = QMessageBox.question(
            None, 'Potrebne ovlasti',
            'Za rad bez sudo-a potrebno je konfigurirati udev pravila.\n'
            'Želite li automatski konfigurirati pravila pristupa?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            password, ok = QInputDialog.getText(
                None, 'Potvrda',
                'Unesite sudo lozinku za konfiguraciju:',
                QLineEdit.EchoMode.Password
            )

            if ok and password:
                # Postavi udev pravila
                udev_rule = '''SUBSYSTEM=="usb", ATTR{idVendor}=="1b1c", ATTR{idProduct}=="0c0a", MODE="0666", GROUP="plugdev"'''
                cmd = f'echo {password} | sudo -S bash -c \'echo "{udev_rule}" > /etc/udev/rules.d/99-liquidctl.rules && udevadm control --reload-rules && udevadm trigger\''
                os.system(cmd)

                QMessageBox.information(
                    None, 'Uspjeh',
                    'Udev pravila su postavljena!\n'
                    'Molimo odjavite se i ponovo prijavite da promjene stupaju na snagu.'
                )
                sys.exit(0)

    except Exception as e:
        logger.error(f"Greška pri provjeri pristupa: {str(e)}")

    return False


def run_with_sudo():
    """Pokreni aplikaciju sa sudo pravima ako je potrebno"""
    app = QApplication(sys.argv)
    password, ok = QInputDialog.getText(
        None, 'Potrebna potvrda',
        'Aplikacija zahtijeva root privilegije.\nUnesite sudo lozinku:',
        QLineEdit.EchoMode.Password
    )

    if ok and password:
        cmd = ["echo", password, "|", "sudo", "-S", "python3"] + sys.argv
        subprocess.run(" ".join(cmd), shell=True)
    sys.exit(0)


# Provjeri pristup prije pokretanja glavnog koda
if not check_device_access():
    run_with_sudo()


class ProfileDialog(QDialog):
    def __init__(self, parent=None, existing_name="", fan_speed=0, pump_speed=0):
        super().__init__(parent)
        self.setWindowTitle("Create/Edit Profile")
        self.setGeometry(200, 200, 300, 250)

        layout = QFormLayout()

        # Polje za unos imena profila
        self.name_input = QLineEdit()
        self.name_input.setText(existing_name)
        layout.addRow("Profile Name:", self.name_input)

        # Slider za brzinu ventilatora
        self.fan_speed_label = QLabel(f"Fan Speed: {fan_speed}%")
        self.fan_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.fan_speed_slider.setMinimum(0)
        self.fan_speed_slider.setMaximum(100)
        self.fan_speed_slider.setTickInterval(10)
        self.fan_speed_slider.setSingleStep(10)
        self.fan_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.fan_speed_slider.setValue(fan_speed)
        self.fan_speed_slider.valueChanged.connect(self.update_fan_speed_label)
        self.fan_speed_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #B1B1B1, stop:1 #c4c4c4);
                margin: 2px 0;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #66e, stop:1 #bbf);
            }
            QSlider::tick-mark:horizontal {
                background: #ffffff;
                height: 2px;
                width: 2px;
                margin: 0px 0;
            }
        """)
        layout.addRow("Fan Speed:", self.fan_speed_slider)
        layout.addRow(self.fan_speed_label)

        # Slider za brzinu pumpe
        self.pump_speed_label = QLabel(f"Pump Speed: {pump_speed}%")
        self.pump_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.pump_speed_slider.setMinimum(0)
        self.pump_speed_slider.setMaximum(100)
        self.pump_speed_slider.setTickInterval(10)
        self.pump_speed_slider.setSingleStep(10)
        self.pump_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.pump_speed_slider.setValue(pump_speed)
        self.pump_speed_slider.valueChanged.connect(self.update_pump_speed_label)
        self.pump_speed_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #B1B1B1, stop:1 #c4c4c4);
                margin: 2px 0;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #66e, stop:1 #bbf);
            }
            QSlider::tick-mark:horizontal {
                background: #ffffff;
                height: 2px;
                width: 2px;
                margin: 0px 0;
            }
        """)
        layout.addRow("Pump Speed:", self.pump_speed_slider)
        layout.addRow(self.pump_speed_label)

        # Tipke Save i Cancel
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

        self.setLayout(layout)

    def update_fan_speed_label(self):
        speed = self.fan_speed_slider.value()
        speed = round(speed / 10) * 10  # Zaokruži na najbližu deseticu
        self.fan_speed_slider.setValue(speed)
        self.fan_speed_label.setText(f"Fan Speed: {speed}%")

    def update_pump_speed_label(self):
        speed = self.pump_speed_slider.value()
        speed = round(speed / 10) * 10  # Zaokruži na najbližu deseticu
        self.pump_speed_slider.setValue(speed)
        self.pump_speed_label.setText(f"Pump Speed: {speed}%")

    def get_values(self):
        name = self.name_input.text().strip()
        if not name:
            name = f"Pump {self.pump_speed_slider.value()} Fan {self.fan_speed_slider.value()}"
        return {
            "name": name,
            "fan_speed": self.fan_speed_slider.value(),
            "pump_speed": self.pump_speed_slider.value()
        }


class LiquidCtlGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mini Corsair iCUE for Linux")
        self.setGeometry(100, 100, 800, 400)

        # Instance varijable
        self.devices = []
        self.selected_device = None
        self.device_combo = None
        self.refresh_button = None
        self.fan_slider = None
        self.fan_label = None
        self.pump_slider = None
        self.pump_label = None
        self.fan_timer = QTimer()
        self.pump_timer = QTimer()
        self.status_timer = QTimer()
        self.fan_labels = []
        self.fan_status_group = None
        self.pump_temp_group = None
        self.temp_label = None
        self.pump_speed_label = None
        self.profile_combo = None
        self.delay = 2000
        self.last_fan_speed = None
        self.last_pump_speed = None
        self.last_fan_update = 0
        self.last_pump_update = 0
        self.debounce_delay = 1.0
        self.fan_speeds = {}
        self.pump_speed = None
        self.water_temp = None
        self.min_fan_rpm = 200
        self.max_fan_rpm = 2000
        self.min_pump_rpm = 1000
        self.max_pump_rpm = 2700

        # Učitavanje profila i postavki iz app.cfg
        self.config = configparser.ConfigParser()
        self.config_file = "app.cfg"
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
        else:
            self.config["DEFAULT"] = {}
            with open(self.config_file, "w") as configfile:
                self.config.write(configfile)

        # Osiguraj da sekcija "Settings" postoji
        if "Settings" not in self.config:
            self.config["Settings"] = {"run_on_start": "False"}
            with open(self.config_file, "w") as configfile:
                self.config.write(configfile)

        # Pokušaj pronaći ikonu na više lokacija
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
            # Fallback na ugrađenu ikonu ako nije pronađena
            app_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

        # Tray ikona
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(app_icon)
        self.tray_menu = QMenu()
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        logger.debug("Initializing LiquidCtlGUI")
        self.init_ui()
        self.load_devices()

        # Postavljanje timera za ažuriranje statusa
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(2000)

        # Očitaj status odmah pri pokretanju
        self.update_status()

    def init_ui(self):
        logger.debug("Setting up UI components")
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        # Device Selection
        device_group = QGroupBox("Device")
        device_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self.select_device)
        device_layout.addWidget(QLabel("Select Device:"))
        device_layout.addWidget(self.device_combo)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.load_devices)
        device_layout.addWidget(self.refresh_button)
        device_group.setLayout(device_layout)
        main_layout.addWidget(device_group)

        # Profiles Section
        profiles_group = QGroupBox("Profiles")
        profiles_layout = QHBoxLayout()
        profiles_label = QLabel("Profiles:")
        self.profile_combo = QComboBox()
        self.update_profile_combo()
        self.profile_combo.currentTextChanged.connect(self.load_profile)
        create_profile_button = QPushButton("Create Profile")
        create_profile_button.clicked.connect(self.create_profile)
        edit_profile_button = QPushButton("Edit Profile")
        edit_profile_button.clicked.connect(self.edit_profile)
        delete_profile_button = QPushButton("Delete Profile")
        delete_profile_button.clicked.connect(self.delete_profile)
        profiles_layout.addWidget(profiles_label)
        profiles_layout.addWidget(self.profile_combo)
        profiles_layout.addWidget(create_profile_button)
        profiles_layout.addWidget(edit_profile_button)
        profiles_layout.addWidget(delete_profile_button)
        profiles_group.setLayout(profiles_layout)
        main_layout.addWidget(profiles_group)

        # Control Panel
        self.control_group = QGroupBox("Fan & Pump Control")
        control_layout = QVBoxLayout()

        self.fan_label = QLabel("Fan Speed: N/A")
        self.fan_slider = QSlider(Qt.Orientation.Horizontal)
        self.fan_slider.setMinimum(0)
        self.fan_slider.setMaximum(100)
        self.fan_slider.setTickInterval(10)
        self.fan_slider.setSingleStep(10)
        self.fan_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.fan_slider.valueChanged.connect(self.adjust_fan_speed)
        self.fan_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #B1B1B1, stop:1 #c4c4c4);
                margin: 2px 0;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #66e, stop:1 #bbf);
            }
            QSlider::tick-mark:horizontal {
                background: #ffffff;
                height: 2px;
                width: 2px;
                margin: 0px 0;
            }
        """)
        control_layout.addWidget(self.fan_label)
        control_layout.addWidget(self.fan_slider)

        self.pump_label = QLabel("Pump Speed: N/A")
        self.pump_slider = QSlider(Qt.Orientation.Horizontal)
        self.pump_slider.setMinimum(0)
        self.pump_slider.setMaximum(100)
        self.pump_slider.setTickInterval(10)
        self.pump_slider.setSingleStep(10)
        self.pump_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.pump_slider.valueChanged.connect(self.adjust_pump_speed)
        self.pump_slider.setStyleSheet(self.fan_slider.styleSheet())
        control_layout.addWidget(self.pump_label)
        control_layout.addWidget(self.pump_slider)

        self.control_group.setLayout(control_layout)
        main_layout.addWidget(self.control_group)

        # Status Layout (Fan Speeds i Pump/Temp desno)
        status_layout = QHBoxLayout()

        # Fan Status Group
        self.fan_status_group = QGroupBox("Fan Speeds")
        self.fan_status_layout = QVBoxLayout()
        for i in range(1, 7):
            label = QLabel(f"Fan {i}: N/A")
            self.fan_labels.append(label)
            self.fan_status_layout.addWidget(label)
        self.fan_status_group.setLayout(self.fan_status_layout)
        status_layout.addWidget(self.fan_status_group)

        # Pump and Temperature Group
        self.pump_temp_group = QGroupBox("Pump & Temperature")
        pump_temp_layout = QVBoxLayout()
        self.temp_label = QLabel("Water Temperature: N/A")
        self.pump_speed_label = QLabel("Pump Speed: N/A")
        pump_temp_layout.addWidget(self.temp_label)
        pump_temp_layout.addWidget(self.pump_speed_label)
        self.pump_temp_group.setLayout(pump_temp_layout)
        status_layout.addWidget(self.pump_temp_group)

        main_layout.addLayout(status_layout)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # Timers
        self.fan_timer.setSingleShot(True)
        self.fan_timer.timeout.connect(self.send_fan_speed_command)
        self.pump_timer.setSingleShot(True)
        self.pump_timer.timeout.connect(self.send_pump_speed_command)

        # Tray meni
        self.init_tray_menu()

        logger.debug("UI setup completed")

    def init_tray_menu(self):
        self.tray_menu.clear()

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)

        run_on_start_action = QAction("Run on start", self)
        run_on_start_action.setCheckable(True)
        run_on_start_action.setChecked(self.config["Settings"].getboolean("run_on_start", False))
        run_on_start_action.toggled.connect(self.toggle_run_on_start)

        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)

        profiles_menu = QMenu("Select Profile", self)
        for profile in self.config.sections():
            if profile == "Settings":
                continue
            fan_speed = self.config[profile]["fan_speed"]
            pump_speed = self.config[profile]["pump_speed"]
            display_name = f"Pump {pump_speed} Fan {fan_speed}"
            profile_action = QAction(display_name, self)
            profile_action.triggered.connect(lambda checked, p=profile: self.load_profile(p))
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
        self.config["Settings"]["run_on_start"] = str(checked)
        with open(self.config_file, "w") as configfile:
            self.config.write(configfile)

    def show_about(self):
        about_text = """
Mini Corsair iCUE for Linux

Ova aplikacija omogućuje upravljanje Corsair Commander Core uređajem na Linuxu.

**Mogućnosti:**
- Kontrola brzine ventilatora i pumpe putem klizača
- Prikaz trenutnih brzina ventilatora i pumpe
- Prikaz temperature vode
- Tray ikona s brzim pregledom statusa
- Logiranje svih operacija za dijagnostiku

**Kreator:** Nele
**Kako je napravljena:** Napravljena je u Pythonu koristeći PyQt6 za grafičko sučelje i `liquidctl` za komunikaciju s uređajem.
        """
        QMessageBox.information(self, "About", about_text)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Mini Corsair iCUE",
            "Aplikacija je minimizirana u system tray. Koristite 'Exit' za zatvaranje.",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            status_message = "Status:\n"
            for fan, (percent, rpm) in self.fan_speeds.items():
                status_message += f"{fan}: {rpm} RPM ({percent}%)\n"
            if self.pump_speed:
                pump_percent, pump_rpm = self.pump_speed
                status_message += f"Pump: {pump_rpm} RPM ({pump_percent}%)\n"
            if self.water_temp is not None:
                status_message += f"Temp: {self.water_temp} °C\n"
            self.tray_icon.showMessage(
                "Mini Corsair iCUE Status",
                status_message,
                QSystemTrayIcon.MessageIcon.Information,
                5000
            )

    def update_profile_combo(self):
        self.profile_combo.clear()
        for profile in self.config.sections():
            if profile == "Settings":
                continue
            fan_speed = self.config[profile]["fan_speed"]
            pump_speed = self.config[profile]["pump_speed"]
            display_name = f"Pump {pump_speed} Fan {fan_speed}"
            self.profile_combo.addItem(display_name, profile)

    def create_profile(self):
        dialog = ProfileDialog(self)
        if dialog.exec():
            values = dialog.get_values()
            profile_name = values["name"]
            if profile_name in self.config.sections():
                profile_name += f"_{len(self.config.sections()) + 1}"
            self.config[profile_name] = {
                "fan_speed": str(values["fan_speed"]),
                "pump_speed": str(values["pump_speed"])
            }
            with open(self.config_file, "w") as configfile:
                self.config.write(configfile)
            self.update_profile_combo()
            self.init_tray_menu()

    def edit_profile(self):
        current_profile = self.profile_combo.currentData()
        if not current_profile:
            QMessageBox.warning(self, "Warning", "Please select a profile to edit.")
            return
        fan_speed = int(self.config[current_profile]["fan_speed"])
        pump_speed = int(self.config[current_profile]["pump_speed"])
        dialog = ProfileDialog(self, current_profile, fan_speed, pump_speed)
        if dialog.exec():
            values = dialog.get_values()
            old_name = current_profile
            new_name = values["name"]
            if new_name != old_name and new_name in self.config.sections():
                new_name += f"_{len(self.config.sections()) + 1}"
            self.config[new_name] = {
                "fan_speed": str(values["fan_speed"]),
                "pump_speed": str(values["pump_speed"])
            }
            if new_name != old_name:
                self.config.remove_section(old_name)
            with open(self.config_file, "w") as configfile:
                self.config.write(configfile)
            self.update_profile_combo()
            self.init_tray_menu()

    def delete_profile(self):
        current_profile = self.profile_combo.currentData()
        if not current_profile:
            QMessageBox.warning(self, "Warning", "Please select a profile to delete.")
            return
        self.config.remove_section(current_profile)
        with open(self.config_file, "w") as configfile:
            self.config.write(configfile)
        self.update_profile_combo()
        self.init_tray_menu()

    def load_profile(self, profile_name):
        if isinstance(profile_name, str) and profile_name in self.config:
            fan_speed = int(self.config[profile_name]["fan_speed"])
            pump_speed = int(self.config[profile_name]["pump_speed"])
            self.fan_slider.setValue(fan_speed)
            self.pump_slider.setValue(pump_speed)
            self.adjust_fan_speed()
            self.adjust_pump_speed()

    def update_tray_menu(self, fan_speeds, pump_speed, water_temp):
        self.fan_speeds = fan_speeds
        self.pump_speed = pump_speed
        self.water_temp = water_temp

    def initialize_device(self):
        if not self.selected_device:
            return

        try:
            cmd = ["liquidctl", "-m", "Corsair Commander Core", "initialize"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.debug(f"Device initialized: {result.stdout}")
            self.log_message(f"Device initialized:\n{result.stdout}")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error initializing device: {e.stderr}", "ERROR")
            logger.error(f"Initialize command failed: {e.stderr}")
        except Exception as e:
            self.log_message(f"Unexpected error initializing device: {str(e)}", "ERROR")
            logger.error(f"Unexpected error in initialize: {str(e)}", exc_info=True)

    def update_status(self):
        if not self.selected_device:
            logger.warning("No device selected for status update")
            return

        try:
            cmd = ["liquidctl", "-m", "Corsair Commander Core", "status", "--json"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.debug(f"liquidctl status output: {result.stdout}")
            self.log_message(f"Device status:\n{result.stdout}")

            try:
                status_data = json.loads(result.stdout)
                self.parse_json_status(status_data)
                return
            except json.JSONDecodeError:
                logger.debug("Failed to parse as JSON, falling back to text parsing")
                self.parse_text_status(result.stdout)

        except subprocess.CalledProcessError as e:
            self.log_message(f"Error fetching status: {e.stderr}", "ERROR")
            logger.error(f"Status command failed: {e.stderr}")
        except Exception as e:
            self.log_message(f"Unexpected error fetching status: {str(e)}", "ERROR")
            logger.error(f"Unexpected error in status update: {str(e)}", exc_info=True)

    def parse_json_status(self, status_data):
        fan_speeds = {}
        pump_speed = None
        water_temp = None

        for item in status_data:
            if item.get('key') == 'Fan speed':
                fan_num = item.get('channel', '1')
                rpm = item.get('value', 0)
                percent = self.rpm_to_percent(rpm)
                fan_speeds[f"Fan {fan_num}"] = (percent, rpm)
            elif item.get('key') == 'Pump speed':
                rpm = item.get('value', 0)
                percent = self.rpm_to_percent(rpm, is_pump=True)
                pump_speed = (percent, rpm)
            elif item.get('key') == 'Water temperature':
                water_temp = item.get('value', 0)

        self.update_ui_with_status(fan_speeds, pump_speed, water_temp)

    def parse_json_status(self, status_data):
        fan_speeds = {}
        pump_speed = None
        water_temp = None

        if not status_data:
            logger.warning("Empty status data received")
            return

        device_status = status_data[0].get("status", [])
        for item in device_status:
            key = item.get("key", "").lower()
            value = item.get("value", 0)

            if "fan speed" in key:
                match = re.search(r"fan speed (\d+)", key)
                if match:
                    fan_num = match.group(1)
                    rpm = int(value)
                    percent = self.rpm_to_percent(rpm)
                    fan_speeds[f"Fan {fan_num}"] = (percent, rpm)

            elif "pump speed" in key:
                rpm = int(value)
                percent = self.rpm_to_percent(rpm, is_pump=True)
                pump_speed = (percent, rpm)

            elif "water temperature" in key:
                water_temp = float(value)

        self.update_ui_with_status(fan_speeds, pump_speed, water_temp)

    def update_ui_with_status(self, fan_speeds, pump_speed, water_temp):
        if fan_speeds and "Fan 1" in fan_speeds:
            fan_percent, fan_rpm = fan_speeds["Fan 1"]
            self.fan_slider.blockSignals(True)
            self.fan_slider.setValue(fan_percent)
            self.fan_slider.blockSignals(False)
            self.fan_label.setText(f"Fan Speed: {fan_percent}% ({fan_rpm} RPM)")
        else:
            self.fan_label.setText("Fan Speed: N/A")

        if pump_speed:
            pump_percent, pump_rpm = pump_speed
            self.pump_slider.blockSignals(True)
            self.pump_slider.setValue(pump_percent)
            self.pump_slider.blockSignals(False)
            self.pump_label.setText(f"Pump Speed: {pump_percent}% ({pump_rpm} RPM)")
            self.pump_speed_label.setText(f"Pump Speed: {pump_rpm} RPM ({pump_percent}%)")
        else:
            self.pump_label.setText("Pump Speed: N/A")
            self.pump_speed_label.setText("Pump Speed: N/A")

        if water_temp is not None:
            self.temp_label.setText(f"Water Temperature: {water_temp} °C")
        else:
            self.temp_label.setText("Water Temperature: N/A")

        for i, label in enumerate(self.fan_labels, 1):
            fan_key = f"Fan {i}"
            if fan_key in fan_speeds:
                percent, rpm = fan_speeds[fan_key]
                label.setText(f"{fan_key}: {percent}% ({rpm} RPM)")
            else:
                label.setText(f"{fan_key}: N/A")

        self.update_tray_menu(fan_speeds, pump_speed, water_temp)

    def log_message(self, message, level="INFO"):
        log_levels = {
            "INFO": logging.INFO,
            "DEBUG": logging.DEBUG,
            "ERROR": logging.ERROR
        }
        level = log_levels.get(level, logging.INFO)
        logger.log(level, f"[{(self.selected_device or {}).get('description', 'No Device')}] {message}")

    def load_devices(self):
        logger.debug("Loading devices with liquidctl")
        try:
            result = subprocess.run(["liquidctl", "list", "--json"], capture_output=True, text=True, check=True)
            logger.debug(f"liquidctl list --json output: {result.stdout}")
            self.devices = json.loads(result.stdout)
            self.device_combo.clear()
            for dev in self.devices:
                desc = dev.get("description", "Unknown Device")
                logger.debug(f"Found device: {desc}")
                if "Corsair Commander Core" in desc:
                    display_name = "Corsair Commander Core"
                    if "broken" in desc.lower():
                        self.log_message("Warning: Device marked as 'broken' by liquidctl", "WARNING")
                else:
                    display_name = desc
                self.device_combo.addItem(display_name, dev)
            if self.devices:
                self.select_device(0)
                self.initialize_device()
            else:
                self.log_message("No devices found.", "WARNING")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error loading devices: {e.stderr}", "ERROR")
            logger.error(f"subprocess error: {e.stderr}")
        except Exception as e:
            self.log_message(f"Error loading devices: {str(e)}", "ERROR")
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)

    def select_device(self, index):
        logger.debug(f"Selecting device at index {index}")
        if 0 <= index < len(self.devices):
            self.selected_device = self.device_combo.itemData(index)
            self.update_controls()
            self.update_status()
            self.initialize_device()
        else:
            logger.warning(f"Invalid device index: {index}")

    def update_controls(self):
        dev = self.selected_device
        if not dev:
            logger.warning("No device selected")
            return
        self.log_message(f"Selected: {dev['description']}")
        desc = dev["description"].lower()
        if "corsair commander core" in desc:
            self.fan_slider.setEnabled(True)
            self.pump_slider.setEnabled(True)
            logger.debug("Enabled controls for Corsair Commander Core")

    def adjust_fan_speed(self):
        speed = self.fan_slider.value()
        speed = round(speed / 10) * 10
        self.fan_slider.setValue(speed)
        self.fan_label.setText(f"Fan Speed: {speed}%")
        current_time = time.time()
        if current_time - self.last_fan_update >= self.debounce_delay:
            self.last_fan_speed = speed
            self.last_fan_update = current_time
            self.fan_timer.start(self.delay)
        logger.debug(f"Fan speed adjusted to {speed}%")

    def send_fan_speed_command(self):
        if not self.selected_device or self.last_fan_speed is None:
            logger.warning("No device or speed set for fan speed command")
            return
        speed = self.last_fan_speed
        try:
            cmd = ["liquidctl", "-m", "Corsair Commander Core", "set", "fan1", "speed", str(speed)]
            logger.debug(f"Executing fan speed command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
            self.log_message(f"Fan speed set to {speed}%:\n{result.stdout}")
            logger.debug(f"Fan speed command output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error setting fan speed: {e.stderr}", "ERROR")
            logger.error(f"Fan speed command failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            self.log_message("Timeout while setting fan speed", "ERROR")
            logger.error("Timeout while setting fan speed")
        except Exception as e:
            self.log_message(f"Unexpected error setting fan speed: {str(e)}", "ERROR")
            logger.error(f"Unexpected error in fan speed command: {str(e)}", exc_info=True)

    def adjust_pump_speed(self):
        speed = self.pump_slider.value()
        speed = round(speed / 10) * 10
        self.pump_slider.setValue(speed)
        self.pump_label.setText(f"Pump Speed: {speed}%")
        current_time = time.time()
        if current_time - self.last_pump_update >= self.debounce_delay:
            self.last_pump_speed = speed
            self.last_pump_update = current_time
            self.pump_timer.start(self.delay)
        logger.debug(f"Pump speed adjusted to {speed}%")

    def send_pump_speed_command(self):
        if not self.selected_device or self.last_pump_speed is None:
            logger.warning("No device or speed set for pump speed command")
            return
        speed = self.last_pump_speed
        try:
            cmd = ["liquidctl", "-m", "Corsair Commander Core", "set", "pump", "speed", str(speed)]
            logger.debug(f"Executing pump speed command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
            self.log_message(f"Pump speed set to {speed}%:\n{result.stdout}")
            logger.debug(f"Pump speed command output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error setting pump speed: {e.stderr}", "ERROR")
            logger.error(f"Pump speed command failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            self.log_message("Timeout while setting pump speed", "ERROR")
            logger.error("Timeout while setting pump speed")
        except Exception as e:
            self.log_message(f"Unexpected error setting pump speed: {str(e)}", "ERROR")
            logger.error(f"Unexpected error in pump speed command: {str(e)}", exc_info=True)

    def rpm_to_percent(self, rpm, is_pump=False):
        if is_pump:
            min_rpm = self.min_pump_rpm
            max_rpm = self.max_pump_rpm
        else:
            min_rpm = self.min_fan_rpm
            max_rpm = self.max_fan_rpm

        if rpm <= min_rpm:
            return 20
        elif rpm >= max_rpm:
            return 100
        else:
            percent = 20 + (rpm - min_rpm) * (80 / (max_rpm - min_rpm))
            percent = round(percent / 10) * 10
            return min(max(int(percent), 20), 100)


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
