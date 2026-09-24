# Windows Audio Auto-Mute Guardian (Python)

[![Windows Audio Tests](https://github.com/farmanullah1/audio-auto-mute-Python/actions/workflows/test.yml/badge.svg)](https://github.com/farmanullah1/audio-auto-mute-Python/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![Platform: Windows 10 / 11](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6.svg)](https://www.microsoft.com/windows)

A lightweight, safe, user-controlled Python 3 tool for Windows 10 & 11 that monitors audio playback device transitions and **automatically mutes laptop speakers when your wireless/Bluetooth earphones disconnect**.

Designed specifically for office workers and open-plan environments to prevent sudden, embarrassing audio blaring when earphones run out of battery or drop Bluetooth connection.

---

## 🔒 Critical Safety & Non-Persistence Guarantee

This tool operates under a strict **Zero-Persistence Policy**:

* **Active ONLY while you run it**: The script only runs while the terminal window is open.
* **Returns 100% to normal on exit**: When stopped with `Ctrl+C`, it unregisters all callbacks and exits cleanly. Windows audio management continues functioning completely normally.
* **No Background Daemons**: Does **not** run as a hidden process or Windows service.
* **No Registry Alterations**: Does **not** modify `HKEY_CURRENT_USER\...\Run` or any system registry keys.
* **No Startup Tasks**: Does **not** add itself to Task Scheduler or the Windows Startup folder (`shell:startup`).
* **No Elevation Required**: Runs strictly within standard user permissions (no Administrator rights, no UAC prompts).
* **100% Offline**: Zero telemetry, zero analytics, zero external network connections.

---

## ⚡ How It Works

```text
              Wireless Earphones Active (Default Output)
                                  │
                                  ▼
                   Earphones Disconnect / Out of Range
                                  │
                                  ▼
         Windows switches default playback device to Laptop Speakers
                                  │
                                  ▼
      IMMNotificationClient Event Sink intercepts switch in real-time (< 20ms)
                                  │
                                  ▼
                       Safety Verification Check
  • Scenario A: Earphones were active/default AND are now disconnected
                AND Windows switched to Speakers ──► Mute Speakers
  • Scenario B: User manually switched outputs while earphones remain connected
                ──► Do NOT mute (respects user intent)
                                  │
                                  ▼
             Mute newly selected default playback device only
               (Leaves pre-existing muted devices untouched)
```

---

## ✨ Features

* **Instant Reaction Time (< 20ms)**: Direct COM event callback via Windows Core Audio (`IMMNotificationClient`).
* **0.0% Idle CPU**: Thread sleeps in a kernel wait state (`threading.Event.wait()`) until Windows fires an audio event.
* **Scenario Discrimination**: Distinguishes between accidental disconnection (Scenario A) and manual device switching (Scenario B).
* **Pre-Existing Mute Safety**: Queries `GetMute()` before taking action. If your laptop speaker was already muted, it is left untouched and will **never** be inadvertently unmuted.
* **Multi-Earphone Support**: Configure single or multiple headset names (e.g. `["RONiN ECLIPSE", "Sony WH-1000XM4", "AirPods"]`).
* **Optional Media Auto-Pause**: Can automatically trigger `VK_MEDIA_PLAY_PAUSE` to pause YouTube, Spotify, or media players upon disconnect.
* **Modern Standby & Sleep Resilience**: Self-heals and re-acquires the Windows Audio COM enumerator after laptop lid-close / sleep cycles.
* **Instant Self-Test Flag (`--test-mute`)**: Verify volume and mute control on your laptop speaker in 2 seconds without having to disconnect hardware.
* **🔋 Live Wireless Earphone Battery Monitoring**:
  * Real-time querying of earphone battery percentage directly via native Windows Configuration Manager (`cfgmgr32.dll`).
  * Reports Left earbud, Right earbud, Charging case, Overall battery percentage, and charging state where hardware/Windows APIs expose them.
  * **Strict No-Guessing Policy**: Never fakes or estimates percentages. If Windows or the hardware does not expose a component, it is honestly reported as `Not available` / `N/A`.
  * **Independent Safety Boundary**: Battery monitoring is completely decoupled from audio auto-muting. A missing battery API will never cause a crash or compromise speaker protection.
  * **Configurable Low-Battery Warnings**: Emits alerts when battery drops to or below threshold (e.g. 20%) with built-in anti-spam latching.
  * **Explicit Stale-Value Labeling**: When disconnected, previous values are explicitly marked as `Last known: XX% (Disconnected)`.

---

## 📦 Requirements

* **Operating System**: Windows 10 or Windows 11 (64-bit)
* **Python**: Python 3.10+
* **Dependencies**: `pycaw`, `comtypes` (Zero additional dependencies for battery monitoring; uses native Windows `cfgmgr32.dll`).

---

## 🚀 Installation

1. Clone or download this repository:
   ```powershell
   git clone https://github.com/farmanullah1/audio-auto-mute-Python.git
   cd audio-auto-mute-Python
   ```

2. Install dependencies:
   ```powershell
   py -m pip install -r requirements.txt
   ```

---

## 💻 Quick Start & Usage

### 1. Check Earphone Battery Level
Quickly inspect your wireless earphone battery level directly from the terminal:
```powershell
python audio_auto_mute.py --battery
```

Example output:
```text
==================================================
 Wireless Earphone Status
==================================================
Target:          RONiN ECLIPSE
Device:          RONiN ECLIPSE Hands-Free AG
Connection:      Connected

Left Earbud:     Not available
Right Earbud:    Not available
Charging Case:   Not available
Overall Battery: 100%

Charging:
Left:            N/A
Right:           N/A
Case:            N/A
Overall:         N/A
==================================================
```

### 2. Test Audio Mute Control (Safe 2-Second Test)
Verify that Windows Audio communication works properly on your system:
```powershell
python audio_auto_mute.py --test-mute
```
*Expected: Your default output mutes for 2 seconds, confirms the mute icon on your taskbar, and restores the original volume state.*

### 3. View All Connected Audio Devices
Inspect all playback endpoints, friendly names, and exact Windows IDs:
```powershell
python audio_auto_mute.py --list-devices
```

### 4. Start Protection & Battery Monitor
You can start protection in any of these ways:
* **1-Click Desktop Icon**: Double-click the **Audio Guardian** shortcut on your Windows Desktop.
* **Batch Launcher**: Double-click [`run.bat`](run.bat).
* **Terminal**: Run in PowerShell or Command Prompt:
  ```powershell
  python audio_auto_mute.py
  ```

Dashboard display:
```text
==================================================
 Windows Wireless Earphone Monitor
==================================================

Application: Running
Persistence: Disabled
Startup:     Disabled
Admin:       Not required

Earphones
--------------------------------------------------
Connection:       Connected
Device:           Headphones (RONiN ECLIPSE)
Left Earbud:      Not available
Right Earbud:     Not available
Charging Case:    Not available
Overall Battery:  100%

Default Output
--------------------------------------------------
Device:           Headphones (RONiN ECLIPSE)
Status:           Active

Audio Protection
--------------------------------------------------
Status:           Armed
Mute-on-disconnect: Enabled

Battery Monitor
--------------------------------------------------
Status:           Active
Refresh interval: 30 seconds

Waiting for changes...
==================================================
```

### 5. Stop Protection
Press **`Ctrl+C`** (or close the terminal window) at any time. The script unregisters all callbacks, cleans up COM handles, and terminates immediately.

---

## 🛠️ CLI Options

You can override settings on the fly from the command line without editing code:

| Argument | Description | Example |
| :--- | :--- | :--- |
| `--battery` | Query connected earphone battery percentage, then exit. | `python audio_auto_mute.py --battery` |
| `--no-battery` | Disable background earphone battery monitoring. | `python audio_auto_mute.py --no-battery` |
| `--battery-interval <SEC>` | Set battery polling interval in seconds (default: 30.0). | `python audio_auto_mute.py --battery-interval 45` |
| `--list-devices` | Lists all audio endpoints with state and IDs, then exits. | `python audio_auto_mute.py --list-devices` |
| `--test-mute` | Safely tests volume mute on default speaker, then exits. | `python audio_auto_mute.py --test-mute` |
| `--device <NAME>` | Target specific earphone name or substring. | `python audio_auto_mute.py --device "RONiN ECLIPSE"` |
| `--device-id <ID>` | Target specific Core Audio Endpoint GUID. | `python audio_auto_mute.py --device-id "{0.0.0...}"` |
| `--restore` | Automatically unmute speakers when earphones reconnect. | `python audio_auto_mute.py --restore` |
| `--pause-media` | Send a media Play/Pause keystroke on disconnect. | `python audio_auto_mute.py --pause-media` |

---

## ⚙️ In-File Configuration

Settings can also be modified directly near the top of [`audio_auto_mute.py`](audio_auto_mute.py):

```python
# Exact or partial friendly name of your wireless/Bluetooth earphones.
# Can be a single string or a list for multiple headsets. Set None to auto-detect.
EARPHONE_DEVICE_NAME = "RONiN ECLIPSE"

# Optional exact Windows Core Audio Endpoint ID
EARPHONE_DEVICE_ID = "{0.0.0.00000000}.{73504252-5a55-4e32-8eb1-1a96cc0659e2}"

# Battery Monitoring Configuration
BATTERY_MONITORING_ENABLED = True
BATTERY_CHECK_INTERVAL = 30.0          # Seconds (lightweight, minimal CPU/memory impact)
LOW_BATTERY_WARNING_ENABLED = True
LOW_BATTERY_THRESHOLD = 20             # Percentage threshold for low-battery alerts

# Mute ONLY the newly selected default playback device (Recommended: True)
MUTE_NEW_DEFAULT_ONLY = True

# Broad protection mode: mutes ALL active render outputs (Default: False)
MUTE_ALL_NON_EARPHONE_OUTPUTS = False

# Restore previous unmuted state when earphones reconnect (Default: False)
RESTORE_ON_EARPHONE_RECONNECT = False

# Send Windows Media Key (VK_MEDIA_PLAY_PAUSE) event on disconnect (Default: False)
PAUSE_MEDIA_ON_DISCONNECT = False

# Heartbeat interval in seconds (Default: 1.0)
POLL_INTERVAL = 1.0

# Logging verbosity: "DEBUG", "INFO", "WARNING", "ERROR"
LOG_LEVEL = "INFO"
```

---

## 🔍 Hardware & Windows Bluetooth Architecture Limitations

### Why Left/Right/Case May Report "Not available"
1. **Bluetooth Profile Differences**:
   * **Hands-Free Profile (HFP)**: Standard Bluetooth Classic audio headsets use HFP (via `AT+IPHONEACCEV` or `AT+XAPL`). The Windows driver (`bthhfenum.sys`) parses this and stores a **single overall battery integer** in the device's PnP property (`DEVPKEY_Device_BatteryLifePercent`).
   * HFP does not have standardized fields for separate Left earbud, Right earbud, or Charging Case percentages.
2. **Charging Case Limitations**:
   * Almost no wireless earphone charging cases contain an active Bluetooth radio when open or in use. When earbuds are in your ears, the case has no RF connection to your PC.
   * Proprietary headsets (such as AirPods or Galaxy Buds) only broadcast case battery via BLE manufacturer advertisement beacons at the instant the case lid opens, which Windows native audio drivers do not bind to standard PnP audio properties.
3. **Windows 10 vs. Windows 11**:
   * Windows 10 (version 1809+) and Windows 11 natively expose Bluetooth battery via `DEVPKEY_Device_BatteryLifePercent` for supported HFP and BLE BAS (Battery Service) devices.
   * If a device exposes multi-component nodes (e.g. Surface Earbuds or BLE sub-nodes), this tool detects and maps them to Left, Right, or Case independently.
   * When hardware does not separate them, this tool follows the **Strict No-Guessing Policy** and reports `Not available`, rather than fabricating numbers.

---

## 🧪 Testing Procedure

You can verify all scenarios using the included unit test suite:

```powershell
python -m unittest test_audio_auto_mute.py -v
```

All 19 test cases cover:
* Muting unmuted endpoints
* Preserving already-muted endpoints
* Restoration safety rules
* Scenario A (Disconnect transition)
* Scenario B (Manual switch rejection)
* Multi-device matching
* Media key event dispatch
* Battery live percentage formatting
* Battery disconnected "Last known" labeling
* Strict no-guessing validation
* Low-battery warning trigger and anti-spam threshold latching
* Case low-battery alerts
* Suppression of alerts when disconnected or disabled
* Auto-mute resilience against simulated battery failure
* Terminal status dashboard rendering

---

## 🔍 Independent Persistence Verification

You can verify at any time that this tool makes **zero** background modifications:

1. **Startup Folder**: Press `Win + R` ➔ type `shell:startup` ➔ confirm folder is empty.
2. **Registry Run Keys**: Press `Win + R` ➔ open `regedit` ➔ inspect `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
3. **Task Scheduler**: Press `Win + R` ➔ open `taskschd.msc` ➔ check Task Scheduler Library.
4. **Services**: Press `Win + R` ➔ open `services.msc` ➔ confirm no custom Python services exist.

---

## 📄 License

MIT License. Free for personal and commercial use.

