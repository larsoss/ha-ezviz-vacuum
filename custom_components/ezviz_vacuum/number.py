"""Numbers for EZVIZ robot settings."""

from __future__ import annotations

from collections.abc import Mapping
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
from .entity import RobotSettingEntity, remove_stale_room_entities, reported
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
    device: Any,
    task: Any,
    language: str | None = "en",
    names: Mapping[int, str] | None = None,
    generic: frozenset[int] = frozenset(),
) -> list[tuple[str, RobotNumberDescription, str]]:
    """Return ``(key, description, room name)`` for per-room passes."""
    map_id = robot.active_map_id(device, task)
    configured = {
        str(room.get("roomID")) for room in robot.room_clean_configs(device, map_id)
    }
    on_map = robot.setting_rooms(device, map_id, language, names)
    room_ids = tuple(int(room_id) for room_id, _ in on_map if room_id in configured)
    return [
        (
            f"room_{room_id}_cleaning_passes",
            RobotNumberDescription(
                key=f"room_{room_id}_cleaning_passes",
                translation_key="room_cleaning_passes",
                icon="mdi:repeat",
                native_min_value=1,
                native_max_value=MAX_PASSES,
                setting=RoomCleanSetting(int(room_id), "cleanTimes", room_ids),
                # Rooms the app named "Room N" itself are often not real rooms.
                entity_registry_enabled_default=int(room_id) not in generic,
            ),
            name,
        )
        for room_id, name in on_map
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
    device = coordinator.data.get("device")
    task = coordinator.data.get("task")
    rooms = room_numbers(
        device,
        task,
        hass.config.language,
        coordinator.room_names,
        coordinator.room_generic,
    )
    entities.extend(
        RobotSettingNumber(coordinator, key, description, {"room": name})
        for key, description, name in rooms
    )
    async_add_entities(entities)
    if robot.rooms_follow_map(
        robot.setting_rooms(
            device,
            robot.active_map_id(device, task),
            hass.config.language,
            coordinator.room_names,
        ),
        coordinator.room_names,
    ):
        serial = coordinator.data["serial"]
        remove_stale_room_entities(
            hass, entry, "number", {f"{serial}_{key}" for key, _, _ in rooms}
        )


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
