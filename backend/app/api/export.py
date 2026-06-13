"""Full per-user data Export API (ADR-0006).

``GET /api/export`` streams a ZIP archive of ALL the calling user's own data
(Sessions + Sets, imported Workouts + route points, Metric samples, activity
summaries, Programs + structure/provenance, PRs, custom Exercises, Gym Profile,
and Diary Entries when nutrition exists) as a JSON document plus one CSV per
record type. CONTEXT.md ("Export"): the data-ownership guarantee of a self-hosted
platform; the read-side mirror of the ingest API.

The response is a ``StreamingResponse`` fed by
:func:`app.services.export_archive.stream_export_zip`, which assembles the ZIP on
disk via server-side cursors (bounded memory — prod has ~6.6M health_records for
one user) and streams it back in byte chunks. Scoped entirely to
``get_current_user``: every underlying query filters by the caller's id, so an
Export can only ever contain the requester's own rows.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.export_archive import archive_filename, stream_export_zip

router = APIRouter()


@router.get("")
async def export_my_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Download a full archive (ZIP of JSON + CSVs) of the caller's own data."""
    filename = archive_filename(user)
    return StreamingResponse(
        stream_export_zip(db, user),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # The body is generated on the fly; make intermediaries not buffer it.
            "Cache-Control": "no-store",
        },
    )
