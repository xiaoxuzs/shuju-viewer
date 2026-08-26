from __future__ import annotations

from app.bu.services.scan_resolver import isolation_window_contains


def test_isolation_window_contains_allows_tiny_boundary_rounding() -> None:
    spec = {
        "precursor": {
            "target_mz": 500.0,
            "lower_offset": 10.0,
            "upper_offset": 10.0,
        }
    }

    assert isolation_window_contains(spec, 510.0005) is True
    assert isolation_window_contains(spec, 510.01) is False
