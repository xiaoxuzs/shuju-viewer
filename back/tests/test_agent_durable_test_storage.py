import pytest
from app.agent_import.test_storage import create_test_storage, validate_test_storage, protect_secrets, unprotect_secrets


def test_new_test_storage_is_owned_explicit_and_not_an_arbitrary_data_path(tmp_path):
    root = tmp_path / "retained"
    token = create_test_storage(root)
    (root / "data").mkdir()
    assert validate_test_storage(root / "data", str(root), token)
    assert not validate_test_storage(root / "data", str(root), "0" * 32)
    assert not validate_test_storage(tmp_path, str(root), token)
    with pytest.raises(ValueError):
        create_test_storage(root)


def test_os_secret_store_is_encrypted_and_roundtrips_without_plaintext_fallback():
    import os
    if os.name != "nt":
        with pytest.raises(RuntimeError):
            protect_secrets({"value": "test-only"})
        return
    secret = {"password": "only-a-synthetic-test-secret", "purpose": "retained test database"}
    encrypted = protect_secrets(secret)
    assert secret["password"].encode() not in encrypted
    assert unprotect_secrets(encrypted) == secret
