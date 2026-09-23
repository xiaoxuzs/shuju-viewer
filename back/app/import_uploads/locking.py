"""OS-held per-upload lock; released even when the owning process crashes."""

from contextlib import contextmanager
from functools import wraps

from app.import_uploads.errors import UploadError
from app.import_uploads.paths import canonical_upload_id, upload_root, _is_link_or_junction


@contextmanager
def upload_lock(upload_id: str):
    safe_id = canonical_upload_id(upload_id)
    directory = upload_root(create=False) / ".locks"
    directory.mkdir(exist_ok=True)
    if _is_link_or_junction(directory):
        raise UploadError("UPLOAD_INVALID_PATH", "Unsafe upload lock directory", 409)
    path = directory / f"{safe_id}.lock"
    if path.exists() and _is_link_or_junction(path):
        raise UploadError("UPLOAD_INVALID_PATH", "Unsafe upload lock", 409)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        import os
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise UploadError("UPLOAD_BUSY", "This upload is being changed by another request", 409) from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def locked_upload(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        with upload_lock(kwargs["upload_id"]):
            return await function(*args, **kwargs)
    return wrapped


def locked_session(function):
    @wraps(function)
    def wrapped(upload_id, *args, **kwargs):
        with upload_lock(upload_id):
            return function(upload_id, *args, **kwargs)
    return wrapped
