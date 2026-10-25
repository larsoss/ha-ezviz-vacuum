"""Switches for EZVIZ robot settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EzvizVacuumCoordinator
from .entity import RobotSettingEntity
from .settings import (
    CleanPlanSetting,
    FieldSetting,
    FirstAvailableSetting,
    FlagFieldSetting,
    RestPlanSetting,
    Setting,
    clean_plans,
)


@dataclass(frozen=True, kw_only=True)
class RobotSwitchDescription(SwitchEntityDescription):
    """Describe a boolean robot setting."""

    setting: Setting
    entity_category: EntityCategory | None = EntityCategory.CONFIG


def _enabled(domain: str, identifier: str) -> FieldSetting:
    return FieldSetting(domain, identifier, "enabled")


SWITCHES: Final[tuple[RobotSwitchDescription, ...]] = (
    RobotSwitchDescription(
        key="station_child_lock",
        translation_key="station_child_lock",
        icon="mdi:lock-outline",
        setting=_enabled("SweeperBaseStationMgr", "ChildLockSwitch"),
    ),
    RobotSwitchDescription(
        key="station_automatic_dust_collection",
        translation_key="station_automatic_dust_collection",
        icon="mdi:delete-sweep-outline",
        setting=_enabled("SweeperCleanTask", "DustCollectionCfg"),
    ),
    RobotSwitchDescription(
        key="station_automatic_cleaning_solution",
        translation_key="station_automatic_cleaning_solution",
        icon="mdi:bottle-tonic-outline",
        setting=_enabled("SweeperCleanTask", "CleaningSolutionCfg"),
    ),
    RobotSwitchDescription(
        key="station_rotating_brush_self_clean",
        translation_key="station_rotating_brush_self_clean",
        icon="mdi:brush-outline",
        setting=_enabled("SweeperCleanTask", "RotatingBrushSelfCleanSwitch"),
    ),
    RobotSwitchDescription(
        key="do_not_disturb",
        translation_key="do_not_disturb",
        icon="mdi:sleep",
        setting=RestPlanSetting("enabled"),
    ),
    RobotSwitchDescription(
        key="do_not_disturb_resume",
        translation_key="do_not_disturb_resume",
        icon="mdi:play-pause",
        setting=RestPlanSetting("cleanContinue"),
    ),
    RobotSwitchDescription(
        key="carpet_detection",
        translation_key="carpet_detection",
        icon="mdi:rug",
        setting=FieldSetting("SweeperCleanTask", "CarpetCleanCfg", "detection"),
    ),
    RobotSwitchDescription(
        key="carpet_boost",
        translation_key="carpet_boost",
        icon="mdi:fan-plus",
        setting=FirstAvailableSetting(
            (
                FieldSetting("SweeperCleanTask", "CarpetCleanCfg", "turboClean"),
                # RE4: the same option, stored as a 0/1 flag.
                FlagFieldSetting(
                    "SweeperCleanTask", "CarpetTurboCleanSwitch", "enabled"
                ),
            )
        ),
    ),
    RobotSwitchDescription(
        key="carpet_extra_clean",
        translation_key="carpet_extra_clean",
        icon="mdi:repeat-once",
        setting=FieldSetting("SweeperCleanTask", "CarpetCleanCfg", "additionalClean"),
    ),
    RobotSwitchDescription(
        key="carpet_cross_when_blocked",
        translation_key="carpet_cross_when_blocked",
        icon="mdi:debug-step-over",
        setting=FieldSetting(
            "SweeperCleanTask", "CarpetCleanCfg", "allowPassageWhenObstructed"
        ),
    ),
    RobotSwitchDescription(
        key="pet_mode",
        translation_key="pet_mode",
        icon="mdi:paw",
        setting=_enabled("SweeperMgr", "PetModeSwitch"),
    ),
    RobotSwitchDescription(
        key="smart_dirt_detection",
        translation_key="smart_dirt_detection",
        icon="mdi:magnify-scan",
        setting=_enabled("SweeperMgr", "SmartDirtDetectionCfg"),
    ),
    RobotSwitchDescription(
        key="debris_boost",
        translation_key="debris_boost",
        icon="mdi:grain",
        setting=_enabled("SweeperCleanTask", "ParticulateCleanEnhanceCfg"),
    ),
    RobotSwitchDescription(
        key="deep_edge_cleaning",
        translation_key="deep_edge_cleaning",
        icon="mdi:border-outside",
        setting=_enabled("SweeperCleanTask", "EdgeDeepCleanCfg"),
    ),
    RobotSwitchDescription(
        key="off_peak_charging",
        translation_key="off_peak_charging",
        icon="mdi:battery-clock-outline",
        setting=_enabled("SweeperMgr", "ValleyCharge"),
    ),
)


_WEEKDAYS = {
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
    7: "sunday",
}


def schedule_label(plan: Any) -> str:
    """Return the schedule name from the app, or its number."""
    name = str(plan.get("name") or "").strip()
    return name or str(int(plan["planID"]) + 1)


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry[EzvizVacuumCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the robot setting switches."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        RobotSettingSwitch(coordinator, description) for description in SWITCHES
    ]
    # Schedules are read once; reload the integration after adding one.
    for plan in clean_plans(coordinator.data.get("device")):
        plan_id = int(plan["planID"])
        entities.append(
            RobotScheduleSwitch(
                coordinator,
                RobotSwitchDescription(
                    key=f"schedule_{plan_id}",
                    translation_key="schedule",
                    icon="mdi:calendar-clock",
                    setting=CleanPlanSetting(plan_id, "enabled"),
                    entity_category=None,
                ),
                plan_id,
                schedule_label(plan),
            )
        )
    async_add_entities(entities)


class RobotSettingSwitch(RobotSettingEntity, SwitchEntity):
    """A boolean robot setting."""

    entity_description: RobotSwitchDescription

    def __init__(
        self,
        coordinator: EzvizVacuumCoordinator,
        description: RobotSwitchDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.setting)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the reported setting."""
        value = self.setting_value
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self.async_write_setting(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self.async_write_setting(False)


class RobotScheduleSwitch(RobotSettingSwitch):
    """Turns a cleaning schedule from the app on or off."""

    def __init__(
        self,
        coordinator: EzvizVacuumCoordinator,
        description: RobotSwitchDescription,
        plan_id: int,
        label: str,
    ) -> None:
        super().__init__(coordinator, description)
        self._plan_id = plan_id
        self._attr_translation_placeholders = {"schedule": label}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Describe when and how the schedule cleans."""
        for plan in clean_plans(self.coordinator.data.get("device")):
            if plan.get("planID") != self._plan_id:
                continue
            action = plan.get("Action") if isinstance(plan.get("Action"), dict) else {}
            return {
                "start_time": plan.get("startTime"),
                "days": [
                    _WEEKDAYS[day]
                    for day in plan.get("RepeatPeriod") or []
                    if day in _WEEKDAYS
                ],
                "cleaning_mode": action.get("cleanMode"),
                "cleaning_range": action.get("cleanRange"),
                "rooms": [
                    region.get("roomID", region.get("ID"))
                    for region in action.get("region") or []
                    if isinstance(region, dict)
                ],
            }
        return {}
