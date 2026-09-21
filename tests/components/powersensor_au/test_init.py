"""Tests for setup, unload, and migration of the Powersensor integration."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from powersensor_local import VirtualHousehold
import pytest

from homeassistant.components.powersensor_au.config_flow import PowersensorConfigFlow
from homeassistant.components.powersensor_au.const import DOMAIN, ROLE_SOLAR
from homeassistant.components.powersensor_au.models import PowersensorRuntimeData
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from tests.common import MockConfigEntry, async_fire_time_changed

PLUG_MAC = "aabbccddeeff"


async def test_setup_entry_populates_runtime_data(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Setup stores a populated PowersensorRuntimeData on the entry."""
    assert config_entry.state is ConfigEntryState.LOADED
    assert isinstance(config_entry.runtime_data, PowersensorRuntimeData)
    assert config_entry.runtime_data.vhh is not None
    assert config_entry.runtime_data.dispatcher is not None
    assert config_entry.runtime_data.devices is not None


async def test_setup_starts_mdns_browser(
    hass: HomeAssistant,
    mock_devices: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """devices.start() is called once during setup with an async callback."""
    mock_devices.start.assert_awaited_once()
    cb = mock_devices.start.call_args[0][0]
    assert callable(cb)


async def test_unload_calls_disconnect_and_stop(
    hass: HomeAssistant,
    mock_devices: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """Unloading the entry calls disconnect() then stop() exactly once each."""
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_devices.stop.assert_awaited_once()
    # dispatcher.disconnect() is also called once; it's a real object so we
    # check indirectly that no exception was raised (state is NOT_LOADED).


async def test_unload_skips_teardown_when_platform_unload_fails(
    hass: HomeAssistant,
    mock_devices: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    """stop() is NOT called when async_unload_platforms returns False."""
    mock_devices.stop.reset_mock()

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=False,
    ):
        result = await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

    assert result is False
    mock_devices.stop.assert_not_called()
    # Entry transitions to FAILED_UNLOAD (not LOADED) when unload fails.
    assert config_entry.state is ConfigEntryState.FAILED_UNLOAD


@pytest.mark.usefixtures("mock_async_zeroconf")
async def test_devices_start_failure_retries_and_recovers(
    hass: HomeAssistant,
    mock_devices: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """A transient devices.start() failure retries and the entry then works normally.

    The sensor platform must not be forwarded before the failure, otherwise the
    retry finds it already registered and never re-runs its setup, leaving a
    LOADED entry that creates no entities.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"roles": {}},
        version=PowersensorConfigFlow.VERSION,
        minor_version=PowersensorConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(hass)

    mock_devices.start = AsyncMock(side_effect=[RuntimeError("no socket"), None])

    with patch(
        "homeassistant.components.powersensor_au.PowersensorZeroconfDevices",
        return_value=mock_devices,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_RETRY
        mock_devices.stop.assert_awaited_once()

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED
    assert mock_devices.start.await_count == 2

    cb = mock_devices.start.call_args[0][0]
    await cb({"event": "device_found", "mac": PLUG_MAC, "device_type": "plug"})
    await hass.async_block_till_done()

    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {e.unique_id for e in entities} >= {
        f"{PLUG_MAC}_power",
        f"{PLUG_MAC}_total_energy",
    }


async def test_setup_constructs_vhh_with_solar_when_role_persisted(
    hass: HomeAssistant,
    mock_async_zeroconf: MagicMock,
) -> None:
    """VirtualHousehold is constructed with with_solar=True when a solar role is persisted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"roles": {"aabbccddeeff": ROLE_SOLAR}},
        version=PowersensorConfigFlow.VERSION,
        minor_version=PowersensorConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(hass)

    constructed_args: list[bool] = []

    class CapturingVHH(VirtualHousehold):
        def __init__(self, with_solar: bool) -> None:
            constructed_args.append(with_solar)
            super().__init__(with_solar)

    devices = MagicMock()
    devices.start = AsyncMock()
    devices.stop = AsyncMock()
    devices.subscribe = MagicMock()
    devices.unsubscribe = MagicMock()

    with (
        patch(
            "homeassistant.components.powersensor_au.PowersensorZeroconfDevices",
            return_value=devices,
        ),
        patch(
            "homeassistant.components.powersensor_au.VirtualHousehold",
            CapturingVHH,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert constructed_args == [True]
