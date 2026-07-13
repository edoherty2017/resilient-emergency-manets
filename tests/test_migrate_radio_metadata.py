from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from migrate_radio_metadata import migrate_document  # noqa: E402


def test_migration_separates_transmit_and_receive_terms():
    document = {"radio": {"eirp_dbm": 26.3, "rx_sensitivity_dbm": -131.0}}
    assert migrate_document(document) is True
    assert document["radio"]["tx_eirp_dbm"] == pytest.approx(24.15)
    assert document["radio"]["rx_power_reference_dbm"] == pytest.approx(26.3)
    assert "eirp_dbm" not in document["radio"]
    assert "radio_metadata_correction" in document


def test_migration_refuses_to_guess_unknown_legacy_value():
    with pytest.raises(ValueError, match="refusing unknown legacy"):
        migrate_document({"radio": {"eirp_dbm": 30.0}})


def test_already_explicit_metadata_is_unchanged():
    document = {"radio": {"tx_eirp_dbm": 24.15}}
    assert migrate_document(document) is False
