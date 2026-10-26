"""Tests for payload interpretation in robot.py."""

from __future__ import annotations

import unittest

from _loader import load
import fixtures

robot = load("robot")


class MapTests(unittest.TestCase):
    """Active map, rooms and room settings."""

    def test_active_map_comes_from_live_task(self) -> None:
        self.assertEqual(robot.active_map_id(fixtures.device(), fixtures.task()), 2)

    def test_active_map_without_task_skips_settings_only_map_zero(self) -> None:
        # StdCleanCfg also lists map 0, which is not a real map.
        self.assertEqual(robot.active_map_id(fixtures.device(), None), 2)

    def test_map_name_and_fallback(self) -> None:
        device = fixtures.device()
        self.assertEqual(robot.map_name(device, 2), "Home.Ciubi")
        self.assertEqual(robot.map_name(device, 7), "Map 7")

    def test_rooms_are_translated(self) -> None:
        self.assertEqual(
            robot.rooms(fixtures.device(), 2),
            [
                ("8", "Bedroom"),
                ("9", "Living Room"),
                ("10", "Bathroom"),
                ("11", "Corridor"),
            ],
        )
        self.assertEqual(robot.rooms(fixtures.device(), 3), [])

    def test_custom_room_names_are_kept(self) -> None:
        self.assertEqual(robot.room_name("Office", 4), "Office")
        self.assertEqual(robot.room_name("", 4), "Room 4")

    def test_room_names_follow_the_language(self) -> None:
        self.assertEqual(robot.room_name("#@ChuF#", 1, "nl"), "Keuken")
        self.assertEqual(robot.room_name("#@ZouL#", 1, "de"), "Flur")
        self.assertEqual(robot.room_name("#@KeT#", 1, "en-GB"), "Living Room")
        self.assertEqual(robot.room_name("#@FangJ#4", 4, "nl"), "Ruimte 4")
        self.assertEqual(robot.room_name("", 7, "pl"), "Lokal 7")
        # Languages without a table fall back to English; typed names stay.
        self.assertEqual(robot.room_name("#@WoS#", 1, "is"), "Bedroom")
        self.assertEqual(robot.room_name("Office", 1, "nl"), "Office")
        self.assertEqual(robot.rooms(fixtures.device(), 2, "fr")[0], ("8", "Chambre"))

    def test_every_language_has_every_preset(self) -> None:
        names = load("room_names").ROOM_NAMES_BY_LANGUAGE
        for language, table in names.items():
            self.assertEqual(set(table), set(names["en"]), language)

    def test_app_names_and_language_variants(self) -> None:
        self.assertEqual(robot.room_name("#@ShuF#", 3, "nl"), "Studeerkamer")
        self.assertEqual(robot.room_name("#@WoS#", 1, "ro"), "Dormitor")
        self.assertEqual(robot.room_name("#@ChuF#", 1, "zh-Hans"), "厨房")
        self.assertEqual(robot.room_name("#@ChuF#", 1, "zh-Hant"), "廚房")

    def test_preset_names_with_index(self) -> None:
        self.assertEqual(robot.room_name("#@FangJ#4", 4), "Room 4")
        self.assertEqual(robot.room_name("#@KeT#2", 9), "Living Room 2")
        self.assertEqual(robot.room_name("#@Unknown#", 5), "Room 5")

    def test_rooms_fall_back_to_room_clean_config(self) -> None:
        # RE4: no RegionBasicInfo, rooms only in RoomCustomCleanCfg.
        device = {
            "FEATURE_INFO": {
                "0": {
                    "SweepingRobot": {
                        "SweeperMapMgr": {
                            "RoomCustomCleanCfg": [
                                {"mapID": 2, "room": [{"roomID": 0}, {"roomID": 3}]}
                            ]
                        }
                    }
                }
            }
        }
        self.assertEqual(robot.rooms(device, 2), [("0", "Room 0"), ("3", "Room 3")])
        self.assertEqual(robot.rooms(device, 4), [])

    def test_room_clean_configs_for_map(self) -> None:
        configs = robot.room_clean_configs(fixtures.device(), 2)
        self.assertEqual([room["roomID"] for room in configs], [8, 9])
        self.assertEqual(robot.room_clean_configs(fixtures.device(), 0), [])


class ModeTests(unittest.TestCase):
    """Cleaning mode."""

    def test_clean_mode_from_device(self) -> None:
        self.assertEqual(robot.clean_mode(fixtures.device()), "sweepThenMop")

    def test_unknown_clean_mode_is_ignored(self) -> None:
        device = fixtures.device()
        device["FEATURE_INFO"]["0"]["SweepingRobot"]["SweeperCleanTask"][
            "SweepMopMode"
        ] = "turbo"
        self.assertIsNone(robot.clean_mode(device))


class DeviceTests(unittest.TestCase):
    """Device registry details."""

    def test_firmware_comes_from_device_infos(self) -> None:
        details = robot.device_details(fixtures.device())
        self.assertEqual(details["sw_version"], "V2.0.2417 build 250331")

    def test_model_from_sub_category(self) -> None:
        details = robot.device_details(fixtures.device())
        self.assertEqual(details["model"], "RS20 Max")
        self.assertEqual(details["model_id"], "CS-RS20-MAX-TGA")
        self.assertEqual(details["name"], "EZVIZ RS20 Max")
        device = fixtures.device()
        device["deviceInfos"]["name"] = "Upstairs"
        self.assertEqual(robot.device_details(device)["name"], "Upstairs")

    def test_model_from_device_type(self) -> None:
        device = fixtures.device()
        del device["deviceInfos"]["deviceSubCategory"]
        self.assertEqual(robot.model_name(device), "RS20 Max")
        device["deviceInfos"]["deviceType"] = "CS-RS20-PRO-PGA2"
        self.assertEqual(robot.model_name(device), "RS20 Pro")

    def test_robot_detection(self) -> None:
        self.assertTrue(robot.is_robot(fixtures.device()))
        camera = {"deviceInfos": {"deviceCategory": "IPC"}, "FEATURE_INFO": {}}
        self.assertFalse(robot.is_robot(camera))

    def test_missing_firmware(self) -> None:
        self.assertIsNone(robot.device_details({})["sw_version"])


class ActivityTests(unittest.TestCase):
    """Vacuum activity from the live task."""

    def check(self, task_name: str, expected: str, **data) -> None:
        task = fixtures.task(currentTask=task_name, **data)
        self.assertEqual(robot.activity(task, fixtures.device()), expected, task_name)

    def test_cleaning(self) -> None:
        for name in ("clean", "regionClean", "sweep", "mop", "edgeClean"):
            self.check(name, robot.ACTIVITY_CLEANING, isOnBasestation=False)

    def test_station_tasks_are_docked_not_cleaning(self) -> None:
        for name in (
            "washMop",
            "dryMop",
            "collectDust",
            "baseSelfClean",
            "selfClean",
            "drainWater",
        ):
            self.check(name, robot.ACTIVITY_DOCKED)

    def test_charging_and_standby(self) -> None:
        self.check("charging", robot.ACTIVITY_DOCKED)
        self.check("standby", robot.ACTIVITY_DOCKED)
        self.check("standby", robot.ACTIVITY_IDLE, isOnBasestation=False)

    def test_pause_and_return(self) -> None:
        self.check("pause", robot.ACTIVITY_PAUSED, isOnBasestation=False)
        self.check("returnCharge", robot.ACTIVITY_RETURNING, isOnBasestation=False)
        self.check("recharge", robot.ACTIVITY_RETURNING, isOnBasestation=False)

    def test_paused_clean_task(self) -> None:
        task = fixtures.task(
            currentTask="clean",
            isOnBasestation=False,
            cleanTaskInfo={"status": "pause", "cleanRange": "full"},
        )
        self.assertEqual(robot.activity(task), robot.ACTIVITY_PAUSED)
        task["data"]["cleanTaskInfo"]["status"] = "running"
        self.assertEqual(robot.activity(task), robot.ACTIVITY_CLEANING)

    def test_exception_is_error(self) -> None:
        self.check("clean", robot.ACTIVITY_ERROR, exception="CR_CleanWaterBoxLow")

    def test_unknown_task_uses_station_flag(self) -> None:
        self.check("somethingNew", robot.ACTIVITY_DOCKED)
        self.check("somethingNew", robot.ACTIVITY_IDLE, isOnBasestation=False)


class CleanLogTests(unittest.TestCase):
    """The cloud clean log gives totals and the last clean (RE4)."""

    log = {
        "list": [
            {
                "cleanArea": 1.7,
                "cleanDuration": 133,
                "cleanRange": "region",
                "cleanMode": "sweep",
                "startType": "mobileAPP",
                "stopType": "normal",
                "startTime": "2026-10-25T20:57:19.000+01:00",
            },
            {
                "cleanArea": 16.17,
                "cleanDuration": 667,
                "cleanRange": "full",
                "cleanMode": "sweep",
                "startType": "timePlan",
                "stopType": "normal",
                "startTime": "2026-10-26T16:43:42.000+01:00",
            },
        ],
        "statistic": {"totalHour": 181.3831, "totalArea": 8661.93, "totalCount": 249},
    }

    def test_statistic(self) -> None:
        self.assertEqual(robot.clean_statistic(self.log)["totalCount"], 249)
        self.assertEqual(robot.clean_statistic(None), {})

    def test_last_clean_is_the_newest(self) -> None:
        last = robot.last_clean_from_log(self.log)
        self.assertEqual(last["area"], 16.17)
        self.assertEqual(last["duration_minutes"], 11)
        self.assertEqual(last["started_by"], "timePlan")
        self.assertIsNone(robot.last_clean_from_log({"list": []}))

    def test_newest_by_time_across_offsets(self) -> None:
        log = {
            "list": [
                {"id": 2, "cleanArea": 1, "startTime": "2026-10-26T10:00:00+02:00"},
                {"id": 1, "cleanArea": 2, "startTime": "2026-10-26T09:30:00+00:00"},
            ]
        }
        self.assertEqual(robot.last_clean_from_log(log)["area"], 2)


class ErrorTests(unittest.TestCase):
    """English error descriptions."""

    def test_numeric_and_named_codes(self) -> None:
        self.assertEqual(robot.error_description("321"), "Mop pad fell off")
        self.assertEqual(
            robot.error_description("CR_CleanWaterBoxLow"), "Clean water tank is low"
        )

    def test_chinese_description_is_translated(self) -> None:
        self.assertEqual(robot.error_description("", "主机被困"), "Robot is stuck")

    def test_unknown_codes(self) -> None:
        self.assertEqual(
            robot.error_description("CR_DustBoxMissing"), "Dust box missing"
        )
        self.assertEqual(robot.error_description("999", "未知"), "Robot error 999")
        self.assertEqual(
            robot.error_description("999", "Lidar blocked"), "Lidar blocked"
        )
        self.assertIsNone(robot.error_description("", ""))


class HistoryTests(unittest.TestCase):
    """Error and cleaning history from the diagnostic blobs."""

    def test_last_error(self) -> None:
        self.assertEqual(
            robot.last_error(fixtures.device()),
            {
                "code": "407",
                "description": "Base station communication error",
                "time": "2026-10-05T18:14:38.062",
            },
        )

    def test_last_clean_combines_passes(self) -> None:
        last = robot.last_clean(fixtures.device())
        self.assertEqual(last["area"], 29.4)
        self.assertEqual(last["duration_minutes"], 50)
        self.assertEqual(last["start"], "10-06 17:56:09.480")

    def test_no_history(self) -> None:
        device = fixtures.device()
        del device["FEATURE_INFO"]["0"]["SweepingRobot"]["OperationDiagnosis"]
        self.assertIsNone(robot.last_error(device))
        self.assertIsNone(robot.last_clean(device))


if __name__ == "__main__":
    unittest.main()
