#!/usr/bin/env python3
"""LoRa airtime and SOS-chain capacity math for the Meshtastic LongFast preset.

Semtech SX126x airtime formulation (AN1200.13 / SX1262 datasheet):
    T_sym = 2^SF / BW
    N_payload = 8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC - 20*IH) / (4*(SF - 2*DE))) * (CR + 4), 0)
    T_packet = (N_preamble + 4.25 + N_payload) * T_sym

LongFast: SF11, BW 250 kHz, CR 4/5 (CR=1); Meshtastic preamble = 16 symbols;
explicit header (IH=0), CRC on (CRC=1); low-data-rate optimize off (DE=0,
since T_sym = 8.192 ms < 16.38 ms).

Supports the <30 s SOS latency claim and the channel-utilization analysis in
trial1_report.tex. Run: python scripts/lora_airtime.py
"""
from __future__ import annotations

import argparse
import json
import math


def airtime_ms(payload_bytes: int, sf: int = 11, bw_hz: int = 250_000,
               cr: int = 1, preamble_syms: int = 16, crc: int = 1,
               implicit_header: int = 0) -> float:
    t_sym = (2 ** sf) / bw_hz * 1000.0  # ms
    de = 1 if t_sym >= 16.38 else 0
    n_payload = 8 + max(
        math.ceil((8 * payload_bytes - 4 * sf + 28 + 16 * crc - 20 * implicit_header)
                  / (4 * (sf - 2 * de))) * (cr + 4),
        0,
    )
    return (preamble_syms + 4.25 + n_payload) * t_sym


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hops", type=int, default=3)
    ap.add_argument("--out", default=None, help="Optional JSON output path")
    args = ap.parse_args()

    cases = {
        # Meshtastic packet = 16 B header + payload (encrypted)
        "position_packet_~40B": airtime_ms(40),
        "sos_text_~64B": airtime_ms(64),
        "ack_~16B": airtime_ms(16),
        "max_~237B": airtime_ms(237),
    }
    sos = cases["sos_text_~64B"]
    results = {
        "preset": "LongFast SF11/BW250/CR4-5, 16-symbol preamble, explicit header, CRC",
        "symbol_time_ms": round((2 ** 11) / 250_000 * 1000, 3),
        "airtime_ms": {k: round(v, 1) for k, v in cases.items()},
        "sos_chain": {
            "hops": args.max_hops,
            "serial_airtime_ms": round(sos * args.max_hops, 1),
            "note": (
                "pure airtime; Meshtastic adds per-hop random CSMA backoff "
                "(typically <1 s/hop under light load), so end-to-end SOS delivery "
                "is seconds, not tens of seconds — the <30 s target has large margin "
                "under light load"
            ),
        },
        "channel_utilization": {
            "assumption": "every node beacons a ~40 B position packet each 60 s",
            "per_node_utilization_pct": round(airtime_ms(40) / 60_000 * 100, 2),
            "nodes_at_10pct_channel_load": int(10 / (airtime_ms(40) / 60_000 * 100)),
            "note": (
                "Trial 1 saw ~22 concurrent nodes at the summit; at default beacon "
                "rates that is ~"
                f"{round(22 * airtime_ms(40) / 60_000 * 100, 1)}% raw airtime before "
                "mesh rebroadcast amplification — congestion management (longer "
                "beacon intervals, hop limits) belongs in the deployment plan"
            ),
        },
    }
    out = json.dumps(results, indent=2)
    print(out)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
