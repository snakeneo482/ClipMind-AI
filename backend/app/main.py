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
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .stream import SESSION
from .instagram import POSTER

app = FastAPI(title="ClipMind AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# --- live HLS preview (our own ad-free feed) ------------------------------
# Explicit no-cache manifest route MUST be registered before the /live mount
# so the player always revalidates the sliding playlist.
@app.get("/live/stream.m3u8")
def hls_manifest():
    m = config.LIVE / "stream.m3u8"
    if not m.exists():
        return Response(status_code=404)
    # Return the FULL playlist as 200 (never a 206 range) — a partial manifest
    # makes hls.js re-parse in a tight loop and stall.
    data = m.read_bytes()
    return Response(
        content=data, media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


app.mount("/live", StaticFiles(directory=str(config.LIVE)), name="live")
app.mount("/clips", StaticFiles(directory=str(config.CLIPS)), name="clips")


class StartReq(BaseModel):
    url: str


@app.on_event("startup")
def _restore_ig():
    try:
        POSTER.restore()
    except Exception:
        pass


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


# --- Instagram (private-login posting, review & approve) -------------------
class LoginReq(BaseModel):
    username: str
    password: str
    verification_code: str = ""


class PostReq(BaseModel):
    file: str
    caption: str


@app.get("/api/instagram/status")
def ig_status():
    return POSTER.status()


@app.post("/api/instagram/login")
def ig_login(req: LoginReq):
    return POSTER.login(req.username, req.password, req.verification_code)


@app.post("/api/instagram/logout")
def ig_logout():
    return POSTER.logout()


@app.post("/api/instagram/post")
def ig_post(req: PostReq):
    name = os.path.basename(req.file)
    clip = next((c for c in SESSION.clips if c["file"] == name), None)
    video = config.CLIPS / name
    thumb = config.CLIPS / clip["thumb"] if (clip and clip.get("thumb")) else None
    res = POSTER.post_reel(video, req.caption, thumb)
    if res.get("ok") and clip is not None:
        clip["posted"] = True
        clip["post_url"] = res.get("url")
        SESSION._log(f"📸 Posted to Instagram: {clip['title']}", "ok")
    return res


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
