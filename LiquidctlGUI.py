import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, QComboBox, QColorDialog, QTextEdit
from PyQt5.QtCore import Qt, QTimer
import subprocess

class LiquidCtlGUI(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("LiquidCTL GUI")
        self.setGeometry(100, 100, 800, 600)

        self.initUI()

        # Timer for delayed pump speed command
        self.pump_command_timer = QTimer()
        self.pump_command_timer.setSingleShot(True)
        self.pump_command_timer.timeout.connect(self.send_pump_speed_command)

        # Pump speed adjustment delay (in milliseconds)
        self.pump_adjustment_delay = 500  # Adjust as needed

        # Timer for delayed fan speed command
        self.fan_command_timer = QTimer()
        self.fan_command_timer.setSingleShot(True)
        self.fan_command_timer.timeout.connect(self.send_fan_speed_command)

        # Fan speed adjustment delay (in milliseconds)
        self.fan_adjustment_delay = 500  # Adjust as needed

    def initUI(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        # Device List and Status Section
        device_layout = QHBoxLayout()
        self.device_list_button = QPushButton("List Devices")
        self.device_list_button.clicked.connect(self.list_devices)
        device_layout.addWidget(self.device_list_button)

        self.status_button = QPushButton("Get Status")
        self.status_button.clicked.connect(self.get_status)
        device_layout.addWidget(self.status_button)

        main_layout.addLayout(device_layout)

        # Fan and Pump Speed Section
        control_layout = QHBoxLayout()

        self.fan_label = QLabel("Fan Speed:")
        control_layout.addWidget(self.fan_label)

        self.fan_slider = QSlider(Qt.Horizontal)
        self.fan_slider.setRange(0, 100)
        self.fan_slider.setValue(50)
        self.fan_slider.valueChanged.connect(self.adjust_fan_speed)
        control_layout.addWidget(self.fan_slider)

        self.pump_label = QLabel("Pump Speed:")
        control_layout.addWidget(self.pump_label)

        self.pump_slider = QSlider(Qt.Horizontal)
        self.pump_slider.setRange(0, 100)
        self.pump_slider.setValue(50)
        self.pump_slider.valueChanged.connect(self.adjust_pump_speed)
        control_layout.addWidget(self.pump_slider)

        main_layout.addLayout(control_layout)

        # RGB Control Section
        rgb_layout = QHBoxLayout()

        self.rgb_mode_label = QLabel("RGB Mode:")
        rgb_layout.addWidget(self.rgb_mode_label)

        self.rgb_mode_combo = QComboBox()
        self.rgb_mode_combo.addItems(["Static", "Breathing", "Blinking", "Spectrum"])
        self.rgb_mode_combo.currentTextChanged.connect(self.set_rgb_mode)
        rgb_layout.addWidget(self.rgb_mode_combo)

        self.rgb_color_button = QPushButton("Set RGB Color")
        self.rgb_color_button.clicked.connect(self.set_rgb_color)
        rgb_layout.addWidget(self.rgb_color_button)

        main_layout.addLayout(rgb_layout)

        # Log Output Section
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(self.log_output)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def log_message(self, message):
        self.log_output.append(message)

    def list_devices(self):
        try:
            result = subprocess.run(["liquidctl", "list"], capture_output=True, text=True, check=True)
            self.log_message(f"Devices:\n{result.stdout}")
        except FileNotFoundError:
            self.log_message("Error: 'liquidctl' command not found. Please make sure it is installed.")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error listing devices: {e.stderr}")

    def get_status(self):
        try:
            result = subprocess.run(["liquidctl", "status"], capture_output=True, text=True, check=True)
            self.log_message(f"Status:\n{result.stdout}")
        except FileNotFoundError:
            self.log_message("Error: 'liquidctl' command not found. Please make sure it is installed.")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error getting status: {e.stderr}")

    def adjust_fan_speed(self):
        speed = self.fan_slider.value()
        fan_channel = "fan1"  # Replace with the appropriate fan channel for your setup
        self.fan_label.setText(f"Fan Speed: {speed}")  # Update label immediately
        self.fan_command_timer.start(self.fan_adjustment_delay)

    def send_fan_speed_command(self):
        speed = self.fan_slider.value()
        try:
            result = subprocess.run(["liquidctl", "--match", "Corsair", "set", "fan1", "speed", str(speed)], capture_output=True, text=True, check=True)
            self.log_message(f"Fan speed set to {speed}:\n{result.stdout}")
        except FileNotFoundError:
            self.log_message("Error: 'liquidctl' command not found. Please make sure it is installed.")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error setting fan speed: {e.stderr}")

    def adjust_pump_speed(self):
        speed = self.pump_slider.value()
        self.pump_label.setText(f"Pump Speed: {speed}")  # Update label immediately
        self.pump_command_timer.start(self.pump_adjustment_delay)

    def send_pump_speed_command(self):
        speed = self.pump_slider.value()
        try:
            result = subprocess.run(["liquidctl", "--match", "Corsair", "set", "pump", "speed", str(speed)], capture_output=True, text=True, check=True)
            self.log_message(f"Pump speed set to {speed}:\n{result.stdout}")
        except FileNotFoundError:
            self.log_message("Error: 'liquidctl' command not found. Please make sure it is installed.")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error setting pump speed: {e.stderr}")

    def set_rgb_mode(self):
        mode = self.rgb_mode_combo.currentText()
        try:
            result = subprocess.run(["liquidctl", "set", "rgb", "mode", mode.lower()], capture_output=True, text=True, check=True)
            self.log_message(f"RGB mode set to {mode}:\n{result.stdout}")
        except FileNotFoundError:
            self.log_message("Error: 'liquidctl' command not found. Please make sure it is installed.")
        except subprocess.CalledProcessError as e:
            self.log_message(f"Error setting RGB mode: {e.stderr}")

    def set_rgb_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            r, g, b = color.red(), color.green(), color.blue()
            try:
                result = subprocess.run(["liquidctl", "set", "rgb", "color", str(r), str(g), str(b)], capture_output=True, text=True, check=True)
                self.log_message(f"RGB color set to ({r}, {g}, {b}):\n{result.stdout}")
            except FileNotFoundError:
                self.log_message("Error: 'liquidctl' command not found. Please make sure it is installed.")
            except subprocess.CalledProcessError as e:
                self.log_message(f"Error setting RGB color: {e.stderr}")

def main():
    app = QApplication(sys.argv)
    gui = LiquidCtlGUI()
    gui.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
