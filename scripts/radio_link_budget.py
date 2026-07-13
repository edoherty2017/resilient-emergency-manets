#!/usr/bin/env python3
"""Canonical radio terminal gains for the project's link-budget calculations.

EIRP is transmitter power plus *transmit-side* antenna gain (minus feed loss).
Receiver antenna gain is applied separately when converting path loss to power
at the receiver input.  Older project code called the sum of both antenna gains
"EIRP", which overstated regulatory transmit power by 2.15 dB even though the
received-power arithmetic itself was otherwise consistent.
"""

from __future__ import annotations

from typing import Final, Mapping


TX_CONDUCTED_DBM: Final = 22.0
TX_ANTENNA_GAIN_DBI: Final = 2.15
TX_FEED_LOSS_DB: Final = 0.0  # Measure and replace if a feed line is introduced.
RX_ANTENNA_GAIN_DBI: Final = 2.15
RX_FEED_LOSS_DB: Final = 0.0

TX_EIRP_DBM: Final = TX_CONDUCTED_DBM + TX_ANTENNA_GAIN_DBI - TX_FEED_LOSS_DB

# The reference level used in Pr = reference - basic_path_loss.  This is not
# EIRP because it includes the receive-side terminal gain.
RX_POWER_REFERENCE_DBM: Final = TX_EIRP_DBM + RX_ANTENNA_GAIN_DBI - RX_FEED_LOSS_DB

RX_SENSITIVITY_DBM: Final = -131.0
PLANNING_THRESHOLD_DBM: Final = -100.0


def received_power_dbm(path_loss_db: float) -> float:
    """Return receiver-input power for a basic path loss in dB."""

    return RX_POWER_REFERENCE_DBM - path_loss_db


def maximum_path_loss_db(receiver_threshold_dbm: float = RX_SENSITIVITY_DBM) -> float:
    """Return the path loss that exactly closes the link budget."""

    return RX_POWER_REFERENCE_DBM - receiver_threshold_dbm


def metadata() -> dict[str, float]:
    """Machine-readable radio terms without conflating EIRP and RX gain."""

    return {
        "tx_conducted_dbm": TX_CONDUCTED_DBM,
        "tx_antenna_gain_dbi": TX_ANTENNA_GAIN_DBI,
        "tx_feed_loss_db": TX_FEED_LOSS_DB,
        "tx_eirp_dbm": TX_EIRP_DBM,
        "rx_antenna_gain_dbi": RX_ANTENNA_GAIN_DBI,
        "rx_feed_loss_db": RX_FEED_LOSS_DB,
        "rx_power_reference_dbm": RX_POWER_REFERENCE_DBM,
        "rx_sensitivity_dbm": RX_SENSITIVITY_DBM,
        "planning_threshold_dbm": PLANNING_THRESHOLD_DBM,
    }


def config_rx_power_reference_dbm(radio: Mapping[str, float]) -> float:
    """Resolve a path-loss reference from explicit or legacy config fields.

    New configurations separate transmitter EIRP from receive-side gain. The
    legacy ``eirp_dbm`` key is accepted as the old received-power reference so
    archived experiment configs remain readable; it must not be presented as
    regulatory transmitter EIRP.
    """

    if "tx_eirp_dbm" in radio:
        return (
            float(radio["tx_eirp_dbm"])
            + float(radio.get("rx_antenna_gain_dbi", 0.0))
            - float(radio.get("rx_feed_loss_db", 0.0))
        )
    if "eirp_dbm" in radio:
        return float(radio["eirp_dbm"])
    raise KeyError(
        "radio config requires tx_eirp_dbm (+ optional RX gains) or legacy eirp_dbm"
    )
