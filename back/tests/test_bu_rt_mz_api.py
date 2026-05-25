from __future__ import annotations

from typing import Any
import inspect

from app.api.v1.bu import overview as overview_api
from app.bu.services.overview_service import build_rt_mz_heatmap, get_rt_mz_heatmap


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_Result":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.sql = ""
        self.params: dict[str, Any] = {}

    def execute(self, stmt: object, params: dict[str, Any]) -> _Result:
        self.sql = str(stmt)
        self.params = params
        return _Result(self.rows)


def test_rt_mz_bins_known_points() -> None:
    out = build_rt_mz_heatmap(
        [(0.0, 400.0), (0.5, 450.0), (1.0, 500.0), (1.0, 500.0)],
        bins_rt=2,
        bins_mz=2,
        run_id=37,
    )

    assert out.run_id == 37
    assert out.total_points == 4
    assert out.max_count == 3
    assert out.counts == [[1, 0], [0, 3]]
    assert len(out.rt_edges) == 3
    assert len(out.mz_edges) == 3


def test_rt_mz_run_filter_and_decoy_exclusion_are_in_sql() -> None:
    session = _Session([{"retention_time": 12.0, "precursor_mz": 500.0}])

    out = get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=37,
        q_max=0.01,
        bins_rt=10,
        bins_mz=10,
        decoy=False,
    )

    assert out.total_points == 1
    assert session.params["run_id"] == 37
    assert "run_id = :run_id" in session.sql
    assert "COALESCE(is_decoy_match, false) = false" in session.sql


def test_rt_mz_decoy_true_includes_decoys() -> None:
    session = _Session([])

    get_rt_mz_heatmap(
        session,  # type: ignore[arg-type]
        {"dataset_id": 39},
        run_id=None,
        q_max=0.01,
        bins_rt=10,
        bins_mz=10,
        decoy=True,
    )

    assert "is_decoy_match" not in session.sql


def test_rt_mz_empty_run_returns_legal_empty_payload() -> None:
    out = build_rt_mz_heatmap([], bins_rt=80, bins_mz=80, run_id=38)

    assert out.run_id == 38
    assert out.total_points == 0
    assert out.max_count == 0
    assert out.rt_edges == []
    assert out.mz_edges == []
    assert out.counts == []


def test_rt_mz_route_declares_bins_bounds() -> None:
    signature = inspect.signature(overview_api.rt_mz)

    for name in ("bins_rt", "bins_mz"):
        metadata = signature.parameters[name].default.metadata
        assert any(getattr(item, "ge", None) == 10 for item in metadata)
        assert any(getattr(item, "le", None) == 200 for item in metadata)
