"""Numbers for EZVIZ robot settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import robot
from .coordinator import EzvizVacuumCoordinator
from .entity import RobotSettingEntity, reported
from .settings import (
    FieldSetting,
    MapCleanSetting,
    RoomCleanSetting,
    ScalarSetting,
    Setting,
)

MAX_PASSES = 3


@dataclass(frozen=True, kw_only=True)
class RobotNumberDescription(NumberEntityDescription):
    """Describe a numeric robot setting."""

    setting: Setting
    entity_category: EntityCategory | None = EntityCategory.CONFIG
    mode: NumberMode = NumberMode.BOX
    native_step: float | None = 1


NUMBERS: Final[tuple[RobotNumberDescription, ...]] = (
    RobotNumberDescription(
        key="cleaning_passes",
        translation_key="cleaning_passes",
        icon="mdi:repeat",
        native_min_value=1,
        native_max_value=MAX_PASSES,
        setting=MapCleanSetting("cleanTimes"),
    ),
    RobotNumberDescription(
        key="mop_wash_interval",
        translation_key="mop_wash_interval",
        icon="mdi:washing-machine",
        native_min_value=5,
        native_max_value=60,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        setting=FieldSetting("SweeperCleanTask", "WashMopCfg", "interval"),
    ),
    RobotNumberDescription(
        key="mop_drying_time",
        translation_key="mop_drying_time",
        icon="mdi:sun-thermometer-outline",
        native_min_value=30,
        native_max_value=720,
        native_step=30,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        setting=FieldSetting("SweeperCleanTask", "DryMopDuration", "duration"),
    ),
    RobotNumberDescription(
        key="dust_collection_frequency",
        translation_key="dust_collection_frequency",
        icon="mdi:delete-clock-outline",
        native_min_value=1,
        native_max_value=10,
        setting=FieldSetting(
            "SweeperCleanTask", "DustCollectionCfg", "frequencyAfterClean"
        ),
    ),
    RobotNumberDescription(
        key="voice_volume",
        translation_key="voice_volume",
        icon="mdi:volume-high",
        native_min_value=0,
        native_max_value=100,
        native_step=10,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        setting=ScalarSetting("SoundSetting", "PromptToneVolume"),
    ),
)


def room_numbers(
    device: Any, task: Any, language: str | None = "en"
) -> list[tuple[str, RobotNumberDescription, str]]:
    """Return ``(key, description, room name)`` for per-room passes."""
    map_id = robot.active_map_id(device, task)
    configured = {
        str(room.get("roomID")) for room in robot.room_clean_configs(device, map_id)
    }
    return [
        (
            f"room_{room_id}_cleaning_passes",
            RobotNumberDescription(
                key=f"room_{room_id}_cleaning_passes",
                translation_key="room_cleaning_passes",
                icon="mdi:repeat",
                native_min_value=1,
                native_max_value=MAX_PASSES,
                setting=RoomCleanSetting(int(room_id), "cleanTimes"),
            ),
            name,
        )
        for room_id, name in robot.rooms(device, map_id, language)
        if room_id in configured
    ]


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry[EzvizVacuumCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the robot setting numbers."""
    coordinator = entry.runtime_data
    entities = [
        RobotSettingNumber(coordinator, description.key, description)
        for description in NUMBERS
        if reported(coordinator, description.setting)
    ]
    entities.extend(
        RobotSettingNumber(coordinator, key, description, {"room": name})
        for key, description, name in room_numbers(
            coordinator.data.get("device"),
            coordinator.data.get("task"),
            hass.config.language,
        )
    )
    async_add_entities(entities)


class RobotSettingNumber(RobotSettingEntity, NumberEntity):
    """A numeric robot setting."""

    entity_description: RobotNumberDescription

    def __init__(
        self,
        coordinator: EzvizVacuumCoordinator,
        key: str,
        description: RobotNumberDescription,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator, key, description.setting)
        self.entity_description = description
        if placeholders:
            self._attr_translation_placeholders = placeholders

    @property
    def native_value(self) -> float | None:
        """Return the reported value."""
        value = self.setting_value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value

    async def async_set_native_value(self, value: float) -> None:
        """Send a new whole-number value to the robot."""
        await self.async_write_setting(int(value))
