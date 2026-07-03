"""Turn a slice of the rolling buffer into a finished vertical clip.

Given a time window, selects the buffered .ts segments covering it, concatenates
them, crops to 9:16, scales to 1080x1920, and burns a title/hook banner.
"""
from __future__ import annotations

import random
import subprocess
from datetime import datetime
from pathlib import Path

from . import config

SEG_FMT = "seg_%Y%m%d_%H%M%S.ts"

HOOKS = [
    "You won't believe what happened",
    "The whole chat lost it",
    "Craziest moment of the stream",
    "Wait for it...",
    "This actually just happened",
    "No way this was real",
]
TITLES = [
    "I Somehow Pulled This Off",
    "The Entire Lobby Lost It",
    "1 HP Miracle",
    "Chat Went Insane",
    "How Did This Happen",
    "Peak Streamer Moment",
]


def _seg_epoch(path: Path) -> float | None:
    try:
        return datetime.strptime(path.name, SEG_FMT).timestamp()
    except ValueError:
        return None


def segments_in_window(start: float, end: float) -> list[Path]:
    out = []
    for p in config.SEGMENTS.glob("seg_*.ts"):
        ts = _seg_epoch(p)
        # a segment starting at ts covers [ts, ts+SEGMENT_SECONDS]
        if ts is not None and ts + config.SEGMENT_SECONDS >= start and ts <= end:
            out.append((ts, p))
    out.sort(key=lambda t: t[0])
    return [p for _, p in out]


def _escape_drawtext(path: Path) -> str:
    # ffmpeg filter path escaping on Windows: C:\x -> C\:/x
    return str(path).replace("\\", "/").replace(":", "\\:")


def build_clip(start: float, end: float, score: float, clip_id: str) -> dict | None:
    # clamp total length to [MIN_CLIP, MAX_CLIP]
    dur = end - start
    if dur < config.MIN_CLIP:
        start = end - config.MIN_CLIP
    elif dur > config.MAX_CLIP:
        start = end - config.MAX_CLIP
    duration = int(round(end - start))
    segs = segments_in_window(start, end)
    if len(segs) < 2:
        return None

    work = config.CLIPS
    concat_list = work / f"{clip_id}.txt"
    concat_list.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8"
    )

    hook = random.choice(HOOKS)
    title = random.choice(TITLES)
    out_path = work / f"{clip_id}.mp4"
    thumb_path = work / f"{clip_id}.jpg"

    # write banner text to files to dodge filtergraph escaping
    hook_file = work / f"{clip_id}_hook.txt"
    hook_file.write_text(hook, encoding="utf-8")

    font = "C\\:/Windows/Fonts/arialbd.ttf"
    vf = (
        f"crop=ih*9/16:ih,scale={config.OUT_W}:{config.OUT_H},"
        f"drawtext=fontfile='{font}':textfile='{_escape_drawtext(hook_file)}':"
        f"fontcolor=white:fontsize=64:box=1:boxcolor=black@0.55:boxborderw=24:"
        f"x=(w-text_w)/2:y=140:enable='lt(t,4)'"
    )
    # some encoders re-time concat output from 0; trim from the front so the
    # clip starts where our window starts rather than at the first segment.
    seek = max(0.0, start - (_seg_epoch(segs[0]) or start))

    cmd = [
        config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{seek:.2f}",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_path.exists():
        return {"error": r.stderr.strip()[:400] or "ffmpeg failed"}

    # grab a thumbnail from ~2s in
    subprocess.run(
        [config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         "-ss", "2", "-i", str(out_path), "-frames:v", "1",
         "-vf", f"scale={config.OUT_W}:{config.OUT_H}", str(thumb_path)],
        capture_output=True,
    )

    # cleanup scratch
    for f in (concat_list, hook_file):
        f.unlink(missing_ok=True)

    return {
        "id": clip_id,
        "file": out_path.name,
        "thumb": thumb_path.name if thumb_path.exists() else None,
        "hook": hook,
        "title": title,
        "score": round(score, 1),
        "duration": duration,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
