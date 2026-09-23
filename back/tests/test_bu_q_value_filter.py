import pytest

from app.api.v1.bu import overview as overview_api
from app.bu.q_value_filter import resolve_q_value_cutoff
from app.schemas import BuRtMzHeatmapOut


@pytest.mark.parametrize("value,expected", [(None, None), (0, 0.0), (0.01, 0.01), (False, None), ("NaN", None)])
def test_only_a_valid_declared_default_enables_q_filter(value, expected):
    assert resolve_q_value_cutoff({"extra_metadata": {"q_value_cutoff": value}}, None) == expected


def test_explicit_disable_cancels_even_a_declared_dataset_threshold():
    dataset = {"extra_metadata": {"q_value_cutoff": 0.01}}
    assert resolve_q_value_cutoff(dataset, None, enabled=False) is None
    assert resolve_q_value_cutoff(dataset, 0.1, enabled=False) is None
    assert resolve_q_value_cutoff(dataset, 0) == 0
    assert resolve_q_value_cutoff({}, None) is None


@pytest.mark.parametrize("cutoff,enabled,expected", [(None, True, None), (0, True, 0), (0.01, True, 0.01), (0.01, False, None)])
def test_heatmap_api_does_not_invent_point_zero_one(monkeypatch, cutoff, enabled, expected):
    monkeypatch.setattr(overview_api, "require_bu_dataset", lambda *a: {"extra_metadata": {"q_value_cutoff": cutoff}})
    captured = {}
    def fetch(*args, **kwargs):
        captured.update(kwargs)
        return BuRtMzHeatmapOut()
    monkeypatch.setattr(overview_api, "get_rt_mz_heatmap", fetch)
    overview_api.rt_mz("sample", q_filter=enabled, session=object())
    assert captured["q_max"] == expected
