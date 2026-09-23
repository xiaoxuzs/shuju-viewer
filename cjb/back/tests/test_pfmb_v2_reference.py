from __future__ import annotations

from pathlib import Path

import pytest

from app.pfmb.index_builder import count_pos_pkl_expansion, read_pfmb_record_count
from app.pfmb.reference_sidecar import find_reference_v2_sidecar, is_v2_sidecar_for_pos_pkl


HELAREF = Path(__file__).resolve().parents[2] / "Hela_DIA_v2_PFMB_delivery_20260629"
HELAPKL = Path(
    r"D:\job\Bottom-up DIA\dia-shuju\DIANN_2.0\DIANN_2.0"
    r"\20200110_Hela_500ng_DIA_25cm_120min_R1.mzML.pos.pkl"
)


@pytest.mark.skipif(not HELAREF.is_dir(), reason="Hela PFMB delivery not present")
@pytest.mark.skipif(not HELAPKL.is_file(), reason="Hela pos.pkl sample not present")
def test_hela_reference_matches_dia_shuju_pos_pkl() -> None:
    reference = find_reference_v2_sidecar(HELAPKL, [HELAREF])
    assert reference is not None
    assert is_v2_sidecar_for_pos_pkl(reference, HELAPKL)
    source_rows, expanded = count_pos_pkl_expansion(HELAPKL)
    assert source_rows == 110024
    assert expanded == 834455
    assert read_pfmb_record_count(reference / "results.pfmb") == expanded
