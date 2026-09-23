"""Explicit durable test delivery ownership; never grants production access."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import uuid


def create_test_storage(root: Path) -> str:
    root = root.absolute()
    if root.exists():
        raise ValueError("Test delivery storage must be a new directory")
    if root.parent.resolve() != root.parent.absolute():
        raise ValueError("Linked test storage parents are forbidden")
    root.mkdir(parents=True)
    identity = uuid.uuid4().hex
    (root / "test-storage.json").write_text(json.dumps({"kind": "viewer-managed-test-delivery", "version": 1, "identity": identity,
        "retention": "retain source, ZP, database, code snapshot, oracle, evidence and handover until explicit operator removal"}), encoding="utf-8")
    return identity


def validate_test_storage(data_root: Path, owner_root: str, identity: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        return False
    root = Path(owner_root).absolute()
    if root == root.parent or not root.is_dir():
        return False
    for path in (root, *root.parents, data_root):
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            return False
    record = json.loads((root / "test-storage.json").read_text(encoding="utf-8"))
    return record.get("kind") == "viewer-managed-test-delivery" and record.get("version") == 1 and record.get("identity") == identity and data_root.resolve() == (root / "data").resolve()


def protect_secrets(value: dict) -> bytes:
    return _crypt(json.dumps(value).encode("utf-8"), decrypt=False)


def unprotect_secrets(value: bytes) -> dict:
    return json.loads(_crypt(value, decrypt=True))


def _crypt(value: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Durable test runtime needs an OS credential store; plaintext fallback is forbidden")
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), "Viewer isolated test runtime", None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise OSError("OS credential protection failed")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(result.data)
