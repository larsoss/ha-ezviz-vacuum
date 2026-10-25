"""Vacuum platform for EZVIZ robot vacuums."""

from __future__ import annotations

from typing import Any

from homeassistant.components.vacuum import (
    Segment,
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import robot
from .coordinator import EzvizVacuumCoordinator
from .entity import RobotEntity
from .settings import MapCleanSetting

# Suction levels of the active map (SweeperMapMgr/StdCleanCfg.fanMode).
FAN_SPEEDS = {"quiet": "Quiet", "normal": "Normal", "strong": "Strong", "super": "Max"}
_FAN_SETTING = MapCleanSetting("fanMode")

_ACTIVITIES = {
    robot.ACTIVITY_CLEANING: VacuumActivity.CLEANING,
    robot.ACTIVITY_PAUSED: VacuumActivity.PAUSED,
    robot.ACTIVITY_RETURNING: VacuumActivity.RETURNING,
    robot.ACTIVITY_DOCKED: VacuumActivity.DOCKED,
    robot.ACTIVITY_IDLE: VacuumActivity.IDLE,
    robot.ACTIVITY_ERROR: VacuumActivity.ERROR,
}


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry[EzvizVacuumCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the robot vacuum entity."""
    async_add_entities([EzvizVacuumVacuum(entry.runtime_data)])


class EzvizVacuumVacuum(RobotEntity, StateVacuumEntity):
    """EZVIZ robot vacuum entity."""

    _attr_name = None
    _attr_supported_features = (
        VacuumEntityFeature.STATE
        | VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.CLEAN_AREA
        | VacuumEntityFeature.FAN_SPEED
    )
    _attr_fan_speed_list = list(FAN_SPEEDS.values())

    def __init__(self, coordinator: EzvizVacuumCoordinator) -> None:
        super().__init__(coordinator, "vacuum")

    @property
    def activity(self) -> VacuumActivity:
        """Return the activity derived from the live task."""
        return _ACTIVITIES[
            robot.activity(
                self.coordinator.data.get("task"),
                self.coordinator.data.get("device"),
            )
        ]

    @property
    def fan_speed(self) -> str | None:
        """Return the suction level used for the active map."""
        value = _FAN_SETTING.read(
            self.coordinator.data.get("device"), self.coordinator.data.get("task")
        )
        return FAN_SPEEDS.get(value) if isinstance(value, str) else None

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set the suction level for whole-home cleaning of the active map."""
        wanted = fan_speed.casefold()
        for value, label in FAN_SPEEDS.items():
            if wanted in (value, label.casefold()):
                await self.coordinator.async_write_setting(_FAN_SETTING, value)
                return
        raise ServiceValidationError(f"Unknown fan speed: {fan_speed}")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose useful task and maintenance details."""
        device = self.coordinator.data["device"]
        task = self.coordinator.data.get("task")
        error = robot.task_exception(task)
        description = robot.task_data(task).get("exceptionDesc")
        return {
            "cleaning_mode": robot.clean_mode(device),
            "error": error,
            "error_description": robot.error_description(error, description)
            if error
            else None,
            "current_task": robot.current_task(self.coordinator.data.get("task"))
            or None,
            "query_error": self.coordinator.data.get("task_error"),
        }

    async def async_start(self) -> None:
        """Start cleaning, or resume a paused clean."""
        paused = self.activity == VacuumActivity.PAUSED
        await self.coordinator.async_clean_control("resume" if paused else "start")

    async def async_pause(self) -> None:
        """Pause cleaning."""
        await self.coordinator.async_clean_control("pause")

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop cleaning."""
        await self.coordinator.async_clean_control("stop")

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return the robot to its base."""
        await self.coordinator.async_return_to_base()

    async def async_get_segments(self) -> list[Segment]:
        """Return the rooms available on the active robot map."""
        await self.coordinator.async_refresh_device()
        device = self.coordinator.data.get("device", {})
        map_id = robot.active_map_id(device, self.coordinator.data.get("task"))
        group = robot.map_name(device, map_id)
        names = self.coordinator.room_names
        return [
            Segment(id=room_id, name=names.get(int(room_id), name), group=group)
            for room_id, name in robot.rooms(device, map_id)
        ]

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        """Clean rooms selected through Home Assistant area mapping."""
        await self.coordinator.async_clean_segments(segment_ids)
