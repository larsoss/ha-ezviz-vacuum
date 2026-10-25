"""EZVIZ robot requests on the integration's own cloud session."""

from __future__ import annotations

import base64
from collections.abc import Callable
import gzip
from importlib import metadata
import json
from typing import Any
import zlib

from .const import CLEAN_MODES, SETTING_ACTIONS, WRITABLE_FEATURES


class EzvizVacuumApiError(Exception):
    """Raised when the robot endpoint rejects a request."""


class UnknownActionError(EzvizVacuumApiError):
    """Raised when the robot model does not have the requested function."""


_UNKNOWN_ACTION = "设备功能未报备"


# Details the cloud sends in Chinese when it refuses a request.
_REJECTIONS = {
    "设备不支持该功能": "the robot does not support this",
    "设备功能未报备": "this model does not declare this function",
    "设备不在线": "the robot is offline",
    "设备响应超时": "the robot did not answer in time",
    "主人，我正在清洁，请稍后再试": "the robot is busy cleaning, try again later",
}


def rejection_reason(result: dict[str, Any], code: Any) -> str:
    """Return a readable reason for a refused request."""
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    message = meta.get("message") or result.get("msg") or "request refused"
    more = meta.get("moreInfo")
    detail = more.get("msgDetail") if isinstance(more, dict) else None
    if isinstance(detail, str) and detail:
        detail = _REJECTIONS.get(detail.strip(), detail.strip())
        if len(detail) > 300:
            detail = detail[:300] + "..."
        return f"{message} ({detail}, code {code})"
    return f"{message} (code {code})"


# Map layer -> key of the layer in the cloud response.
MAP_LAYERS = {
    "map": "sweepRuleMapVo",
    "region": "sweepRuleRegionVo",
    "path": "sweepRulePathVo",
}


class EzvizVacuumApi:
    """Robot commands and reads; ``cloud`` is an ``EzvizCloud``."""

    def __init__(self, cloud: Any) -> None:
        self._cloud = cloud
        # (serial, command group) pairs that need a model's alternative command.
        self._alternatives: set[tuple[str, str]] = set()

    def _with_alternative(
        self,
        serial: str,
        group: str,
        primary: Callable[[], dict[str, Any]],
        alternative: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Run ``primary``; fall back for models that name the command differently.

        The answer is remembered per robot, so the fallback costs one extra
        request only the first time.
        """
        key = (serial.upper(), group)
        if key in self._alternatives:
            return alternative()
        try:
            return primary()
        except UnknownActionError:
            result = alternative()
            self._alternatives.add(key)
            return result

    def query_current_task(self, serial: str) -> dict[str, Any]:
        """Query current task; this action does not move or configure the robot."""
        return self._iot_request(
            serial,
            endpoint="action",
            domain="SweeperTaskMgr",
            identifier="QueryCurrentTask",
            payload={},
        )

    def clean_control(self, serial: str, command: str) -> dict[str, Any]:
        """Start, resume, pause or stop cleaning.

        Most models use ``CleanControl`` with the bare command string; the RS2
        and RE4 made by EZVIZ's manufacturer use ``CleanCtrl`` with an object
        payload instead (the same shape as ``RechargeCtrl``).
        """
        if command not in {"start", "resume", "pause", "stop"}:
            raise ValueError(f"Unsupported robot command: {command}")

        def send(identifier: str, payload: Any) -> dict[str, Any]:
            return self._iot_request(
                serial,
                endpoint="action",
                domain="SweeperCleanTask",
                identifier=identifier,
                payload=payload,
            )

        return self._with_alternative(
            serial,
            "clean",
            lambda: send("CleanControl", command),
            lambda: send("CleanCtrl", {"action": command, "source": "mobile"}),
        )

    def recharge_control(self, serial: str, command: str) -> dict[str, Any]:
        """Send the robot to its base (``start``) or cancel that (``stop``).

        The RS2 made by EZVIZ's manufacturer uses ``RechargeCtrl`` with an
        object payload instead.
        """
        if command not in {"start", "stop"}:
            raise ValueError(f"Unsupported recharge command: {command}")
        return self._with_alternative(
            serial,
            "recharge",
            lambda: self._iot_request(
                serial,
                endpoint="action",
                domain="SweeperTaskMgr",
                identifier="RechargeControl",
                payload=command,
            ),
            lambda: self._iot_request(
                serial,
                endpoint="action",
                domain="SweeperTaskMgr",
                identifier="RechargeCtrl",
                payload={"action": command, "source": "mobile"},
            ),
        )

    def set_clean_mode(self, serial: str, mode: str) -> dict[str, Any]:
        """Set the sweep/mop mode used by future cleaning runs."""
        if mode not in CLEAN_MODES:
            raise ValueError(f"Unsupported cleaning mode: {mode}")
        return self._iot_request(
            serial,
            endpoint="feature",
            domain="SweeperCleanTask",
            identifier="SweepMopMode",
            payload=mode,
        )

    def set_feature(
        self,
        serial: str,
        *,
        domain: str,
        identifier: str,
        value: Any,
    ) -> dict[str, Any]:
        """Write the complete value of an allow-listed robot setting."""
        if (domain, identifier) not in WRITABLE_FEATURES:
            raise ValueError(f"Unsupported robot setting: {domain}/{identifier}")
        if value is None:
            raise ValueError(f"No value for {domain}/{identifier}")
        return self._iot_request(
            serial,
            endpoint="feature",
            domain=domain,
            identifier=identifier,
            payload=value,
        )

    def send_setting_action(
        self,
        serial: str,
        *,
        domain: str,
        action: str,
        payload: dict[str, Any],
        fallback: tuple[str, str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an allow-listed settings action to the robot.

        ``fallback`` is ``(domain, action, payload)`` for models that do not
        have ``action``.
        """
        targets = [(domain, action)] + ([fallback[:2]] if fallback else [])
        for target_domain, target_action in targets:
            if (target_domain, target_action) not in SETTING_ACTIONS:
                raise ValueError(
                    f"Unsupported robot action: {target_domain}/{target_action}"
                )

        def send(target: tuple[str, str, Any]) -> dict[str, Any]:
            return self._iot_request(
                serial,
                endpoint="action",
                domain=target[0],
                identifier=target[1],
                payload=target[2],
            )

        if fallback is None:
            return send((domain, action, payload))
        return self._with_alternative(
            serial,
            f"setting:{domain}/{action}",
            lambda: send((domain, action, payload)),
            lambda: send(fallback),
        )

    def start_region_clean(
        self,
        serial: str,
        *,
        map_id: int,
        room_ids: list[int],
    ) -> dict[str, Any]:
        """Clean selected rooms with the settings stored on the robot.

        This is the payload the EZVIZ app sends; the robot applies its own
        whole-home or per-room settings and the cleaning mode.
        """
        if not room_ids:
            raise ValueError("No room selected")
        payload = {
            "mapID": int(map_id),
            "region": [
                {"regionType": "room", "roomID": int(room_id)} for room_id in room_ids
            ],
        }
        return self._iot_request(
            serial,
            endpoint="action",
            domain="SweeperCleanTask",
            identifier="StartRegionClean",
            payload=payload,
        )

    def client_diagnostics(self) -> dict[str, Any]:
        """Return non-secret library and service-host information."""
        token = self._cloud.token()
        service_urls = token.get("service_urls")
        version = "unknown"
        try:
            version = metadata.version("pyezvizapi")
        except metadata.PackageNotFoundError:
            pass
        return {
            "pyezvizapi_version": version,
            "api_host": token.get("api_url"),
            "service_urls": service_urls if isinstance(service_urls, dict) else {},
        }

    def fetch_map_layer(
        self,
        serial: str,
        layer: str,
        *,
        map_id: int,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Read one map layer (``map``, ``region`` or ``path``) from the cloud.

        This is how the EZVIZ app loads the map; it only reads data.
        """
        if layer not in MAP_LAYERS:
            raise ValueError(f"Unknown map layer: {layer}")
        params: dict[str, Any] = {"deviceSerial": serial.upper(), "mapId": int(map_id)}
        if version is not None:
            params["version"] = int(version)
        response = self._cloud.request(
            "POST", f"/v3/sweeprobot/v3/rule/{layer}", params=params
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise EzvizVacuumApiError("EZVIZ returned an invalid map response")
        meta = result.get("meta")
        code = meta.get("code") if isinstance(meta, dict) else None
        if code not in (None, 0, 200, "0", "200"):
            raise EzvizVacuumApiError(f"map/{layer}: {rejection_reason(result, code)}")
        value = result.get(MAP_LAYERS[layer])
        return value if isinstance(value, dict) else {}

    @staticmethod
    def decode_diagnostic_blob(blob: Any) -> Any:
        """Decode the gzip/base64 diagnostic fields reported by the robot."""
        if not isinstance(blob, dict) or not isinstance(blob.get("content"), str):
            return None
        try:
            raw = base64.b64decode(blob["content"], validate=True)
        except (ValueError, TypeError):
            return {"error": "Invalid base64 encoding"}

        decoded: bytes | None = None
        for decoder in (
            gzip.decompress,
            zlib.decompress,
            lambda data: zlib.decompress(data, -zlib.MAX_WBITS),
        ):
            try:
                decoded = decoder(raw)
                break
            except (OSError, zlib.error):
                continue
        if decoded is None:
            decoded = raw
        try:
            text = decoded.decode("utf-8")
        except UnicodeDecodeError:
            return {"binary_bytes": len(decoded)}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text[:4000], "truncated": len(text) > 4000}

    def raw_feature_request(
        self,
        serial: str,
        *,
        method: str,
        endpoint: str,
        domain: str,
        identifier: str,
        payload: Any = None,
        resource: str = "SweepingRobot",
        local_index: str = "0",
    ) -> dict[str, Any]:
        """Send one iot-feature request and return the raw response.

        Used by the admin-only protocol diagnostics service. Errors reported
        by the cloud are returned instead of raised so they can be inspected.
        """
        method = method.upper()
        if method not in {"GET", "PUT"}:
            raise ValueError("Only GET and PUT are supported")
        if endpoint not in {"feature", "action"}:
            raise ValueError("Endpoint must be 'feature' or 'action'")
        path = (
            f"/v3/iot-feature/{endpoint}/"
            f"{serial.upper()}/{resource}/{local_index}/{domain}/{identifier}"
        )
        if method == "PUT":
            response = self._cloud.request(
                method,
                path,
                data=json.dumps(payload, separators=(",", ":")),
                headers={"Content-Type": "application/json"},
            )
        else:
            response = self._cloud.request(method, path)
        try:
            body: Any = response.json()
        except ValueError:
            body = {"text": response.text[:2000]}
        return {"http_status": response.status_code, "response": body}

    def raw_api_request(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send one request to the account's EZVIZ API host."""
        method = method.upper()
        if method not in {"GET", "POST", "PUT"}:
            raise ValueError("Only GET, POST and PUT are supported")
        if not path.startswith("/") or "://" in path:
            raise ValueError("Path must be relative to the EZVIZ API host")
        response = self._cloud.request(
            method,
            path,
            params=params,
            data=data,
            json_body=json_body,
            headers={str(k): str(v) for k, v in (headers or {}).items()},
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = {
                "content_type": response.headers.get("Content-Type", ""),
                "bytes": len(response.content or b""),
            }
        return {"http_status": response.status_code, "response": body}

    def _iot_request(
        self,
        serial: str,
        *,
        endpoint: str,
        domain: str,
        identifier: str,
        payload: Any,
    ) -> dict[str, Any]:
        response = self._cloud.request(
            "PUT",
            f"/v3/iot-feature/{endpoint}/"
            f"{serial.upper()}/SweepingRobot/0/{domain}/{identifier}",
            data=json.dumps(payload, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise EzvizVacuumApiError("EZVIZ returned an invalid response")

        meta = result.get("meta")
        code = meta.get("code") if isinstance(meta, dict) else result.get("code")
        if code not in (None, 0, 200, "0", "200"):
            meta = meta if isinstance(meta, dict) else {}
            more = meta.get("moreInfo")
            detail = more.get("msgDetail") if isinstance(more, dict) else None
            error = (
                UnknownActionError
                if isinstance(detail, str) and detail.strip() == _UNKNOWN_ACTION
                else EzvizVacuumApiError
            )
            raise error(f"{domain}/{identifier}: {rejection_reason(result, code)}")
        return result
