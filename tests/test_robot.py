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


class GhostRoomTests(unittest.TestCase):
    """Rooms the app made up, and entities left behind by older versions."""

    def test_default_names_are_generic(self) -> None:
        for raw in ("#@FangJ#13", "#@FangJ#", "#@FangJ#4", "", None, "  "):
            self.assertTrue(robot.is_generic_room_name(raw), raw)

    def test_real_names_are_not_generic(self) -> None:
        for raw in ("#@KeT#", "#@ChuF#", "Tuin", "Woonkamer", "Room 13"):
            self.assertFalse(robot.is_generic_room_name(raw), raw)

    def test_only_unprovided_room_entities_are_stale(self) -> None:
        registered = [
            "BC1_room_0_suction",
            "BC1_room_4_suction",
            "BC1_room_4_water_level",
            "BC1_room_7_cleaning_passes",
            "BC1_room_settings",
            "BC1_battery",
        ]
        keep = {"BC1_room_0_suction"}
        self.assertEqual(
            robot.stale_room_entities(registered, keep),
            [
                "BC1_room_4_suction",
                "BC1_room_4_water_level",
                "BC1_room_7_cleaning_passes",
            ],
        )

    def test_nothing_is_stale_when_everything_is_provided(self) -> None:
        registered = ["BC1_room_0_suction", "BC1_room_12_water_level"]
        self.assertEqual(robot.stale_room_entities(registered, set(registered)), [])

    def test_rooms_follow_the_map_only_when_limited_by_it(self) -> None:
        names = {0: "Kitchen", 1: "Living room"}
        self.assertTrue(
            robot.rooms_follow_map([("0", "Kitchen"), ("1", "Living room")], names)
        )
        # Fell back to every configured room: nothing may be removed.
        self.assertFalse(
            robot.rooms_follow_map([("0", "Room 0"), ("4", "Room 4")], names)
        )
        self.assertFalse(robot.rooms_follow_map([("0", "Room 0")], {}))
        self.assertFalse(robot.rooms_follow_map([], names))


class ChargingStatusTests(unittest.TestCase):
    """A docked robot is on the ``charging`` task even while it waits."""

    @staticmethod
    def _task(status):
        data = {"currentTask": "charging", "inCharging": 0}
        if status is not None:
            data["chargingTaskInfo"] = {"status": status}
        return {"data": data}

    def test_waiting_for_the_off_peak_hours(self) -> None:
        self.assertEqual(
            robot.charging_status(self._task("waitingCharge")), "waiting_charge"
        )

    def test_charging(self) -> None:
        self.assertEqual(robot.charging_status(self._task("charging")), "charging")

    def test_no_status(self) -> None:
        for task in (self._task(None), None, {}, {"data": {}}):
            self.assertIsNone(robot.charging_status(task))
        self.assertIsNone(robot.charging_status(self._task("")))
        self.assertIsNone(
            robot.charging_status({"data": {"chargingTaskInfo": "waitingCharge"}})
        )

    def test_unknown_status_is_passed_on_in_snake_case(self) -> None:
        self.assertEqual(robot.charging_status(self._task("chargeFull")), "charge_full")

    def test_the_task_name_alone_still_means_docked(self) -> None:
        self.assertEqual(
            robot.activity(self._task("waitingCharge")), robot.ACTIVITY_DOCKED
        )


class EventTests(unittest.TestCase):
    """The app's event list, as the cloud returns it."""

    MESSAGES = [
        {
            "subType": 2401,
            "msgId": "MVOADPKDN81_4QB3XF600_AB1234567_0",
            "title": "RobbyAnti-drop sensor blocked, please wipe it",
            "from": "Robby",
            "time": 1792960486573,
            "timeStr": "2026-10-25 20:34:46",
            "ext": {"alarmName": "Robby", "alarmType": 30097},
        },
        {
            "subType": 2401,
            "msgId": "MVO91ZB8N8D_4QB21N800_AB1234567_0",
            "title": "RobbyThe wheel is suspended, please put the device on the ground",
            "from": "Robby",
            "time": 1792958259716,
            "timeStr": "2026-10-25 19:57:39",
            "ext": {"alarmName": "Robby", "alarmType": 30109},
        },
    ]

    def test_the_device_name_is_left_out_of_the_text(self) -> None:
        found = robot.events(self.MESSAGES)
        self.assertEqual(found[0]["text"], "Anti-drop sensor blocked, please wipe it")
        self.assertEqual(found[0]["code"], 30097)
        self.assertEqual(found[0]["type"], 2401)
        self.assertEqual(found[0]["id"], "MVOADPKDN81_4QB3XF600_AB1234567_0")

    def test_newest_event_comes_first(self) -> None:
        found = robot.events(list(reversed(self.MESSAGES)))
        self.assertEqual(found[0]["code"], 30097)
        self.assertEqual(found[1]["code"], 30109)

    def test_time_is_the_one_the_app_shows(self) -> None:
        # The cloud's epoch is the robot's local time read as UTC, so the
        # readable time string is used.
        self.assertEqual(robot.events(self.MESSAGES)[0]["time"], "2026-10-25 20:34:46")

    def test_text_without_the_device_name_is_kept(self) -> None:
        found = robot.events([{"title": "Cleaning completed", "from": "Robby"}])
        self.assertEqual(found[0]["text"], "Cleaning completed")

    def test_empty_and_odd_input(self) -> None:
        for value in (None, [], "x", [{"title": ""}], [None, 3], [{"from": "Robby"}]):
            self.assertEqual(robot.events(value), [])


class ErrorExplanationTests(unittest.TestCase):
    """A bare error code from the live task gets the app's explanation."""

    EVENTS = [
        {
            "text": "The wheel is suspended, please put the device on the ground",
            "time": "2026-10-27 09:16:03",
            "code": 30109,
        },
        {"text": "Cleaning completed", "time": "2026-10-27 07:41:02", "code": 30084},
    ]

    @staticmethod
    def _error(robot_time):
        return {"code": "0xe0010025", "robot_time": robot_time}

    def test_the_message_a_few_seconds_away_is_the_explanation(self) -> None:
        found = robot.event_for_error(
            self._error("2026-10-27T09:16:06.000"), self.EVENTS
        )
        self.assertEqual(found["code"], 30109)

    def test_the_closest_message_wins(self) -> None:
        events = [
            {"text": "far", "time": "2026-10-27 09:15:00"},
            {"text": "near", "time": "2026-10-27 09:16:10"},
        ]
        found = robot.event_for_error(self._error("2026-10-27T09:16:06.000"), events)
        self.assertEqual(found["text"], "near")

    def test_a_message_from_hours_ago_is_not_used(self) -> None:
        self.assertIsNone(
            robot.event_for_error(self._error("2026-10-27T11:00:00.000"), self.EVENTS)
        )

    def test_no_clock_or_no_events(self) -> None:
        self.assertIsNone(robot.event_for_error(self._error(None), self.EVENTS))
        self.assertIsNone(robot.event_for_error({"code": "x"}, self.EVENTS))
        self.assertIsNone(robot.event_for_error(None, self.EVENTS))
        self.assertIsNone(
            robot.event_for_error(self._error("2026-10-27T09:16:06.000"), None)
        )
        self.assertIsNone(
            robot.event_for_error(
                self._error("2026-10-27T09:16:06.000"), [{"text": "x", "time": "?"}]
            )
        )

    def test_offsets_on_the_robot_clock_are_ignored(self) -> None:
        found = robot.event_for_error(
            self._error("2026-10-27T09:16:06.000+01:00"), self.EVENTS
        )
        self.assertEqual(found["code"], 30109)


class ActiveErrorTests(unittest.TestCase):
    """An error that was already there before the integration started."""

    EVENTS = [
        {
            "text": "The wheel is suspended, please put the device on the ground",
            "time": "2026-10-27 09:16:03",
            "code": 30109,
            "notice": False,
        },
        {
            "text": "Cleaning completed",
            "time": "2026-10-27 07:41:02",
            "code": 30084,
            "notice": True,
        },
    ]
    ERROR = {"code": "0xe0010025", "robot_time": "2026-10-27T09:25:37.000"}

    def test_no_match_close_in_time_without_the_fallback(self) -> None:
        self.assertIsNone(robot.event_for_error(self.ERROR, self.EVENTS))

    def test_the_newest_earlier_fault_is_used_for_an_active_error(self) -> None:
        found = robot.event_for_error(self.ERROR, self.EVENTS, earlier=6 * 3600)
        self.assertEqual(found["code"], 30109)

    def test_a_finished_clean_is_never_the_explanation(self) -> None:
        events = [self.EVENTS[1]]
        error = {"code": "x", "robot_time": "2026-10-27T07:41:30.000"}
        self.assertIsNone(robot.event_for_error(error, events))
        self.assertIsNone(robot.event_for_error(error, events, earlier=6 * 3600))

    def test_old_messages_are_not_used(self) -> None:
        error = {"code": "x", "robot_time": "2026-10-27T20:00:00.000"}
        self.assertIsNone(robot.event_for_error(error, self.EVENTS, earlier=6 * 3600))

    def test_notices_are_recognised_in_the_cloud_messages(self) -> None:
        found = robot.events(
            [
                {
                    "title": "RobbyCleaning completed",
                    "from": "Robby",
                    "time": 2,
                    "ext": {"alarmType": 30084},
                },
                {
                    "title": "RobbyDone",
                    "from": "Robby",
                    "time": 1,
                    "detailLink": '{"biz":"DeviceRS2ODM","entry":"CleanLog"}',
                },
                {
                    "title": "RobbyThe wheel is suspended",
                    "from": "Robby",
                    "time": 0.5,
                    "detailLink": '{"biz":"DeviceRS2ODM","entry":"index"}',
                    "ext": {"alarmType": 30109},
                },
            ]
        )
        self.assertEqual([event["notice"] for event in found], [True, True, False])

    def test_the_error_code_has_a_description_of_its_own(self) -> None:
        self.assertEqual(
            robot.error_description("0xe0010025"),
            "The wheel is suspended, put the robot on the ground",
        )


class DockedRobotTests(unittest.TestCase):
    """What the RE4 reports while it sits on its dock waiting to charge."""

    @staticmethod
    def _task(name, flag=0, status=None):
        data = {"currentTask": name, "inCharging": 0, "isOnBasestation": flag}
        if status is not None:
            data["chargingTaskInfo"] = {"status": status}
        return {"data": data}

    def test_waiting_to_charge_is_not_shown_as_charging(self) -> None:
        task = self._task("charging", status="waitingCharge")
        self.assertEqual(robot.display_task(task), "waiting_charge")
        # The task itself is unchanged: the robot is still docked.
        self.assertEqual(robot.current_task(task), "charging")
        self.assertEqual(robot.activity(task), robot.ACTIVITY_DOCKED)

    def test_real_charging_and_other_tasks_keep_their_name(self) -> None:
        self.assertEqual(
            robot.display_task(self._task("charging", status="charging")), "charging"
        )
        self.assertEqual(robot.display_task(self._task("charging")), "charging")
        self.assertEqual(robot.display_task(self._task("clean")), "clean")
        self.assertEqual(robot.display_task(None), "")

    def test_a_charging_robot_is_on_the_station_although_the_flag_says_0(self) -> None:
        self.assertIs(robot.on_base_station(self._task("charging", 0)), True)
        self.assertIs(
            robot.on_base_station(self._task("charging", 0, "waitingCharge")), True
        )

    def test_the_flag_still_counts(self) -> None:
        self.assertIs(robot.on_base_station(self._task("standby", 1)), True)
        self.assertIs(robot.on_base_station(self._task("standby", True)), True)

    def test_a_robot_on_the_floor_is_not_on_the_station(self) -> None:
        self.assertIs(robot.on_base_station(self._task("clean", 0)), False)
        self.assertIs(robot.on_base_station(self._task("recharge", 0)), False)
        self.assertIs(robot.on_base_station(self._task("backcharge", 0)), False)

    def test_station_tasks_count_as_docked(self) -> None:
        self.assertIs(robot.on_base_station(self._task("washmop", 0)), True)

    def test_no_information(self) -> None:
        self.assertIsNone(robot.on_base_station(None))
        self.assertIsNone(robot.on_base_station({"data": {"currentTask": ""}}))

    def test_a_numeric_flag_makes_a_resting_robot_docked(self) -> None:
        self.assertEqual(
            robot.activity(self._task("standby", 1)), robot.ACTIVITY_DOCKED
        )
        self.assertEqual(robot.activity(self._task("standby", 0)), robot.ACTIVITY_IDLE)


if __name__ == "__main__":
    unittest.main()
