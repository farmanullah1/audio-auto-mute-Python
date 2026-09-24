#!/usr/bin/env python3
"""
Windows Audio Auto-Mute Guardian
================================
Monitors Windows audio playback-device changes and automatically mutes the
newly selected default playback device when wireless/Bluetooth earphones disconnect.

CRITICAL ARCHITECTURE GUARANTEE:
- The script ONLY operates while this Python process is actively running in your terminal.
- It makes NO permanent or persistent changes to Windows.
- It contains NO registry modifications, NO scheduled tasks, NO Windows services,
  NO startup folder entries, and NO background daemons.
- When stopped (Ctrl+C), it cleanly unregisters callbacks and exits.
  Windows audio continues functioning 100% normally.
"""

import sys

# Ensure COM initializes in Multi-Threaded Apartment (MTA) mode before importing comtypes.
# This allows Windows Core Audio background thread callbacks (IMMNotificationClient)
# to execute directly without requiring an STA Windows GUI message pump loop.
if not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 0  # 0 = COINIT_MULTITHREADED

import argparse
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import threading
import time
from typing import Dict, List, Optional, Tuple, Union

import comtypes
from pycaw.callbacks import MMNotificationClient
from pycaw.pycaw import AudioUtilities, IMMDeviceEnumerator, AudioDeviceState

# ==============================================================================
# USER CONFIGURATION SECTION
# ==============================================================================

# Exact or partial friendly name of your wireless/Bluetooth earphones.
# Can be a single string (e.g., "RONiN ECLIPSE") or a list of names for multiple headsets.
# Matching is case-insensitive. Set to None for automatic earphone detection.
# Examples: "RONiN ECLIPSE", ["RONiN ECLIPSE", "Sony WH-1000XM4", "AirPods Pro"]
EARPHONE_DEVICE_NAME: Optional[Union[str, List[str]]] = "RONiN ECLIPSE"

# Optional: Exact Windows Core Audio Endpoint ID for your earphones.
# If provided, this ID takes precedence over EARPHONE_DEVICE_NAME.
# Run `python audio_auto_mute.py --list-devices` to view all device IDs.
# Example: "{0.0.0.00000000}.{73504252-5a55-4e32-8eb1-1a96cc0659e2}"
EARPHONE_DEVICE_ID: Optional[str] = "{0.0.0.00000000}.{73504252-5a55-4e32-8eb1-1a96cc0659e2}"

# When earphones disconnect and Windows switches default output to speakers:
# True  = Mute ONLY the newly selected default playback device (Recommended).
# False = Do not automatically mute the new default device.
MUTE_NEW_DEFAULT_ONLY: bool = True

# Optional broad-protection mode:
# If True, mutes ALL currently active render output endpoints (except earphones)
# when earphones disconnect.
# Default: False (conservative, safe default).
MUTE_ALL_NON_EARPHONE_OUTPUTS: bool = False

# Optional restoration behavior:
# If True, when earphones reconnect and become default again, the script will
# restore the previous mute state of the device it muted.
# IMPORTANT: If the speakers were ALREADY muted before the script acted, they will
# NEVER be unmuted under any circumstances, preserving your manual mute preference.
# Default: False (conservative: leaves device muted until you manually unmute).
RESTORE_ON_EARPHONE_RECONNECT: bool = False

# Optional Media Pause:
# If True, sends a standard Windows Media Key (VK_MEDIA_PLAY_PAUSE) event
# when earphones disconnect to pause background YouTube, Spotify, or media playback.
# Default: False (leaves media players untouched unless requested).
PAUSE_MEDIA_ON_DISCONNECT: bool = False

# Heartbeat interval in seconds. Event-driven callbacks handle transitions in real-time
# (< 20ms); this interval provides a lightweight fail-safe sync and ensures
# instant responsiveness to Ctrl+C interrupt signals.
POLL_INTERVAL: float = 1.0

# Logging level: "DEBUG", "INFO", "WARNING", "ERROR"
LOG_LEVEL: str = "INFO"

# Optional path to a log file. If None, logs only to console (stdout).
# If a filename is specified, RotatingFileHandler prevents unlimited file growth (max 1MB).
LOG_FILE: Optional[str] = None

# Common keywords used to identify wireless earphones/headsets when auto-detecting
EARPHONE_KEYWORDS = (
    "headphone",
    "headphones",
    "headset",
    "earphone",
    "earphones",
    "earbuds",
    "airpods",
    "buds",
    "wireless",
    "bluetooth",
    "ronin",
    "wh-",
    "wf-",
)

# ==============================================================================
# LOGGING SETUP
# ==============================================================================

def setup_logger(log_level: str, log_file: Optional[str] = None) -> logging.Logger:
    """Configures structured, non-intrusive logging for console and optional file."""
    logger = logging.getLogger("AudioAutoMute")
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] %(message)s",
        datefmt="%H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        try:
            file_handler = RotatingFileHandler(
                log_file, maxBytes=1_000_000, backupCount=1, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning("Could not initialize log file '%s': %s", log_file, e)

    return logger

# ==============================================================================
# AUDIO & SYSTEM HELPER FUNCTIONS
# ==============================================================================

def trigger_media_pause(logger: logging.Logger):
    """
    Simulates a standard Windows VK_MEDIA_PLAY_PAUSE keypress to pause active media.
    Uses native user32.keybd_event without external packages.
    """
    try:
        VK_MEDIA_PLAY_PAUSE = 0xB3
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)
        logger.info("Sent Windows Media Pause (VK_MEDIA_PLAY_PAUSE) event.")
    except Exception as e:
        logger.warning("Could not simulate media pause: %s", e)

def get_friendly_name(enumerator, device_id: str) -> str:
    """Safely retrieves the human-readable friendly name of an audio endpoint."""
    if not device_id:
        return "Unknown Device"
    try:
        imm = enumerator.GetDevice(device_id)
        if not imm:
            return "Unknown Device"
        dev = AudioUtilities.CreateDevice(imm)
        return dev.FriendlyName or "Unknown Device"
    except (comtypes.COMError, OSError):
        return "Disconnected Device"

def get_device_state(enumerator, device_id: str) -> Optional[int]:
    """
    Returns the Windows Core Audio state DWORD:
    1 = DEVICE_STATE_ACTIVE
    2 = DEVICE_STATE_DISABLED
    4 = DEVICE_STATE_NOTPRESENT
    8 = DEVICE_STATE_UNPLUGGED
    Returns None if device cannot be queried.
    """
    if not device_id:
        return None
    try:
        imm = enumerator.GetDevice(device_id)
        if not imm:
            return None
        return imm.GetState()
    except (comtypes.COMError, OSError):
        return None

def is_device_active(enumerator, device_id: str) -> bool:
    """Returns True if the device exists and is currently in the ACTIVE state."""
    state = get_device_state(enumerator, device_id)
    return state == 1

def get_default_render_device(enumerator) -> Tuple[Optional[str], Optional[str]]:
    """
    Queries Windows for the current default playback (eRender) console endpoint.
    Returns (device_id, friendly_name) or (None, None).
    """
    try:
        def_imm = enumerator.GetDefaultAudioEndpoint(0, 0)  # flow=0 (eRender), role=0 (eConsole)
        if not def_imm:
            return None, None
        dev_id = def_imm.GetId()
        dev = AudioUtilities.CreateDevice(def_imm)
        return dev_id, (dev.FriendlyName or "Default Playback Device")
    except (comtypes.COMError, OSError):
        return None, None

def mute_endpoint(
    enumerator,
    device_id: str,
    device_name: str,
    saved_states: Dict[str, dict],
    logger: logging.Logger
) -> bool:
    """
    Safely mutes a playback endpoint.
    Remembers previous volume and mute status.
    Guarantees that an already-muted device is never marked as script-muted.
    """
    if not device_id:
        return False

    try:
        imm = enumerator.GetDevice(device_id)
        if not imm:
            logger.warning("Could not acquire device endpoint for ID: %s", device_id)
            return False

        dev = AudioUtilities.CreateDevice(imm)
        vol = dev.EndpointVolume
        if not vol:
            logger.warning("Could not acquire volume interface for: %s", device_name)
            return False

        try:
            current_mute = bool(vol.GetMute())
        except (comtypes.COMError, OSError):
            current_mute = False

        try:
            current_vol = float(vol.GetMasterVolumeLevelScalar())
        except (comtypes.COMError, OSError):
            current_vol = 0.0

        if current_mute:
            logger.info("Device '%s' is already muted. Preserving original mute state.", device_name)
            saved_states[device_id] = {
                "name": device_name,
                "previous_mute": True,
                "previous_vol": current_vol,
                "script_muted": False,  # Script was NOT the one that muted it
            }
            return True

        # Save previous unmuted state
        saved_states[device_id] = {
            "name": device_name,
            "previous_mute": False,
            "previous_vol": current_vol,
            "script_muted": True,   # Script initiated the mute
        }

        # Perform mute
        vol.SetMute(1, None)
        vol_pct = int(round(current_vol * 100))
        logger.warning(
            "*** [ACTION] Muted playback device: '%s' (Volume was: %d%%) ***",
            device_name,
            vol_pct
        )
        return True
    except (comtypes.COMError, OSError) as e:
        logger.error("Failed to mute device '%s': %s", device_name, e)
        return False

def restore_endpoint(
    enumerator,
    device_id: str,
    saved_states: Dict[str, dict],
    logger: logging.Logger
) -> bool:
    """
    Safely restores a previously unmuted device if RESTORE_ON_EARPHONE_RECONNECT is enabled.
    NEVER unmutes a device that was already muted before the script acted.
    """
    state_info = saved_states.get(device_id)
    if not state_info:
        return False

    device_name = state_info.get("name", device_id)
    script_muted = state_info.get("script_muted", False)

    if not script_muted:
        logger.info(
            "Device '%s' was already muted prior to script action; leaving muted.",
            device_name
        )
        return False

    try:
        imm = enumerator.GetDevice(device_id)
        if not imm:
            return False
        dev = AudioUtilities.CreateDevice(imm)
        vol = dev.EndpointVolume
        if not vol:
            return False

        vol.SetMute(0, None)
        state_info["script_muted"] = False
        logger.info("Restored previous unmuted state for device '%s'.", device_name)
        return True
    except (comtypes.COMError, OSError) as e:
        logger.error("Failed to restore mute state for '%s': %s", device_name, e)
        return False

# ==============================================================================
# DEVICE ENUMERATION & CLI TESTING
# ==============================================================================

def print_devices_summary():
    """Prints a clear, formatted table of all audio playback devices on this system."""
    enumerator = AudioUtilities.GetDeviceEnumerator()
    def_id, def_name = get_default_render_device(enumerator)

    collection = enumerator.EnumAudioEndpoints(0, 0x0000000F)  # eRender, all states
    count = collection.GetCount()

    print("\n" + "=" * 95)
    print(" WINDOWS AUDIO PLAYBACK (RENDER) DEVICES")
    print("=" * 95)
    print(f"{'DEVICE NAME':<38} {'STATE':<12} {'DEFAULT':<8} {'ENDPOINT ID'}")
    print("-" * 95)

    for i in range(count):
        imm = collection.Item(i)
        dev = AudioUtilities.CreateDevice(imm)
        is_def = "YES" if dev.id == def_id else "NO"
        print(f"{dev.FriendlyName[:37]:<38} {dev.state.name:<12} {is_def:<8} {dev.id}")

    print("=" * 95)
    print("Current Default Playback Device:", def_name)
    print("Tip: To configure a specific device, copy its name or ID into the")
    print("     EARPHONE_DEVICE_NAME or EARPHONE_DEVICE_ID setting in audio_auto_mute.py")
    print("=" * 95 + "\n")

def run_test_mute():
    """
    Safely tests volume mute control on the default playback device.
    Mutes for 2 seconds, then restores the exact previous state.
    """
    print("\n" + "=" * 65)
    print(" Testing Windows Audio Mute Control")
    print("=" * 65)
    enumerator = AudioUtilities.GetDeviceEnumerator()
    def_id, def_name = get_default_render_device(enumerator)
    if not def_id:
        print("[ERROR] Could not query default audio playback device.")
        return 1

    print(f"Target Device:  {def_name}")
    try:
        imm = enumerator.GetDevice(def_id)
        dev = AudioUtilities.CreateDevice(imm)
        vol = dev.EndpointVolume
        orig_mute = bool(vol.GetMute())
        orig_vol = float(vol.GetMasterVolumeLevelScalar())

        print(f"Original State: Muted = {orig_mute}, Volume = {int(round(orig_vol * 100))}%")
        print("Muting device for 2 seconds...")
        vol.SetMute(1, None)
        time.sleep(2.0)
        print(f"Restoring original mute state ({orig_mute})...")
        vol.SetMute(orig_mute, None)
        print("[SUCCESS] Test completed successfully. Audio control verified!")
        print("=" * 65 + "\n")
        return 0
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        return 1

# ==============================================================================
# AUDIO GUARDIAN MONITOR CLASS
# ==============================================================================

class AudioAutoMuteMonitor(MMNotificationClient):
    """
    Event-driven Windows Core Audio notification listener.
    Inherits from MMNotificationClient to receive direct COM callbacks from Windows.
    """

    def __init__(
        self,
        earphone_name: Optional[Union[str, List[str]]] = None,
        earphone_id: Optional[str] = None,
        mute_new_default_only: bool = True,
        mute_all_non_earphone: bool = False,
        restore_on_reconnect: bool = False,
        pause_media: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__()
        self.target_earphone_name = earphone_name
        self.target_earphone_id = earphone_id
        self.mute_new_default_only = mute_new_default_only
        self.mute_all_non_earphone = mute_all_non_earphone
        self.restore_on_reconnect = restore_on_reconnect
        self.pause_media = pause_media
        self.logger = logger or logging.getLogger("AudioAutoMute")

        self.enumerator = AudioUtilities.GetDeviceEnumerator()
        self._lock = threading.RLock()
        self._is_registered = False

        # State tracking
        self.tracked_earphone_id: Optional[str] = None
        self.tracked_earphone_name: Optional[str] = None
        self.last_default_id: Optional[str] = None
        self.last_default_name: Optional[str] = None
        self.was_earphone_active_or_default: bool = False
        self.saved_device_states: Dict[str, dict] = {}

    def discover_tracked_earphone(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Discovers the earphone device using configured ID, configured Name,
        or automatic heuristic detection. Supports multiple target names.
        """
        collection = self.enumerator.EnumAudioEndpoints(0, 0x0000000F)
        count = collection.GetCount()
        candidates: List[Tuple[str, str, int]] = []

        for i in range(count):
            try:
                imm = collection.Item(i)
                dev = AudioUtilities.CreateDevice(imm)
                candidates.append((dev.id, dev.FriendlyName, imm.GetState()))
            except (comtypes.COMError, OSError):
                continue

        # 1. Match by exact ID if configured
        if self.target_earphone_id:
            for dev_id, name, state in candidates:
                if dev_id.strip() == self.target_earphone_id.strip():
                    return dev_id, name

        # 2. Match by configured Name(s) if specified
        if self.target_earphone_name:
            target_list = (
                [self.target_earphone_name]
                if isinstance(self.target_earphone_name, str)
                else self.target_earphone_name
            )
            for target in target_list:
                target_lower = target.lower().strip()
                for dev_id, name, state in candidates:
                    if target_lower in name.lower():
                        return dev_id, name

        # 3. Auto-detect from current default device if it contains earphone keywords
        cur_def_id, cur_def_name = get_default_render_device(self.enumerator)
        if cur_def_id and cur_def_name:
            cur_def_lower = cur_def_name.lower()
            if any(kw in cur_def_lower for kw in EARPHONE_KEYWORDS):
                return cur_def_id, cur_def_name

        # 4. Auto-detect from paired/connected devices (State 1 = Active, State 8 = Unplugged)
        # Prioritize wireless/Bluetooth earphones over motherboard audio chips
        generic_chips = ("realtek", "high definition audio", "intel(r)", "amd ")

        # 4a. Active or Unplugged devices matching earphone keywords, NOT generic motherboard chips
        for dev_id, name, state in candidates:
            if state in (1, 8):
                name_lower = name.lower()
                if any(kw in name_lower for kw in EARPHONE_KEYWORDS) and not any(chip in name_lower for chip in generic_chips):
                    return dev_id, name

        # 4b. Any Active or Unplugged device matching earphone keywords
        for dev_id, name, state in candidates:
            if state in (1, 8):
                name_lower = name.lower()
                if any(kw in name_lower for kw in EARPHONE_KEYWORDS):
                    return dev_id, name

        # 4c. Fallback across all states
        for dev_id, name, state in candidates:
            name_lower = name.lower()
            if any(kw in name_lower for kw in EARPHONE_KEYWORDS):
                return dev_id, name

        return None, None

    def initialize_state(self):
        """Initializes the baseline audio state upon startup."""
        with self._lock:
            cur_def_id, cur_def_name = get_default_render_device(self.enumerator)
            self.last_default_id = cur_def_id
            self.last_default_name = cur_def_name

            # Discover earphone
            earphone_id, earphone_name = self.discover_tracked_earphone()
            self.tracked_earphone_id = earphone_id
            self.tracked_earphone_name = earphone_name

            if self.tracked_earphone_id:
                earphone_active = is_device_active(self.enumerator, self.tracked_earphone_id)
                is_default = (self.last_default_id == self.tracked_earphone_id)
                self.was_earphone_active_or_default = earphone_active or is_default

                status_str = "ACTIVE (Connected)" if earphone_active else "STANDBY (Disconnected / Unplugged)"
                self.logger.info("Monitored Earphone: '%s' [%s]", self.tracked_earphone_name, status_str)
                if is_default:
                    self.logger.info("[ARMED] Earphones are currently the default playback device.")
                elif earphone_active:
                    self.logger.info("[ARMED] Earphones are connected and ready.")
                else:
                    self.logger.info("[STANDBY] Waiting for earphones to connect...")
            else:
                self.was_earphone_active_or_default = False
                self.logger.warning("No earphone device identified yet.")
                self.logger.warning("Connect your wireless earphones or configure EARPHONE_DEVICE_NAME.")

            self.logger.info("Current default playback output: '%s'", self.last_default_name or "None")

    def register_callbacks(self):
        """Registers the IMMNotificationClient COM callback with Windows Core Audio."""
        with self._lock:
            if not self._is_registered:
                self.enumerator.RegisterEndpointNotificationCallback(self)
                self._is_registered = True
                self.logger.info("Registered Windows Core Audio event notifications.")

    def unregister_callbacks(self):
        """Safely unregisters the COM callback."""
        with self._lock:
            if self._is_registered:
                try:
                    self.enumerator.UnregisterEndpointNotificationCallback(self)
                except Exception as e:
                    self.logger.debug("Callback unregister note: %s", e)
                finally:
                    self._is_registered = False
                    self.logger.info("Unregistered Windows Core Audio event notifications.")

    # --------------------------------------------------------------------------
    # COM Event Callbacks (Invoked asynchronously by Windows on system thread)
    # --------------------------------------------------------------------------

    def on_default_device_changed(self, flow: str, flow_id: int, role: str, role_id: int, default_device_id: str):
        """Fired by Windows Core Audio when the default audio endpoint changes."""
        # We only monitor audio playback (flow_id == 0: eRender)
        if flow_id != 0:
            return

        with self._lock:
            self._process_state_transition(
                trigger_reason=f"Windows default device changed (role={role})",
                new_default_id=default_device_id
            )

    def on_device_state_changed(self, device_id: str, new_state: str, new_state_id: int):
        """Fired by Windows Core Audio when an audio endpoint changes state."""
        with self._lock:
            # If the state change involves our monitored earphone, process immediately
            if self.tracked_earphone_id and device_id == self.tracked_earphone_id:
                self.logger.info(
                    "Earphone state transitioned to: %s (code=%d)",
                    new_state,
                    new_state_id
                )
                self._process_state_transition(
                    trigger_reason=f"Earphone hardware state changed to {new_state}"
                )
            elif not self.tracked_earphone_id:
                # If we hadn't found an earphone earlier, check if a newly active device is one
                self.tracked_earphone_id, self.tracked_earphone_name = self.discover_tracked_earphone()
                if self.tracked_earphone_id:
                    self.logger.info("Newly discovered earphone device: '%s'", self.tracked_earphone_name)
                    self._process_state_transition(trigger_reason="Earphone discovered")

    def on_device_added(self, added_device_id: str):
        """Fired when an audio device is installed or plugged in."""
        with self._lock:
            if not self.tracked_earphone_id:
                self.tracked_earphone_id, self.tracked_earphone_name = self.discover_tracked_earphone()

    def on_device_removed(self, removed_device_id: str):
        """Fired when an audio device is removed from the system."""
        with self._lock:
            if removed_device_id == self.tracked_earphone_id:
                self.logger.warning("Monitored earphone endpoint removed from system.")
                self._process_state_transition(trigger_reason="Earphone endpoint removed")

    # --------------------------------------------------------------------------
    # Core Transition & Safety Logic
    # --------------------------------------------------------------------------

    def _process_state_transition(self, trigger_reason: str, new_default_id: Optional[str] = None):
        """
        Evaluates audio state changes against safety rules:
        - Scenario A: Earphones were active/default, now disconnected, new output selected -> MUTE.
        - Scenario B: User manually switched default device while earphones remain connected -> DO NOT MUTE.
        - Reconnect: Earphones reconnect and become default again -> optionally restore previous state.
        """
        if not self.tracked_earphone_id:
            self.tracked_earphone_id, self.tracked_earphone_name = self.discover_tracked_earphone()

        # If Windows passed new_default_id directly in callback, use it; otherwise query
        if new_default_id:
            cur_def_id = new_default_id
            cur_def_name = get_friendly_name(self.enumerator, cur_def_id)
        else:
            cur_def_id, cur_def_name = get_default_render_device(self.enumerator)

        if not cur_def_id:
            return

        earphone_active = False
        if self.tracked_earphone_id:
            earphone_active = is_device_active(self.enumerator, self.tracked_earphone_id)

        self.logger.debug(
            "Evaluation (%s): cur_def='%s', earphone_active=%s, was_active=%s",
            trigger_reason,
            cur_def_name,
            earphone_active,
            self.was_earphone_active_or_default
        )

        # ----------------------------------------------------------------------
        # CASE 1: EARPHONES DISCONNECTED (Scenario A)
        # ----------------------------------------------------------------------
        if self.was_earphone_active_or_default and not earphone_active:
            # If earphones disconnected but Windows hasn't finished switching the default endpoint yet,
            # wait up to 100ms (5 x 20ms) to catch the new default output immediately.
            if cur_def_id == self.tracked_earphone_id:
                for _ in range(5):
                    time.sleep(0.02)
                    new_id, new_name = get_default_render_device(self.enumerator)
                    if new_id and new_id != self.tracked_earphone_id:
                        cur_def_id, cur_def_name = new_id, new_name
                        break

            if cur_def_id != self.tracked_earphone_id:
                self.logger.warning(
                    "--> Wireless earphones disconnected! Windows switched default output to: '%s'",
                    cur_def_name
                )

                # Mute the newly selected default output device
                if self.mute_new_default_only:
                    mute_endpoint(
                        self.enumerator,
                        cur_def_id,
                        cur_def_name,
                        self.saved_device_states,
                        self.logger
                    )

                # Optional broad mode: mute all non-earphone render endpoints
                if self.mute_all_non_earphone:
                    try:
                        collection = self.enumerator.EnumAudioEndpoints(0, 1)  # eRender, ACTIVE
                        for idx in range(collection.GetCount()):
                            imm = collection.Item(idx)
                            dev_id = imm.GetId()
                            if dev_id != self.tracked_earphone_id and dev_id != cur_def_id:
                                dev = AudioUtilities.CreateDevice(imm)
                                mute_endpoint(
                                    self.enumerator,
                                    dev_id,
                                    dev.FriendlyName,
                                    self.saved_device_states,
                                    self.logger
                                )
                    except Exception as e:
                        self.logger.error("Error executing broad mute: %s", e)

                # Optional Media Pause
                if self.pause_media:
                    trigger_media_pause(self.logger)

                self.was_earphone_active_or_default = False
                self.last_default_id = cur_def_id
                self.last_default_name = cur_def_name
                self.logger.info("[STANDBY] Protection armed standby. Waiting for earphones to reconnect...")
                return

        # ----------------------------------------------------------------------
        # CASE 2: MANUAL DEVICE SWITCH (Scenario B)
        # ----------------------------------------------------------------------
        if earphone_active and cur_def_id != self.tracked_earphone_id:
            if cur_def_id != self.last_default_id:
                self.logger.info(
                    "Default playback device changed to '%s', but earphones ('%s') "
                    "are still connected. Treating as manual device switch (Scenario B); no mute applied.",
                    cur_def_name,
                    self.tracked_earphone_name
                )
                self.last_default_id = cur_def_id
                self.last_default_name = cur_def_name
                self.was_earphone_active_or_default = False
                return

        # ----------------------------------------------------------------------
        # CASE 3: EARPHONES RECONNECTED
        # ----------------------------------------------------------------------
        if earphone_active and cur_def_id == self.tracked_earphone_id:
            if not self.was_earphone_active_or_default:
                self.logger.info(
                    "Wireless earphones reconnected and active as default: '%s'",
                    self.tracked_earphone_name
                )
                self.was_earphone_active_or_default = True
                self.logger.info("[ARMED] Earphones are active. Laptop speakers will be muted if disconnected.")

                # Optional restoration
                if self.restore_on_reconnect and self.saved_device_states:
                    self.logger.info("Restoring previous audio states for muted devices...")
                    for dev_id in list(self.saved_device_states.keys()):
                        restore_endpoint(
                            self.enumerator,
                            dev_id,
                            self.saved_device_states,
                            self.logger
                        )

        # Update last known default
        self.last_default_id = cur_def_id
        self.last_default_name = cur_def_name

    def heartbeat_check(self):
        """
        Periodic fail-safe check run in the main thread loop.
        Re-acquires COM enumerator and re-registers callbacks if invalid (e.g. after laptop sleep).
        """
        with self._lock:
            try:
                self._process_state_transition(trigger_reason="Heartbeat sync")
            except (comtypes.COMError, OSError) as e:
                # 0x800706BA: RPC Server Unavailable / Sleep wake
                hr = getattr(e, "hresult", 0)
                if hr in (-2147023174, -2147467259):
                    self.logger.warning("Re-acquiring Windows Audio COM enumerator after system wake/disconnect...")
                    try:
                        self.enumerator = AudioUtilities.GetDeviceEnumerator()
                        self.enumerator.RegisterEndpointNotificationCallback(self)
                        self._is_registered = True
                        self.logger.info("Successfully re-registered audio event notifications after system wake.")
                    except Exception as re_err:
                        self.logger.debug("Re-registration note: %s", re_err)
            except Exception as e:
                self.logger.debug("Heartbeat sync note: %s", e)

# ==============================================================================
# MAIN APPLICATION CONTROLLER
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Windows Audio Auto-Mute Guardian: Mutes speakers when wireless earphones disconnect."
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List all audio playback endpoints with their names, states, and IDs, then exit."
    )
    parser.add_argument(
        "--test-mute",
        action="store_true",
        help="Test volume mute control on the default playback device (mutes for 2s, restores, then exits)."
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Override EARPHONE_DEVICE_NAME directly from the command line (e.g. --device 'RONiN ECLIPSE')."
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default=None,
        help="Override EARPHONE_DEVICE_ID directly from the command line."
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Enable RESTORE_ON_EARPHONE_RECONNECT behavior via command line."
    )
    parser.add_argument(
        "--pause-media",
        action="store_true",
        help="Send a Windows Media Play/Pause key event on disconnect to pause background playback."
    )
    args = parser.parse_args()

    if args.list_devices:
        print_devices_summary()
        return 0

    if args.test_mute:
        return run_test_mute()

    # CLI overrides for runtime convenience
    effective_name = args.device if args.device is not None else EARPHONE_DEVICE_NAME
    effective_id = args.device_id if args.device_id is not None else EARPHONE_DEVICE_ID
    effective_restore = True if args.restore else RESTORE_ON_EARPHONE_RECONNECT
    effective_pause = True if args.pause_media else PAUSE_MEDIA_ON_DISCONNECT

    logger = setup_logger(LOG_LEVEL, LOG_FILE)

    print("\n" + "=" * 65)
    print(" Windows Audio Auto-Mute Guardian")
    print("=" * 65)
    print(" Status: ACTIVE (Monitoring audio device events)")
    print(" Mode:   Non-persistent (Active ONLY while running)")
    print(" Exit:   Press Ctrl+C at any time to stop cleanly")
    print("=" * 65 + "\n")

    logger.info("Starting Audio Auto-Mute Guardian...")

    monitor = AudioAutoMuteMonitor(
        earphone_name=effective_name,
        earphone_id=effective_id,
        mute_new_default_only=MUTE_NEW_DEFAULT_ONLY,
        mute_all_non_earphone=MUTE_ALL_NON_EARPHONE_OUTPUTS,
        restore_on_reconnect=effective_restore,
        pause_media=effective_pause,
        logger=logger,
    )

    monitor.initialize_state()
    monitor.register_callbacks()

    shutdown_event = threading.Event()

    def signal_handler(signum, frame):
        logger.info("Interrupt signal received (%s). Initiating clean shutdown...", signum)
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Register Win32 console handler for clean exit when terminal window [X] is clicked
    try:
        from ctypes import wintypes
        HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        def win_console_ctrl_handler(ctrl_type):
            logger.info("Windows console event received (code=%d). Initiating clean shutdown...", ctrl_type)
            shutdown_event.set()
            try:
                monitor.unregister_callbacks()
                comtypes.CoUninitialize()
            except Exception:
                pass
            return True
        _console_ctrl_handler = HandlerRoutine(win_console_ctrl_handler)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_ctrl_handler, True)
    except Exception as e:
        logger.debug("Console handler note: %s", e)

    logger.info("Audio Auto-Mute Guardian is running. Waiting for events...")

    try:
        while not shutdown_event.is_set():
            if shutdown_event.wait(timeout=POLL_INTERVAL):
                break
            monitor.heartbeat_check()
    except (KeyboardInterrupt, SystemExit):
        logger.info("KeyboardInterrupt detected.")
    finally:
        print("\nStopping audio monitor...")
        print("Cleaning up resources...")
        monitor.unregister_callbacks()
        comtypes.CoUninitialize()
        print("Audio monitor stopped cleanly.")
        logger.info("Audio monitor stopped. Process exiting.")

    return 0

if __name__ == "__main__":
    sys.exit(main())
