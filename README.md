# Windows Audio Auto-Mute Guardian (Python)

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

---

## 📦 Requirements

* **Operating System**: Windows 10 or Windows 11 (64-bit)
* **Python**: Python 3.10+
* **Dependencies**: `pycaw`, `comtypes`

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

### 1. Test Audio Mute Control (Safe 2-Second Test)
Verify that Windows Audio communication works properly on your system:
```powershell
python audio_auto_mute.py --test-mute
```
*Expected: Your default output mutes for 2 seconds, confirms the mute icon on your taskbar, and restores the original volume state.*

### 2. View All Connected Audio Devices
Inspect all playback endpoints, friendly names, and exact Windows IDs:
```powershell
python audio_auto_mute.py --list-devices
```

### 3. Start Protection
Run the guardian in your terminal when you begin working:
```powershell
python audio_auto_mute.py
```
*(or simply double-click `run.bat`)*

### 4. Stop Protection
Press **`Ctrl+C`** at any time. The script unregisters all callbacks, cleans up COM handles, and terminates immediately.

---

## 🛠️ CLI Options

You can override settings on the fly from the command line without editing code:

| Argument | Description | Example |
| :--- | :--- | :--- |
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
EARPHONE_DEVICE_NAME = None  # e.g., "RONiN ECLIPSE" or ["RONiN", "AirPods"]

# Optional exact Windows Core Audio Endpoint ID
EARPHONE_DEVICE_ID = None

# Mute ONLY the newly selected default playback device (Recommended: True)
MUTE_NEW_DEFAULT_ONLY = True

# Broad protection mode: mutes ALL active render outputs (Default: False)
MUTE_ALL_NON_EARPHONE_OUTPUTS = False

# Restore previous unmuted state when earphones reconnect (Default: False)
# If a device was already muted before script action, it is NEVER unmuted.
RESTORE_ON_EARPHONE_RECONNECT = False

# Send Windows Media Key (VK_MEDIA_PLAY_PAUSE) event on disconnect (Default: False)
PAUSE_MEDIA_ON_DISCONNECT = False

# Heartbeat interval in seconds (Default: 1.0)
POLL_INTERVAL = 1.0

# Logging verbosity: "DEBUG", "INFO", "WARNING", "ERROR"
LOG_LEVEL = "INFO"
```

---

## 🧪 Testing Procedure

You can verify all scenarios using the included unit test suite:

```powershell
python -m unittest test_audio_auto_mute.py -v
```

All 9 test cases cover:
* Muting unmuted endpoints
* Preserving already-muted endpoints
* Restoration safety rules
* Scenario A (Disconnect transition)
* Scenario B (Manual switch rejection)
* Multi-device matching
* Media key event dispatch

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
