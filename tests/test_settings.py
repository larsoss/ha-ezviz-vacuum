"""Tests for building complete setting writes."""

from __future__ import annotations

import unittest

from _loader import load
import fixtures

settings = load("settings")
helpers = load("helpers")


class FieldSettingTests(unittest.TestCase):
    """Object settings keep their other fields."""

    def test_read(self) -> None:
        setting = settings.FieldSetting(
            "SweeperCleanTask", "CarpetCleanCfg", "turboClean"
        )
        self.assertIs(setting.read(fixtures.device()), True)

    def test_write_keeps_companions_and_drops_timestamp(self) -> None:
        setting = settings.FieldSetting(
            "SweeperCleanTask", "DustCollectionCfg", "enabled"
        )
        domain, identifier, payload = setting.write(fixtures.device(), None, False)
        self.assertEqual(
            (domain, identifier), ("SweeperCleanTask", "DustCollectionCfg")
        )
        self.assertEqual(payload, {"frequencyAfterClean": 1, "enabled": False})

    def test_write_does_not_touch_the_coordinator_data(self) -> None:
        device = fixtures.device()
        setting = settings.FieldSetting("SweeperCleanTask", "WashMopCfg", "interval")
        setting.write(device, None, 30)
        self.assertEqual(
            helpers.feature(device, "SweeperCleanTask", "WashMopCfg")["interval"], 15
        )

    def test_missing_feature_is_unavailable(self) -> None:
        setting = settings.FieldSetting("SweeperMgr", "Unknown", "enabled")
        self.assertFalse(setting.available(fixtures.device()))


class CarpetBoostTests(unittest.TestCase):
    """Carpet boost lives in CarpetCleanCfg (RS20) or CarpetTurboCleanSwitch (RE4)."""

    setting = settings.FirstAvailableSetting(
        (
            settings.FieldSetting("SweeperCleanTask", "CarpetCleanCfg", "turboClean"),
            settings.FlagFieldSetting(
                "SweeperCleanTask", "CarpetTurboCleanSwitch", "enabled"
            ),
        )
    )

    @staticmethod
    def re4(enabled: int) -> dict:
        return {
            "FEATURE_INFO": {
                "0": {
                    "SweepingRobot": {
                        "SweeperCleanTask": {
                            "CarpetTurboCleanSwitch": {"enabled": enabled}
                        }
                    }
                }
            }
        }

    def test_rs20_uses_carpet_clean_cfg(self) -> None:
        self.assertIs(self.setting.read(fixtures.device()), True)
        domain, identifier, _ = self.setting.write(fixtures.device(), None, False)
        self.assertEqual(identifier, "CarpetCleanCfg")

    def test_re4_reads_flag_and_writes_boolean(self) -> None:
        self.assertIs(self.setting.read(self.re4(1)), True)
        self.assertIs(self.setting.read(self.re4(0)), False)
        domain, identifier, payload = self.setting.write(self.re4(1), None, False)
        self.assertEqual(
            (domain, identifier), ("SweeperCleanTask", "CarpetTurboCleanSwitch")
        )
        self.assertEqual(payload, {"enabled": False})

    def test_unavailable_without_either(self) -> None:
        self.assertFalse(self.setting.available({}))


class ScalarSettingTests(unittest.TestCase):
    """Plain values are sent as they are."""

    def test_read_and_write(self) -> None:
        setting = settings.ScalarSetting("SoundSetting", "PromptToneVolume")
        self.assertEqual(setting.read(fixtures.device()), 100)
        self.assertEqual(
            setting.write(fixtures.device(), None, 40),
            ("SoundSetting", "PromptToneVolume", 40),
        )


class MapCleanSettingTests(unittest.TestCase):
    """Whole-home settings belong to the active map."""

    def test_reads_active_map_not_default_entry(self) -> None:
        setting = settings.MapCleanSetting("fanMode")
        self.assertEqual(setting.read(fixtures.device(), fixtures.task()), "super")

    def test_write_changes_only_the_active_map(self) -> None:
        setting = settings.MapCleanSetting("fanMode")
        _, _, payload = setting.write(fixtures.device(), fixtures.task(), "quiet")
        by_map = {entry["mapID"]: entry for entry in payload}
        self.assertEqual(by_map[2]["fanMode"], "quiet")
        self.assertEqual(by_map[0]["fanMode"], "normal")
        self.assertEqual(by_map[2]["waterQuantity"], "middle")

    def test_write_adds_missing_map(self) -> None:
        setting = settings.MapCleanSetting("waterQuantity")
        _, _, payload = setting.write(
            fixtures.device(), fixtures.task(currentMapID=7), "high"
        )
        added = [entry for entry in payload if entry["mapID"] == 7]
        self.assertEqual(added[0]["waterQuantity"], "high")
        self.assertEqual(len(payload), 3)


class ActionTests(unittest.TestCase):
    """Cleaning settings are changed through robot actions."""

    def test_map_setting_action(self) -> None:
        self.assertEqual(
            settings.MapCleanSetting("fanMode").action(
                fixtures.device(), fixtures.task(), "quiet"
            ),
            ("SweeperMapMgr", "SetFanModeOfStdClean", {"mapID": 2, "fanMode": "quiet"}),
        )
        self.assertEqual(
            settings.MapCleanSetting("cleanConfigType").action(
                fixtures.device(), fixtures.task(), "custom"
            )[1],
            "SetCleanCfg",
        )

    def test_room_setting_action_keeps_other_fields(self) -> None:
        self.assertEqual(
            settings.RoomCleanSetting(8, "waterQuantity").action(
                fixtures.device(), fixtures.task(), "high"
            ),
            (
                "SweeperMapMgr",
                "SetRoomCustomCleanCfg",
                {
                    "mapID": 2,
                    "roomID": 8,
                    "fanMode": "normal",
                    "waterQuantity": "high",
                    "cleanTimes": 1,
                },
            ),
        )

    def test_global_clean_cfg_fallback_for_re7(self) -> None:
        device = fixtures.device()
        tree = load("robot").robot_features(device)
        tree["SweeperMapMgr"]["GlobalCleanCfg"] = [
            {"mapID": 2, "fanMode": "normal", "waterQuantity": "low", "ts": 1}
        ]
        setting = settings.MapCleanSetting("fanMode")
        self.assertEqual(
            setting.fallback_action(device, fixtures.task(), "super"),
            (
                "SweeperMapMgr",
                "SetGlobalCleanCfg",
                {
                    "mapID": 2,
                    "fanMode": "super",
                    "waterQuantity": "low",
                    "cleanMode": "sweepThenMop",
                    "dataSource": "global",
                },
            ),
        )
        del tree["SweeperMapMgr"]["StdCleanCfg"]
        self.assertEqual(setting.read(device, fixtures.task()), "normal")
        self.assertIsNone(
            settings.MapCleanSetting("cleanTimes").fallback_action(
                device, fixtures.task(), 2
            )
        )

    def test_feature_settings_have_no_action(self) -> None:
        self.assertIsNone(
            settings.ScalarSetting("SoundSetting", "PromptToneVolume").action(
                fixtures.device(), None, 50
            )
        )


class RoomCleanSettingTests(unittest.TestCase):
    """Per-room settings change one room of the active map."""

    def test_read(self) -> None:
        setting = settings.RoomCleanSetting(9, "fanMode")
        self.assertEqual(setting.read(fixtures.device(), fixtures.task()), "normal")

    def test_write_one_room(self) -> None:
        setting = settings.RoomCleanSetting(8, "cleanTimes")
        domain, identifier, payload = setting.write(
            fixtures.device(), fixtures.task(), 2
        )
        self.assertEqual((domain, identifier), ("SweeperMapMgr", "RoomCustomCleanCfg"))
        rooms = {room["roomID"]: room for room in payload[0]["room"]}
        self.assertEqual(rooms[8]["cleanTimes"], 2)
        self.assertEqual(rooms[9]["cleanTimes"], 1)
        self.assertEqual(rooms[8]["order"], 3)

    def test_unknown_room_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            settings.RoomCleanSetting(99, "fanMode").write(
                fixtures.device(), fixtures.task(), "quiet"
            )


class RestPlanSettingTests(unittest.TestCase):
    """Do-not-disturb keeps the rest of the period."""

    def test_read(self) -> None:
        self.assertEqual(
            settings.RestPlanSetting("endTime").read(fixtures.device()), "07:00:00"
        )

    def test_write(self) -> None:
        _, identifier, payload = settings.RestPlanSetting("startTime").write(
            fixtures.device(), None, "23:30:00"
        )
        self.assertEqual(identifier, "RestPlan")
        self.assertEqual(
            payload,
            {
                "plan": [
                    {
                        "startTime": "23:30:00",
                        "ID": 0,
                        "endTime": "07:00:00",
                        "enabled": True,
                        "cleanContinue": False,
                    }
                ]
            },
        )

    def test_write_creates_a_period(self) -> None:
        device = fixtures.device()
        device["FEATURE_INFO"]["0"]["SweepingRobot"]["SweeperMgr"]["RestPlan"] = {
            "plan": []
        }
        _, _, payload = settings.RestPlanSetting("enabled").write(device, None, True)
        self.assertTrue(payload["plan"][0]["enabled"])
        self.assertEqual(payload["plan"][0]["ID"], 0)


class CleanPlanSettingTests(unittest.TestCase):
    """Schedules are changed one at a time."""

    def test_list_and_read(self) -> None:
        device = fixtures.device()
        self.assertEqual([p["planID"] for p in settings.clean_plans(device)], [0])
        self.assertEqual(
            settings.CleanPlanSetting(0, "startTime").read(device), "10:00:00"
        )

    def test_write_keeps_the_action(self) -> None:
        _, identifier, payload = settings.CleanPlanSetting(0, "enabled").write(
            fixtures.device(), None, True
        )
        self.assertEqual(identifier, "CleanPlan")
        plan = payload["Plan"][0]
        self.assertTrue(plan["enabled"])
        self.assertEqual(plan["Action"]["cleanMode"], "sweepThenMop")
        self.assertEqual(plan["RepeatPeriod"], [1, 2, 3, 4, 5, 6, 7])
        self.assertNotIn("ts", payload)

    def test_unknown_schedule(self) -> None:
        with self.assertRaises(ValueError):
            settings.CleanPlanSetting(5, "enabled").write(fixtures.device(), None, True)


class ApplyWriteTests(unittest.TestCase):
    """Local updates mirror what was sent."""

    def test_apply_write_updates_a_copy(self) -> None:
        device = fixtures.device()
        setting = settings.FieldSetting("SweeperCleanTask", "WashMopCfg", "interval")
        updated = settings.apply_write(device, setting.write(device, None, 30))
        self.assertEqual(setting.read(updated), 30)
        self.assertEqual(setting.read(device), 15)
        self.assertIn("ts", helpers.feature(updated, "SweeperCleanTask", "WashMopCfg"))

    def test_apply_scalar(self) -> None:
        device = fixtures.device()
        setting = settings.ScalarSetting("SweeperCleanTask", "SweepMopMode")
        updated = settings.apply_write(device, setting.write(device, None, "mop"))
        self.assertEqual(setting.read(updated), "mop")

    def test_every_setting_targets_an_allowed_feature(self) -> None:
        const = load("const")
        self.assertNotIn(
            ("SweeperMgr", "CliffDetectionSwitch"), const.WRITABLE_FEATURES
        )


if __name__ == "__main__":
    unittest.main()
