"""ClipMind AI backend — FastAPI.

Endpoints:
    POST /api/stream/start   {url}     start ingest + detection
    POST /api/stream/stop               stop everything
    GET  /api/status                    full live snapshot (poll ~2Hz)
    POST /api/clip/manual               force a clip now (test / manual grab)
    GET  /clips/<file>                  serve finished mp4 / thumbnail
"""
from __future__ import annotations

import os
import shutil
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .stream import SESSION

app = FastAPI(title="ClipMind AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
app.mount("/clips", StaticFiles(directory=str(config.CLIPS)), name="clips")


class StartReq(BaseModel):
    url: str


@app.get("/api/health")
def health():
    return {"ok": True, "ffmpeg": config.FFMPEG, "streamlink": config.STREAMLINK}


@app.post("/api/stream/start")
def start(req: StartReq):
    return SESSION.start(req.url.strip())


@app.post("/api/stream/stop")
def stop():
    return SESSION.stop()


@app.get("/api/status")
def status():
    return SESSION.snapshot()


@app.post("/api/clip/manual")
def manual_clip():
    """Grab the last MANUAL_CLIP seconds right now, regardless of score."""
    if not SESSION.running:
        return {"ok": False, "error": "No stream running"}
    now = time.time()
    SESSION._finalize_clip(now - config.MANUAL_CLIP, now, SESSION.state.get("score", 0))
    return {"ok": True}


class SaveReq(BaseModel):
    file: str


@app.post("/api/clip/save")
def save_clip(req: SaveReq):
    """Copy a finished clip into the user's Downloads folder (local use)."""
    name = os.path.basename(req.file)
    src = config.CLIPS / name
    if not src.exists() or src.suffix != ".mp4":
        return {"ok": False, "error": "Clip not found"}
    dest = config.DOWNLOADS / name
    try:
        config.DOWNLOADS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return {"ok": True, "path": str(dest)}
    except Exception as e:  # noqa
        return {"ok": False, "error": str(e)}
