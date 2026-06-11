from __future__ import annotations

import inspect
from collections import Counter
from typing import Any

import pytest

from app.api.v1.bu import overview as overview_api
from app.bu.services.overview_service import (
    build_rt_mz_heatmap_from_bins,
    get_rt_mz_heatmap,
)


class _Result:
    def __init__(self, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
        self._payload = payload

    def mappings(self) -> "_Result":
        return self

    def one(self) -> dict[str, Any]:
        assert isinstance(self._payload, dict)
        return self._payload

    def all(self) -> list[dict[str, Any]]:
        assert isinstance(self._payload, list)
        return self._payload


class _Session:
    def __init__(self, *payloads: dict[str, Any] | list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, stmt: object, params: dict[str, Any]) -> _Result:
        self.calls.append((str(stmt), dict(params)))
        return _Result(self.payloads.pop(0))


def _reference_bins(
    points: list[tuple[float, float]],
    *,
    bins_rt: int,
    bins_mz: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    valid = [(rt, mz) for rt, mz in points if rt is not None and mz is not None]
    if not valid:
        return {
            "rt_min": None,
            "rt_max": None,
            "mz_min": None,
            "mz_max": None,
            "total_points": 0,
        }, []

    rt_min = min(point[0] for point in valid)
    rt_max_raw = max(point[0] for point in valid)
    mz_min = min(point[1] for point in valid)
    mz_max_raw = max(point[1] for point in valid)
    rt_max = rt_min + 1.0 if rt_min == rt_max_raw else rt_max_raw
    mz_max = mz_min + 1.0 if mz_min == mz_max_raw else mz_max_raw
    counts: Counter[tuple[int, int]] = Counter()
    for rt, mz in valid:
        rt_bin = min(max(int((rt - rt_min) / (rt_max - rt_min) * bins_rt), 0), bins_rt - 1)
        mz_bin = min(max(int((mz - mz_min) / (mz_max - mz_min) * bins_mz), 0), bins_mz - 1)
        counts[(rt_bin, mz_bin)] += 1
    rows = [
        {"rt_bin": rt_bin, "mz_bin": mz_bin, "point_count": count}
        for (rt_bin, mz_bin), count in sorted(counts.items())
    ]
    return {
        "rt_min": rt_min,
        "rt_max": rt_max_raw,
        "mz_min": mz_min,
        "mz_max": mz_max_raw,
        "total_points": len(valid),
    }, rows


def test_rt_mz_database_bins_match_reference_algorithm() -> None:
    bounds, rows = _reference_bins(
        [(0.0, 400.0), (0.5, 450.0), (1.0, 500.0), (1.0, 500.0)],
        bins_rt=2,
        bins_mz=2,
    )
    session = _Session(bounds, rows)

    out = get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=37,
        q_max=0.01,
        bins_rt=2,
        bins_mz=2,
        decoy=False,
    )

    assert out.run_id == 37
    assert out.total_points == 4
    assert out.max_count == 3
    assert out.counts == [[1, 0], [0, 3]]
    assert out.rt_edges == [0.0, 0.5, 1.0]
    assert out.mz_edges == [400.0, 450.0, 500.0]


def test_rt_mz_uses_postgresql_aggregate_queries_only() -> None:
    bounds, rows = _reference_bins([(12.0, 500.0)], bins_rt=10, bins_mz=10)
    session = _Session(bounds, rows)

    get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=37,
        q_max=0.01,
        bins_rt=10,
        bins_mz=10,
        decoy=False,
    )

    assert len(session.calls) == 2
    bounds_sql, bounds_params = session.calls[0]
    aggregate_sql, aggregate_params = session.calls[1]
    assert "min(retention_time)" in bounds_sql
    assert "max(precursor_mz)" in bounds_sql
    assert "count(*) AS total_points" in bounds_sql
    assert "width_bucket" in aggregate_sql
    assert "GROUP BY rt_bin, mz_bin" in aggregate_sql
    assert "count(*) AS point_count" in aggregate_sql
    assert "SELECT retention_time, precursor_mz" not in aggregate_sql
    assert "run_id = :run_id" in bounds_sql
    assert "run_id = :run_id" in aggregate_sql
    assert "COALESCE(is_decoy_match, false) = false" in aggregate_sql
    assert "retention_time IS NOT NULL" in aggregate_sql
    assert "precursor_mz IS NOT NULL" in aggregate_sql
    assert bounds_params == {"dataset_id": 39, "q_max": 0.01, "run_id": 37}
    assert aggregate_params["bins_rt"] == 10
    assert aggregate_params["bins_mz"] == 10
    assert aggregate_params["run_id"] == 37


def test_rt_mz_max_boundaries_are_clamped_to_last_bin() -> None:
    points = [(1.0, 400.0), (1.0, 700.0), (5.0, 400.0), (5.0, 700.0)]
    bounds, rows = _reference_bins(points, bins_rt=2, bins_mz=2)
    session = _Session(bounds, rows)

    out = get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=None,
        q_max=0.01,
        bins_rt=2,
        bins_mz=2,
        decoy=False,
    )

    assert out.counts == [[1, 1], [1, 1]]
    aggregate_sql = session.calls[1][0]
    assert "LEAST" in aggregate_sql
    assert "GREATEST" in aggregate_sql
    assert ") - 1 AS rt_bin" in aggregate_sql
    assert ") - 1 AS mz_bin" in aggregate_sql


def test_rt_mz_single_point_expands_edges_without_division_by_zero() -> None:
    bounds, rows = _reference_bins([(7.5, 555.0)], bins_rt=10, bins_mz=10)
    session = _Session(bounds, rows)

    out = get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=38,
        q_max=0.01,
        bins_rt=10,
        bins_mz=10,
        decoy=False,
    )

    assert out.rt_edges[0] == 7.5
    assert out.rt_edges[-1] == 8.5
    assert out.mz_edges[0] == 555.0
    assert out.mz_edges[-1] == 556.0
    assert out.counts[0][0] == 1
    assert out.total_points == 1


def test_rt_mz_empty_run_returns_legal_empty_payload() -> None:
    bounds, _rows = _reference_bins([], bins_rt=80, bins_mz=80)
    session = _Session(bounds)

    out = get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=38,
        q_max=0.01,
        bins_rt=80,
        bins_mz=80,
        decoy=False,
    )

    assert len(session.calls) == 1
    assert out.run_id == 38
    assert out.total_points == 0
    assert out.max_count == 0
    assert out.rt_edges == []
    assert out.mz_edges == []
    assert out.counts == []


def test_rt_mz_decoy_true_includes_decoys() -> None:
    bounds, rows = _reference_bins([(1.0, 400.0)], bins_rt=10, bins_mz=10)
    session = _Session(bounds, rows)

    get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=None,
        q_max=0.01,
        bins_rt=10,
        bins_mz=10,
        decoy=True,
    )

    assert all("is_decoy_match" not in sql for sql, _params in session.calls)


def test_rt_mz_rejects_nonpositive_bins() -> None:
    session = _Session()

    with pytest.raises(ValueError, match="bin counts must be positive"):
        get_rt_mz_heatmap(
            session,  # type: ignore[arg-type]
            {"dataset_id": 39},
            run_id=None,
            q_max=0.01,
            bins_rt=0,
            bins_mz=10,
            decoy=False,
        )

    assert session.calls == []


def test_rt_mz_rejects_more_aggregate_rows_than_bins() -> None:
    rows = [{"rt_bin": 0, "mz_bin": 0, "point_count": 1}] * 5

    with pytest.raises(RuntimeError, match="more rows than available bins"):
        build_rt_mz_heatmap_from_bins(
            rows,
            rt_min=0.0,
            rt_max=1.0,
            mz_min=400.0,
            mz_max=500.0,
            bins_rt=2,
            bins_mz=2,
            total_points=5,
            run_id=None,
        )


def test_rt_mz_rejects_out_of_range_or_duplicate_bins() -> None:
    with pytest.raises(RuntimeError, match="invalid bin"):
        build_rt_mz_heatmap_from_bins(
            [{"rt_bin": 2, "mz_bin": 0, "point_count": 1}],
            rt_min=0.0,
            rt_max=1.0,
            mz_min=400.0,
            mz_max=500.0,
            bins_rt=2,
            bins_mz=2,
            total_points=1,
            run_id=None,
        )


def test_rt_mz_route_declares_bins_bounds() -> None:
    signature = inspect.signature(overview_api.rt_mz)

    for name in ("bins_rt", "bins_mz"):
        metadata = signature.parameters[name].default.metadata
        assert any(getattr(item, "ge", None) == 10 for item in metadata)
        assert any(getattr(item, "le", None) == 200 for item in metadata)
