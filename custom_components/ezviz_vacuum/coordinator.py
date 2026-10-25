"""Coordinator for EZVIZ robot vacuums."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from functools import partial
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from . import robot
from .api import EzvizVacuumApi, EzvizVacuumApiError
from .cloud_camera import capture_cloud_snapshot, trace_cloud_stream
from .const import (
    ACTIVE_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SOURCE_ENTRY_ID,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_REFRESH_INTERVAL,
    DOMAIN,
)
from .mapdata import build_layers
from .maprender import render_svg
from .settings import Setting, apply_write


def find_api(runtime_data: Any) -> Any | None:
    """Find the pyezviz client without depending on HA's private data class."""
    candidates = (
        runtime_data,
        getattr(runtime_data, "coordinator", None),
        getattr(runtime_data, "data", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        for attribute in ("api", "client", "ezviz_client"):
            api = getattr(candidate, attribute, None)
            if api is not None and hasattr(api, "get_device_infos"):
                return api
        if hasattr(candidate, "get_device_infos"):
            return candidate
    return None


class EzvizVacuumCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch robot data through the already authenticated EZVIZ client."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source_entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.source_entry = source_entry
        self.serial: str = entry.data.get(CONF_SERIAL, "")
        self.robot_api: EzvizVacuumApi | None = None
        self._device: dict[str, Any] | None = None
        self._device_fetched: float = 0.0
        self._device_task: str | None = None
        self.map_image: bytes | None = None
        self.map_image_updated: datetime | None = None
        self.map_error: str | None = None
        self._map_cache: dict[str, tuple[int | None, dict[str, Any]]] = {}
        self._map_show_path: bool | None = None
        self._map_cache_id: int | None = None
        self.camera_snapshot: bytes | None = None
        self.camera_snapshot_updated: datetime | None = None

    def _api(self) -> Any:
        if self.source_entry.state is not ConfigEntryState.LOADED:
            raise ConfigEntryNotReady("Official EZVIZ integration is not loaded")
        api = find_api(getattr(self.source_entry, "runtime_data", None))
        if api is None:
            raise ConfigEntryNotReady("No active EZVIZ session found")
        return api

    def _device_is_stale(self, task_name: str | None) -> bool:
        """Return whether the full device report should be fetched again.

        The account-wide device list is large, so it is fetched every few
        minutes and whenever the robot starts a different task; the small
        live task is polled on every update.
        """
        if self._device is None:
            return True
        if task_name and self._device_task and task_name != self._device_task:
            return True
        return monotonic() - self._device_fetched >= DEVICE_REFRESH_INTERVAL

    async def _async_fetch_device(self, source_api: Any) -> tuple[str, dict[str, Any]]:
        try:
            raw = await self.hass.async_add_executor_job(source_api.get_device_infos)
        except Exception as err:
            raise UpdateFailed(f"EZVIZ read error: {err}") from err
        if not isinstance(raw, Mapping):
            raise UpdateFailed("EZVIZ returned an invalid device list")

        if self.serial:
            selected = raw.get(self.serial)
            if not isinstance(selected, Mapping):
                raise UpdateFailed(f"Device not found: {self.serial}")
            return self.serial, dict(selected)

        taken = {
            str(entry.unique_id).upper()
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != self.entry.entry_id and entry.unique_id
        }
        for serial, payload in raw.items():
            if (
                isinstance(payload, Mapping)
                and robot.is_robot(payload)
                and str(serial).upper() not in taken
            ):
                self.serial = str(serial)
                return self.serial, dict(payload)
        raise UpdateFailed("No EZVIZ robot vacuum found on the account")

    async def _async_update_data(self) -> dict[str, Any]:
        source_api = self._api()
        if self.serial == "" or self._device is None:
            # The serial is needed before the live task can be queried.
            self.serial, self._device = await self._async_fetch_device(source_api)
            self._device_fetched = monotonic()

        self.robot_api = EzvizVacuumApi(source_api)
        task: dict[str, Any] = {}
        task_error: str | None = None
        try:
            task = await self.hass.async_add_executor_job(
                self.robot_api.query_current_task,
                self.serial,
            )
        except Exception as err:
            task_error = str(err)

        task_name = robot.current_task(task) if task else None
        if self._device_is_stale(task_name):
            self.serial, self._device = await self._async_fetch_device(source_api)
            self._device_fetched = monotonic()
        if task_name is not None:
            self._device_task = task_name

        if task:
            await self._async_refresh_map(task)
            # Follow the robot closely while it moves; idle polling is enough
            # otherwise.
            moving = robot.activity(task, self._device) in (
                robot.ACTIVITY_CLEANING,
                robot.ACTIVITY_RETURNING,
            )
            self.update_interval = (
                ACTIVE_SCAN_INTERVAL if moving else DEFAULT_SCAN_INTERVAL
            )

        return {
            "serial": self.serial,
            "device": self._device,
            "task": task,
            "task_error": task_error,
        }

    async def _async_refresh_map(self, task: Mapping[str, Any]) -> None:
        """Fetch map layers whose version changed and redraw the map.

        Failures never fail the update; the last map stays visible.
        """
        from homeassistant.util import dt as dt_util

        map_id = robot.active_map_id(self._device, task)
        if map_id is None or self.robot_api is None:
            return
        if map_id != self._map_cache_id:
            self._map_cache = {}
            self._map_cache_id = map_id
        versions = robot.map_versions(task, map_id)
        changed = False
        try:
            for layer in ("map", "region", "path"):
                version = versions.get(layer)
                cached = self._map_cache.get(layer)
                if cached is not None and version is not None and cached[0] == version:
                    continue
                # Like the app, ask for the latest layer without a version;
                # with one, the path layer comes back empty while cleaning.
                value = await self.hass.async_add_executor_job(
                    partial(
                        self.robot_api.fetch_map_layer,
                        self.serial,
                        layer,
                        map_id=map_id,
                    )
                )
                if not value.get("mapId"):
                    # Empty answer: keep the last layer and retry next poll.
                    continue
                self._map_cache[layer] = (version, value)
                changed = True
        except Exception as err:  # noqa: BLE001 - the map is optional
            self.map_error = str(err)
            self.logger.debug("Could not read the robot map: %s", err)
        else:
            self.map_error = None
        # The path of a finished clean is hidden once the robot is docked.
        show_path = robot.activity(task, self._device) != robot.ACTIVITY_DOCKED
        if show_path != self._map_show_path:
            self._map_show_path = show_path
            changed = True
        if not changed and self.map_image is not None:
            return

        layers = build_layers(
            *(
                self._map_cache.get(layer, (None, None))[1]
                for layer in ("map", "region", "path")
            )
        )
        names = {
            int(room_id): name for room_id, name in robot.rooms(self._device, map_id)
        }
        image = await self.hass.async_add_executor_job(
            partial(render_svg, layers, names, show_path=show_path)
        )
        if image is not None and image != self.map_image:
            self.map_image = image
            self.map_image_updated = dt_util.utcnow()

    async def async_refresh_device(self) -> None:
        """Fetch the full device report on the next update."""
        self._device_fetched = 0.0
        await self.async_request_refresh()

    async def _async_call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking API call and turn failures into HA errors."""
        if self.robot_api is None:
            raise HomeAssistantError("The robot client is not ready yet")
        try:
            return await self.hass.async_add_executor_job(
                partial(func, *args, **kwargs)
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except EzvizVacuumApiError as err:
            raise HomeAssistantError(f"EZVIZ rejected the command: {err}") from err
        except Exception as err:
            raise HomeAssistantError(f"Could not reach the EZVIZ cloud: {err}") from err

    async def async_clean_control(self, command: str) -> None:
        """Send a documented robot control and refresh state."""
        await self._async_call(self.robot_api.clean_control, self.serial, command)
        await self.async_request_refresh()

    async def async_return_to_base(self) -> None:
        """Send the robot back to its base station."""
        await self._async_call(self.robot_api.recharge_control, self.serial, "start")
        await self.async_request_refresh()

    async def async_write_setting(self, setting: Setting, value: Any) -> None:
        """Change one robot setting and show the new value immediately."""
        if self.robot_api is None:
            raise HomeAssistantError("The robot client is not ready yet")
        device = self.data.get("device", {})
        try:
            write = setting.write(device, self.data.get("task"), value)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        try:
            action = setting.action(device, self.data.get("task"), value)
            fallback = setting.fallback_action(device, self.data.get("task"), value)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        if action is not None:
            domain, name, payload = action
            await self._async_call(
                self.robot_api.send_setting_action,
                self.serial,
                domain=domain,
                action=name,
                payload=payload,
                fallback=fallback,
            )
        else:
            domain, identifier, payload = write
            await self._async_call(
                self.robot_api.set_feature,
                self.serial,
                domain=domain,
                identifier=identifier,
                value=payload,
            )
        # The cloud accepted the full value; keep showing it until the next
        # full device report confirms it.
        self._device = apply_write(device, write)
        self.async_set_updated_data({**self.data, "device": self._device})

    async def async_clean_segments(self, segment_ids: list[str]) -> None:
        """Clean the selected rooms with the robot's own settings."""
        if self.robot_api is None:
            raise HomeAssistantError("The robot client is not ready yet")
        device = self.data.get("device", {})
        map_id = robot.active_map_id(device, self.data.get("task"))
        known = {room_id for room_id, _ in robot.rooms(device, map_id)}
        if map_id is None or not known:
            raise HomeAssistantError("The robot has not reported its rooms yet")
        requested = [str(item) for item in segment_ids]
        missing = sorted(set(requested) - known)
        if missing:
            raise ServiceValidationError(f"Unknown robot rooms: {', '.join(missing)}")
        await self._async_call(
            self.robot_api.start_region_clean,
            self.serial,
            map_id=map_id,
            room_ids=[int(item) for item in requested],
        )
        await self.async_request_refresh()

    async def async_camera_trace(self) -> dict[str, Any]:
        """Open a short, body-free camera transport diagnostic."""
        return await self.hass.async_add_executor_job(
            trace_cloud_stream,
            self._api(),
            self.serial,
        )

    async def async_refresh_camera_snapshot(self, ffmpeg_path: str) -> None:
        """Capture one image on demand and immediately close the video stream."""
        from homeassistant.util import dt as dt_util

        try:
            self.camera_snapshot = await self.hass.async_add_executor_job(
                partial(
                    capture_cloud_snapshot,
                    self._api(),
                    self.serial,
                    ffmpeg_path,
                )
            )
        except ConfigEntryNotReady as err:
            raise HomeAssistantError(str(err)) from err
        except Exception as err:
            raise HomeAssistantError(f"Could not capture a snapshot: {err}") from err
        self.camera_snapshot_updated = dt_util.utcnow()
        self.async_update_listeners()


def get_source_entry(hass: HomeAssistant, entry: ConfigEntry) -> ConfigEntry:
    """Resolve the official EZVIZ config entry."""
    source_id = entry.data[CONF_SOURCE_ENTRY_ID]
    source = hass.config_entries.async_get_entry(source_id)
    if source is None:
        raise ConfigEntryNotReady("Referenced EZVIZ integration not found")
    return source
