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
- **Auto-clipping**: opens a highlight when the score crosses the threshold and
  **auto-extends while the hype lasts** — clips run a dynamic **15–60s**, cropped
  to 1080×1920 with a burned-in AI hook/title banner + thumbnail.
- **Dashboard**: live player embed, viral-score gauge, sub-scores, detection feed,
  clip grid with inline playback, **Save to PC** (copies into your Downloads
  folder) and Download. Plus a **Clip now** manual grab (last 45s).

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
`CLIPMIND_THRESHOLD` (42, opens a highlight) · `CLIPMIND_SUSTAIN` (24, keeps it
open) · `CLIPMIND_MIN_CLIP` (15) · `CLIPMIND_MAX_CLIP` (60) · `CLIPMIND_PRE_ROLL`
(10) · `CLIPMIND_MANUAL` (45) · `CLIPMIND_COOLDOWN` (15).
Output lands in `clipmind/data/clips`; **Save to PC** copies to `~/Downloads`.

## Requirements
Python 3.11+, Node 18+, `ffmpeg`, `streamlink` (installed automatically if you
used the setup path). Twitch chat needs no auth (anonymous IRC).

## Source-only publication

This repository is shared as source code for learning and reference. No hosted demo or active deployment is provided. Some features require third-party services and your own configuration; API availability is not guaranteed. AI tools assisted development. Review and test the code before using it in production.

## License and dependencies

Original project code is licensed under MIT (see LICENSE). Third-party libraries, bundled code and assets retain their original licenses and notices; the root license does not relicense those materials.
