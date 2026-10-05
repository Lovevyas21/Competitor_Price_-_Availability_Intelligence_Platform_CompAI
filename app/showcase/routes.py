from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.ai.chat import answer_question
from app.core.db import session_scope
from app.core.settings import Settings, get_settings
from app.showcase.pipeline import FETCH_LIMIT, STAGES, run_fetch, run_pipeline

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"

router = APIRouter(prefix="/showcase", tags=["showcase"])


def is_enabled(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    if s.showcase_enabled is not None:
        return s.showcase_enabled
    return s.env == "dev"


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def intro() -> FileResponse:
    return FileResponse(TEMPLATES / "intro.html")


@router.get("/run", include_in_schema=False)
def console() -> FileResponse:
    return FileResponse(TEMPLATES / "console.html")


def _sse(events: Iterator[dict]) -> Iterator[str]:
    for event in events:
        yield f"data: {json.dumps(event, default=str)}\n\n"


@router.get("/api/stream", include_in_schema=False)
def stream(stage: str | None = Query(default=None)) -> StreamingResponse:
    return StreamingResponse(
        _sse(run_pipeline(only=stage)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/fetch", include_in_schema=False)
def fetch(limit: int = Query(default=FETCH_LIMIT, ge=1, le=300)) -> StreamingResponse:
    return StreamingResponse(
        _sse(run_fetch(limit)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


DATASET_SQL = """
select pe.observed_at::date as observed_date,
       r.name               as retailer,
       coalesce(pv.title, p.external_id) as product,
       p.upc,
       pe.price,
       pe.currency,
       s.name               as source
from price_events pe
join products  p using (product_id)
join retailers r using (retailer_id)
join sources   s on s.source_id = p.source_id
left join product_versions pv on pv.product_id = p.product_id and pv.is_current
order by pe.observed_at desc
limit :limit
"""


@router.get("/api/dataset", include_in_schema=False)
def dataset(
    limit: int = Query(default=500, ge=1, le=10_000),
    download: bool = Query(default=False),
):
    with session_scope() as session:
        rows = [dict(r) for r in session.execute(text(DATASET_SQL), {"limit": limit}).mappings()]

    if not download:
        return JSONResponse({"count": len(rows), "rows": jsonable_encoder(rows)})

    def as_csv() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]) if rows else ["observed_date"])
        writer.writeheader()
        yield buffer.getvalue()
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow(row)
            yield buffer.getvalue()

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        as_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="price-observations-{stamp}.csv"'},
    )


class Question(BaseModel):
    question: str = Field(max_length=2000)


@router.post("/api/chat", include_in_schema=False)
def chat(payload: Question) -> dict:
    with session_scope() as session:
        return answer_question(session, payload.question).as_dict()


@router.get("/api/stages", include_in_schema=False)
def stages() -> list[dict]:
    return [{"id": s["id"], "title": s["title"], "subtitle": s["subtitle"]} for s in STAGES]


def mount(app) -> bool:
    if not is_enabled():
        return False
    app.mount("/showcase/static", StaticFiles(directory=STATIC), name="showcase-static")
    app.include_router(router)
    return True
