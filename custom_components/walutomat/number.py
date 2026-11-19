"""Number entity for the Walutomat exchange commission."""
from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_COMMISSION,
    DEFAULT_COMMISSION,
    DOMAIN,
    SIGNAL_COMMISSION_UPDATED,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the commission number entity (one per installation)."""
    if hass.data[DOMAIN].get("commission_number_created"):
        return
    hass.data[DOMAIN]["commission_number_created"] = True
    async_add_entities([WalutomatCommissionNumber(entry)])


class WalutomatCommissionNumber(RestoreNumber):
    """Commission (%) used by the "with commission" rate sensors."""

    _attr_name = "Walutomat Commission"
    _attr_unique_id = "walutomat_commission"
    _attr_icon = "mdi:percent"
    _attr_native_min_value = 0
    _attr_native_max_value = 5
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        api_key = entry.data.get(CONF_API_KEY)
        if api_key:
            # Same device as the balance sensors
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=f"Walutomat Account (...{api_key[-4:]})",
                manufacturer="Walutomat",
                model="Account Balances",
                entry_type="service",
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, "public_rates")},
                name="Walutomat Public Rates",
                manufacturer="Walutomat",
                model="Public Exchange Rates",
            )

    async def async_added_to_hass(self) -> None:
        """Restore the last value after a restart."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.hass.data[DOMAIN][DATA_COMMISSION] = float(last.native_value)
            async_dispatcher_send(self.hass, SIGNAL_COMMISSION_UPDATED)

    @property
    def native_value(self) -> float:
        """Return the current commission in percent."""
        return float(self.hass.data[DOMAIN].get(DATA_COMMISSION, DEFAULT_COMMISSION))

    async def async_set_native_value(self, value: float) -> None:
        """Set a new commission and update the rate sensors."""
        self.hass.data[DOMAIN][DATA_COMMISSION] = float(value)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_COMMISSION_UPDATED)
