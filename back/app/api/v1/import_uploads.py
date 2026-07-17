"""HTTP API for managed local browser uploads."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.import_uploads import service
from app.import_uploads.errors import UploadError
from app.import_uploads.models import (
    ImportUploadCreateIn,
    ImportUploadCreatedOut,
    ImportUploadFileOut,
    ImportUploadSessionOut,
    ImportUploadStartIn,
)
from app.schemas.imports import ImportJobCreatedOut

router = APIRouter(tags=["import-uploads"])


def _http_error(exc: UploadError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("/import-uploads", response_model=ImportUploadCreatedOut, status_code=status.HTTP_201_CREATED)
def create_import_upload(body: ImportUploadCreateIn) -> ImportUploadCreatedOut:
    try:
        return service.create_upload(body.import_type)
    except UploadError as exc:
        raise _http_error(exc) from exc


@router.put("/import-uploads/{upload_id}/files", response_model=ImportUploadFileOut)
async def put_import_upload_file(
    upload_id: str,
    relative_path: str,
    request: Request,
) -> ImportUploadFileOut:
    try:
        return await service.upload_file(
            upload_id=upload_id,
            relative_path=relative_path,
            content_length_header=request.headers.get("content-length"),
            chunks=request.stream(),
        )
    except UploadError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/import-uploads/{upload_id}/start",
    response_model=ImportJobCreatedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_import_upload(upload_id: str, body: ImportUploadStartIn) -> ImportJobCreatedOut:
    try:
        return service.start_upload(upload_id, parameters=body.parameters)
    except UploadError as exc:
        raise _http_error(exc) from exc


@router.get("/import-uploads/{upload_id}", response_model=ImportUploadSessionOut)
def get_import_upload(upload_id: str) -> ImportUploadSessionOut:
    try:
        return service.get_upload(upload_id)
    except UploadError as exc:
        raise _http_error(exc) from exc


@router.delete("/import-uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import_upload(upload_id: str) -> Response:
    try:
        service.delete_upload(upload_id)
    except UploadError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
