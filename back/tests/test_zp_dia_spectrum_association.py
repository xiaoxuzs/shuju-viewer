from __future__ import annotations

from app.zp_runtime.package import ensure_binary_layer_importable


def test_dia_spectrum_association_allows_tiny_isolation_boundary_rounding() -> None:
    ensure_binary_layer_importable()
    from binary_layer.blocks import BlockCollection, ISOLATION_WINDOW_KIND, PrecursorBlock, SpectrumBlock
    from binary_layer.dia_spectrum_association import DiaSpectrumAssociator

    blocks = BlockCollection(
        spectra=[
            SpectrumBlock(
                spectrum_id="spectrum_1",
                run_id="run_1",
                ms_level=2,
                scan_number=101,
                native_id="controllerType=0 controllerNumber=1 scan=101",
                rt=60.0,
                precursor_id="precursor_1",
                mz_array_id="spectrum_1:mz",
                intensity_array_id="spectrum_1:intensity",
            )
        ],
        precursors=[
            PrecursorBlock(
                precursor_id="precursor_1",
                spectrum_id="spectrum_1",
                precursor_kind=ISOLATION_WINDOW_KIND,
                isolation_lower_mz=499.0,
                isolation_upper_mz=501.0,
            )
        ],
    )

    association = DiaSpectrumAssociator(blocks).associate(
        rt_minutes=1.0,
        precursor_mz=501.0005,
    )

    assert association.scan_number == 101
