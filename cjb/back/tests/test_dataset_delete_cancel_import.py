from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1 import datasets as datasets_api
from app.services import import_jobs


def test_delete_dataset_with_cancel_import_cancels_then_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[str] = []
    deleted: list[tuple[str, bool]] = []

    def fake_cancel(slug: str) -> int:
        cancelled.append(slug)
        return 1

    def fake_delete(slug: str, *, bypass_active_job_guard: bool = False) -> import_jobs.DeleteResult:
        deleted.append((slug, bypass_active_job_guard))
        return import_jobs.DeleteResult(
            deleted_db=True,
            deleted_disk=False,
            folder=None,
            folder_existed=False,
        )

    monkeypatch.setattr(import_jobs, "cancel_active_import_jobs_for_slug", fake_cancel)
    monkeypatch.setattr(import_jobs, "delete_dataset", fake_delete)

    out = datasets_api.delete_dataset("dia-shuju", cancel_import=True)

    assert cancelled == ["dia-shuju"]
    assert deleted == [("dia-shuju", True)]
    assert out.slug == "dia-shuju"
    assert out.deleted_db is True


def test_delete_dataset_without_cancel_import_keeps_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled: list[str] = []
    deleted: list[tuple[str, bool]] = []

    def fake_cancel(slug: str) -> int:
        cancelled.append(slug)
        return 0

    def fake_delete(slug: str, *, bypass_active_job_guard: bool = False) -> import_jobs.DeleteResult:
        deleted.append((slug, bypass_active_job_guard))
        return import_jobs.DeleteResult(
            deleted_db=True,
            deleted_disk=False,
            folder=None,
            folder_existed=False,
        )

    monkeypatch.setattr(import_jobs, "cancel_active_import_jobs_for_slug", fake_cancel)
    monkeypatch.setattr(import_jobs, "delete_dataset", fake_delete)

    out = datasets_api.delete_dataset("foo", cancel_import=False)

    assert cancelled == []
    assert deleted == [("foo", False)]
    assert out.slug == "foo"


def test_delete_dataset_maps_active_job_conflict_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_delete(slug: str, *, bypass_active_job_guard: bool = False) -> import_jobs.DeleteResult:
        raise RuntimeError("Refusing to delete: an import job for this slug is still queued or running.")

    monkeypatch.setattr(import_jobs, "delete_dataset", fake_delete)

    with pytest.raises(HTTPException) as exc_info:
        datasets_api.delete_dataset("foo", cancel_import=False)

    assert exc_info.value.status_code == 409
