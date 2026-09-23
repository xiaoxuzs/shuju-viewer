"""用于自下而上（Bottom-Up）质谱数据的轻量级 b/y 离子理论碎片匹配工具"""

from __future__ import annotations

from dataclasses import dataclass

from pyteomics import mass

from app.bu.services.modified_sequence import parse_modified_sequence
from app.schemas import BuMatchedIon


@dataclass(frozen=True)
class _TheoIon:
    ion_type: str
    position: int
    charge: int
    mz: float


def _strip_sequence(sequence: str) -> str:
    return "".join(ch for ch in sequence.upper() if "A" <= ch <= "Z")


def _theoretical_ions(
    sequence: str,
    modified_sequence: str | None = None,
) -> list[_TheoIon]:
    # 使用纯氨基酸序列作为校验基准，并将 Modified.Sequence 解析为 N 端和各残基的 UniMod 质量偏移。
    stripped = _strip_sequence(sequence)
    modifications = parse_modified_sequence(
        modified_sequence,
        expected_sequence=stripped,
    )
    ions: list[_TheoIon] = []
    # 对每个肽键切点分别构造 N 端 b 离子和 C 端 y 离子，只累加碎片实际覆盖的修饰位点。
    for pos in range(1, len(stripped)):
        prefix = stripped[:pos]
        suffix = stripped[-pos:]
        b_delta = modifications.b_delta(pos)
        y_delta = modifications.y_delta(pos)
        # UniMod 记录的是中性质量变化，换算为 m/z 偏移时需要除以离子电荷数。
        for charge in (1, 2):
            ions.append(
                _TheoIon(
                    ion_type="b",
                    position=pos,
                    charge=charge,
                    mz=float(mass.fast_mass(prefix, ion_type="b", charge=charge))
                    + b_delta / charge,
                )
            )
            ions.append(
                _TheoIon(
                    ion_type="y",
                    position=pos,
                    charge=charge,
                    mz=float(mass.fast_mass(suffix, ion_type="y", charge=charge))
                    + y_delta / charge,
                )
            )
    return ions


def match_by_ions(
    *,
    sequence: str,
    modified_sequence: str | None = None,
    mz: list[float],
    intensity: list[float],
    ppm: float,
) -> list[BuMatchedIon]:
    """针对每个理论 b/y 离子，返回一个最佳实验峰。"""
    if not sequence:
        return []

    theoretical_ions = _theoretical_ions(sequence, modified_sequence)
    if not mz or not intensity:
        return []

    used_peak_indexes: set[int] = set()
    matches: list[BuMatchedIon] = []
    peak_pairs = list(enumerate(zip(mz, intensity, strict=False)))
    for ion in theoretical_ions:
        tolerance = ion.mz * ppm * 1e-6
        candidates: list[tuple[float, float, int, float]] = []
        for idx, (exp_mz, exp_intensity) in peak_pairs:
            if idx in used_peak_indexes:
                continue
            delta = abs(float(exp_mz) - ion.mz)
            if delta <= tolerance:
                candidates.append((float(exp_intensity), delta, idx, float(exp_mz)))
        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[0], item[1]))
        exp_intensity, _delta, idx, exp_mz = candidates[0]
        used_peak_indexes.add(idx)
        matches.append(
            BuMatchedIon(
                ion_type=ion.ion_type,  # type: ignore[arg-type]
                position=ion.position,
                charge=ion.charge,
                theo_mz=ion.mz,
                exp_mz=exp_mz,
                ppm=(exp_mz - ion.mz) / ion.mz * 1e6,
                intensity=exp_intensity,
            )
        )
    return matches
