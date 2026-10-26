"""Time entities for EZVIZ robot settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any, Final

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EzvizVacuumCoordinator
from .entity import RobotSettingEntity, reported
from .settings import (
    CleanPlanSetting,
    FieldSetting,
    Setting,
    clean_plans,
    do_not_disturb,
)
from .switch import schedule_label


@dataclass(frozen=True, kw_only=True)
class RobotTimeDescription(TimeEntityDescription):
    """Describe a time-of-day robot setting (``HH:MM:SS``)."""

    setting: Setting
    entity_category: EntityCategory | None = EntityCategory.CONFIG


TIMES: Final[tuple[RobotTimeDescription, ...]] = (
    RobotTimeDescription(
        key="do_not_disturb_start",
        translation_key="do_not_disturb_start",
        icon="mdi:weather-night",
        setting=do_not_disturb("startTime"),
    ),
    RobotTimeDescription(
        key="do_not_disturb_end",
        translation_key="do_not_disturb_end",
        icon="mdi:weather-sunset-up",
        setting=do_not_disturb("endTime"),
    ),
    RobotTimeDescription(
        key="off_peak_charging_start",
        translation_key="off_peak_charging_start",
        icon="mdi:battery-clock-outline",
        setting=FieldSetting("SweeperMgr", "ValleyCharge", "startTime"),
    ),
    RobotTimeDescription(
        key="off_peak_charging_end",
        translation_key="off_peak_charging_end",
        icon="mdi:battery-clock",
        setting=FieldSetting("SweeperMgr", "ValleyCharge", "endTime"),
    ),
)


def parse_time(value: Any) -> time | None:
    """Parse the robot's ``HH:MM[:SS]`` text."""
    if not isinstance(value, str):
        return None
    try:
        parts = [int(part) for part in value.split(":")]
        return time(*parts[:3])
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry[EzvizVacuumCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the robot time settings."""
    coordinator = entry.runtime_data
    entities = [
        RobotSettingTime(coordinator, description.key, description)
        for description in TIMES
        if reported(coordinator, description.setting)
    ]
    for plan in clean_plans(coordinator.data.get("device")):
        plan_id = int(plan["planID"])
        description = RobotTimeDescription(
            key=f"schedule_{plan_id}_start",
            translation_key="schedule_start",
            icon="mdi:clock-start",
            setting=CleanPlanSetting(plan_id, "startTime"),
            entity_category=None,
        )
        entities.append(
            RobotSettingTime(
                coordinator,
                description.key,
                description,
                {"schedule": schedule_label(plan)},
            )
        )
    async_add_entities(entities)


class RobotSettingTime(RobotSettingEntity, TimeEntity):
    """A time-of-day robot setting."""

    entity_description: RobotTimeDescription

    def __init__(
        self,
        coordinator: EzvizVacuumCoordinator,
        key: str,
        description: RobotTimeDescription,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator, key, description.setting)
        self.entity_description = description
        if placeholders:
            self._attr_translation_placeholders = placeholders

    @property
    def native_value(self) -> time | None:
        """Return the reported time."""
        return parse_time(self.setting_value)

    async def async_set_value(self, value: time) -> None:
        """Send the new time to the robot."""
        await self.async_write_setting(value.strftime("%H:%M:00"))
