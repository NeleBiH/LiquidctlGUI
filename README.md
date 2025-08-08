# LiquidctlGUI

<img width="1916" height="1038" alt="Screenshot_20250808_204023" src="https://github.com/user-attachments/assets/d67cde9d-b9ba-4dbd-a7ef-5cb1ed0cbab4" />



A simple GUI for [liquidctl](https://github.com/liquidctl/liquidctl) to control **fans** and **pump** on devices such as the Corsair Commander Core.  
I am not a programmer – this was **built with AI assistance** – use at your own risk. If your cat catches fire, it’s on you. 😉

---

## 📌 Features
------------------------------------------------------------------------------------
- **Device discovery:** lists devices via `liquidctl list --json` (no hard-coding).
- **Live status:** per-fan RPM, pump RPM (if present), autodetected **fan count**, and **water temp** from `liquidctl`; **CPU/GPU temps** from system sensors.
- **Speed control:** per-fan sliders + **All Fans** quick slider and optional **Link fans** (move one = move all). Pump slider shown only if supported.
- **Profiles:** save current sliders, edit/rename, delete; last profile auto-loads; quick switching from the **tray menu**.
- **Safety (Emergency Boost):** on CPU or water temp above thresholds → force 100% (fans/pump); turns off with configurable **hysteresis**.
- **Simple auto-curves (optional):** 3 points for CPU + 3 points for Water; linear interpolation; optional apply-to-pump.
- **Fan rename:** double-click a fan name to rename (e.g., “Front top”); names persist.
- **System Info:** OS/distro, **clean CPU model**, **clean GPU model** (NVIDIA/AMD/Intel), RAM and root disk usage.
- **Graph (optional):** rolling CPU/Water temps (matplotlib), readable axes/grid, seconds on X; show/hide toggle.
- **Permissions helper:** one-click **Fix permissions** writes a safe udev rule (TAG+=uaccess) — no `sudo` at runtime.
- **Export/Import settings:** full JSON of profiles, names, safety, curves, etc.
- **Debug window:** separate log with Copy/Clear.
- **Tray icon:** profile picker, quick “All fans 30/50/70/100”, tooltip with temps + RPM snapshot.
- **Adaptive UI:** compact mode for 1080p (tighter spacing, scrollable layout), separators between Water | CPU | GPU, one-line per fan: **Name | RPM | % | Slider**.

---

## ⚙️ How It Works
------------------------------------------------------------------------------------
- **GUI:** PyQt6.
- **Device I/O:** all status/set operations go through the `liquidctl` CLI (`subprocess`).
- **Status parsing:** prefers `--json`; falls back to plain text if needed.
- **Set commands:** tries several variants (`speed`/`duty`, indexed/global) and uses the first that succeeds (helps with different drivers).
- **Temps:**
  - CPU from `sensors -j` (fallback to parsing `sensors`).
  - GPU from `nvidia-smi` (if available), else `glxinfo -B`, else `lspci`.
  - Water temp from `liquidctl status`.
- **Graph:** matplotlib; grid + margins tuned so axis labels are visible.
- **Config:** `~/.liquidctl_gui.json` (reads legacy `~/.LIquidctl_settings.json` on first run).
- **Udev:** installs a minimal rule with `TAG+="uaccess"` for both USB and `hidraw`.
- **Autostart:** optional `.desktop` entry in `~/.config/autostart`.

---

## 🖱 Usage
------------------------------------------------------------------------------------

1. **Run the app** and **select your device** from the dropdown.
2. If you see permission errors, click **Fix permissions** (or add the udev rule manually), then replug or relogin.
3. **Move fan sliders**; **All Fans** sets all at once; enable **Link fans** to keep them locked together.
4. **Pump slider** appears only if the driver supports pump control.
5. **Save Current Profile** to capture the current sliders; use **Edit/Delete** as needed.  
   Quick-switch profiles from the **tray icon**.
6. Toggle **Safety** and set **CPU/Water thresholds** + **hysteresis** for emergency boost.
7. Optional: open **Curves…** to enable simple auto-curves (CPU/Water).  
   (We apply linear interpolation; pump can follow the same target if enabled.)
8. Use **Debug…** to grab logs when reporting issues.  
   **Export/Import Settings** to share or back up your setup.
9. Toggle **Show graph** if you installed matplotlib.

> **Notes:**
---------------------------------------------------------------------
> – Some devices (e.g., “Commander Core (broken)”) won’t support pump/RGB control; we’ll show the pump row only when it’s actually supported.  
> – The RPM↔% mapping in the UI is an estimate; real RPM is shown from device status on refresh.


---------------------------------------------------------------------------------

## ⚠ Current Limitations

- **RGB control**: currently **not working** (on my H170 the RGB status is broken in liquidctl; lights may blink when adjusting speeds)
- Fan/Pump speeds update on a **refresh interval**; physical RPM may take a few seconds to stabilize – normal controller behavior
- Supported devices depend entirely on what `liquidctl` supports

-----------------------------------------------------------------------

## 📦 Requirements
- Linux, Python 3.8+ (recommended 3.10+)
- `liquidctl`
- `PyQt6` ≥ 6.5
- `matplotlib` ≥ 3.8 *(optional, for the graph)*

### For temperatures & system info
- `lm-sensors` (run `sudo sensors-detect`)
- `pciutils` (for `lspci`)
- `mesa-utils` (for `glxinfo`, optional)
- *(optional, NVIDIA)* `nvidia-smi` (comes with NVIDIA driver)

--------------------------------------------------------------

🔧 Installation

Ubuntu / Debian
-------------------------------------------------------------------------------

sudo apt update
sudo apt install -y python3 python3-pip pciutils lm-sensors mesa-utils
pip3 install --user liquidctl pyqt6 matplotlib   # matplotlib is optional (graph)
sudo sensors-detect --auto

------------------------------------------------------------------------------
Fedora
-------------------------------------------------------------------------------

sudo dnf -y update
sudo dnf install -y python3 python3-pip pciutils lm_sensors mesa-demos
pip3 install --user liquidctl pyqt6 matplotlib   # matplotlib is optional (graph)
sudo sensors-detect --auto

-------------------------------------------------------------------------------
I use arch btw people 😉
-------------------------------------------------------------------------------

sudo pacman -Syu --noconfirm
sudo pacman -S --noconfirm python python-pip pciutils lm_sensors mesa-demos
pip3 install --user liquidctl pyqt6 matplotlib   # matplotlib is optional (graph)
sudo sensors-detect --auto

-------------------------------------------------------------------------------
▶ Running the App
-------------------------------------------------------------------------------
git clone https://github.com/NeleBiH/LiquidctlGUI
cd LiquidctlGUI
python3 LiquidctlGUI.py

(Optional) Virtual env:

python3 -m venv .venv
source .venv/bin/activate
pip install liquidctl pyqt6 matplotlib
python3 LiquidctlGUI.py


📅 Roadmap
-----------------------------------------------------------------------
-RGB control (when/if liquidctl supports it properly)



