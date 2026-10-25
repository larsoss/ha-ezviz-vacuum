"""Unit tests for the EZVIZ robot request adapter."""

from __future__ import annotations

import base64
import gzip
import json
import unittest

from _loader import load

EzvizVacuumApi = load("api").EzvizVacuumApi


class FakeResponse:
    """Small requests.Response stand-in."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """Capture PUT calls."""

    def __init__(self) -> None:
        self.headers = {"sessionId": "secret"}
        self.calls: list[dict] = []

    def put(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse({"meta": {"code": 200}, "data": {"ok": True}})

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse({"meta": {"code": 200}, "data": {"path": []}})


class FakeClient:
    """Stand-in for ``EzvizCloud``: records requests on a fake HTTP session."""

    def __init__(self) -> None:
        self._session = FakeSession()
        self._token = {"api_url": "api.example.test", "session_id": "secret"}

    def token(self) -> dict:
        return dict(self._token)

    def request(
        self,
        method: str,
        path: str,
        *,
        params=None,
        data=None,
        json_body=None,
        headers=None,
    ):
        url = f"https://{self._token['api_url']}{path}"
        kwargs = {"params": params, "data": data, "json": json_body}
        if headers:
            kwargs["headers"] = headers
        if method == "PUT":
            return self._session.put(url, **kwargs)
        if method == "POST":
            return self._session.post(url, **kwargs)
        return self._session.request(method, url, **kwargs)


class ApiTests(unittest.TestCase):
    """Verify routes and JSON string bodies."""

    def setUp(self) -> None:
        self.client = FakeClient()
        self.api = EzvizVacuumApi(self.client)

    def test_query_current_task(self) -> None:
        self.api.query_current_task("ab1234567")
        call = self.client._session.calls[0]
        self.assertTrue(
            call["url"].endswith(
                "/AB1234567/SweepingRobot/0/SweeperTaskMgr/QueryCurrentTask"
            )
        )
        self.assertEqual(call["data"], "{}")

    def test_clean_control_uses_json_string(self) -> None:
        self.api.clean_control("AB1234567", "pause")
        call = self.client._session.calls[0]
        self.assertTrue(
            call["url"].endswith(
                "/AB1234567/SweepingRobot/0/SweeperCleanTask/CleanControl"
            )
        )
        self.assertEqual(json.loads(call["data"]), "pause")

    def test_return_to_base_uses_recharge_control(self) -> None:
        self.api.recharge_control("AB1234567", "start")
        call = self.client._session.calls[0]
        self.assertTrue(
            call["url"].endswith(
                "/AB1234567/SweepingRobot/0/SweeperTaskMgr/RechargeControl"
            )
        )
        self.assertEqual(json.loads(call["data"]), "start")
        with self.assertRaises(ValueError):
            self.api.clean_control("AB1234567", "return_charge")

    def test_resume_command(self) -> None:
        self.api.clean_control("AB1234567", "resume")
        self.assertEqual(json.loads(self.client._session.calls[0]["data"]), "resume")

    def test_unknown_command_is_rejected_locally(self) -> None:
        with self.assertRaises(ValueError):
            self.api.clean_control("AB1234567", "factory_reset")
        self.assertEqual(self.client._session.calls, [])

    def test_set_feature_uses_feature_endpoint(self) -> None:
        self.api.set_feature(
            "ab1234567",
            domain="SweeperBaseStationMgr",
            identifier="ChildLockSwitch",
            value={"enabled": True},
        )
        call = self.client._session.calls[0]
        self.assertTrue(
            call["url"].endswith(
                "/AB1234567/SweepingRobot/0/SweeperBaseStationMgr/ChildLockSwitch"
            )
        )
        self.assertEqual(json.loads(call["data"]), {"enabled": True})

    def test_unlisted_feature_is_rejected_locally(self) -> None:
        with self.assertRaises(ValueError):
            self.api.set_feature(
                "ab1234567",
                domain="SweeperBaseStationMgr",
                identifier="FactoryReset",
                value={"enabled": True},
            )
        self.assertEqual(self.client._session.calls, [])

    def test_cliff_detection_is_never_written(self) -> None:
        with self.assertRaises(ValueError):
            self.api.set_feature(
                "ab1234567",
                domain="SweeperMgr",
                identifier="CliffDetectionSwitch",
                value=False,
            )
        self.assertEqual(self.client._session.calls, [])

    def test_fetch_map_layer_posts_to_rule_route(self) -> None:
        self.client._session.post = lambda url, **kw: (
            self.client._session.calls.append({"url": url, **kw})
            or FakeResponse({"meta": {"code": 200}, "sweepRuleMapVo": {"mapId": 2}})
        )
        value = self.api.fetch_map_layer("ab1234567", "map", map_id=2, version=7)
        call = self.client._session.calls[0]
        self.assertTrue(call["url"].endswith("/v3/sweeprobot/v3/rule/map"))
        self.assertEqual(
            call["params"], {"deviceSerial": "AB1234567", "mapId": 2, "version": 7}
        )
        self.assertEqual(value, {"mapId": 2})

    def test_unknown_map_layer_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.api.fetch_map_layer("ab1234567", "everything", map_id=2)

    def test_start_region_clean_sends_room_ids_like_the_app(self) -> None:
        self.api.start_region_clean("ab1234567", map_id=2, room_ids=[11, 8])
        call = self.client._session.calls[0]
        self.assertTrue(
            call["url"].endswith(
                "/AB1234567/SweepingRobot/0/SweeperCleanTask/StartRegionClean"
            )
        )
        self.assertEqual(
            json.loads(call["data"]),
            {
                "mapID": 2,
                "region": [
                    {"regionType": "room", "roomID": 11},
                    {"regionType": "room", "roomID": 8},
                ],
            },
        )
        with self.assertRaises(ValueError):
            self.api.start_region_clean("ab1234567", map_id=2, room_ids=[])

    def test_setting_action_is_allow_listed(self) -> None:
        self.api.send_setting_action(
            "ab1234567",
            domain="SweeperMapMgr",
            action="SetFanModeOfStdClean",
            payload={"mapID": 2, "fanMode": "quiet"},
        )
        call = self.client._session.calls[0]
        self.assertIn("/v3/iot-feature/action/", call["url"])
        self.assertTrue(call["url"].endswith("/SweeperMapMgr/SetFanModeOfStdClean"))
        with self.assertRaises(ValueError):
            self.api.send_setting_action(
                "ab1234567", domain="SweeperMapMgr", action="DeleteMap", payload={}
            )

    def test_clean_mode_accepts_robot_enum(self) -> None:
        for mode in ("sweep", "mop", "sweepAndMop", "sweepThenMop"):
            self.api.set_clean_mode("ab1234567", mode)
        sent = [json.loads(call["data"]) for call in self.client._session.calls]
        self.assertEqual(sent, ["sweep", "mop", "sweepAndMop", "sweepThenMop"])
        with self.assertRaises(ValueError):
            self.api.set_clean_mode("ab1234567", "sweepMop")

    def test_decode_diagnostic_blob(self) -> None:
        content = base64.b64encode(gzip.compress(b'{"path":[1,2,3]}')).decode()
        result = self.api.decode_diagnostic_blob(
            {"encodeType": "gzip/base64", "content": content}
        )
        self.assertEqual(result, {"path": [1, 2, 3]})


class RejectionTests(unittest.TestCase):
    """Refused requests explain why."""

    def test_chinese_detail_is_translated(self) -> None:
        reason = load("api").rejection_reason(
            {
                "meta": {
                    "code": 400,
                    "message": "Incorrect request parameter.",
                    "moreInfo": {"msgDetail": "设备不支持该功能"},
                }
            },
            400,
        )
        self.assertEqual(
            reason,
            "Incorrect request parameter. (the robot does not support this, code 400)",
        )

    def test_without_detail(self) -> None:
        reason = load("api").rejection_reason({"meta": {"message": "Bad"}}, 500)
        self.assertEqual(reason, "Bad (code 500)")


if __name__ == "__main__":
    unittest.main()


class UnknownActionSession(FakeSession):
    """Refuse the given actions the way a model without them does."""

    def __init__(self, unknown: set[str]) -> None:
        super().__init__()
        self.unknown = unknown

    def put(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if url.rsplit("/", 1)[-1] in self.unknown:
            return FakeResponse(
                {
                    "meta": {
                        "code": 400,
                        "message": "Incorrect request parameter.",
                        "moreInfo": {"msgDetail": "设备功能未报备"},
                    }
                }
            )
        return FakeResponse({"meta": {"code": 200}})


class ModelVariantTests(unittest.TestCase):
    """Models that name commands differently fall back once, then remember."""

    def setUp(self) -> None:
        self.client = FakeClient()
        self.client._session = UnknownActionSession({"CleanControl", "RechargeControl"})
        self.api = EzvizVacuumApi(self.client)

    def names(self) -> list[str]:
        return [call["url"].rsplit("/", 1)[-1] for call in self.client._session.calls]

    def test_clean_control_falls_back_to_clean_ctrl(self) -> None:
        self.api.clean_control("AB1234567", "start")
        self.api.clean_control("AB1234567", "pause")
        self.assertEqual(self.names(), ["CleanControl", "CleanCtrl", "CleanCtrl"])
        # CleanControl takes the bare command; CleanCtrl (RS2, RE4) an object.
        self.assertEqual(json.loads(self.client._session.calls[0]["data"]), "start")
        self.assertEqual(
            json.loads(self.client._session.calls[-1]["data"]),
            {"action": "pause", "source": "mobile"},
        )

    def test_recharge_falls_back_to_recharge_ctrl(self) -> None:
        self.api.recharge_control("AB1234567", "start")
        self.assertEqual(self.names(), ["RechargeControl", "RechargeCtrl"])
        self.assertEqual(
            json.loads(self.client._session.calls[-1]["data"]),
            {"action": "start", "source": "mobile"},
        )

    def test_setting_falls_back(self) -> None:
        self.client._session.unknown = {"SetFanModeOfStdClean"}
        self.api.send_setting_action(
            "AB1234567",
            domain="SweeperMapMgr",
            action="SetFanModeOfStdClean",
            payload={"mapID": 2, "fanMode": "strong"},
            fallback=(
                "SweeperMapMgr",
                "SetGlobalCleanCfg",
                {"mapID": 2, "fanMode": "strong", "dataSource": "global"},
            ),
        )
        self.assertEqual(self.names(), ["SetFanModeOfStdClean", "SetGlobalCleanCfg"])

    def test_other_errors_do_not_fall_back(self) -> None:
        self.client._session.unknown = set()
        session = self.client._session
        session.put = lambda url, **kw: (
            session.calls.append({"url": url, **kw})
            or FakeResponse({"meta": {"code": 500, "message": "busy"}})
        )
        with self.assertRaises(load("api").EzvizVacuumApiError):
            self.api.clean_control("AB1234567", "start")
        self.assertEqual(self.names(), ["CleanControl"])
