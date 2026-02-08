"""Data ingestion (upload) API routes."""

import asyncio
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
from app.schemas.dashboard import ImportStatusResponse
from app.services.xml_parser import parse_health_export

router = APIRouter()

ALLOWED_EXTENSIONS = {".xml", ".zip"}
MAX_UPLOAD_SIZE = 4 * 1024 * 1024 * 1024  # 4 GB


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
    return extract_dir / xml_candidates[0]


def _run_parser_sync(file_path: str, user_id: int, batch_id: str, database_url: str) -> None:
    """Run the async XML parser in a fresh event loop with its own engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
            file_path.unlink(missing_ok=True)
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
    # 5. The batch itself
    await db.execute(delete(ImportBatch).where(ImportBatch.id == batch_id))

    await db.commit()
