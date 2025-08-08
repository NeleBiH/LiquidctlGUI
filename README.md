# LiquidctlGUI

<img width="1916" height="1038" alt="Screenshot_20250808_204023" src="https://github.com/user-attachments/assets/d67cde9d-b9ba-4dbd-a7ef-5cb1ed0cbab4" />



A simple GUI for [liquidctl](https://github.com/liquidctl/liquidctl) to control **fans** and **pump** on devices such as the Corsair Commander Core.  
I am not a programmer – this was **built with AI assistance** – use at your own risk. If your cat catches fire, it’s on you. 😉

---

## 📌 Features

- **List devices** detected by `liquidctl`
- **Status**: fan RPM, pump RPM, number of connected fans, water temperature
- **Speed control**: per-fan control and separate pump control
- **Profiles**: create, edit, delete + **Save Current Profile** (stores the current slider positions)
- **Clean UI**: one line per fan → **Name | RPM | % | Slider**
- **System Info**: OS/distro, CPU model, GPU model, RAM and disk (root) usage
- **Tray icon with** profile selection and popup with temps and fan/pump speeds


    How It Works
  --------------------------------------------------------------------------------------------

    GUI built in PyQt6

    All status/set commands are executed via liquidctl CLI (subprocess)

    CPU model is read from lscpu (with LC_ALL=C), fallback /proc/cpuinfo

    GPU: first tries nvidia-smi, then falls back to lspci | grep VGA

    Temperatures: read from lm-sensors and optionally nvidia-smi

    Profiles are saved in: ~/.LIquidctl_settings.json

  🖱 Usage

    Sliders: moving a slider instantly updates the % and estimated RPM in the UI; actual RPM is confirmed on the next refresh

    Save Current Profile: store the current fan/pump % values as a new profile

    Profiles: select, load, and manage profiles from the dropdown menu



---

## ⚠ Current Limitations

- **RGB control**: currently **not working** (on my H170 the RGB status is broken in liquidctl; lights may blink when adjusting speeds)
- Fan/Pump speeds update on a **refresh interval**; physical RPM may take a few seconds to stabilize – normal controller behavior
- Supported devices depend entirely on what `liquidctl` supports

---

## 📦 Requirements

- Linux, Python 3.8+
- `liquidctl`, `pyqt6`
- For temperatures and system info:
  - `lm-sensors` + `sensors-detect`
  - `pciutils` (for `lspci`)
  - (optional) NVIDIA `nvidia-smi` for nicer GPU names

---

## 🔧 Installation

**Ubuntu / Debian**
-------------------------------------------------------------
-  sudo apt update
-  sudo apt install -y python3 python3-pip pciutils lm-sensors
-  pip3 install --user liquidctl pyqt6
-  sudo sensors-detect --auto

**Fedora**
----------------------------------------------------------------
-  sudo dnf -y update
-  sudo dnf install -y python3 python3-pip pciutils lm_sensors
-  pip3 install --user liquidctl pyqt6
-  sudo sensors-detect --auto

**I use Arch btw people**
-----------------------------------------------------------------------------
-  sudo pacman -Syu --noconfirm
-  sudo pacman -S --noconfirm python python-pip pciutils lm_sensors
-  pip3 install --user liquidctl pyqt6
-  sudo sensors-detect --auto Running Without sudo (udev Rule)

▶ Running the App

-  git clone https://github.com/<your-user>/<your-repo>.git
-  cd <your-repo>
-  python3 LiquidctlGUI.py



*📅 Roadmap
----------------------------------------------------------
-   fix CPU model detection 

-   App icon

-   RGB control (when/if liquidctl supports it properly)

-    Master slider (All Fans) and fan grouping

-    Safety limit (force minimum % above X °C water temp)

-    Rename fans

-    Export/Import profiles**



