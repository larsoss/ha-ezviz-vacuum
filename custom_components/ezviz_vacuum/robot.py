"""Interpretation of EZVIZ robot payloads (no Home Assistant imports)."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import re
from typing import Any

from .api import EzvizVacuumApi
from .const import CLEAN_MODES
from .helpers import feature, robot_features

# Preset room names are stored by the robot as pinyin codes.
ROOM_NAMES = {
    "#@ChuF#": "Kitchen",
    "#@KeT#": "Living Room",
    "#@WoS#": "Bedroom",
    "#@ZhuW#": "Master Bedroom",
    "#@CiW#": "Guest Bedroom",
    "#@ErTF#": "Kids Room",
    "#@XuanG#": "Entrance",
    "#@WeiYJ#": "Bathroom",
    "#@ZouL#": "Hallway",
    "#@CanT#": "Dining Room",
    "#@ShuF#": "Study",
    "#@YangT#": "Balcony",
    "#@YiMJ#": "Closet",
    "#@XiYF#": "Laundry Room",
    "#@FangJ#": "Room",
}

# A preset code, optionally with a trailing index (e.g. "#@FangJ#4").
_PRESET_NAME = re.compile(r"^(#@\w+#)(\d*)$")


def task_data(task: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return the ``data`` block of a QueryCurrentTask response."""
    if isinstance(task, Mapping):
        data = task.get("data")
        if isinstance(data, Mapping):
            return data
    return {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _map_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def active_map_id(
    device: Mapping[str, Any] | None, task: Mapping[str, Any] | None = None
) -> int | None:
    """Return the map the robot is using.

    The live task reports ``currentMapID``. Without it, prefer a map marked
    ``inUse``, then any map that has rooms, then the first known map.
    """
    current = _map_id(task_data(task).get("currentMapID"))
    if current is not None and current > 0:
        return current
    maps = [
        item
        for item in _as_list(feature(device, "SweeperMapMgr", "MapBasicProperty"))
        if isinstance(item, Mapping) and _map_id(item.get("mapID")) is not None
    ]
    for item in maps:
        if item.get("inUse") is True:
            return _map_id(item["mapID"])
    for map_id in room_map_ids(device):
        return map_id
    if maps:
        return _map_id(maps[0]["mapID"])
    return current


# Live task version keys for each map layer.
_LAYER_VERSION_KEYS = {"map": "mapOutline", "region": "roomOutline", "path": "path"}


def map_versions(task: Mapping[str, Any] | None, map_id: int | None) -> dict[str, int]:
    """Return the current version of each map layer of ``map_id``.

    The cloud only needs to be asked for a layer again when its version
    changes.
    """
    for item in _as_list(task_data(task).get("version")):
        if not isinstance(item, Mapping) or _map_id(item.get("mapID")) != map_id:
            continue
        result = {}
        for layer, key in _LAYER_VERSION_KEYS.items():
            value = _map_id(item.get(key))
            if value is not None:
                result[layer] = value
        return result
    return {}


def room_map_ids(device: Mapping[str, Any] | None) -> list[int]:
    """Return the IDs of maps that have room information."""
    info = feature(device, "SweeperMapMgr", "RegionBasicInfo")
    result = []
    for item in _as_list(info.get("mapList") if isinstance(info, Mapping) else None):
        if isinstance(item, Mapping) and (map_id := _map_id(item.get("mapID"))):
            result.append(map_id)
    return result


def map_name(device: Mapping[str, Any] | None, map_id: int | None) -> str:
    """Return the user-given map name, or ``Map N``."""
    for item in _as_list(feature(device, "SweeperMapMgr", "MapBasicProperty")):
        if (
            isinstance(item, Mapping)
            and _map_id(item.get("mapID")) == map_id
            and item.get("mapName")
        ):
            return str(item["mapName"])
    return f"Map {map_id}" if map_id is not None else "Map"


def room_name(raw_name: Any, room_id: Any) -> str:
    """Translate a robot room name into a readable name.

    Rooms are named by a preset code (``#@CanT#`` -> Dining Room), a preset
    code with a trailing index (``#@FangJ#4`` -> Room 4), or free text the
    user typed in the app (returned as-is). An unknown preset code falls back
    to ``Room N`` rather than surfacing the raw ``#@...#`` wrapper.
    """
    name = str(raw_name or "").strip()
    if not name:
        return f"Room {room_id}"
    if name in ROOM_NAMES:
        return ROOM_NAMES[name]
    match = _PRESET_NAME.match(name)
    if match:
        base, index = ROOM_NAMES.get(match.group(1)), match.group(2)
        if base:
            return f"{base} {index}" if index else base
        return f"Room {index or room_id}"
    return name


def rooms(
    device: Mapping[str, Any] | None, map_id: int | None
) -> list[tuple[str, str]]:
    """Return ``(room_id, name)`` for the rooms of ``map_id``."""
    info = feature(device, "SweeperMapMgr", "RegionBasicInfo")
    for item in _as_list(info.get("mapList") if isinstance(info, Mapping) else None):
        if not isinstance(item, Mapping) or _map_id(item.get("mapID")) != map_id:
            continue
        found = [
            (str(region["ID"]), room_name(region.get("name"), region["ID"]))
            for region in _as_list(item.get("regionList"))
            if isinstance(region, Mapping)
            and region.get("regionType") == "room"
            and region.get("ID") is not None
        ]
        if found:
            return found
    # Fallback: some models (e.g. the RE4 / CS-RE4P-PWT) don't report
    # RegionBasicInfo at all — their rooms live in RoomCustomCleanCfg instead,
    # keyed `roomID`. No name is carried there, so room_name() falls back to
    # "Room N". The RoomBasicProperty feature holds only a capability flag
    # (a bare `true`), not the user-assigned names.
    for item in _as_list(feature(device, "SweeperMapMgr", "RoomCustomCleanCfg")):
        if not isinstance(item, Mapping) or _map_id(item.get("mapID")) != map_id:
            continue
        return [
            (str(room["roomID"]), room_name(room.get("name"), room["roomID"]))
            for room in _as_list(item.get("room"))
            if isinstance(room, Mapping) and room.get("roomID") is not None
        ]
    return []


def room_clean_configs(
    device: Mapping[str, Any] | None, map_id: int | None
) -> list[dict[str, Any]]:
    """Return the per-room cleaning settings of ``map_id``."""
    for item in _as_list(feature(device, "SweeperMapMgr", "RoomCustomCleanCfg")):
        if isinstance(item, Mapping) and _map_id(item.get("mapID")) == map_id:
            return [
                dict(room)
                for room in _as_list(item.get("room"))
                if isinstance(room, Mapping)
            ]
    return []


def clean_mode(device: Mapping[str, Any] | None) -> str | None:
    """Return the configured sweep/mop mode, if it is a known value."""
    mode = feature(device, "SweeperCleanTask", "SweepMopMode")
    return mode if mode in CLEAN_MODES else None


def model_name(device: Mapping[str, Any] | None) -> str:
    """Return a readable model such as ``RS20 Max``."""
    info = _device_infos(device)
    sub = str(info.get("deviceSubCategory") or "").strip()
    if sub:
        return sub
    device_type = str(info.get("deviceType") or "").strip().upper()
    parts = [part for part in device_type.split("-") if part]
    if parts and parts[0] == "CS":
        parts = parts[1:]
    if len(parts) > 2:
        parts = parts[:-1]  # drop the regional/hardware suffix
    if parts:
        return " ".join([parts[0], *(part.capitalize() for part in parts[1:])])
    return "Robot vacuum"


def is_robot(device: Mapping[str, Any] | None) -> bool:
    """Return whether a device payload belongs to an EZVIZ robot vacuum."""
    info = _device_infos(device)
    if str(info.get("deviceCategory", "")).casefold() == "sweepingrobot":
        return True
    if not isinstance(device, Mapping):
        return False
    for resource in _as_list(device.get("resourceInfos")):
        if (
            isinstance(resource, Mapping)
            and str(resource.get("resourceCategory", "")).casefold() == "sweepingrobot"
        ):
            return True
    return bool(robot_features(device))


def device_details(device: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Return model, name and firmware for the device registry."""
    info = _device_infos(device)
    version = info.get("version")
    model = model_name(device)
    name = str(info.get("name") or "").strip() or model
    # A name the owner chose ("Upstairs") is kept as is; the app's default,
    # the bare model name, gets the brand so it reads "EZVIZ RS20 Max".
    if name.casefold() == model.casefold() and not name.upper().startswith("EZVIZ"):
        name = f"EZVIZ {name}"
    return {
        "model": model,
        "model_id": str(info.get("deviceType") or "") or None,
        "name": name,
        "sw_version": str(version) if version else None,
    }


def _device_infos(device: Mapping[str, Any] | None) -> Mapping[str, Any]:
    info = device.get("deviceInfos") if isinstance(device, Mapping) else None
    return info if isinstance(info, Mapping) else {}


ACTIVITY_CLEANING = "cleaning"
ACTIVITY_PAUSED = "paused"
ACTIVITY_RETURNING = "returning"
ACTIVITY_DOCKED = "docked"
ACTIVITY_IDLE = "idle"
ACTIVITY_ERROR = "error"

# Tasks the base station runs while the robot sits on it. Matched before the
# generic "clean" check so that e.g. mop washing or self cleaning is not
# reported as the robot cleaning the floor.
_STATION_WORDS = (
    "wash",
    "dry",
    "collect",
    "dust",
    "selfclean",
    "drain",
    "addwater",
    "station",
    "upgrade",
)
_RETURN_WORDS = ("return", "recharge", "backcharge", "gohome", "goback")
_CLEAN_WORDS = (
    "clean",
    "sweep",
    "mop",
    "work",
    "run",
    "explor",
    "buildmap",
    "relocat",
    "spot",
    "zone",
    "region",
    "edge",
)
_REST_WORDS = ("standby", "idle", "sleep", "rest", "none", "")


def current_task(task: Mapping[str, Any] | None) -> str:
    """Return the raw current task name reported by the robot."""
    return str(task_data(task).get("currentTask") or "")


def task_exception(task: Mapping[str, Any] | None) -> str | None:
    """Return the active exception code, if the robot reports one."""
    data = task_data(task)
    for key in ("exception", "exceptionCode"):
        value = str(data.get(key) or "").strip()
        if value and value.casefold() not in ("none", "normal", "0"):
            return value
    return None


def task_paused(task: Mapping[str, Any] | None) -> bool:
    """Return whether the current task reports itself as paused.

    A paused clean keeps ``currentTask: clean`` and reports the pause in
    ``cleanTaskInfo.status`` (likewise for other ``*TaskInfo`` blocks).
    """
    for key, value in task_data(task).items():
        if str(key).endswith("TaskInfo") and isinstance(value, Mapping):
            status = str(value.get("status") or "").casefold()
            if status.startswith("pause") or status == "suspend":
                return True
    return False


def activity(
    task: Mapping[str, Any] | None, device: Mapping[str, Any] | None = None
) -> str:
    """Map the live task to a vacuum activity (see ``ACTIVITY_*``)."""
    if task_exception(task):
        return ACTIVITY_ERROR
    data = task_data(task)
    name = current_task(task).replace("_", "").casefold()
    on_station = data.get("isOnBasestation") is True

    if "pause" in name or "suspend" in name or task_paused(task):
        return ACTIVITY_PAUSED
    if any(word in name for word in _RETURN_WORDS):
        return ACTIVITY_RETURNING
    if "charg" in name:
        return ACTIVITY_DOCKED
    if any(word in name for word in _STATION_WORDS):
        return ACTIVITY_DOCKED
    if name in _REST_WORDS:
        return ACTIVITY_DOCKED if on_station else ACTIVITY_IDLE
    if any(word in name for word in _CLEAN_WORDS):
        return ACTIVITY_CLEANING

    info = _device_infos(device)
    if info.get("status") in (0, "0"):
        return ACTIVITY_ERROR
    return ACTIVITY_DOCKED if on_station else ACTIVITY_IDLE


# Error codes reported in the robot's abnormal history and live task,
# with the Chinese description the robot sends for each.
ERROR_CODES: dict[str, str] = {
    "201": "Mop pad installation failed",
    "301": "Side brush is tangled",
    "302": "Main brush is tangled",
    "316": "Dirty water tank is full",
    "321": "Mop pad fell off",
    "324": "Clean water tank is empty",
    "404": "Robot is stuck",
    "405": "Docking failed in front of the station",
    "406": "Could not relocate on the map",
    "407": "Base station communication error",
    "411": "Could not find the station to dock",
    "413": "Docking failed (did not start from the station)",
    "414": "Leaving the station is blocked",
    "CR_CleanWaterBoxLow": "Clean water tank is low",
}
_CHINESE_ERRORS: dict[str, str] = {
    "拖布盘安装失败": "201",
    "边刷被缠绕": "301",
    "滚刷缠绕": "302",
    "污水箱满水": "316",
    "拖布盘脱落异常": "321",
    "清水箱缺水": "324",
    "主机被困": "404",
    "在基站前回充失败": "405",
    "重定位失败": "406",
    "基站通信连接异常": "407",
    "不在基站前回充失败": "411",
    "没有从基站出发回充失败": "413",
    "出基站被阻挡": "414",
}
_CJK = re.compile(r"[\u3400-\u9fff]")


def error_description(code: Any, description: Any = None) -> str | None:
    """Return an English description for a robot error code."""
    code_text = str(code or "").strip()
    desc_text = str(description or "").strip()
    if not code_text and not desc_text:
        return None
    if code_text in ERROR_CODES:
        return ERROR_CODES[code_text]
    if desc_text in _CHINESE_ERRORS:
        return ERROR_CODES[_CHINESE_ERRORS[desc_text]]
    if desc_text and not _CJK.search(desc_text):
        return desc_text
    if code_text.startswith("CR_"):
        words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", code_text[3:]).lower()
        return words[:1].upper() + words[1:]
    return f"Robot error {code_text}" if code_text else "Robot error"


@lru_cache(maxsize=8)
def _decode_history(content: str) -> tuple[Mapping[str, Any], ...]:
    decoded = EzvizVacuumApi.decode_diagnostic_blob({"content": content})
    items = decoded.get("list") if isinstance(decoded, Mapping) else None
    return tuple(item for item in _as_list(items) if isinstance(item, Mapping))


def history(
    device: Mapping[str, Any] | None, key: str
) -> tuple[Mapping[str, Any], ...]:
    """Return ``cleanHistory`` or ``abnormalHistory`` entries, oldest first."""
    params = feature(device, "OperationDiagnosis", "DeviceOperationParams")
    blob = params.get(key) if isinstance(params, Mapping) else None
    content = blob.get("content") if isinstance(blob, Mapping) else None
    return _decode_history(content) if isinstance(content, str) else ()


def last_error(device: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the most recent entry of the robot's error history."""
    entries = history(device, "abnormalHistory")
    if not entries:
        return None
    entry = max(entries, key=lambda item: str(item.get("datetime") or ""))
    code = str(entry.get("no") or "")
    return {
        "code": code or None,
        "description": error_description(code, entry.get("name")),
        "time": entry.get("datetime"),
    }


def _numbers(value: Any) -> list[float]:
    result = []
    for part in str(value or "").split(","):
        try:
            result.append(float(part))
        except ValueError:
            continue
    return result


def last_clean(device: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the most recent cleaning run.

    Runs that sweep and then mop report one area and duration per pass.
    """
    entries = history(device, "cleanHistory")
    if not entries:
        return None
    entry = max(entries, key=lambda item: _map_id(item.get("ID")) or 0)
    areas = _numbers(entry.get("cleanArea"))
    durations = _numbers(entry.get("cleanDuration"))
    return {
        "area": max(areas) if areas else None,
        "duration_minutes": int(sum(durations)) if durations else None,
        "start": entry.get("startDatetime"),
        "end": entry.get("stopDatetime"),
        "cleaning_mode": entry.get("cleanMode"),
        "cleaning_range": entry.get("cleanRange"),
        "started_by": entry.get("startType"),
        "stop_reason": entry.get("stopType"),
        "map_id": entry.get("mapID"),
    }
