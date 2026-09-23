import pytest

from app.bu.services.protein_detail_service import _protein_decoy_payload


@pytest.mark.parametrize("metadata,value,expected,state", [
    (None, False, False, "DIRECT"),
    ({"is_decoy_state": "MISSING"}, False, None, "MISSING"),
    ({"is_decoy_state": "AMBIGUOUS"}, False, None, "AMBIGUOUS"),
    ({"is_decoy_state": "DIRECT"}, True, True, "DIRECT"),
])
def test_protein_detail_decoy_metadata_does_not_call_an_undefined_helper(metadata, value, expected, state):
    original = {"is_decoy": value, "extra_metadata": metadata}
    result = _protein_decoy_payload(original)
    assert result["is_decoy"] is expected
    assert result["is_decoy_state"] == state
    assert "is_decoy_state" not in original
