"""Tests for the Walutomat sensors."""
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.walutomat.const import (
    CONF_COMMISSION,
    CONF_CURRENCY_PAIRS,
    DOMAIN,
)
from custom_components.walutomat.sensor import effective_rate


@pytest.mark.asyncio
async def test_rate_sensors(hass: HomeAssistant) -> None:
    """Test the rate sensors."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            CONF_CURRENCY_PAIRS: ["EUR_PLN", "USD_PLN"],
        },
        entry_id="test-rates",
    )

    with patch(
        "walutomat_py.WalutomatClient.get_public_rate",
        side_effect=[
            {"buyRate": 4.5, "sellRate": 4.6},
            {"buyRate": 3.8, "sellRate": 3.9},
        ],
    ):
        config_entry.add_to_hass(hass)
        setup_result = await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        assert setup_result
        assert config_entry.state == ConfigEntryState.LOADED

        eur_buy_sensor = hass.states.get("sensor.walutomat_eur_pln_buy_rate")
        eur_sell_sensor = hass.states.get("sensor.walutomat_eur_pln_sell_rate")
        usd_buy_sensor = hass.states.get("sensor.walutomat_usd_pln_buy_rate")
        usd_sell_sensor = hass.states.get("sensor.walutomat_usd_pln_sell_rate")

        assert eur_buy_sensor is not None
        assert eur_sell_sensor is not None
        assert usd_buy_sensor is not None
        assert usd_sell_sensor is not None

        assert eur_buy_sensor.state == "4.5"
        assert eur_sell_sensor.state == "4.6"
        assert usd_buy_sensor.state == "3.8"
        assert usd_sell_sensor.state == "3.9"

        assert eur_buy_sensor.attributes["unit_of_measurement"] == "PLN"

        # Effective rates with default 0.2% commission
        eur_buy_eff = hass.states.get(
            "sensor.walutomat_eur_pln_buy_rate_with_commission"
        )
        eur_sell_eff = hass.states.get(
            "sensor.walutomat_eur_pln_sell_rate_with_commission"
        )
        assert float(eur_buy_eff.state) == pytest.approx(4.5 / 0.998, abs=1e-6)
        assert float(eur_sell_eff.state) == pytest.approx(4.6 * 0.998, abs=1e-6)
        assert eur_buy_eff.attributes["commission_percent"] == 0.2
        assert eur_buy_eff.attributes["market_rate"] == 4.5
        assert eur_buy_eff.attributes["unit_of_measurement"] == "PLN"


@pytest.mark.asyncio
async def test_effective_rate_custom_commission(hass: HomeAssistant) -> None:
    """Effective rate sensors use the commission set in options."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_CURRENCY_PAIRS: ["EUR_PLN"], CONF_COMMISSION: 0.1},
        entry_id="test-commission",
    )
    with patch(
        "walutomat_py.WalutomatClient.get_public_rate",
        return_value={"buyRate": "4.2500", "sellRate": "4.2400"},
    ):
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    buy = hass.states.get("sensor.walutomat_eur_pln_buy_rate_with_commission")
    sell = hass.states.get("sensor.walutomat_eur_pln_sell_rate_with_commission")
    assert float(buy.state) == pytest.approx(4.25 / 0.999, abs=1e-6)
    assert float(sell.state) == pytest.approx(4.24 * 0.999, abs=1e-6)


def test_effective_rate_math() -> None:
    """Commission makes buying more expensive and selling less profitable."""
    assert effective_rate(4.0, "buyRate", 0) == 4.0
    assert effective_rate(4.0, "sellRate", 0) == 4.0
    assert effective_rate(4.0, "buyRate", 0.2) > 4.0
    assert effective_rate(4.0, "sellRate", 0.2) < 4.0
    # 1000 PLN buys 1000/4.0*0.998 EUR -> effective price 4.0/0.998
    assert effective_rate(4.0, "buyRate", 0.2) == pytest.approx(4.0 / 0.998)
