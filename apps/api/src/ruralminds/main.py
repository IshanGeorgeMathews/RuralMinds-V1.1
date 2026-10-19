from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from . import api_admin, api_student, api_teacher
from .answer import AnswerQueue
from .auth import LoginThrottle
from .config import settings
from .db import connect, init_schema
from .ingest import load_books, sync_manifest_chapters
from .revision_worker import RevisionWorker
from .uploads import JobRunner


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.db = connect(settings.db_path)
    init_schema(app.state.db)
    if settings.books_file.exists():
        sync_manifest_chapters(app.state.db, load_books(settings.books_file))
    app.state.http = httpx.AsyncClient()
    app.state.queue = AnswerQueue(settings.llm_parallel, settings.max_queue, settings.max_wait_s)
    app.state.asking = {}  # session-token hash -> start time of its question in flight
    app.state.tasks = set()  # background answers for teachers' revision questions
    app.state.answering = set()  # revision question ids being answered right now
    app.state.last_ask = 0.0  # time.monotonic() of the last question from a phone
    app.state.revision = RevisionWorker(app.state) if settings.revision_worker else None
    if app.state.revision is not None:
        app.state.revision.start()
    app.state.throttle = LoginThrottle(
        settings.login_max_failures, settings.login_window_minutes * 60
    )
    app.state.jobs = JobRunner(app.state.db)
    app.state.jobs.start()  # resumes uploads interrupted by a power cut, cleans orphans
    yield
    await app.state.jobs.stop()
    if app.state.revision is not None:
        await app.state.revision.stop()
    await app.state.http.aclose()
    app.state.db.close()


app = FastAPI(title="RuralMinds API", version="0.2.0", lifespan=lifespan)
app.include_router(api_student.router)
app.include_router(api_teacher.router)
app.include_router(api_admin.router)


@app.middleware("http")
async def json_posts_only(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """A web page on another site can submit a plain form to us, but not a JSON request
    (the browser would ask permission first). Together with the SameSite cookie this
    blocks cross-site requests made in a signed-in teacher's or admin's name."""
    if request.method == "POST" and request.url.path.startswith("/api/"):
        content_type = request.headers.get("content-type", "")
        has_body = request.headers.get("content-length", "0") != "0"
        if has_body and not content_type.startswith("application/json"):
            return JSONResponse({"detail": "request.json_required"}, status_code=415)
    return await call_next(request)


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "ruralminds-api"}


@app.get("/generate_204", tags=["operations"], status_code=204)
async def generate_204() -> Response:
    """Android checks this URL to decide whether Wi-Fi "has internet"; answering keeps the
    phone on the school network instead of switching to mobile data."""
    return Response(status_code=204)


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str) -> Response:
    """The built SvelteKit app. Unknown paths get index.html so client-side routes work."""
    root = settings.frontend_dir.resolve()
    candidate = (root / path).resolve()
    if path and candidate.is_file() and candidate.is_relative_to(root):
        immutable = path.startswith("_app/immutable/")
        cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return FileResponse(candidate, headers={"Cache-Control": cache})
    if path.startswith(("api/", "_app/")):  # a missing script must 404, not return a page
        return JSONResponse({"detail": "not_found"}, status_code=404)
    index = root / "index.html"
    if not index.is_file():
        return JSONResponse({"detail": "frontend.not_built"}, status_code=404)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
