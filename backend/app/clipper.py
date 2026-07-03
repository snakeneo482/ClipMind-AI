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
from . import captions

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


def build_clip(start: float, end: float, score: float, clip_id: str,
               platform: str | None = None) -> dict | None:
    # pad the window a touch so we never clip the very start/end of the action
    start -= config.MIN_CLIP if (end - start) < config.MIN_CLIP else 0
    segs = segments_in_window(start, end)
    if len(segs) < 2:
        return None
    # Cut on whole-segment boundaries only -> always CONTINUOUS, never sliced
    # mid-action. Keep from the START of the window (the buildup + the trigger
    # come first, the reaction follows) so the clip STARTS at the right moment
    # and we trim only an over-long tail. Ensure at least MIN_CLIP.
    max_segs = max(1, round(config.MAX_CLIP / config.SEGMENT_SECONDS))
    min_segs = max(2, round(config.MIN_CLIP / config.SEGMENT_SECONDS))
    if len(segs) > max_segs:
        segs = segs[:max_segs]
    if len(segs) < min_segs:
        # too short — WIDEN the window back toward MAX to pull in more buffered
        # footage (falls short only if the buffer genuinely doesn't have it yet)
        wider = segments_in_window(end - config.MAX_CLIP, end)
        if len(wider) > len(segs):
            segs = wider[:max_segs]
    duration = len(segs) * config.SEGMENT_SECONDS

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
    W, H = config.OUT_W, config.OUT_H
    # Quality-first 9:16: scale the FULL frame DOWN to fit the width (sharp, no
    # upscaling) and center it over a blurred, zoomed copy of itself — instead
    # of cropping a narrow slice and upscaling it (which was the blurry look).
    fc = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},gblur=sigma=22[bgb];"
        f"[fg]scale={W}:-2:flags=lanczos[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,"
        f"drawtext=fontfile='{font}':textfile='{_escape_drawtext(hook_file)}':"
        f"fontcolor=white:fontsize=62:box=1:boxcolor=black@0.6:boxborderw=24:"
        f"x=(w-text_w)/2:y=210:enable='lt(t,4)'[v]"
    )
    # Re-encode the whole concatenated run — no -ss, no -t, so the FULL clip is
    # produced continuously. genpts + faststart keep timestamps monotonic and
    # make the mp4 stream/seek cleanly in the browser and on Instagram.
    cmd = [
        config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-fflags", "+genpts",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-movflags", "+faststart",
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

    cap = captions.generate(title, hook, platform, clip_id, score)
    return {
        "id": clip_id,
        "file": out_path.name,
        "thumb": thumb_path.name if thumb_path.exists() else None,
        "hook": hook,
        "title": title,
        "score": round(score, 1),
        "duration": duration,
        "caption": cap["caption"],
        "hashtags": cap["hashtags"],
        "posted": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
