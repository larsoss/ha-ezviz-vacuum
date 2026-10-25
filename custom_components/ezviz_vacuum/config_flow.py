"""Config flow for EZVIZ robot vacuums."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.helpers import selector
from pyezvizapi.exceptions import (
    EzvizAuthVerificationCode,
    HTTPError,
    InvalidURL,
    PyEzvizError,
)
import voluptuous as vol

from . import robot
from .cloud import EU_URL, RUSSIA_URL, new_client, sign_in
from .const import CONF_SERIAL, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_SMS_CODE = "sms_code"


def _error_key(err: Exception) -> str:
    """Translate a pyezvizapi login error into a form error key."""
    if isinstance(err, (InvalidURL, HTTPError)):
        return "cannot_connect"
    message = str(err).casefold()
    if "incorrect username" in message or "incorrect password" in message:
        return "invalid_auth"
    if "mfa code is invalid" in message:
        return "invalid_code"
    if "locked" in message:
        return "user_locked"
    return "unknown"


def _account_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(autocomplete="username")
            ),
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD,
                    autocomplete="current-password",
                )
            ),
            vol.Required(
                CONF_URL, default=defaults.get(CONF_URL, EU_URL)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[EU_URL, RUSSIA_URL],
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


class EzvizVacuumConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in to an EZVIZ account and add one of its robots."""

    VERSION = 2

    def __init__(self) -> None:
        self._username = ""
        self._client: Any = None
        self._token: dict[str, Any] = {}
        self._robots: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the EZVIZ account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_login(user_input)
            if not errors:
                return await self.async_step_robot()
            if errors.get("base") == "verification_required":
                return await self.async_step_sms_code()
        return self.async_show_form(
            step_id="user",
            data_schema=_account_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_sms_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the verification code EZVIZ sent to the account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Keep the code as text: a leading zero is part of the code.
            code = "".join(str(user_input[CONF_SMS_CODE]).split())
            if not code.isdigit():
                errors = {"base": "invalid_code"}
            else:
                errors = await self._async_login({}, sms_code=code)
            if not errors:
                if self.source == SOURCE_REAUTH:
                    return self._async_finish_reauth()
                return await self.async_step_robot()
        return self.async_show_form(
            step_id="sms_code",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SMS_CODE): selector.TextSelector(
                        selector.TextSelectorConfig(autocomplete="one-time-code")
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_robot(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the robot when the account has several."""
        if user_input is not None:
            return await self._async_create(user_input[CONF_SERIAL])

        if not self._robots:
            robots = await self._async_discover()
            if robots is None:
                return self.async_abort(reason="cannot_connect")
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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start signing in again when the session has expired."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account password again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_login(user_input)
            if not errors:
                return self._async_finish_reauth()
            if errors.get("base") == "verification_required":
                return await self.async_step_sms_code()
        token = entry.data.get(CONF_TOKEN)
        defaults = {
            CONF_USERNAME: entry.data.get(CONF_USERNAME, ""),
            CONF_URL: (token or {}).get("api_url", EU_URL)
            if isinstance(token, Mapping)
            else EU_URL,
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_account_schema(user_input or defaults),
            description_placeholders={"robot": entry.title},
            errors=errors,
        )

    def _async_finish_reauth(self) -> ConfigFlowResult:
        return self.async_update_reload_and_abort(
            self._get_reauth_entry(),
            data_updates={CONF_TOKEN: self._token, CONF_USERNAME: self._username},
        )

    async def _async_login(
        self, user_input: Mapping[str, Any], *, sms_code: str | None = None
    ) -> dict[str, str]:
        """Log in; return form errors (empty on success)."""
        if user_input:
            self._username = str(user_input[CONF_USERNAME]).strip()
            self._client = await self.hass.async_add_executor_job(
                new_client,
                self._username,
                str(user_input[CONF_PASSWORD]),
                str(user_input[CONF_URL]).strip(),
            )
        try:
            self._token = await self.hass.async_add_executor_job(
                partial(sign_in, self._client, sms_code)
            )
        except EzvizAuthVerificationCode:
            # The client keeps the credentials for the attempt with the code.
            return {"base": "verification_required"}
        except PyEzvizError as err:
            return {"base": _error_key(err)}
        except Exception:
            _LOGGER.exception("Unexpected error while signing in to EZVIZ")
            return {"base": "unknown"}
        return {}

    async def _async_create(self, serial: str) -> ConfigFlowResult:
        serial = serial.strip().upper()
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self._robots.get(serial) or f"EZVIZ robot {serial}",
            data={
                CONF_SERIAL: serial,
                CONF_USERNAME: self._username,
                CONF_TOKEN: self._token,
            },
        )

    async def _async_discover(self) -> dict[str, str] | None:
        """Return ``serial -> name`` for robot vacuums on the account."""
        try:
            devices = await self.hass.async_add_executor_job(
                self._client.get_device_infos
            )
        except Exception:  # noqa: BLE001 - any cloud failure aborts the flow
            return None
        if not isinstance(devices, Mapping):
            return None
        return {
            str(serial): str(robot.device_details(payload)["name"])
            for serial, payload in devices.items()
            if isinstance(payload, Mapping) and robot.is_robot(payload)
        }
