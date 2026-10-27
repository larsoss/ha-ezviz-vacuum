"""Base entity shared by all robot platforms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import robot
from .const import CONF_ROOM_DEVICES, DOMAIN
from .coordinator import EzvizVacuumCoordinator
from .settings import Setting


class RobotEntity(CoordinatorEntity[EzvizVacuumCoordinator]):
    """Entity attached to one robot device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EzvizVacuumCoordinator, key: str) -> None:
        super().__init__(coordinator)
        serial = coordinator.data["serial"]
        self._attr_unique_id = f"{serial}_{key}"
        details = robot.device_details(coordinator.data.get("device"))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer="EZVIZ",
            model=details["model"],
            model_id=details["model_id"],
            name=details["name"],
            sw_version=details["sw_version"],
            serial_number=serial,
        )


class RobotSettingEntity(RobotEntity):
    """Entity that shows and changes one robot setting."""

    def __init__(
        self, coordinator: EzvizVacuumCoordinator, key: str, setting: Setting
    ) -> None:
        super().__init__(coordinator, key)
        self.setting = setting

    @property
    def setting_value(self) -> Any:
        """Return the value the robot reported for this setting."""
        data = self.coordinator.data
        return self.setting.read(data.get("device"), data.get("task"))

    @property
    def available(self) -> bool:
        """Hide settings the robot does not report."""
        data = self.coordinator.data
        return super().available and self.setting.available(
            data.get("device"), data.get("task")
        )

    async def async_write_setting(self, value: Any) -> None:
        """Send a new value to the robot."""
        await self.coordinator.async_write_setting(self.setting, value)


def reported(coordinator: EzvizVacuumCoordinator, setting: Setting) -> bool:
    """Return whether the robot reports a setting, so its entity is created.

    Settings a model does not have (no carpet options, no cleaning mode on
    the RE4) get no entity instead of one that is always unavailable.
    """
    data = coordinator.data or {}
    return setting.available(data.get("device"), data.get("task"))


def sync_room_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    domain: str,
    *,
    enable: set[str],
) -> None:
    """Enable per-room entities whose room got a real name in the app.

    Call this before the platform adds its entities. Entities that were
    disabled by the integration because the room still had the app's default
    name are enabled once the room has a real name; entities the user disabled
    stay disabled.

    Entities of rooms that are no longer on the map are not deleted: on a robot
    with several maps they belong to the other map, and deleting an entity
    loses what the user set on it. Home Assistant shows them as no longer
    provided, and the user can delete them.
    """
    registry = er.async_get(hass)
    registered = {
        item.unique_id: item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == domain and item.unique_id
    }
    for unique_id in enable:
        item = registered.get(unique_id)
        if (
            item is not None
            and item.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        ):
            registry.async_update_entity(item.entity_id, disabled_by=None)


def room_devices(entry: ConfigEntry) -> bool:
    """Whether each room's settings are shown as a device of its own."""
    return bool(entry.options.get(CONF_ROOM_DEVICES, False))


def room_device_info(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: EzvizVacuumCoordinator,
    room_id: int,
    room_name: str,
) -> DeviceInfo:
    """Return the device of one room, linked to the robot's device."""
    serial = coordinator.data["serial"]
    details = robot.device_details(coordinator.data.get("device"))
    # The robot's device may not exist yet when this platform loads first.
    robot_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, serial)},
        manufacturer="EZVIZ",
        model=details["model"],
        name=details["name"],
    )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{serial}_room_{room_id}")},
        manufacturer="EZVIZ",
        model="Room",
        name=f"{details['name']} {room_name}",
        via_device_id=robot_device.id,
    )


def room_id_of(key: str) -> int:
    """Return the room id of a per-room key such as ``room_8_suction``."""
    return int(key.split("_")[1])
