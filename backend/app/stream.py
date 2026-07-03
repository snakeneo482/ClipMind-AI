"""Live stream session: ingest -> rolling buffer -> detect -> clip.

Pipeline:
    streamlink <url> best --stdout  |  ffmpeg -c copy -f segment  ->  seg_<ts>.ts

Loudness is measured *from the rolling segments* with a short `volumedetect`
pass every ~1.5s (robust and self-contained — no fragile long-lived stderr
parsing). A ticker thread folds loudness + chat stats through the Detector and
fires clips when the viral score crosses the threshold.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config
from .chat import ChatReader, parse_twitch_channel
from .clipper import build_clip
from .detector import Detector

_MV_RE = re.compile(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB")
_CREATE_NO_WINDOW = 0x08000000  # keep spawned ffmpeg consoles hidden on Windows


def _measure_loudness(seg: Path) -> float | None:
    """Return mean volume (dBFS) of a segment, or None on failure."""
    try:
        r = subprocess.run(
            [config.FFMPEG, "-hide_banner", "-nostats", "-i", str(seg),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
        m = _MV_RE.search(r.stderr)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def _embed_info(url: str) -> dict | None:
    """Build an embeddable player URL for the dashboard preview."""
    u = url.strip()
    low = u.lower()
    if "twitch.tv" in low:
        ch = parse_twitch_channel(u)
        if ch:
            return {"type": "twitch",
                    "src": f"https://player.twitch.tv/?channel={ch}&parent=localhost&muted=true"}
    if "youtube" in low or "youtu.be" in low:
        parsed = urlparse(u if "://" in u else "https://" + u)
        vid = None
        if "youtu.be" in parsed.netloc:
            vid = parsed.path.lstrip("/")
        else:
            vid = (parse_qs(parsed.query).get("v") or [None])[0]
            if not vid and "/live/" in parsed.path:
                vid = parsed.path.split("/live/")[-1]
        if vid:
            return {"type": "youtube",
                    "src": f"https://www.youtube.com/embed/{vid}?autoplay=1&mute=1"}
    if "kick.com" in low:
        parsed = urlparse(u if "://" in u else "https://" + u)
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            return {"type": "kick", "src": f"https://player.kick.com/{parts[0]}"}
    return None


class StreamSession:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.url: str | None = None
        self.platform: str | None = None
        self.embed: dict | None = None
        self.running = False
        self.status = "idle"
        self.error: str | None = None
        self.started_at: float | None = None
        self.detector = Detector()
        self.chat: ChatReader | None = None
        self._loudness: float | None = None
        self._loud_ts = 0.0
        self._last_seg_ts = 0.0
        self.state = {"score": 0, "audio": 0, "chat": 0, "chat_rate": 0, "loudness": None}
        self.events: deque = deque(maxlen=60)
        self.clips: list[dict] = []
        self._last_clip_ts = 0.0
        # open-highlight tracking for dynamic 15-60s clips
        self._hl_start = 0.0
        self._hl_last_hot = 0.0
        self._hl_peak = 0.0
        self._in_hl = False
        self._procs: list[subprocess.Popen] = []
        self._stop = threading.Event()

    # -- public api ---------------------------------------------------------
    def start(self, url: str) -> dict:
        with self.lock:
            if self.running:
                return {"ok": False, "error": "A stream is already running. Stop it first."}
            self.reset()
            # clear any stale segments from a previous run so end-detection
            # and clip windows only ever see fresh footage
            for p in config.SEGMENTS.glob("seg_*.ts"):
                try:
                    p.unlink()
                except OSError:
                    pass
            self.url = url
            self.platform = self._detect_platform(url)
            self.embed = _embed_info(url)
            self._stop.clear()
            self.running = True
            self.status = "connecting"
            self.started_at = time.time()

        self.chat = ChatReader(url)
        self.chat.start()
        threading.Thread(target=self._run, daemon=True).start()
        self._log(f"Starting capture for {self.platform} stream")
        return {"ok": True}

    def stop(self) -> dict:
        self._stop.set()
        if self.chat:
            self.chat.stop()
        for p in self._procs:
            try:
                p.terminate()
            except Exception:
                pass
        self.running = False
        self.status = "stopped"
        self._log("Stream stopped")
        return {"ok": True}

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "status": self.status,
            "error": self.error,
            "url": self.url,
            "platform": self.platform,
            "embed": self.embed,
            "uptime": int(time.time() - self.started_at) if self.started_at else 0,
            "chat_connected": bool(self.chat and self.chat.connected),
            "threshold": config.SCORE_THRESHOLD,
            "state": self.state,
            "events": list(self.events),
            "clips": self.clips[:50],
        }

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _detect_platform(url: str) -> str:
        u = url.lower()
        if "twitch" in u:
            return "Twitch"
        if "youtube" in u or "youtu.be" in u:
            return "YouTube"
        if "kick" in u:
            return "Kick"
        return "Stream"

    def _log(self, msg: str, kind: str = "info"):
        self.events.appendleft(
            {"t": datetime.now().strftime("%H:%M:%S"), "kind": kind, "msg": msg}
        )

    def _run(self):
        # NOTE: we intentionally do NOT pass --twitch-disable-ads. Ad-blocking on
        # anonymous Twitch sessions makes the feed stall on an "ad break" filler
        # segment. Letting ads play through keeps the stream flowing (they just
        # get captured like any other footage).
        sl_cmd = [
            config.STREAMLINK, "--stdout", "--hls-live-edge", "2",
            "--retry-open", "3", "--retry-streams", "5", self.url, "best",
        ]
        ff_cmd = [
            config.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            # NOTE: no -reset_timestamps — segments must keep continuous PTS so
            # concatenating them yields one seamless, non-glitchy clip.
            "-map", "0", "-c", "copy", "-f", "segment",
            "-segment_time", str(config.SEGMENT_SECONDS), "-strftime", "1",
            str(config.SEGMENTS / "seg_%Y%m%d_%H%M%S.ts"),
        ]
        try:
            sl = subprocess.Popen(sl_cmd, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
            ff = subprocess.Popen(ff_cmd, stdin=sl.stdout, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW)
            sl.stdout.close()
            self._procs = [sl, ff]
        except Exception as e:  # noqa
            self.error = f"Failed to launch capture: {e}"
            self.status = "error"
            self.running = False
            self._log(self.error, "error")
            return

        threading.Thread(target=self._loudness_sampler, daemon=True).start()
        threading.Thread(target=self._janitor, daemon=True).start()
        self._tick_loop()

    def _newest_segment(self, min_age: float = 1.2) -> Path | None:
        now = time.time()
        best, best_mt = None, 0.0
        for p in config.SEGMENTS.glob("seg_*.ts"):
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if mt > best_mt and now - mt >= min_age:
                best, best_mt = p, mt
        if best is not None:
            self._last_seg_ts = best_mt
        return best

    def _loudness_sampler(self):
        last: Path | None = None
        first = True
        while not self._stop.is_set() and self.running:
            seg = self._newest_segment()
            if seg is not None:
                if first:
                    self.status = "live"
                    self._log("Live — analyzing audio + chat", "ok")
                    first = False
                if seg != last:
                    last = seg
                    mv = _measure_loudness(seg)
                    if mv is not None:
                        self._loudness = mv
                        self._loud_ts = time.time()
            # end detection: no fresh segments for a while
            if not first and time.time() - self._last_seg_ts > 25:
                self._log("Stream input ended", "warn")
                self.status = "ended"
                self.running = False
                break
            self._stop.wait(1.5)

    def _janitor(self):
        while not self._stop.is_set():
            cutoff = time.time() - config.BUFFER_SECONDS
            for p in config.SEGMENTS.glob("seg_*.ts"):
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink(missing_ok=True)
                except OSError:
                    pass
            self._stop.wait(5)

    def _tick_loop(self):
        while not self._stop.is_set() and self.running:
            loud = self._loudness if (time.time() - self._loud_ts) < 6 else None
            rate, hype = self.chat.stats() if self.chat else (0.0, 0.0)
            st = self.detector.update(loud, rate, hype)
            st["chat_connected"] = bool(self.chat and self.chat.connected)
            self.state = st
            self._update_highlight(st["score"])
            self._stop.wait(0.5)

    def _update_highlight(self, score: float):
        """Open a highlight on a spike, extend it while hot, then finalize into
        a 15-60s clip once the hype fades or the max length is hit."""
        now = time.time()
        if not self._in_hl:
            if score >= config.SCORE_THRESHOLD and now - self._last_clip_ts >= config.CLIP_COOLDOWN:
                self._in_hl = True
                self._hl_start = now
                self._hl_last_hot = now
                self._hl_peak = score
                self._log(f"🔥 Highlight building — score {score:.0f}…", "clip")
            return

        # inside an open highlight
        self._hl_peak = max(self._hl_peak, score)
        if score >= config.SUSTAIN_SCORE:
            self._hl_last_hot = now

        length = now - self._hl_start + config.PRE_ROLL + config.POST_ROLL
        faded = now - self._hl_last_hot > 3.0
        maxed = length >= config.MAX_CLIP
        if faded or maxed:
            start = self._hl_start - config.PRE_ROLL
            end = self._hl_last_hot + config.POST_ROLL
            peak = self._hl_peak
            self._in_hl = False
            self._last_clip_ts = now
            self._finalize_clip(start, end, peak)

    def _finalize_clip(self, start: float, end: float, score: float):
        clip_id = datetime.fromtimestamp(end).strftime("clip_%Y%m%d_%H%M%S")
        self._log(f"✂ Cutting clip — peak score {score:.0f}…", "clip")

        def _worker():
            # wait until the tail footage (POST_ROLL past the end) is buffered
            wait = max(0.0, (end + config.POST_ROLL + 2) - time.time())
            self._stop.wait(wait)
            if self._stop.is_set():
                return
            result = build_clip(start, end, score, clip_id, self.platform)
            if not result:
                self._log("Clip skipped — not enough buffered footage", "warn")
            elif result.get("error"):
                self._log(f"Clip failed: {result['error'][:120]}", "error")
            else:
                self.clips.insert(0, result)
                self._log(f"✅ Clip ready: {result['title']}", "ok")

        threading.Thread(target=_worker, daemon=True).start()


SESSION = StreamSession()
