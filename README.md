# ClipMind AI — MVP (live heuristic clipper)

Paste a **Twitch / YouTube Live / Kick** URL → it ingests the live stream, watches
**audio energy** + **chat velocity**, and auto-cuts **9:16 vertical clips** of the
spikes with a burned-in hook banner.

## What actually works (MVP scope)
- **Live ingest** via `streamlink` → `ffmpeg` rolling buffer (last ~150s kept).
- **Heuristic detection** (no ML training):
  - Audio: momentary loudness (EBU R128) vs. an adaptive baseline.
  - Chat: messages/sec + hype-word density (Twitch anonymous IRC). YouTube/Kick
    degrade gracefully to audio-only.
- **Auto-clipping**: on score ≥ threshold, cut `PRE_ROLL`s before → `POST_ROLL`s
  after, crop to 1080×1920, burn an AI hook/title banner, generate a thumbnail.
- **Dashboard**: live viral-score gauge, sub-scores, detection feed, clip grid
  with inline playback + download. Plus a **Clip now** manual grab button.

## Not yet (documented roadmap, per spec)
Facecam CV emotion, per-game event models, Whisper animated subtitles, auto-posting
to socials, the self-learning engagement model. The engine is structured so these
slot in as extra score layers / post-processing stages.

## Run
```
# 1. backend (FastAPI)  — port 8000
cd clipmind/backend
python -m uvicorn app.main:app --port 8000

# 2. frontend (Next.js) — port 3000
cd clipmind/frontend
npm install
npm run dev
```
Open http://localhost:3000, paste a live URL, press **Start clipping**.

## Tunables (env vars)
`CLIPMIND_THRESHOLD` (70) · `CLIPMIND_PRE_ROLL` (20) · `CLIPMIND_POST_ROLL` (15) ·
`CLIPMIND_COOLDOWN` (45). Output lands in `clipmind/data/clips`.

## Requirements
Python 3.11+, Node 18+, `ffmpeg`, `streamlink` (installed automatically if you
used the setup path). Twitch chat needs no auth (anonymous IRC).
