"""
Unit & Integration Test Suite for Windows Audio Auto-Mute Guardian
Verifies state transitions, safety rules, mute logic, and persistence non-existence.
"""

import unittest
from unittest.mock import MagicMock, patch
import audio_auto_mute as aam


class TestAudioMuteGuardian(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.monitor = aam.AudioAutoMuteMonitor(
            earphone_name="RONiN ECLIPSE",
            earphone_id="{earphone-guid-1234}",
            mute_new_default_only=True,
            mute_all_non_earphone=False,
            restore_on_reconnect=False,
            logger=self.logger,
        )
        self.monitor.tracked_earphone_id = "{earphone-guid-1234}"
        self.monitor.tracked_earphone_name = "Headphones (RONiN ECLIPSE)"

    def test_mute_endpoint_when_unmuted(self):
        """Verify that an unmuted device is muted and marked as script_muted."""
        saved = {}
        mock_enum = MagicMock()
        mock_imm = MagicMock()
        mock_enum.GetDevice.return_value = mock_imm
        mock_dev = MagicMock()
        mock_vol = MagicMock()
        mock_vol.GetMute.return_value = 0  # Currently unmuted
        mock_vol.GetMasterVolumeLevelScalar.return_value = 0.35
        mock_dev.EndpointVolume = mock_vol

        with patch("audio_auto_mute.AudioUtilities.CreateDevice", return_value=mock_dev):
            res = aam.mute_endpoint(mock_enum, "dev_spk", "Speakers", saved, self.logger)
            self.assertTrue(res)
            self.assertIn("dev_spk", saved)
            self.assertTrue(saved["dev_spk"]["script_muted"])
            self.assertEqual(saved["dev_spk"]["previous_mute"], False)
            self.assertEqual(saved["dev_spk"]["previous_vol"], 0.35)
            mock_vol.SetMute.assert_called_once_with(1, None)

    def test_mute_endpoint_when_already_muted(self):
        """Verify that an already-muted device is NOT marked as script_muted and SetMute is skipped."""
        saved = {}
        mock_enum = MagicMock()
        mock_imm = MagicMock()
        mock_enum.GetDevice.return_value = mock_imm
        mock_dev = MagicMock()
        mock_vol = MagicMock()
        mock_vol.GetMute.return_value = 1  # Already muted!
        mock_vol.GetMasterVolumeLevelScalar.return_value = 0.22
        mock_dev.EndpointVolume = mock_vol

        with patch("audio_auto_mute.AudioUtilities.CreateDevice", return_value=mock_dev):
            res = aam.mute_endpoint(mock_enum, "dev_spk", "Speakers", saved, self.logger)
            self.assertTrue(res)
            self.assertIn("dev_spk", saved)
            self.assertFalse(saved["dev_spk"]["script_muted"])  # Script did NOT mute it!
            mock_vol.SetMute.assert_not_called()

    def test_restore_endpoint_safety(self):
        """Verify that restore never unmutes a device that was already muted."""
        mock_enum = MagicMock()

        # Case 1: Was already muted before script acted
        saved = {
            "dev_spk": {
                "name": "Speakers",
                "script_muted": False,
                "previous_mute": True,
            }
        }
        res = aam.restore_endpoint(mock_enum, "dev_spk", saved, self.logger)
        self.assertFalse(res)  # Must reject restoration!

        # Case 2: Was unmuted and script muted it
        mock_imm = MagicMock()
        mock_enum.GetDevice.return_value = mock_imm
        mock_dev = MagicMock()
        mock_vol = MagicMock()
        mock_dev.EndpointVolume = mock_vol
        saved = {
            "dev_spk": {
                "name": "Speakers",
                "script_muted": True,
                "previous_mute": False,
            }
        }
        with patch("audio_auto_mute.AudioUtilities.CreateDevice", return_value=mock_dev):
            res = aam.restore_endpoint(mock_enum, "dev_spk", saved, self.logger)
            self.assertTrue(res)
            self.assertFalse(saved["dev_spk"]["script_muted"])
            mock_vol.SetMute.assert_called_once_with(0, None)

    def test_scenario_a_disconnect_transition(self):
        """Scenario A: Earphones were active/default, disconnect -> switches to speakers -> mutes speakers."""
        self.monitor.was_earphone_active_or_default = True
        self.monitor.last_default_id = "{earphone-guid-1234}"

        with patch(
            "audio_auto_mute.get_default_render_device",
            return_value=("{speaker-guid}", "Speakers"),
        ), patch(
            "audio_auto_mute.is_device_active", return_value=False
        ), patch(
            "audio_auto_mute.mute_endpoint"
        ) as mock_mute:
            self.monitor._process_state_transition("Earphone disconnect event")
            mock_mute.assert_called_once()
            self.assertEqual(mock_mute.call_args[0][1], "{speaker-guid}")
            self.assertFalse(self.monitor.was_earphone_active_or_default)

    def test_scenario_b_manual_switch_transition(self):
        """Scenario B: Earphones still active, user manually changed default -> MUST NOT MUTE."""
        self.monitor.was_earphone_active_or_default = True
        self.monitor.last_default_id = "{earphone-guid-1234}"

        with patch(
            "audio_auto_mute.get_default_render_device",
            return_value=("{speaker-guid}", "Speakers"),
        ), patch(
            "audio_auto_mute.is_device_active", return_value=True
        ), patch(
            "audio_auto_mute.mute_endpoint"
        ) as mock_mute:
            self.monitor._process_state_transition("User manual switch")
            mock_mute.assert_not_called()  # Must NOT mute
            self.assertEqual(self.monitor.last_default_id, "{speaker-guid}")

    def test_reconnect_without_restore(self):
        """Earphones reconnect when RESTORE_ON_EARPHONE_RECONNECT is False -> does not restore."""
        self.monitor.restore_on_reconnect = False
        self.monitor.was_earphone_active_or_default = False
        self.monitor.saved_device_states = {
            "{speaker-guid}": {
                "name": "Speakers",
                "script_muted": True,
                "previous_mute": False,
            }
        }

        with patch(
            "audio_auto_mute.get_default_render_device",
            return_value=("{earphone-guid-1234}", "Headphones (RONiN ECLIPSE)"),
        ), patch(
            "audio_auto_mute.is_device_active", return_value=True
        ), patch(
            "audio_auto_mute.restore_endpoint"
        ) as mock_restore:
            self.monitor._process_state_transition("Reconnect event")
            mock_restore.assert_not_called()
            self.assertTrue(self.monitor.was_earphone_active_or_default)

    def test_reconnect_with_restore(self):
        """Earphones reconnect when RESTORE_ON_EARPHONE_RECONNECT is True -> restores muted endpoint."""
        self.monitor.restore_on_reconnect = True
        self.monitor.was_earphone_active_or_default = False
        self.monitor.saved_device_states = {
            "{speaker-guid}": {
                "name": "Speakers",
                "script_muted": True,
                "previous_mute": False,
            }
        }

        with patch(
            "audio_auto_mute.get_default_render_device",
            return_value=("{earphone-guid-1234}", "Headphones (RONiN ECLIPSE)"),
        ), patch(
            "audio_auto_mute.is_device_active", return_value=True
        ), patch(
            "audio_auto_mute.restore_endpoint"
        ) as mock_restore:
            self.monitor._process_state_transition("Reconnect event")
            mock_restore.assert_called_once_with(
                self.monitor.enumerator,
                "{speaker-guid}",
                self.monitor.saved_device_states,
                self.logger,
            )
            self.assertTrue(self.monitor.was_earphone_active_or_default)

    def test_disconnect_with_pause_media(self):
        """Verify that VK_MEDIA_PLAY_PAUSE is triggered when pause_media is True."""
        self.monitor.pause_media = True
        self.monitor.was_earphone_active_or_default = True
        self.monitor.last_default_id = "{earphone-guid-1234}"

        with patch("audio_auto_mute.get_default_render_device", return_value=("{speaker-guid}", "Speakers")), \
             patch("audio_auto_mute.is_device_active", return_value=False), \
             patch("audio_auto_mute.mute_endpoint"), \
             patch("audio_auto_mute.trigger_media_pause") as mock_pause:
            self.monitor._process_state_transition("Disconnect with media pause")
            mock_pause.assert_called_once_with(self.logger)

    def test_multi_device_list_detection(self):
        """Verify that a list of earphone names can be matched."""
        monitor = aam.AudioAutoMuteMonitor(
            earphone_name=["AirPods Pro", "RONiN ECLIPSE"],
            logger=self.logger
        )
        mock_enum = MagicMock()
        mock_imm = MagicMock()
        mock_imm.GetState.return_value = 8
        mock_dev = MagicMock()
        mock_dev.id = "{guid-ronin}"
        mock_dev.FriendlyName = "Headphones (RONiN ECLIPSE)"

        mock_collection = MagicMock()
        mock_collection.GetCount.return_value = 1
        mock_collection.Item.return_value = mock_imm
        mock_enum.EnumAudioEndpoints.return_value = mock_collection
        monitor.enumerator = mock_enum

        with patch("audio_auto_mute.AudioUtilities.CreateDevice", return_value=mock_dev):
            dev_id, name = monitor.discover_tracked_earphone()
            self.assertEqual(dev_id, "{guid-ronin}")
            self.assertEqual(name, "Headphones (RONiN ECLIPSE)")

    # --------------------------------------------------------------------------
    # Wireless Earphone Battery Monitoring Tests
    # --------------------------------------------------------------------------

    def test_battery_info_formatting_live(self):
        """Verify battery percentage formatting when live/connected."""
        info = aam.EarphoneBatteryInfo(
            overall=85,
            left=82,
            right=76,
            case=64,
            charging_overall=False,
            charging_left=False,
            charging_right=False,
            charging_case=True,
            is_live=True
        )
        self.assertEqual(info.format_percentage(info.overall), "85%")
        self.assertEqual(info.format_percentage(info.left), "82%")
        self.assertEqual(info.format_percentage(info.right), "76%")
        self.assertEqual(info.format_percentage(info.case), "64%")
        self.assertEqual(info.format_percentage(None), "Not available")
        self.assertEqual(info.format_charging(True), "Yes")
        self.assertEqual(info.format_charging(False), "No")
        self.assertEqual(info.format_charging(None), "N/A")
        self.assertIn("Left=82%", info.summary_str())
        self.assertIn("Right=76%", info.summary_str())
        self.assertIn("Case=64%", info.summary_str())
        self.assertNotIn("Last known", info.summary_str())

    def test_battery_info_formatting_stale_when_disconnected(self):
        """Verify that disconnected earphones label battery values as Last known."""
        info = aam.EarphoneBatteryInfo(
            overall=85,
            left=82,
            right=76,
            case=64,
            is_live=False
        )
        self.assertEqual(info.format_percentage(info.overall), "Last known: 85%")
        self.assertEqual(info.format_percentage(info.left), "Last known: 82%")
        self.assertEqual(info.format_percentage(info.right), "Last known: 76%")
        self.assertEqual(info.format_percentage(info.case), "Last known: 64%")
        self.assertIn("(Disconnected)", info.summary_str())
        self.assertIn("Last known", info.summary_str())

    def test_battery_never_guessed_or_fabricated(self):
        """Ensure missing components evaluate to None and format as Not available."""
        # Single HFP device reports only overall
        info = aam.EarphoneBatteryInfo(overall=100, is_live=True)
        self.assertIsNone(info.left)
        self.assertIsNone(info.right)
        self.assertIsNone(info.case)
        self.assertEqual(info.format_percentage(info.left), "Not available")
        self.assertEqual(info.format_percentage(info.right), "Not available")
        self.assertEqual(info.format_percentage(info.case), "Not available")
        self.assertEqual(info.format_percentage(info.overall), "100%")

    def test_low_battery_warning_trigger_and_anti_spam_latch(self):
        """Verify that low battery warning logs once and suppresses spam until state changes."""
        self.monitor.low_battery_warning_enabled = True
        self.monitor.low_battery_threshold = 20

        # Step 1: Battery drops to 18% -> warning triggered
        info1 = aam.EarphoneBatteryInfo(overall=18, left=18, is_live=True)
        self.monitor.check_low_battery_warnings(info1)
        self.assertEqual(self.logger.warning.call_count, 2)  # Left earbud + Wireless earphone

        # Step 2: Next check, battery still at 18% -> NO duplicate warning (anti-spam)
        self.logger.warning.reset_mock()
        self.monitor.check_low_battery_warnings(info1)
        self.logger.warning.assert_not_called()

        # Step 3: Battery drops by > 5% (to 12%) -> triggers update warning
        info2 = aam.EarphoneBatteryInfo(overall=12, left=12, is_live=True)
        self.monitor.check_low_battery_warnings(info2)
        self.assertEqual(self.logger.warning.call_count, 2)

        # Step 4: Recharged to 40% -> warning latch clears
        self.logger.warning.reset_mock()
        info3 = aam.EarphoneBatteryInfo(overall=40, left=40, is_live=True)
        self.monitor.check_low_battery_warnings(info3)
        self.logger.warning.assert_not_called()
        self.assertNotIn("Left earbud", self.monitor._warned_low_battery)
        self.assertNotIn("Wireless earphone", self.monitor._warned_low_battery)

    def test_case_low_battery_warning(self):
        """Verify charging case low-battery warning when case battery is available."""
        self.monitor.low_battery_warning_enabled = True
        self.monitor.low_battery_threshold = 20
        info = aam.EarphoneBatteryInfo(case=15, is_live=True)
        self.monitor.check_low_battery_warnings(info)
        self.logger.warning.assert_called_with("WARNING: %s battery is low: %d%%", "Charging case", 15)

    def test_low_battery_warning_disabled_when_disconnected(self):
        """Verify low battery warnings are suppressed when device is disconnected."""
        self.monitor.low_battery_warning_enabled = True
        self.monitor.low_battery_threshold = 20
        info = aam.EarphoneBatteryInfo(overall=10, is_live=False)
        self.monitor.check_low_battery_warnings(info)
        self.logger.warning.assert_not_called()

    def test_disconnect_marks_battery_last_known(self):
        """Verify disconnect transition marks battery status as not live."""
        self.monitor.was_earphone_active_or_default = True
        self.monitor.last_default_id = "{earphone-guid-1234}"
        self.monitor.battery_info = aam.EarphoneBatteryInfo(overall=90, is_live=True)

        with patch("audio_auto_mute.get_default_render_device", return_value=("{speaker-guid}", "Speakers")), \
             patch("audio_auto_mute.is_device_active", return_value=False), \
             patch("audio_auto_mute.mute_endpoint"):
            self.monitor._process_state_transition("Disconnect event")
            self.assertFalse(self.monitor.battery_info.is_live)
            self.assertEqual(self.monitor.battery_info.overall, 90)

    def test_reconnect_triggers_battery_refresh(self):
        """Verify earphone reconnect triggers immediate battery refresh."""
        self.monitor.was_earphone_active_or_default = False
        self.monitor.battery_monitoring_enabled = True

        with patch("audio_auto_mute.get_default_render_device", return_value=("{earphone-guid-1234}", "Headphones (RONiN ECLIPSE)")), \
             patch("audio_auto_mute.is_device_active", return_value=True), \
             patch.object(self.monitor, "refresh_battery") as mock_refresh:
            self.monitor._process_state_transition("Reconnect event")
            mock_refresh.assert_called_once_with(force=True)

    def test_audio_auto_mute_resilient_to_battery_failure(self):
        """Verify that any battery query error does NOT interrupt auto-mute protection."""
        self.monitor.was_earphone_active_or_default = True
        self.monitor.last_default_id = "{earphone-guid-1234}"

        with patch("audio_auto_mute.get_default_render_device", return_value=("{speaker-guid}", "Speakers")), \
             patch("audio_auto_mute.is_device_active", return_value=False), \
             patch("audio_auto_mute.mute_endpoint") as mock_mute, \
             patch.object(self.monitor, "refresh_battery", side_effect=RuntimeError("Simulated Bluetooth failure")):
            self.monitor._process_state_transition("Disconnect event")
            mock_mute.assert_called_once()
            self.assertFalse(self.monitor.was_earphone_active_or_default)

    def test_format_status_display(self):
        """Verify terminal status display formatting contains required sections."""
        self.monitor.battery_info = aam.EarphoneBatteryInfo(overall=100, is_live=True)
        display = self.monitor.format_status_display()
        self.assertIn("Windows Wireless Earphone Monitor", display)
        self.assertIn("Overall Battery:  100%", display)
        self.assertIn("Battery Monitor", display)
        self.assertIn("Audio Protection", display)


if __name__ == "__main__":
    unittest.main()

