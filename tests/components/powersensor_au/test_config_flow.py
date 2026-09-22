"""Tests for the powersensor_au config flow."""

from collections.abc import Callable, Coroutine
from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant import config_entries
import homeassistant.components.powersensor_au
from homeassistant.components.powersensor_au.config_flow import PowersensorConfigFlow
from homeassistant.components.powersensor_au.const import (
    CFG_ROLES,
    DOMAIN,
    ROLE_HOUSENET,
    ROLE_SOLAR,
    ROLE_UNKNOWN,
    ROLE_WATER,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from tests.common import MockConfigEntry

PLUG_MAC = "a4cf1218f158"
SECOND_MAC = "a4cf1218f160"
MAINS_MAC = "c001eat5"
SOLAR_MAC = "cafebabe"
UNKNOWN_MAC = "d3adb33f"


def _sensor_name(mac: str) -> str:
    return f"Powersensor Sensor ({mac})"


@pytest.fixture
def bypass_setup(
    monkeypatch: pytest.MonkeyPatch,
    mock_async_zeroconf: MagicMock,
) -> None:
    """Bypass actual entry setup and prevent real zeroconf socket from opening."""
    monkeypatch.setattr(
        homeassistant.components.powersensor_au,
        "async_setup_entry",
        AsyncMock(return_value=True),
    )


def _zc_info(mac: str, ip: str = "192.168.0.33") -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(ip),
        ip_addresses=[ip_address(ip)],
        hostname=f"Powersensor-gateway-{mac}-civet.local",
        name=f"Powersensor-gateway-{mac}-civet._powersensor._udp.local",
        port=49476,
        type="_powersensor._udp.local.",
        properties={"version": "1", "id": mac},
    )


# ---------------------------------------------------------------------------
# User flow
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("bypass_setup")
async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """User-initiated flow reaches the confirm form then creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert isinstance(result["data"]["roles"], dict)


@pytest.mark.usefixtures("bypass_setup")
async def test_user_flow_aborts_when_already_configured(hass: HomeAssistant) -> None:
    """A second user flow aborts with single_instance_allowed once an entry exists."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "single_instance_allowed"


@pytest.mark.usefixtures("bypass_setup")
async def test_user_flow_aborts_when_already_in_progress(hass: HomeAssistant) -> None:
    """A second user flow aborts if the first is still on the confirm form."""
    result1 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result1["type"] is FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_in_progress"


# ---------------------------------------------------------------------------
# Zeroconf flow
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("bypass_setup")
async def test_zeroconf_flow_creates_entry(hass: HomeAssistant) -> None:
    """Zeroconf discovery reaches confirm form then creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zc_info(PLUG_MAC),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert isinstance(result["data"]["roles"], dict)


@pytest.mark.usefixtures("bypass_setup")
async def test_zeroconf_second_plug_aborts_when_configured(hass: HomeAssistant) -> None:
    """A second plug discovery aborts once the entry exists."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zc_info(PLUG_MAC),
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zc_info(SECOND_MAC, ip="192.168.0.37"),
    )
    assert result2["type"] is FlowResultType.ABORT


@pytest.mark.usefixtures("bypass_setup")
async def test_zeroconf_simultaneous_discoveries_deduplicate(
    hass: HomeAssistant,
) -> None:
    """Two simultaneous discoveries only produce one flow; the second aborts."""
    result1 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zc_info(PLUG_MAC),
    )
    assert result1["type"] is FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zc_info(SECOND_MAC, ip="192.168.0.37"),
    )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_in_progress"

    result1 = await hass.config_entries.flow.async_configure(
        result1["flow_id"], user_input={}
    )
    assert result1["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("bypass_setup")
async def test_zeroconf_missing_id_aborts(hass: HomeAssistant) -> None:
    """Discovery aborts when the plug advertises without an 'id' property."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=ZeroconfServiceInfo(
            ip_address=ip_address("192.168.0.33"),
            ip_addresses=[ip_address("192.168.0.33")],
            hostname="Powersensor-gateway.local",
            name="Powersensor-gateway._powersensor._udp.local",
            port=49476,
            type="_powersensor._udp.local.",
            properties={"version": "1"},  # no 'id'
        ),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "firmware_not_compatible"


# ---------------------------------------------------------------------------
# Reconfigure flow
# ---------------------------------------------------------------------------


@pytest.fixture
async def reconfigure_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fire: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
) -> MockConfigEntry:
    """A loaded entry with a house-net, a solar and an unassigned sensor discovered."""
    await fire({"event": "device_found", "mac": MAINS_MAC, "device_type": "sensor"})
    await fire({"event": "now_relaying_for", "mac": MAINS_MAC, "role": ROLE_HOUSENET})
    await fire({"event": "device_found", "mac": SOLAR_MAC, "device_type": "sensor"})
    await fire({"event": "now_relaying_for", "mac": SOLAR_MAC, "role": ROLE_SOLAR})
    await fire({"event": "device_found", "mac": UNKNOWN_MAC, "device_type": "sensor"})
    await hass.async_block_till_done()
    return config_entry


async def _start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return result["flow_id"]


@pytest.mark.parametrize("check_translations", [None])
@pytest.mark.parametrize(
    ("mac", "submitted", "persisted"),
    [
        pytest.param(UNKNOWN_MAC, ROLE_WATER, ROLE_WATER, id="assign_role"),
        pytest.param(SOLAR_MAC, ROLE_UNKNOWN, None, id="clear_role"),
    ],
)
async def test_reconfigure_persists_roles_and_reloads(
    hass: HomeAssistant,
    reconfigure_entry: MockConfigEntry,
    mock_devices: MagicMock,
    mac: str,
    submitted: str,
    persisted: str | None,
) -> None:
    """Submitted roles are written to entry.data in one update and the entry is reloaded."""
    flow_id = await _start_reconfigure(hass, reconfigure_entry)

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input={_sensor_name(mac): submitted}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert reconfigure_entry.data[CFG_ROLES] == {
        MAINS_MAC: ROLE_HOUSENET,
        SOLAR_MAC: ROLE_SOLAR,
        mac: persisted,
    }
    assert reconfigure_entry.state is ConfigEntryState.LOADED
    mock_devices.stop.assert_awaited_once()
    assert mock_devices.start.await_count == 2


@pytest.mark.parametrize("check_translations", [None])
async def test_reconfigure_form_suggests_persisted_roles(
    hass: HomeAssistant,
    reconfigure_entry: MockConfigEntry,
) -> None:
    """The form lists every discovered sensor, suggesting its persisted role or unknown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": reconfigure_entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"] is not None

    suggested = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
    }
    assert suggested == {
        _sensor_name(MAINS_MAC): ROLE_HOUSENET,
        _sensor_name(SOLAR_MAC): ROLE_SOLAR,
        _sensor_name(UNKNOWN_MAC): ROLE_UNKNOWN,
    }


@pytest.mark.usefixtures("mock_async_zeroconf")
async def test_reconfigure_aborts_when_entry_not_loaded(hass: HomeAssistant) -> None:
    """Reconfigure aborts when the entry is not loaded, as sensors are only known at runtime."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CFG_ROLES: {}},
        version=PowersensorConfigFlow.VERSION,
        minor_version=PowersensorConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"
