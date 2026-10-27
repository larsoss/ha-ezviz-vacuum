"""Selects for EZVIZ robot cleaning settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import robot
from .const import CLEAN_MODES
from .coordinator import EzvizVacuumCoordinator
from .entity import RobotSettingEntity, reported, sync_room_entities
from .settings import (
    FAN_SPEEDS,
    ROOM_SETTING_MODES,
    WATER_LEVELS,
    FieldSetting,
    MapCleanSetting,
    RoomCleanSetting,
    ScalarSetting,
    Setting,
)


@dataclass(frozen=True, kw_only=True)
class RobotSelectDescription(SelectEntityDescription):
    """Describe a robot setting with a fixed set of values."""

    setting: Setting
    entity_category: EntityCategory | None = EntityCategory.CONFIG
    values: dict[str, str] | None = None
    """Option -> robot value, when the robot's values are not valid option keys."""


# Home Assistant option keys must be snake_case; the robot uses camelCase.
CLEAN_MODE_OPTIONS: Final = {
    "sweep": "sweep",
    "mop": "mop",
    "sweepAndMop": "sweep_and_mop",
    "sweepThenMop": "sweep_then_mop",
}


SELECTS: Final[tuple[RobotSelectDescription, ...]] = (
    RobotSelectDescription(
        key="water_level",
        translation_key="water_level",
        icon="mdi:water-outline",
        options=list(WATER_LEVELS),
        setting=MapCleanSetting("waterQuantity"),
    ),
    RobotSelectDescription(
        key="cleaning_mode",
        translation_key="cleaning_mode",
        icon="mdi:broom",
        options=[CLEAN_MODE_OPTIONS[mode] for mode in CLEAN_MODES],
        values={option: mode for mode, option in CLEAN_MODE_OPTIONS.items()},
        setting=ScalarSetting("SweeperCleanTask", "SweepMopMode"),
        entity_category=None,
    ),
    RobotSelectDescription(
        key="room_settings",
        translation_key="room_settings",
        icon="mdi:floor-plan",
        options=list(ROOM_SETTING_MODES),
        setting=MapCleanSetting("cleanConfigType"),
    ),
    RobotSelectDescription(
        key="mop_wash_trigger",
        translation_key="mop_wash_trigger",
        icon="mdi:washing-machine",
        options=["time", "region"],
        setting=FieldSetting("SweeperCleanTask", "WashMopCfg", "type"),
    ),
)


def room_selects(
    device: Any,
    task: Any,
    language: str | None = "en",
    names: Mapping[int, str] | None = None,
    generic: frozenset[int] = frozenset(),
) -> list[tuple[str, RobotSelectDescription, str]]:
    """Return ``(key, description, room name)`` for every room of the active map."""
    map_id = robot.active_map_id(device, task)
    configured = {
        str(room.get("roomID")) for room in robot.room_clean_configs(device, map_id)
    }
    result = []
    on_map = robot.setting_rooms(device, map_id, language, names)
    room_ids = tuple(int(room_id) for room_id, _ in on_map if room_id in configured)
    for room_id, name in on_map:
        if room_id not in configured:
            continue
        for field, suffix, options, icon in (
            ("fanMode", "suction", FAN_SPEEDS, "mdi:fan"),
            ("waterQuantity", "water_level", WATER_LEVELS, "mdi:water-outline"),
        ):
            description = RobotSelectDescription(
                key=f"room_{room_id}_{suffix}",
                translation_key=f"room_{suffix}",
                icon=icon,
                options=list(options),
                setting=RoomCleanSetting(int(room_id), field, room_ids),
                # Rooms the app named "Room N" itself are often not real rooms.
                entity_registry_enabled_default=int(room_id) not in generic,
            )
            result.append((description.key, description, name))
    return result


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry[EzvizVacuumCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the robot setting selects."""
    coordinator = entry.runtime_data
    entities = [
        RobotSettingSelect(coordinator, description.key, description)
        for description in SELECTS
        if reported(coordinator, description.setting)
    ]
    # Rooms are read once; reload the integration after editing the map.
    device = coordinator.data.get("device")
    task = coordinator.data.get("task")
    rooms = room_selects(
        device,
        task,
        hass.config.language,
        coordinator.room_names,
        coordinator.room_generic,
    )
    serial = coordinator.data["serial"]
    sync_room_entities(
        hass,
        entry,
        "select",
        enable={
            f"{serial}_{key}"
            for key, description, _ in rooms
            if description.entity_registry_enabled_default
        },
    )
    entities.extend(
        RobotSettingSelect(coordinator, key, description, {"room": name})
        for key, description, name in rooms
    )
    async_add_entities(entities)


class RobotSettingSelect(RobotSettingEntity, SelectEntity):
    """A robot setting with a fixed set of values."""

    entity_description: RobotSelectDescription

    def __init__(
        self,
        coordinator: EzvizVacuumCoordinator,
        key: str,
        description: RobotSelectDescription,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator, key, description.setting)
        self.entity_description = description
        if placeholders:
            self._attr_translation_placeholders = placeholders

    @property
    def current_option(self) -> str | None:
        """Return the reported value when it is a known option."""
        value = self.setting_value
        values = self.entity_description.values
        if values:
            value = next((key for key, item in values.items() if item == value), None)
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Send the chosen value to the robot."""
        values = self.entity_description.values
        await self.async_write_setting(values.get(option, option) if values else option)
