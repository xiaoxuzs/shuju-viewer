"""Read TopPIC PrSM XML metadata for PFMB Form B assembly."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToppicXmlPrsmRecord:
    prsm_id: int
    spectrum_id: int
    spectrum_scan: int
    adjusted_prec_mass: float | None
    ori_prec_mass: float | None
    frac_feature_inte: float | None
    p_value: float | None
    e_value: float | None
    fdr: float | None
    match_peak_num: float | None
    match_fragment_num: float | None
    sequence_name: str
    sequence_description: str
    proteoform_id: int | None
    sequence_id: int | None
    start_pos: int | None
    end_pos: int | None
    annotated_seq: str
    n_acetylation: bool


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _float(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def load_toppic_prsm_records(prsm_xml: Path) -> list[ToppicXmlPrsmRecord]:
    """Parse ``*_toppic_prsm.xml`` into ordered records (index == list position)."""
    root = ET.parse(prsm_xml).getroot()
    records: list[ToppicXmlPrsmRecord] = []
    for prsm in root.findall("prsm"):
        proteoform = prsm.find("proteoform")
        fasta = proteoform.find("fasta_seq") if proteoform is not None else None
        prot_mod = proteoform.find("prot_mod") if proteoform is not None else None
        extreme = prsm.find("extreme_value")
        seq_name = _text(fasta.find("seq_name")) if fasta is not None else ""
        seq_desc = _text(fasta.find("seq_desc")) if fasta is not None else ""
        mod_name = _text(prot_mod.find("name")) if prot_mod is not None else ""
        records.append(
            ToppicXmlPrsmRecord(
                prsm_id=_int(_text(prsm.find("prsm_id"))) or len(records),
                spectrum_id=_int(_text(prsm.find("spectrum_id"))) or 0,
                spectrum_scan=_int(_text(prsm.find("spectrum_scan"))) or 0,
                adjusted_prec_mass=_float(_text(prsm.find("adjusted_prec_mass"))),
                ori_prec_mass=_float(_text(prsm.find("ori_prec_mass"))),
                frac_feature_inte=_float(_text(prsm.find("frac_feature_inte"))),
                p_value=_float(_text(extreme.find("p_value"))) if extreme is not None else None,
                e_value=_float(_text(extreme.find("e_value"))) if extreme is not None else None,
                fdr=_float(_text(prsm.find("fdr"))),
                match_peak_num=_float(_text(prsm.find("match_peak_num"))),
                match_fragment_num=_float(_text(prsm.find("match_fragment_num"))),
                sequence_name=seq_name,
                sequence_description=seq_desc,
                proteoform_id=_int(_text(proteoform.find("proteo_cluster_id"))) if proteoform is not None else None,
                sequence_id=_int(_text(proteoform.find("prot_id"))) if proteoform is not None else None,
                start_pos=_int(_text(proteoform.find("start_pos"))) if proteoform is not None else None,
                end_pos=_int(_text(proteoform.find("end_pos"))) if proteoform is not None else None,
                annotated_seq=_text(proteoform.find("proteo_match_seq")) if proteoform is not None else "",
                n_acetylation=mod_name.upper() == "NME",
            )
        )
    if not records:
        raise ValueError(f"no <prsm> entries found in {prsm_xml}")
    return records
