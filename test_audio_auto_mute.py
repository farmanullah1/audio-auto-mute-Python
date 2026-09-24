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


if __name__ == "__main__":
    unittest.main()
