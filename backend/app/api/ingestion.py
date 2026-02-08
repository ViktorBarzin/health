"""Data ingestion (upload) API routes."""

import asyncio
import uuid
import zipfile
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_current_user
from app.database import async_session, get_db
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.schemas.dashboard import ImportStatusResponse
from app.services.xml_parser import parse_health_export

router = APIRouter()

ALLOWED_EXTENSIONS = {".xml", ".zip"}


def _extract_xml_from_zip(zip_path: Path) -> Path:
    """Extract export.xml from an Apple Health ZIP archive."""
    extract_dir = zip_path.parent / zip_path.stem
    with zipfile.ZipFile(zip_path, "r") as zf:
        xml_candidates = [
            n for n in zf.namelist()
            if n.endswith("export.xml") or n.endswith("Export.xml")
        ]
        if not xml_candidates:
            xml_candidates = [n for n in zf.namelist() if n.endswith(".xml")]
        if not xml_candidates:
            raise ValueError("No XML file found in ZIP archive")
        zf.extractall(extract_dir)
    return extract_dir / xml_candidates[0]


def _run_parser_sync(file_path: str, user_id: int, batch_id: str) -> None:
    """Run the async XML parser from a sync background task context."""
    asyncio.run(parse_health_export(file_path, user_id, batch_id, async_session))


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_health_data(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept a health data export file (XML or ZIP) and begin processing."""
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {suffix}. Accepted: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    batch_id = uuid.uuid4()
    safe_filename = f"{batch_id}{suffix}"
    file_path = upload_dir / safe_filename

    content = await file.read()
    file_path.write_bytes(content)

    # If ZIP, extract the XML
    xml_path = file_path
    if suffix == ".zip":
        try:
            xml_path = _extract_xml_from_zip(file_path)
        except (zipfile.BadZipFile, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    batch = ImportBatch(
        id=batch_id,
        user_id=user.id,
        filename=file.filename,
        status="processing",
        record_count=0,
    )
    db.add(batch)
    await db.flush()

    background_tasks.add_task(
        _run_parser_sync, str(xml_path), user.id, str(batch_id)
    )

    return {"batch_id": str(batch_id), "status": "processing"}


@router.get("/upload/status/{batch_id}", response_model=ImportStatusResponse)
async def get_upload_status(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportStatusResponse:
    """Check the status of an import batch."""
    stmt = select(ImportBatch).where(
        ImportBatch.id == batch_id,
        ImportBatch.user_id == user.id,
    )
    result = await db.execute(stmt)
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found",
        )

    return ImportStatusResponse(
        batch_id=batch.id,
        status=batch.status,
        record_count=batch.record_count,
        filename=batch.filename,
        imported_at=batch.imported_at,
    )
