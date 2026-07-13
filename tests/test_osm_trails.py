from __future__ import annotations

from scripts import osm_trails


def test_mixed_osm_and_chord_route_is_not_labeled_all_osm(monkeypatch) -> None:
    monkeypatch.setattr(
        osm_trails,
        "fetch_trails",
        lambda _bbox: [[(0.0, 0.0), (0.0, 0.001), (0.0, 0.002)]],
    )
    _, source, provenance = osm_trails.trail_polyline(
        [(0.0, 0.0), (0.0, 0.002), (1.0, 1.0)]
    )

    assert source == "mixed_osm_chord"
    assert provenance["routed_legs"] == 1
    assert provenance["chord_fallback_legs"] == 1


def test_fetch_failure_is_explicit_chord_fallback(monkeypatch) -> None:
    def fail(_bbox):
        raise TimeoutError("fixture timeout")

    monkeypatch.setattr(osm_trails, "fetch_trails", fail)
    polyline, source, provenance = osm_trails.trail_polyline(
        [(44.0, -71.0), (44.1, -71.1)]
    )

    assert polyline == [(44.0, -71.0), (44.1, -71.1)]
    assert source == "chord"
    assert provenance["fetch_error_type"] == "TimeoutError"
    assert provenance["chord_fallback_legs"] == 1
