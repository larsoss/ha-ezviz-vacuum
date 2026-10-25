"""Config flow for EZVIZ robot vacuums."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import voluptuous as vol

from . import robot
from .const import CONF_SERIAL, CONF_SOURCE_ENTRY_ID, DOMAIN, SOURCE_DOMAIN
from .coordinator import find_api


class EzvizVacuumConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Add one EZVIZ robot by reusing the official EZVIZ session."""

    VERSION = 1

    def __init__(self) -> None:
        self._source_entry_id: str | None = None
        self._robots: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the EZVIZ account to use."""
        source_entries = self.hass.config_entries.async_entries(SOURCE_DOMAIN)
        if not source_entries:
            return self.async_abort(reason="ezviz_not_configured")
        if len(source_entries) == 1 and user_input is None:
            user_input = {CONF_SOURCE_ENTRY_ID: source_entries[0].entry_id}

        if user_input is not None:
            self._source_entry_id = user_input[CONF_SOURCE_ENTRY_ID]
            return await self.async_step_robot()

        options = [
            selector.SelectOptionDict(value=entry.entry_id, label=entry.title)
            for entry in source_entries
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_ENTRY_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_robot(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose the robot when the account has several."""
        if user_input is not None:
            return await self._async_create(user_input[CONF_SERIAL])

        if not self._robots:
            robots = await self._async_discover()
            if robots is None:
                return self.async_abort(reason="ezviz_not_loaded")
            configured = {
                str(entry.unique_id).upper() for entry in self._async_current_entries()
            }
            self._robots = {
                serial: name
                for serial, name in robots.items()
                if serial.upper() not in configured
            }
        if not self._robots:
            return self.async_abort(reason="no_robots")
        if len(self._robots) == 1:
            return await self._async_create(next(iter(self._robots)))

        return self.async_show_form(
            step_id="robot",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIAL): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=serial, label=f"{name} ({serial})"
                                )
                                for serial, name in self._robots.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def _async_create(self, serial: str) -> FlowResult:
        serial = serial.strip().upper()
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self._robots.get(serial) or f"EZVIZ robot {serial}",
            data={CONF_SOURCE_ENTRY_ID: self._source_entry_id, CONF_SERIAL: serial},
        )

    async def _async_discover(self) -> dict[str, str] | None:
        """Return ``serial -> name`` for robot vacuums on the account."""
        source = self.hass.config_entries.async_get_entry(self._source_entry_id or "")
        if source is None or source.state is not ConfigEntryState.LOADED:
            return None
        api = find_api(getattr(source, "runtime_data", None))
        if api is None:
            return None
        try:
            devices = await self.hass.async_add_executor_job(api.get_device_infos)
        except Exception:  # noqa: BLE001 - any cloud failure aborts the flow
            return None
        if not isinstance(devices, Mapping):
            return None
        return {
            str(serial): str(robot.device_details(payload)["name"])
            for serial, payload in devices.items()
            if isinstance(payload, Mapping) and robot.is_robot(payload)
        }
