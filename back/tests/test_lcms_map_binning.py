from __future__ import annotations

from app.lcms_map.binning import build_point_cloud
from app.lcms_map.contracts import SpectrumFrame


def test_lcms_binning_keeps_max_intensity_per_rt_mz_cell() -> None:
    frames = [
        SpectrumFrame(
            spec_id=1,
            scan=10,
            rt_seconds=1.0,
            ms_level=1,
            mz=[100.0, 100.1, 200.0],
            intensity=[5.0, 10.0, 1.0],
        ),
        SpectrumFrame(
            spec_id=2,
            scan=11,
            rt_seconds=2.0,
            ms_level=1,
            mz=[100.0, 300.0],
            intensity=[7.0, 20.0],
        ),
    ]

    cloud = build_point_cloud(frames, rt_bins=2, mz_bins=2, max_points=10)

    assert cloud.raw_point_count == 5
    assert cloud.filtered_point_count == 5
    assert cloud.binned_point_count <= 4
    assert cloud.returned_point_count == cloud.binned_point_count
    assert max(cloud.intensity) == 20.0
    assert 10.0 in cloud.intensity


def test_lcms_binning_applies_mz_window_and_point_limit() -> None:
    frames = [
        SpectrumFrame(
            spec_id=1,
            scan=10,
            rt_seconds=1.0,
            ms_level=1,
            mz=[90.0, 100.0, 110.0, 200.0],
            intensity=[1.0, 2.0, 3.0, 100.0],
        )
    ]

    cloud = build_point_cloud(
        frames,
        rt_bins=4,
        mz_bins=4,
        max_points=2,
        mz_min=95.0,
        mz_max=115.0,
    )

    assert cloud.raw_point_count == 4
    assert cloud.filtered_point_count == 2
    assert cloud.returned_point_count == 2
    assert cloud.mz == [100.0, 110.0]
    assert 200.0 not in cloud.mz
