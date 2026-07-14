from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core import config


def _set_safe_test_environment(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    data_root = root / "data"
    data_root.mkdir(exist_ok=True)
    monkeypatch.setenv("VIEWER_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{(root / 'test.sqlite').as_posix()}")
    monkeypatch.setenv("DATA_ROOT", str(data_root))


def test_test_mode_requires_explicit_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_safe_test_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("DATABASE_URL")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        config.load_settings()


def test_test_mode_requires_explicit_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_safe_test_environment(monkeypatch, tmp_path)
    monkeypatch.delenv("DATA_ROOT")

    with pytest.raises(RuntimeError, match="DATA_ROOT"):
        config.load_settings()


def test_test_mode_rejects_universal_viewer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_safe_test_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/Universal_Viewer",
    )

    with pytest.raises(RuntimeError, match="Universal_Viewer"):
        config.load_settings()


def test_test_mode_does_not_read_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_backend = tmp_path / "backend"
    fake_backend.mkdir()
    (fake_backend / ".env").write_text(
        "DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/Universal_Viewer\n"
        "DATA_ROOT=../production-data\n",
        encoding="utf-8",
    )
    _set_safe_test_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "BACKEND_ROOT", fake_backend)

    loaded = config.load_settings()

    assert loaded.database_url.endswith("/test.sqlite")
    assert loaded.data_root == (tmp_path / "data").resolve()


def test_normal_mode_still_reads_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_backend = tmp_path / "backend"
    fake_backend.mkdir()
    expected_data_root = tmp_path / "normal-data"
    (fake_backend / ".env").write_text(
        "DATABASE_URL=postgresql+psycopg://viewer:secret@db.example/viewer_normal\n"
        "DATA_ROOT=../normal-data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIEWER_ENV", "development")
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("DATA_ROOT")
    monkeypatch.setattr(config, "BACKEND_ROOT", fake_backend)

    loaded = config.load_settings()

    assert loaded.database_url.endswith("/viewer_normal")
    assert loaded.resolved_data_root == expected_data_root.resolve()


def test_test_data_root_uses_resolved_path_boundary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    allowed_temp = tmp_path / "allowed"
    prefix_sibling = tmp_path / "allowed-sibling"
    allowed_temp.mkdir()
    prefix_sibling.mkdir()
    data_root = prefix_sibling / "data"
    data_root.mkdir()
    monkeypatch.setenv("VIEWER_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{(allowed_temp / 'test.sqlite').as_posix()}")
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setattr(config.tempfile, "gettempdir", lambda: str(allowed_temp))

    with pytest.raises(RuntimeError, match="system temporary directory"):
        config.load_settings()


def test_test_data_root_rejects_symlink_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    allowed_temp = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed_temp.mkdir()
    outside.mkdir()
    symlink = allowed_temp / "linked-data"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    monkeypatch.setenv("VIEWER_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{(allowed_temp / 'test.sqlite').as_posix()}")
    monkeypatch.setenv("DATA_ROOT", str(symlink))
    monkeypatch.setattr(config.tempfile, "gettempdir", lambda: str(allowed_temp))

    with pytest.raises(RuntimeError, match="system temporary directory"):
        config.load_settings()


@pytest.mark.skipif(os.name != "nt", reason="Windows path comparison semantics")
def test_test_data_root_boundary_is_case_insensitive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    allowed_temp = tmp_path / "CaseSensitiveName"
    data_root = allowed_temp / "Data"
    data_root.mkdir(parents=True)
    monkeypatch.setenv("VIEWER_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{(allowed_temp / 'test.sqlite').as_posix()}")
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setattr(config.tempfile, "gettempdir", lambda: str(allowed_temp).swapcase())

    loaded = config.load_settings()

    assert loaded.data_root == data_root.resolve()


def test_viewer_environment_is_separate_from_deployment_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIEWER_ENV", "test")
    monkeypatch.delenv("VIEWER_DEPLOYMENT_MODE", raising=False)

    assert config._viewer_environment() == "test"
    assert "VIEWER_DEPLOYMENT_MODE" not in os.environ
