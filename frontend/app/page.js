"use client";
import { memo, useEffect, useRef, useState } from "react";

const STATUS_LABEL = {
  idle: "Idle", connecting: "Connecting…", live: "Live", stopped: "Stopped",
  ended: "Stream ended", error: "Error",
};

// Isolated so the 2Hz status polling can never re-render / reload the live
// player. It only re-mounts when the src string actually changes.
const LivePlayer = memo(function LivePlayer({ src }) {
  return (
    <div className="preview">
      <iframe src={src} allow="autoplay; fullscreen" allowFullScreen title="live stream" />
    </div>
  );
});

export default function Home() {
  const [url, setUrl] = useState("");
  const [snap, setSnap] = useState(null);
  const [busy, setBusy] = useState(false);
  const [apiDown, setApiDown] = useState(false);
  const [liveSrc, setLiveSrc] = useState(null);   // sticky player src
  const [saved, setSaved] = useState({});
  const feedRef = useRef(null);

  async function poll() {
    try {
      const r = await fetch("/api/status");
      if (!r.ok) throw new Error("bad status");
      setSnap(await r.json());
      setApiDown(false);
    } catch {
      setApiDown(true);
    }
  }
  useEffect(() => {
    poll();
    const id = setInterval(poll, 500);
    return () => clearInterval(id);
  }, []);

  const running = snap?.running;
  const status = snap?.status || "idle";
  const st = snap?.state || {};
  const score = Math.round(st.score || 0);
  const thr = snap?.threshold || 42;

  // Keep the player mounted while a stream is active; only drop it on a real stop.
  useEffect(() => {
    if (running && snap?.embed?.src) {
      if (snap.embed.src !== liveSrc) setLiveSrc(snap.embed.src);
    } else if (!running && ["stopped", "idle", "ended", "error"].includes(status)) {
      if (liveSrc !== null) setLiveSrc(null);
    }
  }, [running, status, snap?.embed?.src, liveSrc]);

  async function start() {
    if (!url.trim()) return;
    setBusy(true);
    await fetch("/api/stream/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    setBusy(false); poll();
  }
  async function stop() { setBusy(true); await fetch("/api/stream/stop", { method: "POST" }); setBusy(false); poll(); }
  async function manual() { await fetch("/api/clip/manual", { method: "POST" }); poll(); }
  async function saveToPC(c) {
    const r = await fetch("/api/clip/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: c.file }),
    });
    const j = await r.json();
    setSaved((s) => ({ ...s, [c.id]: j.ok ? "saved" : "err" }));
  }

  const dotClass = status === "live" ? "live" : status === "error" ? "err"
    : status === "ended" ? "warn" : "";

  return (
    <div className="wrap">
      <div className="brand">
        <div className="logo">🎬</div>
        <div>
          <h1>ClipMind AI</h1>
          <div className="tag">Never miss a viral moment again.</div>
        </div>
      </div>

      {apiDown && (
        <div className="notice">
          ⚠️ <b>Engine not connected.</b> This is the ClipMind dashboard. The real-time
          capture engine (streamlink + ffmpeg) runs as a persistent backend — start it
          locally, or set <code>NEXT_PUBLIC_API</code> to your backend URL. Live clipping
          can’t run on serverless hosting.
        </div>
      )}

      <div className="bar">
        <input
          placeholder="Paste a Twitch / YouTube / Kick live URL…"
          value={url} onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !running && start()}
          disabled={running}
        />
        {!running ? (
          <button className="btn-go" onClick={start} disabled={busy || !url.trim()}>
            ▶ Start clipping
          </button>
        ) : (
          <>
            <button className="btn-ghost" onClick={manual}>✂ Clip now</button>
            <button className="btn-stop" onClick={stop} disabled={busy}>■ Stop</button>
          </>
        )}
      </div>

      {liveSrc && <LivePlayer src={liveSrc} />}
      {running && !snap?.embed?.src && (
        <div className="preview ph-box">Live preview unavailable for this URL — detection still running.</div>
      )}

      <div className="grid">
        {/* LEFT: live score + status */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="card">
            <div className="status-row">
              <span className={`dot ${dotClass}`} />
              <strong>{STATUS_LABEL[status] || status}</strong>
              {snap?.platform && <span className="pill">{snap.platform}</span>}
              {snap?.chat_connected && <span className="pill">💬 chat</span>}
            </div>
            {snap?.error && <div style={{ color: "var(--red)", fontSize: 12 }}>{snap.error}</div>}

            <div className="gauge">
              <div className="num">{score}</div>
              <div className="lbl">Live Viral Score</div>
            </div>
            <div className="track"><div style={{ width: `${Math.min(100, score)}%` }} /></div>
            <div className="thr">Clip fires at ≥ {thr}</div>

            <div className="sub">
              <div className="m"><div className="k">Audio energy</div><div className="v">{Math.round(st.audio || 0)}</div></div>
              <div className="m"><div className="k">Chat hype</div><div className="v">{Math.round(st.chat || 0)}</div></div>
              <div className="m"><div className="k">Chat msgs/s</div><div className="v">{(st.chat_rate || 0).toFixed(1)}</div></div>
              <div className="m"><div className="k">Loudness</div><div className="v">{st.loudness != null ? `${st.loudness}` : "—"}</div></div>
            </div>
          </div>

          <div className="card">
            <h3>Detection feed</h3>
            <div className="feed" ref={feedRef}>
              {(snap?.events || []).length === 0 && <div className="empty">No activity yet.</div>}
              {(snap?.events || []).map((e, i) => (
                <div className={`ev ${e.kind}`} key={i}>
                  <span className="t">{e.t}</span>
                  <span className="m">{e.msg}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT: clips */}
        <div className="card">
          <h3>Clips ({snap?.clips?.length || 0})</h3>
          {(!snap?.clips || snap.clips.length === 0) ? (
            <div className="empty">
              Detected highlights turn into vertical clips here.<br />
              Start a stream, or hit <b>Clip now</b> once it’s live to grab the last {45}s.
            </div>
          ) : (
            <div className="clips">
              {snap.clips.map((c) => (
                <div className="clip" key={c.id}>
                  <video src={`/clips/${c.file}`} poster={c.thumb ? `/clips/${c.thumb}` : undefined}
                    controls preload="metadata" />
                  <div className="meta">
                    <div className="title">{c.title}</div>
                    <div className="row">
                      <span className="score">🔥 {c.score}</span>
                      <span>{c.duration}s</span>
                    </div>
                    <div className="clipbtns">
                      <button className="mini" onClick={() => saveToPC(c)}>
                        {saved[c.id] === "saved" ? "✓ Saved" : saved[c.id] === "err" ? "Failed" : "💾 Save to PC"}
                      </button>
                      <a className="mini alt" href={`/clips/${c.file}`} download>⬇ Download</a>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="hint">
            Heuristic engine: audio-energy spikes + Twitch chat velocity/hype words.
            Clips run 15–60s — they auto-extend while the hype lasts — cropped to 9:16.
            <b> Save to PC</b> copies straight into your Downloads folder.
          </div>
        </div>
      </div>
    </div>
  );
}
