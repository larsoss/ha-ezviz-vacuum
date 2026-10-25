"""Readable and writable robot settings (no Home Assistant imports).

Each setting knows where its value lives in the device payload and how to
build the complete feature value that has to be sent back to the cloud.
The cloud replaces a feature value as a whole, so writes always start from
the value the robot reported and change a single field.
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import dataclass
from typing import Any

from . import robot
from .helpers import feature

Write = tuple[str, str, Any]
"""``(domain, identifier, payload)`` for an iot-feature PUT."""

FAN_SPEEDS = ("quiet", "normal", "strong", "super")
WATER_LEVELS = ("low", "middle", "high")
ROOM_SETTING_MODES = ("universal", "custom")


def _strip(value: Any) -> Any:
    """Copy a reported value without the robot's ``ts`` timestamps."""
    if isinstance(value, Mapping):
        return {str(k): _strip(v) for k, v in value.items() if k != "ts"}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True)
class Setting:
    """Base class; subclasses implement ``read`` and ``write``."""

    def read(self, device: Any, task: Any = None) -> Any:
        raise NotImplementedError

    def write(self, device: Any, task: Any, value: Any) -> Write:
        raise NotImplementedError

    def available(self, device: Any, task: Any = None) -> bool:
        return self.read(device, task) is not None

    def action(self, device: Any, task: Any, value: Any) -> Write | None:
        """Return ``(domain, action, payload)`` when the robot needs an action.

        ``write`` still describes the new stored value, which is shown until
        the next refresh.
        """
        return None

    def fallback_action(self, device: Any, task: Any, value: Any) -> Write | None:
        """Return the action for models that do not have ``action``."""
        return None


@dataclass(frozen=True)
class ScalarSetting(Setting):
    """A feature whose value is a plain string, number or boolean."""

    domain: str
    identifier: str

    def read(self, device: Any, task: Any = None) -> Any:
        value = feature(device, self.domain, self.identifier)
        return None if isinstance(value, (Mapping, list)) else value

    def write(self, device: Any, task: Any, value: Any) -> Write:
        return self.domain, self.identifier, value


@dataclass(frozen=True)
class FieldSetting(Setting):
    """One field of an object feature, e.g. ``CarpetCleanCfg.detection``."""

    domain: str
    identifier: str
    field: str

    def read(self, device: Any, task: Any = None) -> Any:
        block = feature(device, self.domain, self.identifier)
        return block.get(self.field) if isinstance(block, Mapping) else None

    def write(self, device: Any, task: Any, value: Any) -> Write:
        block = feature(device, self.domain, self.identifier)
        payload = _strip(block) if isinstance(block, Mapping) else {}
        payload[self.field] = value
        return self.domain, self.identifier, payload


@dataclass(frozen=True)
class FlagFieldSetting(FieldSetting):
    """A field the robot reports as 0/1 but the cloud accepts only as true/false."""

    def read(self, device: Any, task: Any = None) -> Any:
        value = super().read(device, task)
        if value is None or isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        return None


@dataclass(frozen=True)
class FirstAvailableSetting(Setting):
    """One option that different models store in different features.

    Reads and writes use the first variant the robot reports.
    """

    options: tuple[Setting, ...]

    def _pick(self, device: Any, task: Any = None) -> Setting:
        for option in self.options:
            if option.available(device, task):
                return option
        return self.options[0]

    def read(self, device: Any, task: Any = None) -> Any:
        return self._pick(device, task).read(device, task)

    def available(self, device: Any, task: Any = None) -> bool:
        return any(option.available(device, task) for option in self.options)

    def write(self, device: Any, task: Any, value: Any) -> Write:
        return self._pick(device, task).write(device, task, value)

    def action(self, device: Any, task: Any, value: Any) -> Write | None:
        return self._pick(device, task).action(device, task, value)

    def fallback_action(self, device: Any, task: Any, value: Any) -> Write | None:
        return self._pick(device, task).fallback_action(device, task, value)


def _global_clean_cfg(device: Any, map_id: Any) -> Mapping[str, Any] | None:
    """Return the RE7 Edge's ``SweeperMapMgr/GlobalCleanCfg`` for a map."""
    value = feature(device, "SweeperMapMgr", "GlobalCleanCfg")
    if isinstance(value, Mapping):
        entries = value.get("cfg") if isinstance(value.get("cfg"), list) else [value]
    elif isinstance(value, list):
        entries = value
    else:
        return None
    for entry in entries:
        if isinstance(entry, Mapping) and entry.get("mapID") in (None, map_id):
            return entry
    return None


_STD_ACTIONS = {
    "fanMode": "SetFanModeOfStdClean",
    "waterQuantity": "SetWaterQuantityOfStdClean",
    "cleanTimes": "SetCleanTimesOfStdClean",
    "cleanConfigType": "SetCleanCfg",
}


@dataclass(frozen=True)
class MapCleanSetting(Setting):
    """A field of the active map's entry in ``SweeperMapMgr/StdCleanCfg``."""

    field: str

    def action(self, device: Any, task: Any, value: Any) -> Write | None:
        map_id = robot.active_map_id(device, task)
        if map_id is None:
            raise ValueError("The robot has not reported its map yet")
        return (
            "SweeperMapMgr",
            _STD_ACTIONS[self.field],
            {"mapID": map_id, self.field: value},
        )

    def _entries(self, device: Any) -> list[Any]:
        value = feature(device, "SweeperMapMgr", "StdCleanCfg")
        return value if isinstance(value, list) else []

    def read(self, device: Any, task: Any = None) -> Any:
        map_id = robot.active_map_id(device, task)
        for entry in self._entries(device):
            if isinstance(entry, Mapping) and entry.get("mapID") == map_id:
                return entry.get(self.field)
        global_cfg = _global_clean_cfg(device, map_id)
        return global_cfg.get(self.field) if global_cfg is not None else None

    def fallback_action(self, device: Any, task: Any, value: Any) -> Write | None:
        """RE7 Edge: suction and water go through ``SetGlobalCleanCfg``."""
        if self.field not in ("fanMode", "waterQuantity"):
            return None
        map_id = robot.active_map_id(device, task)
        if map_id is None:
            return None
        payload: dict[str, Any] = dict(_strip(_global_clean_cfg(device, map_id) or {}))
        payload.update(
            {
                "mapID": map_id,
                "cleanMode": robot.clean_mode(device) or "sweepThenMop",
                self.field: value,
                "dataSource": "global",
            }
        )
        return "SweeperMapMgr", "SetGlobalCleanCfg", payload

    def write(self, device: Any, task: Any, value: Any) -> Write:
        map_id = robot.active_map_id(device, task)
        entries = _strip(self._entries(device))
        for entry in entries:
            if isinstance(entry, dict) and entry.get("mapID") == map_id:
                entry[self.field] = value
                break
        else:
            entry = {
                "mapID": map_id,
                "cleanConfigType": "universal",
                "fanMode": "normal",
                "waterQuantity": "middle",
                "cleanTimes": 1,
            }
            entry[self.field] = value
            entries.append(entry)
        return "SweeperMapMgr", "StdCleanCfg", entries


@dataclass(frozen=True)
class RoomCleanSetting(Setting):
    """A field of one room in ``SweeperMapMgr/RoomCustomCleanCfg``."""

    room_id: int
    field: str

    def _entries(self, device: Any) -> list[Any]:
        value = feature(device, "SweeperMapMgr", "RoomCustomCleanCfg")
        return value if isinstance(value, list) else []

    def read(self, device: Any, task: Any = None) -> Any:
        map_id = robot.active_map_id(device, task)
        for room in robot.room_clean_configs(device, map_id):
            if room.get("roomID") == self.room_id:
                return room.get(self.field)
        return None

    def action(self, device: Any, task: Any, value: Any) -> Write | None:
        map_id = robot.active_map_id(device, task)
        for room in robot.room_clean_configs(device, map_id):
            if room.get("roomID") == self.room_id:
                payload = {
                    "mapID": map_id,
                    "roomID": self.room_id,
                    "fanMode": room.get("fanMode"),
                    "waterQuantity": room.get("waterQuantity"),
                    "cleanTimes": room.get("cleanTimes"),
                }
                payload[self.field] = value
                return "SweeperMapMgr", "SetRoomCustomCleanCfg", payload
        raise ValueError(f"Room {self.room_id} has no cleaning settings")

    def write(self, device: Any, task: Any, value: Any) -> Write:
        map_id = robot.active_map_id(device, task)
        entries = _strip(self._entries(device))
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("mapID") != map_id:
                continue
            for room in entry.get("room") or []:
                if isinstance(room, dict) and room.get("roomID") == self.room_id:
                    room[self.field] = value
                    return "SweeperMapMgr", "RoomCustomCleanCfg", entries
        raise ValueError(f"Room {self.room_id} has no cleaning settings")


@dataclass(frozen=True)
class RestPlanSetting(Setting):
    """A field of the do-not-disturb period (``SweeperMgr/RestPlan``)."""

    field: str

    def _plan(self, device: Any) -> list[Any]:
        block = feature(device, "SweeperMgr", "RestPlan")
        plan = block.get("plan") if isinstance(block, Mapping) else None
        return plan if isinstance(plan, list) else []

    def read(self, device: Any, task: Any = None) -> Any:
        plan = self._plan(device)
        if plan and isinstance(plan[0], Mapping):
            return plan[0].get(self.field)
        return None

    def available(self, device: Any, task: Any = None) -> bool:
        return isinstance(feature(device, "SweeperMgr", "RestPlan"), Mapping)

    def write(self, device: Any, task: Any, value: Any) -> Write:
        plan = _strip(self._plan(device))
        if not plan or not isinstance(plan[0], dict):
            plan = [
                {
                    "ID": 0,
                    "enabled": False,
                    "startTime": "22:00:00",
                    "endTime": "08:00:00",
                    "cleanContinue": False,
                }
            ]
        plan[0][self.field] = value
        return "SweeperMgr", "RestPlan", {"plan": plan}


@dataclass(frozen=True)
class CleanPlanSetting(Setting):
    """A field of one cleaning schedule (``SweeperCleanTask/CleanPlan``)."""

    plan_id: int
    field: str

    def _plans(self, device: Any) -> list[Any]:
        block = feature(device, "SweeperCleanTask", "CleanPlan")
        plans = block.get("Plan") if isinstance(block, Mapping) else None
        return plans if isinstance(plans, list) else []

    def read(self, device: Any, task: Any = None) -> Any:
        for plan in self._plans(device):
            if isinstance(plan, Mapping) and plan.get("planID") == self.plan_id:
                return plan.get(self.field)
        return None

    def write(self, device: Any, task: Any, value: Any) -> Write:
        plans = _strip(self._plans(device))
        for plan in plans:
            if isinstance(plan, dict) and plan.get("planID") == self.plan_id:
                plan[self.field] = value
                return "SweeperCleanTask", "CleanPlan", {"Plan": plans}
        raise ValueError(f"Schedule {self.plan_id} does not exist")


def clean_plans(device: Any) -> list[Mapping[str, Any]]:
    """Return the cleaning schedules configured in the app."""
    block = feature(device, "SweeperCleanTask", "CleanPlan")
    plans = block.get("Plan") if isinstance(block, Mapping) else None
    return [
        plan
        for plan in (plans if isinstance(plans, list) else [])
        if isinstance(plan, Mapping) and plan.get("planID") is not None
    ]


def apply_write(device: Mapping[str, Any], write: Write) -> dict[str, Any]:
    """Return a copy of ``device`` with a written value applied locally.

    Used to show a change immediately, before the next cloud refresh.
    """
    domain, identifier, payload = write
    result = copy.deepcopy(dict(device))
    tree = robot.robot_features(result)
    block = tree.get(domain) if isinstance(tree, dict) else None
    if isinstance(block, dict):
        previous = block.get(identifier)
        if isinstance(previous, Mapping) and isinstance(payload, Mapping):
            merged = dict(payload)
            if "ts" in previous:
                merged["ts"] = previous["ts"]
            block[identifier] = merged
        else:
            block[identifier] = copy.deepcopy(payload)
    return result
