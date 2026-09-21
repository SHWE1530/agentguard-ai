from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.routes import router
from backend.app import config
from backend.app.config import API_KEY, CORS_ORIGINS
from backend.app.database.db import init_db, session
from backend.app.services import auth, sandbox, simulator
from backend.app.services.events import hub

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sentinel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    hub.bind_loop(asyncio.get_running_loop())
    db = session()
    try:
        sandbox.ensure_baseline(db)
        simulator.ensure_all_agents(db)
    finally:
        db.close()
    log.info("Agent Sentinel ready. Docs at /docs%s", " (write endpoints require X-API-Key)" if API_KEY else "")
    yield


app = FastAPI(
    title="Agent Sentinel",
    description=("Detection, intervention and recovery layer for autonomous AI agents. All agent actions "
                 "in this system are SIMULATED inside a sandbox; no real file, service, database or "
                 "permission is ever modified."),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/config"}


@app.middleware("http")
async def security(request: Request, call_next):
    """1) signed-token auth + read-only viewer role  2) optional shared API key for scripts."""
    path = request.url.path
    if path.startswith("/api") and request.method != "OPTIONS":
        if config.AUTH_ENABLED and path not in PUBLIC_PATHS:
            header = request.headers.get("authorization", "")
            claims = auth.verify(header[7:]) if header.lower().startswith("bearer ") else None
            if claims is None:
                return JSONResponse(status_code=401, content={"error": "unauthorized",
                                                              "detail": "Sign in to continue."})
            if claims["role"] == "viewer" and request.method != "GET":
                return JSONResponse(status_code=403, content={
                    "error": "forbidden", "detail": "Your account is read-only (viewer). Sign in as an operator to act."})
            request.state.user = claims["user"]
        if API_KEY and request.method in ("POST", "PUT", "PATCH", "DELETE") and path not in PUBLIC_PATHS:
            if not hmac.compare_digest(request.headers.get("x-api-key", ""), API_KEY) and not config.AUTH_ENABLED:
                return JSONResponse(status_code=401, content={"error": "unauthorized",
                                                              "detail": "A valid X-API-Key header is required."})
    return await call_next(request)


app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Never leak a stack trace to the browser."""
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={
        "error": "internal_error",
        "detail": "The safety service hit an unexpected error. Check the backend logs for details."})


@app.get("/")
def root():
    return {"service": "Agent Sentinel", "notice": "Controlled safety simulation. No real systems are affected.",
            "docs": "/docs", "websocket": "/ws/events"}


@app.websocket("/ws/events")
async def events_socket(ws: WebSocket) -> None:
    if config.AUTH_ENABLED and auth.verify(ws.query_params.get("token", "")) is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    queue = hub.subscribe()
    try:
        await ws.send_json({"type": "connected", "data": {"history": hub.history[-40:]}, "timestamp": ""})
        while True:
            await ws.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - client vanished mid-send
        pass
    finally:
        hub.unsubscribe(queue)
