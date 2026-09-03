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

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.core.settings import Settings, get_settings
from app.showcase.pipeline import STAGES, run_pipeline

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
