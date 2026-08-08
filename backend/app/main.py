"""Speak, Don't Just Read v8 — FastAPI application factory.

Middleware: CORS (env ALLOWED_ORIGINS), security headers, request-id +
access log, in-memory 60 req/min/IP rate limit. Serves the built frontend
from app/static at / with SPA fallback to index.html (never crashes when
the static dir is empty).

v10 (2026-08-06): startup warns (never crashes) when a configured DeepSeek
model name was retired on 2026-07-24.

v11 M1 (2026-08-08): mounts the realtime speech-to-speech WebSocket router
(/api/realtime/ws, app/realtime/).
"""
import asyncio
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .config import get_settings, warn_on_retired_models
from .db.database import close_db, init_db
from .db.session_store import session_store
from .logging_config import setup_logging
from .routers import (
    auth,
    chat,
    health,
    history,
    languages,
    realtime,
    scenarios,
    stats,
    voices,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ── Lifespan ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting Speak, Don't Just Read v{}", __version__)
    warn_on_retired_models(settings)
    await init_db()
    session_store.start()
    yield
    await session_store.shutdown()
    await close_db()
    logger.info("Shutdown complete")


# ── App factory ──────────────────────────────────────────────────────

def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Speak, Don't Just Read",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
    )

    # ── Global error handler ──
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", "unknown")
        logger.exception("Unhandled error [{}]: {}", rid, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": rid},
        )

    # ── Request ID + access log ──
    class RequestIDMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            rid = uuid.uuid4().hex[:8]
            request.state.request_id = rid
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response

    class AccessLogMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start = time.time()
            response = await call_next(request)
            elapsed = (time.time() - start) * 1000
            logger.info(
                "{} {} -> {} ({}ms)",
                request.method, request.url.path, response.status_code, round(elapsed),
            )
            return response

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

    # ── Rate limiter (in-memory, per-IP sliding window) ──
    class RateLimiter:
        def __init__(self, max_req: int, window: int = 60):
            self.max_req = max_req
            self.window = window
            self._buckets: dict[str, list[float]] = defaultdict(list)
            self._lock = asyncio.Lock()

        async def allow(self, key: str) -> bool:
            now = time.time()
            cutoff = now - self.window
            async with self._lock:
                bucket = self._buckets[key]
                while bucket and bucket[0] < cutoff:
                    bucket.pop(0)
                if len(bucket) >= self.max_req:
                    return False
                bucket.append(now)
                return True

    limiter = RateLimiter(max_req=settings.rate_limit_per_minute)

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path.startswith("/api/"):
                client = request.headers.get(
                    "X-Forwarded-For",
                    request.client.host if request.client else "unknown",
                )
                if not await limiter.allow(client):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many requests", "retry_after": 60},
                    )
            return await call_next(request)

    # Registration order = outermost last (CORS wraps everything).
    application.add_middleware(RequestIDMiddleware)
    application.add_middleware(AccessLogMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
        expose_headers=["X-Request-ID"],
    )

    # ── Routers ──
    application.include_router(health.router, prefix="/api")
    application.include_router(languages.router, prefix="/api")
    application.include_router(scenarios.router, prefix="/api")
    application.include_router(voices.router, prefix="/api")
    application.include_router(auth.router, prefix="/api")
    application.include_router(chat.router, prefix="/api")
    application.include_router(realtime.router, prefix="/api")
    application.include_router(history.router, prefix="/api")
    application.include_router(stats.router, prefix="/api")

    # ── Static frontend with SPA fallback (after API routes) ──
    STATIC_DIR.mkdir(exist_ok=True)

    class SPAStaticFiles(StaticFiles):
        """StaticFiles that falls back to index.html for client-side routes.

        Safe when the directory is empty: unknown paths then yield a JSON 404
        instead of crashing.
        """

        async def get_response(self, path: str, scope):
            from starlette.exceptions import HTTPException as StarletteHTTPException

            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    index = STATIC_DIR / "index.html"
                    if index.is_file():
                        from fastapi.responses import FileResponse

                        return FileResponse(index)
                raise

    application.mount(
        "/",
        SPAStaticFiles(directory=str(STATIC_DIR), html=True, check_dir=False),
        name="frontend",
    )

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    setup_logging(settings.log_level)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment != "production",
    )
