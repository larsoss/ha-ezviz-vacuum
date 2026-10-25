"""Binary sensors for EZVIZ robot vacuums."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import robot
from .coordinator import EzvizVacuumCoordinator
from .entity import RobotEntity


@dataclass(frozen=True, kw_only=True)
class RobotBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a yes/no value of the live task."""

    value_fn: Callable[[Mapping[str, Any]], Any]


BINARY_SENSORS: Final[tuple[RobotBinarySensorDescription, ...]] = (
    RobotBinarySensorDescription(
        key="on_base_station",
        translation_key="on_base_station",
        icon="mdi:home-import-outline",
        value_fn=lambda data: robot.task_data(data.get("task")).get("isOnBasestation"),
    ),
    RobotBinarySensorDescription(
        key="do_not_disturb_active",
        translation_key="do_not_disturb_active",
        icon="mdi:sleep",
        value_fn=lambda data: robot.task_data(data.get("task")).get("inDNDMode"),
    ),
)


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry[EzvizVacuumCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the robot binary sensors."""
    async_add_entities(
        RobotBinarySensor(entry.runtime_data, description)
        for description in BINARY_SENSORS
    )


class RobotBinarySensor(RobotEntity, BinarySensorEntity):
    """A yes/no value reported by the robot."""

    entity_description: RobotBinarySensorDescription

    def __init__(
        self,
        coordinator: EzvizVacuumCoordinator,
        description: RobotBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the reported value."""
        value = self.entity_description.value_fn(self.coordinator.data)
        if isinstance(value, bool):
            return value
        # Some models report these flags as 0/1 integers rather than JSON
        # booleans (e.g. the RE4's isOnBasestation), so coerce numerics too.
        if isinstance(value, (int, float)):
            return bool(value)
        return None
