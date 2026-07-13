#!/usr/bin/env python3
"""Audit modeled backhaul and trail coverage at two RF thresholds.

This is a *model screen*, not a field-validation result.  It reports both:

1. the receiver sensitivity floor (``-131 dBm``), useful only for identifying
   links that cannot close even under the model; and
2. the engineering planning threshold (``-100 dBm`` by default), which is the
   actual pass/fail gate and leaves margin for unmodeled losses. The controlling
   gate also excludes the uncalibrated short-link substitution. A separate
   counterfactual reports what happens if that optimistic policy is assumed.

Backhaul links use the link matrix's q90 received-power estimate.  Route files
currently contain only q50 path loss, so trail coverage is explicitly reported
as q50 and may not be described as a q90 reliability result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from radio_link_budget import (  # noqa: E402
    PLANNING_THRESHOLD_DBM,
    RX_SENSITIVITY_DBM,
    maximum_path_loss_db,
)


def _input_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _link_endpoints(label: str) -> tuple[str, str]:
    parts = str(label).split("<->")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid link label {label!r}; expected 'site_a<->site_b'")
    return parts[0], parts[1]


def connectivity(
    sites: Mapping[str, Mapping[str, Any]],
    links: pd.DataFrame,
    threshold_dbm: float,
    *,
    allow_short_link_policy: bool = True,
) -> dict[str, Any]:
    """Return gateway reachability using q90 RSSI at ``threshold_dbm``."""

    required = {"link", "pred_rssi_dbm_q90"}
    missing = required.difference(links.columns)
    if missing:
        raise ValueError(f"link matrix missing columns: {sorted(missing)}")
    if not math.isfinite(threshold_dbm):
        raise ValueError("receiver threshold must be finite")

    parent = {name: name for name in sites}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    used_links = 0
    excluded_short_link_policy = 0
    assumed_short_link_policy = 0
    for row in links.itertuples(index=False):
        a, b = _link_endpoints(row.link)
        unknown = {a, b}.difference(sites)
        if unknown:
            raise ValueError(f"link {row.link!r} references unknown sites {sorted(unknown)}")
        path_type = getattr(row, "path_type", None)
        policy_link = path_type in {
            "short_link_policy",
            "excluded_unvalidated_short_link",
        } or not bool(getattr(row, "planning_evidence_eligible", True))
        if policy_link and not allow_short_link_policy:
            excluded_short_link_policy += 1
            continue
        if policy_link and path_type == "excluded_unvalidated_short_link":
            if not hasattr(row, "policy_rssi_dbm_q90"):
                raise ValueError(
                    f"excluded policy link {row.link!r} lacks preserved policy RSSI"
                )
            rssi = float(row.policy_rssi_dbm_q90)
            assumed_short_link_policy += 1
        else:
            rssi = float(row.pred_rssi_dbm_q90)
            if policy_link:
                assumed_short_link_policy += 1
        if not math.isfinite(rssi):
            raise ValueError(f"link {row.link!r} has non-finite q90 RSSI")
        if rssi >= threshold_dbm:
            union(a, b)
            used_links += 1

    components: dict[str, list[str]] = {}
    for name in sites:
        components.setdefault(find(name), []).append(name)

    component_rows: list[dict[str, Any]] = []
    reachable: set[str] = set()
    stranded: list[str] = []
    for members in sorted(components.values(), key=lambda values: (-len(values), values)):
        members = sorted(members)
        gateways = [name for name in members if bool(sites[name].get("mqtt_uplink"))]
        reaches_backhaul = bool(gateways)
        if reaches_backhaul:
            reachable.update(members)
        else:
            stranded.extend(members)
        component_rows.append(
            {
                "n_sites": len(members),
                "gateways": gateways,
                "reaches_backhaul": reaches_backhaul,
                "members": members,
            }
        )

    return {
        "threshold_dbm": threshold_dbm,
        "link_estimate": "pred_rssi_dbm_q90",
        "n_usable_links": used_links,
        "allows_unvalidated_short_link_policy": allow_short_link_policy,
        "n_excluded_short_link_policy": excluded_short_link_policy,
        "n_assumed_short_link_policy": assumed_short_link_policy,
        "n_components": len(components),
        "components": component_rows,
        "reachable_sites": sorted(reachable),
        "stranded_sites": sorted(stranded),
    }


def trail_coverage(
    routes: Mapping[str, Mapping[str, Any]],
    reachable_sites: set[str],
    threshold_dbm: float,
    minimum_fraction: float,
) -> list[dict[str, Any]]:
    """Score q50 route samples against reachable fixed sites."""

    if not 0.0 <= minimum_fraction <= 1.0:
        raise ValueError("trail threshold must be between 0 and 1")
    max_loss_db = maximum_path_loss_db(threshold_dbm)
    rows: list[dict[str, Any]] = []

    for route_name, route in routes.items():
        sample_times = route.get("loss_t_s")
        loss_by_site = route.get("loss_db_q50")
        if not isinstance(sample_times, list) or not isinstance(loss_by_site, dict):
            raise ValueError(f"route {route_name!r} lacks loss_t_s/loss_db_q50 arrays")
        sample_count = len(sample_times)
        usable_sites = sorted(set(loss_by_site).intersection(reachable_sites))
        for site in usable_sites:
            if len(loss_by_site[site]) != sample_count:
                raise ValueError(
                    f"route {route_name!r}, site {site!r}: loss array length "
                    f"{len(loss_by_site[site])} != {sample_count}"
                )

        in_range = 0
        for index in range(sample_count):
            losses = [float(loss_by_site[site][index]) for site in usable_sites]
            if any(not math.isfinite(loss) for loss in losses):
                raise ValueError(f"route {route_name!r} has non-finite q50 path loss")
            if losses and min(losses) <= max_loss_db:
                in_range += 1

        fraction = in_range / sample_count if sample_count else 0.0
        rows.append(
            {
                "route": route_name,
                "geometry": route.get("geometry", "unknown"),
                "samples": sample_count,
                "reachable_candidate_sites": len(usable_sites),
                "estimate_quantile": "loss_db_q50",
                "receiver_threshold_dbm": threshold_dbm,
                "maximum_path_loss_db": max_loss_db,
                "coverage": round(fraction, 6),
                "ok": fraction >= minimum_fraction,
            }
        )
    return sorted(rows, key=lambda row: (row["coverage"], row["route"]))


def audit_tier(
    sites: Mapping[str, Mapping[str, Any]],
    links: pd.DataFrame,
    routes: Mapping[str, Mapping[str, Any]],
    threshold_dbm: float,
    minimum_fraction: float,
    *,
    allow_short_link_policy: bool = True,
) -> dict[str, Any]:
    """Build one internally consistent model-screen tier."""

    backhaul = connectivity(
        sites,
        links,
        threshold_dbm,
        allow_short_link_policy=allow_short_link_policy,
    )
    trails = trail_coverage(
        routes,
        set(backhaul["reachable_sites"]),
        threshold_dbm,
        minimum_fraction,
    )
    bad_routes = [row["route"] for row in trails if not row["ok"]]
    passed = not backhaul["stranded_sites"] and not bad_routes
    return {
        "receiver_threshold_dbm": threshold_dbm,
        "maximum_path_loss_db": maximum_path_loss_db(threshold_dbm),
        "backhaul_estimate": "q90 modeled received power",
        "trail_estimate": "q50 modeled path loss (route input has no q90)",
        "n_components": backhaul["n_components"],
        "n_usable_links": backhaul["n_usable_links"],
        "allows_unvalidated_short_link_policy": allow_short_link_policy,
        "n_excluded_short_link_policy": backhaul[
            "n_excluded_short_link_policy"
        ],
        "n_assumed_short_link_policy": backhaul[
            "n_assumed_short_link_policy"
        ],
        "components": backhaul["components"],
        "stranded_sites": backhaul["stranded_sites"],
        "trail_coverage": trails,
        "routes_under_threshold": bad_routes,
        "verdict": "PASS" if passed else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit modeled SAR coverage")
    parser.add_argument("--suffix", default="_statewide")
    parser.add_argument(
        "--routes",
        default=None,
        help="routes file (default: artifacts/sim/routes<suffix>.json)",
    )
    parser.add_argument(
        "--trail-threshold",
        type=float,
        default=0.85,
        help="minimum modeled fraction of route samples in range",
    )
    parser.add_argument(
        "--planning-threshold-dbm",
        type=float,
        default=PLANNING_THRESHOLD_DBM,
        help="engineering gate; sensitivity is reported separately",
    )
    parser.add_argument(
        "--allow-unvalidated-short-link-policy",
        action="store_true",
        help="permit FSPL+allowance short links in the controlling gate",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    topology_path = ROOT / f"artifacts/sim/topology{args.suffix}.json"
    links_path = ROOT / f"artifacts/sim/link_matrix{args.suffix}.csv"
    routes_path = ROOT / (
        args.routes or f"artifacts/sim/routes{args.suffix}.json"
    )
    topology = json.loads(topology_path.read_text())
    links = pd.read_csv(links_path)
    route_document = json.loads(routes_path.read_text())
    sites = topology["sites"]
    routes = route_document["routes"]

    sensitivity = audit_tier(
        sites,
        links,
        routes,
        RX_SENSITIVITY_DBM,
        args.trail_threshold,
        allow_short_link_policy=True,
    )
    planning_with_short_link_assumption = audit_tier(
        sites,
        links,
        routes,
        args.planning_threshold_dbm,
        args.trail_threshold,
        allow_short_link_policy=True,
    )
    planning = audit_tier(
        sites,
        links,
        routes,
        args.planning_threshold_dbm,
        args.trail_threshold,
        allow_short_link_policy=args.allow_unvalidated_short_link_policy,
    )

    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_kind": "uncalibrated_model_screen",
        "claim_status": (
            "PLANNING_SCREEN_PASS_NOT_FIELD_VALIDATED"
            if planning["verdict"] == "PASS"
            else "PLANNING_SCREEN_FAIL"
        ),
        "inputs": {
            "generator": _input_record(Path(__file__)),
            "topology": _input_record(topology_path),
            "link_matrix": _input_record(links_path),
            "routes": _input_record(routes_path),
        },
        "criteria": {
            "minimum_route_fraction": args.trail_threshold,
            "sensitivity_floor_dbm": RX_SENSITIVITY_DBM,
            "planning_threshold_dbm": args.planning_threshold_dbm,
            "controlling_gate_allows_unvalidated_short_link_policy": args.allow_unvalidated_short_link_policy,
            "overall_verdict_follows": "planning_screen",
        },
        "limitations": [
            "All values are predictions from project-generated topology and propagation inputs, not independent field observations.",
            "Backhaul uses modeled q90 RSSI; trails have only q50 path-loss arrays and therefore do not establish q90 route reliability.",
            "The model does not establish installation feasibility, permission, legal authorization, hardware performance, body/foliage loss, local clutter, or weather robustness.",
            "Site selection and evaluation share the same project model, so a pass would be an internal design screen rather than independent validation.",
            "The controlling gate excludes the sub-1.35 km FSPL-plus-allowance policy by default because it was chosen without independent calibration; a counterfactual tier reports its effect.",
        ],
        "n_sites": len(sites),
        "sensitivity_floor_screen": sensitivity,
        "planning_screen_with_unvalidated_short_link_assumption": planning_with_short_link_assumption,
        "planning_screen": planning,
        # Compatibility fields deliberately mirror the controlling planning tier.
        "n_components": planning["n_components"],
        "components": planning["components"],
        "stranded_sites": planning["stranded_sites"],
        "trail_coverage": planning["trail_coverage"],
        "verdict": planning["verdict"],
    }

    output_path = ROOT / (
        args.out or f"artifacts/sim/coverage_audit{args.suffix}.json"
    )
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(audit, indent=2) + "\n")
    temporary_path.replace(output_path)

    for label, tier in (
        ("sensitivity + policy", sensitivity),
        ("planning + policy", planning_with_short_link_assumption),
        ("controlling plan", planning),
    ):
        print(
            f"{label:18s} {tier['receiver_threshold_dbm']:7.1f} dBm: "
            f"{tier['verdict']} — {len(tier['stranded_sites'])} stranded sites; "
            f"{len(tier['routes_under_threshold'])} routes below "
            f"{args.trail_threshold:.0%} q50 modeled coverage"
        )
    print("OVERALL MODEL-SCREEN VERDICT:", planning["verdict"])
    print("This is not field validation.")
    return 0 if planning["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
