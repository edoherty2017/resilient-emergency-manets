from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from radio_link_budget import (  # noqa: E402
    RX_ANTENNA_GAIN_DBI,
    RX_POWER_REFERENCE_DBM,
    TX_ANTENNA_GAIN_DBI,
    TX_CONDUCTED_DBM,
    TX_EIRP_DBM,
    config_rx_power_reference_dbm,
    maximum_path_loss_db,
    metadata,
    received_power_dbm,
)


def test_eirp_excludes_receive_antenna_gain():
    assert TX_EIRP_DBM == TX_CONDUCTED_DBM + TX_ANTENNA_GAIN_DBI
    assert RX_POWER_REFERENCE_DBM == TX_EIRP_DBM + RX_ANTENNA_GAIN_DBI
    assert TX_EIRP_DBM == 24.15
    assert RX_POWER_REFERENCE_DBM == pytest.approx(26.3)


def test_received_power_and_path_loss_closure_are_inverse():
    max_loss = maximum_path_loss_db(-131.0)
    assert max_loss == 157.3
    assert received_power_dbm(max_loss) == -131.0


def test_metadata_uses_unambiguous_names():
    values = metadata()
    assert values["tx_eirp_dbm"] == 24.15
    assert values["rx_power_reference_dbm"] == pytest.approx(26.3)
    assert "eirp_dbm" not in values


def test_config_reference_supports_explicit_terms_and_legacy_input():
    assert config_rx_power_reference_dbm(
        {
            "tx_eirp_dbm": 24.15,
            "rx_antenna_gain_dbi": 2.15,
            "rx_feed_loss_db": 0.0,
        }
    ) == pytest.approx(26.3)
    assert config_rx_power_reference_dbm({"eirp_dbm": 26.3}) == 26.3
