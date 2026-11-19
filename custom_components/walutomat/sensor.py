"""Platform for sensor integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_COMMISSION,
    DEFAULT_COMMISSION,
    DOMAIN,
    SIGNAL_COMMISSION_UPDATED,
)
from .coordinator import WalutomatBalancesCoordinator, WalutomatRatesCoordinator

_LOGGER = logging.getLogger(__name__)

# MDI icons mapping for currencies
CURRENCY_ICONS = {
    "EUR": "mdi:currency-eur",
    "USD": "mdi:currency-usd",
    "GBP": "mdi:currency-gbp",
    "CHF": "mdi:currency-chf",
    "UAH": "mdi:currency-uah",
    "RON": "mdi:currency-ron",
    "JPY": "mdi:currency-jpy",
    "CNY": "mdi:currency-cny",
}
DEFAULT_CURRENCY_ICON = "mdi:cash"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    entities = []

    # --- Setup Rate Sensors (Singleton) ---
    # The coordinator is global, but we check a flag to create entities only once.
    if "rate_sensors_created" not in hass.data[DOMAIN]:
        rates_coordinator: WalutomatRatesCoordinator = hass.data[DOMAIN]["rates_coordinator"]
        if rates_coordinator.data:
            rate_sensors = []
            for pair in rates_coordinator.data:
                rate_sensors.append(
                    WalutomatRateSensor(rates_coordinator, pair, "buyRate", "Buy Rate")
                )
                rate_sensors.append(
                    WalutomatRateSensor(
                        rates_coordinator, pair, "sellRate", "Sell Rate"
                    )
                )
                rate_sensors.append(
                    WalutomatEffectiveRateSensor(
                        rates_coordinator,
                        pair,
                        "buyRate",
                        "Buy Rate (with commission)",
                    )
                )
                rate_sensors.append(
                    WalutomatEffectiveRateSensor(
                        rates_coordinator,
                        pair,
                        "sellRate",
                        "Sell Rate (with commission)",
                    )
                )
            entities.extend(rate_sensors)
            hass.data[DOMAIN]["rate_sensors_created"] = True
            _LOGGER.debug("Created %d rate sensors", len(rate_sensors))

    # --- Setup Balance Sensors (Per Account) ---
    if entry.entry_id in hass.data[DOMAIN]:
        balances_coordinator: WalutomatBalancesCoordinator = hass.data[DOMAIN][
            entry.entry_id
        ]["balances_coordinator"]
        if balances_coordinator.data:
            balance_sensors = [
                WalutomatBalanceSensor(balances_coordinator, idx)
                for idx, balance_data in enumerate(balances_coordinator.data)
            ]
            entities.extend(balance_sensors)
            _LOGGER.debug("Created %d balance sensors", len(balance_sensors))

    if entities:
        async_add_entities(entities)


class WalutomatBalanceSensor(CoordinatorEntity[WalutomatBalancesCoordinator], SensorEntity):
    """Representation of a Walutomat Balance Sensor."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator: WalutomatBalancesCoordinator, idx: int) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._idx = idx
        self._balance_data = self.coordinator.data[self._idx]
        currency = self._balance_data["currency"]

        self._attr_name = f"Walutomat Balance {currency}"
        self._attr_unique_id = f"{self.coordinator.config_entry.entry_id}_{currency}"
        self._attr_native_unit_of_measurement = currency
        self._attr_icon = CURRENCY_ICONS.get(currency, DEFAULT_CURRENCY_ICON)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=f"Walutomat Account (...{self.coordinator.config_entry.data.get('api_key', '')[-4:]})",
            manufacturer="Walutomat",
            model="Account Balances",
            entry_type="service",
        )

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        return self.coordinator.data[self._idx]["balanceAvailable"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.coordinator.data[self._idx]


class WalutomatRateSensor(CoordinatorEntity[WalutomatRatesCoordinator], SensorEntity):
    """Representation of a Walutomat Rate Sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:cash-multiple"

    def __init__(
        self,
        coordinator: WalutomatRatesCoordinator,
        pair: str,
        rate_type: str,
        rate_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.pair = pair
        self.rate_type = rate_type
        self.base_currency, self.quote_currency = pair.split("_")

        self._attr_name = f"Walutomat {pair.replace('_', '/')} {rate_name}"
        self._attr_unique_id = f"walutomat_public_{pair}_{rate_type}"
        self._attr_native_unit_of_measurement = self.quote_currency

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "public_rates")},
            name="Walutomat Public Rates",
            manufacturer="Walutomat",
            model="Public Exchange Rates",
        )

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.pair in self.coordinator.data:
            return self.coordinator.data[self.pair][self.rate_type]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.pair in self.coordinator.data:
            return self.coordinator.data[self.pair]
        return None


def effective_rate(rate: float, rate_type: str, commission_percent: float) -> float:
    """Return the rate after Walutomat's commission is deducted.

    Walutomat deducts its commission from the amount of currency bought
    (boughtAmount - commissionAmount lands in the wallet), so:
    - buying the base currency at ``rate``: you receive (1 - c) units per
      ``rate`` paid, i.e. an effective price of ``rate / (1 - c)``;
    - selling the base currency at ``rate``: you receive ``rate * (1 - c)``.
    """
    c = commission_percent / 100
    if rate_type == "buyRate":
        return rate / (1 - c)
    return rate * (1 - c)


class WalutomatEffectiveRateSensor(WalutomatRateSensor):
    """Exchange rate including the configured Walutomat commission."""

    _attr_icon = "mdi:cash-minus"
    _attr_suggested_display_precision = 4

    def __init__(
        self,
        coordinator: WalutomatRatesCoordinator,
        pair: str,
        rate_type: str,
        rate_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, pair, rate_type, rate_name)
        self._attr_unique_id = f"walutomat_public_{pair}_{rate_type}_with_commission"

    async def async_added_to_hass(self) -> None:
        """Recalculate when the commission number entity changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_COMMISSION_UPDATED, self.async_write_ha_state
            )
        )

    @property
    def commission(self) -> float:
        """Return the current commission in percent."""
        return float(
            self.hass.data.get(DOMAIN, {}).get(DATA_COMMISSION, DEFAULT_COMMISSION)
        )

    @property
    def native_value(self) -> float | None:
        """Return the rate after commission."""
        rate = super().native_value
        if rate is None:
            return None
        try:
            return round(effective_rate(float(rate), self.rate_type, self.commission), 6)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.pair not in self.coordinator.data:
            return None
        return {
            "market_rate": self.coordinator.data[self.pair][self.rate_type],
            "commission_percent": self.commission,
        }
