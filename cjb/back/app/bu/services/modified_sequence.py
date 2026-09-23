"""Strict DIA-NN ``Modified.Sequence`` parsing backed by the local UniMod snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping
from xml.etree import ElementTree


_UNIMOD_NAMESPACE = "http://www.unimod.org/xmlns/schema/unimod_2"
_UNIMOD_TOKEN = re.compile(r"\((?i:unimod):(\d+)\)")
_DEFAULT_UNIMOD_XML = (
    Path(__file__).resolve().parents[3] / "third_party" / "unimod" / "unimod.xml"
)


class ModifiedSequenceError(ValueError):
    """Raised when a modified sequence cannot be annotated without guessing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedModifiedSequence:
    sequence: str
    residue_deltas: tuple[float, ...]
    n_terminal_delta: float = 0.0
    modification_count: int = 0

    @property
    def has_modifications(self) -> bool:
        return self.modification_count > 0

    def b_delta(self, position: int) -> float:
        return self.n_terminal_delta + sum(self.residue_deltas[:position])

    def y_delta(self, position: int) -> float:
        return sum(self.residue_deltas[-position:])


def _error(code: str, message: str) -> ModifiedSequenceError:
    return ModifiedSequenceError(code, message)


@lru_cache(maxsize=8)
def _load_unimod_masses_cached(
    xml_path: str,
    modified_time_ns: int,
    file_size: int,
) -> Mapping[str, float]:
    del modified_time_ns, file_size
    try:
        root = ElementTree.parse(xml_path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise _error(
            "unimod_mass_source_unavailable",
            f"Cannot read the local UniMod mass table: {xml_path}",
        ) from exc

    namespace = {"umod": _UNIMOD_NAMESPACE}
    masses: dict[str, float] = {}
    for modification in root.findall(".//umod:mod", namespace):
        record_id = modification.get("record_id")
        delta = modification.find("umod:delta", namespace)
        mono_mass = delta.get("mono_mass") if delta is not None else None
        if not record_id or mono_mass is None:
            continue
        try:
            normalised_record_id = str(int(record_id))
            parsed_mass = float(mono_mass)
        except ValueError:
            continue
        if math.isfinite(parsed_mass):
            masses[normalised_record_id] = parsed_mass
    if not masses:
        raise _error(
            "unimod_mass_source_unavailable",
            f"The local UniMod mass table contains no usable modifications: {xml_path}",
        )
    return MappingProxyType(masses)


def load_unimod_masses(xml_path: Path | None = None) -> Mapping[str, float]:
    """Load monoisotopic delta masses once per local snapshot revision."""
    resolved = (xml_path or _DEFAULT_UNIMOD_XML).resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise _error(
            "unimod_mass_source_unavailable",
            f"Cannot read the local UniMod mass table: {resolved}",
        ) from exc
    return _load_unimod_masses_cached(str(resolved), stat.st_mtime_ns, stat.st_size)


def _normalise_expected_sequence(sequence: str) -> str:
    expected = sequence.strip().upper()
    if not expected or any(not ("A" <= residue <= "Z") for residue in expected):
        raise _error(
            "stripped_sequence_invalid",
            "The stripped peptide sequence must contain amino-acid letters only.",
        )
    return expected


def _trim_dialect_markers(modified_sequence: str) -> str:
    text = modified_sequence.strip()
    if text.startswith("_"):
        text = text[1:]
    if text.endswith("_"):
        text = text[:-1]
    return text


def parse_modified_sequence(
    modified_sequence: str | None,
    *,
    expected_sequence: str,
    unimod_xml_path: Path | None = None,
) -> ParsedModifiedSequence:
    """Parse residue-local and leading N-terminal DIA-NN UniMod tokens.

    Unknown or malformed notation is rejected so it cannot silently produce
    scientifically incorrect unmodified fragment masses.
    """
    expected = _normalise_expected_sequence(expected_sequence)
    if modified_sequence is None or not modified_sequence.strip():
        return ParsedModifiedSequence(expected, (0.0,) * len(expected))

    text = _trim_dialect_markers(modified_sequence)
    if text == expected:
        return ParsedModifiedSequence(expected, (0.0,) * len(expected))

    unimod_masses: Mapping[str, float] | None = None

    def delta_for(token_match: re.Match[str]) -> float:
        nonlocal unimod_masses
        if unimod_masses is None:
            unimod_masses = load_unimod_masses(unimod_xml_path)
        record_id = str(int(token_match.group(1)))
        delta = unimod_masses.get(record_id)
        if delta is None:
            raise _error(
                "unimod_id_unknown",
                f"UniMod:{record_id} is not present in the local UniMod mass table.",
            )
        return delta

    cursor = 0
    n_terminal_delta = 0.0
    modification_count = 0
    while (token := _UNIMOD_TOKEN.match(text, cursor)) is not None:
        n_terminal_delta += delta_for(token)
        modification_count += 1
        cursor = token.end()

    residues: list[str] = []
    residue_deltas: list[float] = []
    while cursor < len(text):
        residue = text[cursor]
        if not ("A" <= residue <= "Z"):
            raise _error(
                "modified_sequence_invalid",
                f"Unsupported Modified.Sequence notation at character {cursor + 1}.",
            )
        residues.append(residue)
        residue_deltas.append(0.0)
        cursor += 1
        while (token := _UNIMOD_TOKEN.match(text, cursor)) is not None:
            residue_deltas[-1] += delta_for(token)
            modification_count += 1
            cursor = token.end()

    parsed_sequence = "".join(residues)
    if parsed_sequence != expected:
        raise _error(
            "modified_sequence_mismatch",
            "Modified.Sequence does not reconstruct to the stored stripped peptide sequence.",
        )
    return ParsedModifiedSequence(
        sequence=expected,
        residue_deltas=tuple(residue_deltas),
        n_terminal_delta=n_terminal_delta,
        modification_count=modification_count,
    )
