"""Serving layer for the showcase.

Three routes: an intro page, the console page, and the stream that feeds it.

The stream is Server-Sent Events rather than one JSON response, because the whole point
is that results appear as they are produced. A single response body would arrive complete
and the console would have nothing left to reveal.

**This blueprint is not mounted in production by default.** It reads real mart data and,
unlike `/products` and friends, carries no API key check -- a demo you have to
authenticate into is not much of a demo. So it follows `env`: on in dev, off in prod
unless `showcase_enabled=true` is set deliberately. See `is_enabled`.
"""

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
    """Whether the showcase should be served at all.

    Default is `env == "dev"`. The explicit flag is what a demo deployment sets when it
    genuinely wants an unauthenticated window onto the marts -- an opt-in, so it can
    never be the thing nobody noticed was public.
    """
    s = settings or get_settings()
    if s.showcase_enabled is not None:
        return s.showcase_enabled
    return s.env == "dev"


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def intro() -> FileResponse:
    return FileResponse(TEMPLATES / "intro.html")


@router.get("/run", include_in_schema=False)
def console() -> FileResponse:
    return FileResponse(TEMPLATES / "console.html")


# --------------------------------------------------------------------------- #
# stream
# --------------------------------------------------------------------------- #
def _sse(events: Iterator[dict]) -> Iterator[str]:
    """Frame events as SSE.

    `default=str` is doing real work here: prices are Decimal and dates are date, and
    neither is JSON-serialisable. Rendering the Decimal rather than casting to float
    also keeps 0.99 from arriving as 0.9899999999999999.
    """
    for event in events:
        yield f"data: {json.dumps(event, default=str)}\n\n"


@router.get("/api/stream", include_in_schema=False)
def stream(stage: str | None = Query(default=None)) -> StreamingResponse:
    """Run the pipeline, streaming each event as it is produced.

    `X-Accel-Buffering: no` and `Cache-Control: no-cache` matter: an intermediary that
    buffers this response would hold every event until the run finished and deliver the
    whole thing at once, which defeats the exercise.
    """
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
    """Pull fresh data from Open Prices, streaming progress as it goes.

    A GET so the browser's EventSource can drive it, which is a deliberate compromise:
    the call is not read-only, and normally that would be a POST. It is acceptable here
    only because the operation is idempotent in effect -- re-running it stores nothing
    new unless prices actually moved -- and because the showcase is dev-only.
    """
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
    """The collected observations, as JSON to display or CSV to keep.

    Streamed and capped rather than materialised whole: the table is partitioned and
    grows without limit, and an unbounded `select *` behind a browser button is how a
    demo takes the database down in front of an audience.
    """
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
    """Answer a question about the data, guarded the same way the brief is.

    A POST, unlike the streams above: it spends model allowance and it takes a body.
    """
    with session_scope() as session:
        return answer_question(session, payload.question).as_dict()


@router.get("/api/stages", include_in_schema=False)
def stages() -> list[dict]:
    """The stage list, so the intro page describes the real pipeline, not a copy of it."""
    return [{"id": s["id"], "title": s["title"], "subtitle": s["subtitle"]} for s in STAGES]


def mount(app) -> bool:
    """Attach the showcase to a FastAPI app. Returns whether it was mounted."""
    if not is_enabled():
        return False
    app.mount("/showcase/static", StaticFiles(directory=STATIC), name="showcase-static")
    app.include_router(router)
    return True
