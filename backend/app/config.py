"""Runtime configuration and external-tool resolution for ClipMind AI."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# --- Directories -----------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]        # .../clipmind
DATA = ROOT / "data"
SEGMENTS = DATA / "segments"                        # rolling live buffer (.ts)
CLIPS = DATA / "clips"                              # finished vertical clips
LIVE = DATA / "live"                                # ad-free HLS preview feed
for d in (DATA, SEGMENTS, CLIPS, LIVE):
    d.mkdir(parents=True, exist_ok=True)


def _resolve(name: str, *candidates: str) -> str:
    """Return an absolute path to an executable, checking PATH then fallbacks."""
    found = shutil.which(name)
    if found:
        return found
    for c in candidates:
        if c and Path(c).exists():
            return c
    # last resort: bare name and hope PATH picks it up at call time
    return name


_APPDATA = os.environ.get("APPDATA", "")
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")

FFMPEG = _resolve(
    "ffmpeg",
    rf"{_LOCALAPPDATA}\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe",
    rf"{_LOCALAPPDATA}\Microsoft\WinGet\Links\ffmpeg.exe",
)
STREAMLINK = _resolve("streamlink", rf"{_APPDATA}\Python\Python314\Scripts\streamlink.exe")

# --- Tunables (overridable via env) ---------------------------------------
SEGMENT_SECONDS = 2                 # length of each rolling buffer segment
BUFFER_SECONDS = 220                # how much history to retain for pre-roll
# Chat/audio react AFTER the moment, so pre-roll must reach back to the buildup
# to START at the right time; post-roll lets the reaction land before we END.
PRE_ROLL = int(os.environ.get("CLIPMIND_PRE_ROLL", 18))    # secs before event
POST_ROLL = int(os.environ.get("CLIPMIND_POST_ROLL", 15))  # tail after hype ends
# viral score needed to *open* a highlight. Lowered so normal hype clips.
SCORE_THRESHOLD = float(os.environ.get("CLIPMIND_THRESHOLD", 42))
# once open, keep extending the clip while score stays above this
SUSTAIN_SCORE = float(os.environ.get("CLIPMIND_SUSTAIN", 24))
MIN_CLIP = int(os.environ.get("CLIPMIND_MIN_CLIP", 28))     # never shorter
MAX_CLIP = int(os.environ.get("CLIPMIND_MAX_CLIP", 90))     # never longer
MANUAL_CLIP = int(os.environ.get("CLIPMIND_MANUAL", 55))    # length of "Clip now"
CLIP_COOLDOWN = int(os.environ.get("CLIPMIND_COOLDOWN", 15))  # min secs between clips
DOWNLOADS = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"

# Vertical output
OUT_W, OUT_H = 1080, 1920
