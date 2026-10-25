"""EZVIZ robot vacuum integration."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from pyezvizapi.exceptions import EzvizAuthTokenExpired, PyEzvizError
import voluptuous as vol

from . import robot
from .cloud import EzvizCloud
from .const import (
    CONF_LEGACY_SOURCE_ENTRY_ID,
    CONF_SERIAL,
    CONF_TOKEN,
    DOMAIN,
    SERVICE_API_REQUEST,
    SERVICE_CAMERA_DIAGNOSTICS,
    SERVICE_FEATURE_REQUEST,
    SERVICE_INSPECT,
    SERVICE_MAP_DIAGNOSTICS,
    SERVICE_REFRESH_CAMERA,
)
from .coordinator import EzvizVacuumCoordinator
from .helpers import feature
from .mapdata import decode_path

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
    Platform.VACUUM,
]

type EzvizVacuumConfigEntry = ConfigEntry[EzvizVacuumCoordinator]

ATTR_SERIAL = "serial"
_SERIAL_SCHEMA = {vol.Optional(ATTR_SERIAL): cv.string}

_SENSITIVE_PARTS = (
    "accesscode",
    "authcode",
    "content",
    "encryptpwd",
    "key",
    "password",
    "pwd",
    "secret",
    "session",
    "token",
    "verificationcode",
)


def _sanitize(value: Any) -> Any:
    """Remove authentication material while preserving protocol metadata."""
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]"
            if any(part in str(key).casefold() for part in _SENSITIVE_PARTS)
            else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Move entries off the official EZVIZ integration's session.

    Version 1 entries have no login of their own; setup then asks the user to
    sign in once (re-authentication) and keeps every entity.
    """
    if entry.version > 2:
        return False
    if entry.version == 1:
        data = {
            key: value
            for key, value in entry.data.items()
            if key != CONF_LEGACY_SOURCE_ENTRY_ID
        }
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EzvizVacuumConfigEntry) -> bool:
    """Set up one robot from a config entry."""
    token = entry.data.get(CONF_TOKEN)
    if not isinstance(token, Mapping) or not token.get("session_id"):
        raise ConfigEntryAuthFailed("Sign in to your EZVIZ account")

    def save_token(new_token: dict[str, Any]) -> None:
        """Store a renewed session; called from the client's worker thread."""
        hass.loop.call_soon_threadsafe(_store_token, hass, entry, new_token)

    cloud = await hass.async_add_executor_job(
        partial(EzvizCloud.from_token, dict(token), on_token_updated=save_token)
    )
    try:
        await hass.async_add_executor_job(cloud.refresh)
    except EzvizAuthTokenExpired as err:
        raise ConfigEntryAuthFailed(
            "The EZVIZ login has expired; please sign in again"
        ) from err
    except PyEzvizError as err:
        raise ConfigEntryNotReady(f"Could not reach the EZVIZ cloud: {err}") from err
    except Exception as err:
        raise ConfigEntryNotReady(f"Could not reach the EZVIZ cloud: {err}") from err

    coordinator = EzvizVacuumCoordinator(hass, entry, cloud)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _migrate_to_serial(hass, entry, coordinator.serial)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


def _store_token(
    hass: HomeAssistant, entry: ConfigEntry, token: dict[str, Any]
) -> None:
    if entry.data.get(CONF_TOKEN) != token:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: token}
        )


def _migrate_to_serial(hass: HomeAssistant, entry: ConfigEntry, serial: str) -> None:
    """Pin entries created before multi-robot support to their robot.

    Older versions used the integration domain as unique ID and stored an
    empty serial, which only allowed one robot.
    """
    if not serial:
        return
    if entry.unique_id == serial and entry.data.get(CONF_SERIAL) == serial:
        return
    hass.config_entries.async_update_entry(
        entry,
        unique_id=serial,
        data={**entry.data, CONF_SERIAL: serial},
    )


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> EzvizVacuumCoordinator:
    """Return the robot addressed by a service call (default: the first)."""
    wanted = str(call.data.get(ATTR_SERIAL) or "").strip().upper()
    loaded = [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(getattr(entry, "runtime_data", None), EzvizVacuumCoordinator)
    ]
    if not loaded:
        raise HomeAssistantError("No EZVIZ robot is loaded")
    if not wanted:
        return loaded[0]
    for coordinator in loaded:
        if coordinator.serial.upper() == wanted:
            return coordinator
    raise ServiceValidationError(f"No EZVIZ robot with serial {wanted} is loaded")


async def _ready(coordinator: EzvizVacuumCoordinator) -> EzvizVacuumCoordinator:
    if coordinator.robot_api is None:
        await coordinator.async_request_refresh()
    if coordinator.robot_api is None:
        raise HomeAssistantError("The robot client is not ready yet")
    return coordinator


def _register_services(hass: HomeAssistant) -> None:  # noqa: C901
    """Register the integration services once."""
    if hass.services.has_service(DOMAIN, SERVICE_INSPECT):
        return

    async def async_inspect(call: ServiceCall) -> dict[str, Any]:
        """Return sanitized raw device data for protocol discovery."""
        coordinator = _coordinator(hass, call)
        await coordinator.async_refresh_device()
        return _sanitize(coordinator.data)

    async def async_map_diagnostics(call: ServiceCall) -> dict[str, Any]:
        """Read the map layers and summarise them (no raw map data)."""
        coordinator = await _ready(_coordinator(hass, call))
        device = coordinator.data.get("device", {})
        task = coordinator.data.get("task")
        map_id = robot.active_map_id(device, task) or 0
        versions = robot.map_versions(task, map_id)
        layers: dict[str, Any] = {}
        for layer in ("map", "region", "path"):
            try:
                value = await hass.async_add_executor_job(
                    partial(
                        coordinator.robot_api.fetch_map_layer,
                        coordinator.serial,
                        layer,
                        map_id=map_id,
                    )
                )
            except Exception as err:  # noqa: BLE001 - diagnostics report it
                layers[layer] = {"error": str(err)}
                continue
            layers[layer] = {
                key: item
                for key, item in value.items()
                if key not in ("mapData", "coordinate", "pathdata", "room")
            }
            if layer == "path":
                segments = decode_path(value)
                layers[layer]["pathdata_length"] = len(value.get("pathdata") or "")
                layers[layer]["segments"] = len(segments)
                layers[layer]["points"] = sum(len(seg) for seg in segments)
            if layer == "region":
                layers[layer]["rooms"] = [
                    room.get("roomID") for room in value.get("room") or []
                ]
        client = await hass.async_add_executor_job(
            coordinator.robot_api.client_diagnostics
        )
        operation = feature(device, "OperationDiagnosis", "DeviceOperationParams")
        operation = operation if isinstance(operation, Mapping) else {}
        return _sanitize(
            {
                "map_id": map_id,
                "versions": versions,
                "layers": layers,
                "client": client,
                "clean_history": coordinator.robot_api.decode_diagnostic_blob(
                    operation.get("cleanHistory")
                ),
                "abnormal_history": coordinator.robot_api.decode_diagnostic_blob(
                    operation.get("abnormalHistory")
                ),
            }
        )

    async def async_camera_diagnostics(call: ServiceCall) -> dict[str, Any]:
        """Verify encrypted cloud transport without returning media bytes."""
        coordinator = _coordinator(hass, call)
        try:
            return _sanitize(await coordinator.async_camera_trace())
        except Exception as err:  # noqa: BLE001 - diagnostics report the failure
            return {"error": str(err)}

    async def async_refresh_camera(call: ServiceCall) -> None:
        """Capture a single robot-camera frame only when explicitly called."""
        coordinator = _coordinator(hass, call)
        ffmpeg = hass.data.get("ffmpeg")
        ffmpeg_path = str(getattr(ffmpeg, "binary", "ffmpeg"))
        await coordinator.async_refresh_camera_snapshot(ffmpeg_path)

    async def async_feature_request(call: ServiceCall) -> dict[str, Any]:
        """Send one raw iot-feature request (protocol discovery)."""
        coordinator = await _ready(_coordinator(hass, call))
        result = await hass.async_add_executor_job(
            partial(
                coordinator.robot_api.raw_feature_request,
                coordinator.serial,
                method=call.data["method"],
                endpoint=call.data["endpoint"],
                domain=call.data["domain"],
                identifier=call.data["identifier"],
                payload=call.data.get("payload"),
                resource=call.data.get("resource", "SweepingRobot"),
                local_index=str(call.data.get("local_index", "0")),
            )
        )
        return _sanitize(result)

    async def async_api_request(call: ServiceCall) -> dict[str, Any]:
        """Send one raw request to the EZVIZ API host (protocol discovery)."""
        coordinator = await _ready(_coordinator(hass, call))
        result = await hass.async_add_executor_job(
            partial(
                coordinator.robot_api.raw_api_request,
                method=call.data["method"],
                path=call.data["path"],
                params=call.data.get("params"),
                data=call.data.get("data"),
                json_body=call.data.get("json"),
                headers=call.data.get("headers"),
            )
        )
        return _sanitize(result)

    serial_only = vol.Schema(_SERIAL_SCHEMA)
    for name, handler, response in (
        (SERVICE_INSPECT, async_inspect, SupportsResponse.ONLY),
        (SERVICE_MAP_DIAGNOSTICS, async_map_diagnostics, SupportsResponse.ONLY),
        (SERVICE_CAMERA_DIAGNOSTICS, async_camera_diagnostics, SupportsResponse.ONLY),
        (SERVICE_REFRESH_CAMERA, async_refresh_camera, SupportsResponse.NONE),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema=serial_only, supports_response=response
        )

    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_FEATURE_REQUEST,
        async_feature_request,
        schema=vol.Schema(
            {
                **_SERIAL_SCHEMA,
                vol.Required("method"): vol.In(["GET", "PUT"]),
                vol.Required("endpoint"): vol.In(["feature", "action"]),
                vol.Required("domain"): cv.string,
                vol.Required("identifier"): cv.string,
                vol.Optional("payload"): object,
                vol.Optional("resource"): cv.string,
                vol.Optional("local_index"): vol.Coerce(str),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_API_REQUEST,
        async_api_request,
        schema=vol.Schema(
            {
                **_SERIAL_SCHEMA,
                vol.Required("method"): vol.In(["GET", "POST", "PUT"]),
                vol.Required("path"): cv.string,
                vol.Optional("params"): dict,
                vol.Optional("data"): dict,
                vol.Optional("json"): object,
                vol.Optional("headers"): {cv.string: cv.string},
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )


async def async_unload_entry(
    hass: HomeAssistant, entry: EzvizVacuumConfigEntry
) -> bool:
    """Unload a robot."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.cloud.close)
    if unloaded and len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        for name in (
            SERVICE_INSPECT,
            SERVICE_MAP_DIAGNOSTICS,
            SERVICE_CAMERA_DIAGNOSTICS,
            SERVICE_REFRESH_CAMERA,
            SERVICE_FEATURE_REQUEST,
            SERVICE_API_REQUEST,
        ):
            hass.services.async_remove(DOMAIN, name)
    return unloaded
