"""Config flow for the Powersensor integration."""

from typing import Any, override

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.helpers.selector import selector
from homeassistant.helpers.service_info import zeroconf

from .const import (
    CFG_ROLES,
    DOMAIN,
    ROLE_APPLIANCE,
    ROLE_HOUSENET,
    ROLE_SOLAR,
    ROLE_UNKNOWN,
    ROLE_WATER,
)


class PowersensorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Powersensor."""

    VERSION = 1
    MINOR_VERSION = 1

    _name2mac: dict[str, str]

    async def async_step_reconfigure(
        self, user_input: dict[str, str | None] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfigure step. The primary use case is adding roles to sensors."""
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            roles: dict[str, str | None] = dict(entry.data[CFG_ROLES])
            for name, role in user_input.items():
                roles[self._name2mac[name]] = None if role == ROLE_UNKNOWN else role
            return self.async_update_reload_and_abort(
                entry, data_updates={CFG_ROLES: roles}
            )

        # The sensor list only exists in runtime discovery state.
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        # Field keys are display names; remember the mapping so the submit step
        # resolves exactly the sensors the user was shown.
        self._name2mac = {
            f"Powersensor Sensor ({mac})": mac
            for mac in entry.runtime_data.dispatcher.sensors
        }

        sensor_roles = {}
        for sensor_name, sensor_mac in self._name2mac.items():
            role = entry.data[CFG_ROLES].get(sensor_mac) or ROLE_UNKNOWN
            sel = selector(
                {
                    "select": {
                        "options": [
                            ROLE_HOUSENET,
                            ROLE_SOLAR,
                            ROLE_WATER,
                            ROLE_APPLIANCE,
                            ROLE_UNKNOWN,
                        ],
                        "mode": "dropdown",
                        "translation_key": "sensor_role",
                    }
                }
            )
            sensor_roles[
                vol.Optional(
                    sensor_name,
                    description={"suggested_value": role, "name": sensor_name},
                )
            ] = sel

        docs_url = "https://dius.github.io/homeassistant-powersensor/data.html#virtual-household"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(sensor_roles),
            description_placeholders={"docs_url": docs_url},
        )

    async def _async_prepare_setup(self) -> ConfigFlowResult | None:
        """Register a unique ID and guard against duplicate entries or parallel flows."""
        if self._async_in_progress(include_uninitialized=True):
            return self.async_abort(reason="already_in_progress")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self.context.update({"title_placeholders": {"name": "Powersensor"}})
        return None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        if result := await self._async_prepare_setup():
            return result
        return await self.async_step_manual_confirm()

    @override
    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery of a Powersensor plug.

        Zeroconf is used only to trigger config entry creation when a
        Powersensor device is first seen on the network.  All ongoing
        plug discovery and connection management is handled by the
        powersensor_local library.
        """
        properties = discovery_info.properties or {}
        if "id" not in properties:
            return self.async_abort(reason="firmware_not_compatible")

        if result := await self._async_prepare_setup():
            return result

        return await self.async_step_discovery_confirm()

    async def _async_confirm_step(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Shared confirmation step used by both discovery and manual flows."""
        if user_input is not None:
            return self.async_create_entry(
                title="Powersensor",
                data={CFG_ROLES: {}},
            )
        return self.async_show_form(step_id=step_id)

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the user wants to add the discovered Powersensor integration."""
        return await self._async_confirm_step(
            step_id="discovery_confirm", user_input=user_input
        )

    async def async_step_manual_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the user wants to add the integration without discovered plugs."""
        return await self._async_confirm_step(
            step_id="manual_confirm", user_input=user_input
        )
