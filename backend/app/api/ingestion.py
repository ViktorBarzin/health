"""Data ingestion (upload) API routes."""

import asyncio
import logging
import uuid
import zipfile
from pathlib import Path

import aiofiles
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.models.workout import Workout
from app.models.workout_route_point import WorkoutRoutePoint
from app.models.health_record import HealthRecord
from app.models.category_record import CategoryRecord
from app.models.activity_summary import ActivitySummary
from app.schemas.dashboard import ImportStatusResponse
from app.services.xml_parser import parse_health_export

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {".xml", ".zip"}
MAX_UPLOAD_SIZE = 4 * 1024 * 1024 * 1024  # 4 GB


def _validate_xml_complete(xml_path: Path) -> None:
    """Check that the XML file ends with a proper closing tag.

    Apple Health exports can be truncated if the phone runs out of space
    or the export is interrupted.  A truncated file will be missing the
    ``</HealthData>`` closing tag.
    """
    tail_bytes = min(1024, xml_path.stat().st_size)
    with open(xml_path, "rb") as f:
        f.seek(-tail_bytes, 2)
        tail = f.read().decode("utf-8", errors="replace")
    if "</HealthData>" not in tail:
        raise ValueError(
            "The export.xml file appears truncated (missing </HealthData> "
            "closing tag). Please re-export from the Apple Health app and "
            "ensure the export completes fully before uploading."
        )


def _extract_xml_from_zip(zip_path: Path) -> Path:
    """Extract export.xml from an Apple Health ZIP archive."""
    extract_dir = zip_path.parent / zip_path.stem
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Validate against path traversal (zip slip)
        resolved_base = extract_dir.resolve()
        for member in zf.namelist():
            target = (extract_dir / member).resolve()
            if not str(target).startswith(str(resolved_base)):
                raise ValueError("Zip contains path traversal entry")

        xml_candidates = [
            n for n in zf.namelist()
            if n.endswith("export.xml") or n.endswith("Export.xml")
        ]
        if not xml_candidates:
            xml_candidates = [n for n in zf.namelist() if n.endswith(".xml")]
        if not xml_candidates:
            raise ValueError("No XML file found in ZIP archive")
        zf.extractall(extract_dir)

    xml_path = extract_dir / xml_candidates[0]
    _validate_xml_complete(xml_path)
    return xml_path


def _run_parser_sync(file_path: str, user_id: int, batch_id: str, database_url: str) -> None:
    """Run the async XML parser in a fresh event loop with its own engine."""
    import logging as _logging
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    # Ensure app loggers are visible (background thread may not inherit config)
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    engine = create_async_engine(
        database_url, echo=False,
        pool_size=8, max_overflow=4,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _run() -> None:
        try:
            await parse_health_export(file_path, user_id, batch_id, session_factory)
        finally:
            await engine.dispose()

    asyncio.run(_run())


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

    # Stream file to disk in chunks to avoid loading entire file into memory
    total_size = 0
    async with aiofiles.open(file_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):  # 1 MB chunks
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE:
                await out.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024 * 1024)} GB",
                )
            await out.write(chunk)

    # If ZIP, extract the XML
    xml_path = file_path
    if suffix == ".zip":
        try:
            xml_path = await asyncio.to_thread(_extract_xml_from_zip, file_path)
        except (zipfile.BadZipFile, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
    else:
        # Validate standalone XML upload
        try:
            await asyncio.to_thread(_validate_xml_complete, file_path)
        except ValueError as e:
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
    await db.commit()

    background_tasks.add_task(
        _run_parser_sync, str(xml_path), user.id, str(batch_id), settings.DATABASE_URL
    )

    return {"batch_id": str(batch_id), "status": "processing"}


@router.get("/uploads", response_model=list[ImportStatusResponse])
async def list_uploads(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ImportStatusResponse]:
    """List all import batches for the current user."""
    stmt = (
        select(ImportBatch)
        .where(ImportBatch.user_id == user.id)
        .order_by(ImportBatch.imported_at.desc())
    )
    result = await db.execute(stmt)
    batches = result.scalars().all()
    return [
        ImportStatusResponse(
            batch_id=b.id,
            status=b.status,
            record_count=b.record_count,
            filename=b.filename,
            imported_at=b.imported_at,
            error_count=b.error_count,
            skipped_count=b.skipped_count,
            error_messages=b.error_messages,
        )
        for b in batches
    ]


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
        error_count=batch.error_count,
        skipped_count=batch.skipped_count,
        error_messages=batch.error_messages,
    )


@router.post("/upload/{batch_id}/cancel")
async def cancel_import_batch(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request cancellation of a running import."""
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

    if batch.status != "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only processing imports can be cancelled",
        )

    await db.execute(
        update(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .values(status="cancelling")
    )
    await db.commit()

    return {"status": "cancelling"}


@router.delete("/upload/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import_batch(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an import batch and all associated records."""
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

    if batch.status in ("processing", "cancelling"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a batch that is currently processing",
        )

    # Delete in FK-safe order
    # 1. Route points (via workout IDs belonging to this batch)
    workout_ids_stmt = select(Workout.id).where(Workout.batch_id == batch_id)
    await db.execute(
        delete(WorkoutRoutePoint).where(
            WorkoutRoutePoint.workout_id.in_(workout_ids_stmt)
        )
    )
    # 2. Workouts
    await db.execute(delete(Workout).where(Workout.batch_id == batch_id))
    # 3. Health records
    await db.execute(delete(HealthRecord).where(HealthRecord.batch_id == batch_id))
    # 4. Category records
    await db.execute(delete(CategoryRecord).where(CategoryRecord.batch_id == batch_id))
    # 5. Activity summaries (no batch_id FK — delete by user + date range overlap)
    # Activity summaries don't have batch_id, so we skip them in batch delete.
    # They'll be deduped on re-import via ON CONFLICT DO NOTHING.
    # 6. The batch itself
    await db.execute(delete(ImportBatch).where(ImportBatch.id == batch_id))

    await db.commit()


@router.post("/upload/{batch_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_import_batch(
    batch_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-process an import from its stored ZIP/XML file.

    Deletes all records from the batch and re-runs the parser against the
    original file, which is still stored on disk.
    """
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

    if batch.status in ("processing", "cancelling"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reprocess a batch that is currently processing",
        )

    upload_dir = Path(settings.UPLOAD_DIR)

    # Find the stored XML file
    extract_dir = upload_dir / str(batch_id)
    xml_candidates = list(extract_dir.rglob("export.xml")) + list(
        extract_dir.rglob("Export.xml")
    )

    # Also check for ZIP file that could be re-extracted
    zip_path = upload_dir / f"{batch_id}.zip"
    if not xml_candidates and zip_path.exists():
        try:
            xml_path = await asyncio.to_thread(_extract_xml_from_zip, zip_path)
            xml_candidates = [xml_path]
        except (zipfile.BadZipFile, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Stored ZIP is invalid: {e}",
            )

    if not xml_candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No stored export file found for this batch. "
                   "The original file may have been cleaned up.",
        )

    xml_path = xml_candidates[0]

    # Validate the XML is complete
    try:
        await asyncio.to_thread(_validate_xml_complete, xml_path)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Delete existing records for this batch
    workout_ids_stmt = select(Workout.id).where(Workout.batch_id == batch_id)
    await db.execute(
        delete(WorkoutRoutePoint).where(
            WorkoutRoutePoint.workout_id.in_(workout_ids_stmt)
        )
    )
    await db.execute(delete(Workout).where(Workout.batch_id == batch_id))
    await db.execute(delete(HealthRecord).where(HealthRecord.batch_id == batch_id))
    await db.execute(delete(CategoryRecord).where(CategoryRecord.batch_id == batch_id))

    # Reset batch status
    await db.execute(
        update(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .values(status="processing", record_count=0, error_count=0, skipped_count=0, error_messages=None)
    )
    await db.commit()

    background_tasks.add_task(
        _run_parser_sync, str(xml_path), user.id, str(batch_id), settings.DATABASE_URL
    )

    return {"batch_id": str(batch_id), "status": "reprocessing"}
