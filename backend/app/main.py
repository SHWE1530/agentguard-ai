from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.routes import router
from backend.app.config import CORS_ORIGINS
from backend.app.database.db import init_db, session
from backend.app.services import sandbox, simulator
from backend.app.services.events import hub

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sentinel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    hub.bind_loop(asyncio.get_running_loop())
    db = session()
    try:
        simulator.ensure_agent(db)
        sandbox.ensure_baseline(db)
    finally:
        db.close()
    log.info("Agent Sentinel ready. Docs at /docs")
    yield


app = FastAPI(
    title="Agent Sentinel",
    description=("Detection, intervention and recovery layer for autonomous AI agents. "
                 "All agent actions in this system are SIMULATED inside a sandbox; no real "
                 "file, service, database or permission is ever modified."),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Never leak a stack trace to the browser."""
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error",
                 "detail": "The safety service hit an unexpected error. "
                           "Check the backend logs for details."},
    )


@app.get("/")
def root():
    return {
        "service": "Agent Sentinel",
        "notice": "Controlled safety simulation. No real systems are affected.",
        "docs": "/docs",
        "websocket": "/ws/events",
    }


@app.websocket("/ws/events")
async def events_socket(ws: WebSocket) -> None:
    await ws.accept()
    queue = hub.subscribe()
    try:
        await ws.send_json({"type": "connected",
                            "data": {"history": hub.history[-40:]},
                            "timestamp": ""})
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - client vanished mid-send
        pass
    finally:
        hub.unsubscribe(queue)
