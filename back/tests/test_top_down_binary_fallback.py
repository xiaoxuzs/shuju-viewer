from __future__ import annotations

from typing import Any

from app.api.v1 import proteins, proteoforms, prsms
from app.zp_runtime import ZpAssetReadError


def _raise_unreadable(*_args: Any, **_kwargs: Any) -> None:
    raise ZpAssetReadError("binary_zp_unreadable")


def test_protein_payload_falls_back_when_top_down_extension_is_missing(
    monkeypatch,
) -> None:
    payload: dict[str, object] = {
        "sequence_id": 1,
        "sequence_name": "P12345",
        "prsm_number": 2,
    }
    monkeypatch.setattr(proteins, "get_binary_top_down_protein", _raise_unreadable)

    assert proteins._binary_protein_payload(None, 40, payload) == payload  # type: ignore[arg-type]  # noqa: SLF001


def test_proteoform_payload_falls_back_when_top_down_extension_is_missing(
    monkeypatch,
) -> None:
    payload: dict[str, object] = {
        "proteoform_id": 7,
        "sequence_id": 1,
        "prsm_number": 2,
    }
    monkeypatch.setattr(proteoforms, "get_binary_top_down_proteoform", _raise_unreadable)

    assert proteoforms._binary_proteoform_payload(None, 40, payload) == payload  # type: ignore[arg-type]  # noqa: SLF001


def test_prsm_payload_falls_back_when_top_down_extension_is_missing(
    monkeypatch,
) -> None:
    payload: dict[str, object] = {
        "prsm_id": 9,
        "sequence_id": 1,
        "e_value": 0.01,
    }
    monkeypatch.setattr(prsms, "get_binary_top_down_prsm", _raise_unreadable)

    assert prsms._binary_prsm_list_payload(None, 40, payload) == payload  # type: ignore[arg-type]  # noqa: SLF001
