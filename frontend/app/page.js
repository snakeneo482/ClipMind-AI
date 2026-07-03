"use client";
import { memo, useEffect, useRef, useState } from "react";
import Hls from "hls.js";

const STATUS_LABEL = {
  idle: "Idle", connecting: "Connecting…", live: "Live", stopped: "Stopped",
  ended: "Stream ended", error: "Error",
};

// Plays OUR captured, ad-free HLS feed (never Twitch's player), so their
// "commercial break in progress" overlay can't appear. Memoized + no props so
// the 2Hz status poll can never re-mount or interrupt it.
const LivePlayer = memo(function LivePlayer() {
  const ref = useRef(null);
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const src = "/live/stream.m3u8";
    let hls;
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src; // native HLS (Safari)
    } else if (Hls.isSupported()) {
      hls = new Hls({
        liveSyncDurationCount: 3,
        manifestLoadingMaxRetry: 30,
        manifestLoadingRetryDelay: 1000,
        levelLoadingMaxRetry: 30,
      });
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, (_e, data) => {
        // stream not up yet / transient — keep retrying instead of dying
        if (data.fatal) {
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR) setTimeout(() => hls.startLoad(), 1500);
          else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
        }
      });
    }
    return () => { if (hls) hls.destroy(); };
  }, []);
  return (
    <div className="preview">
      <video ref={ref} autoPlay muted controls playsInline />
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

  // Instagram
  const [ig, setIg] = useState({ logged_in: false });
  const [creds, setCreds] = useState({ username: "", password: "", verification_code: "" });
  const [needsCode, setNeedsCode] = useState(false);
  const [igBusy, setIgBusy] = useState(false);
  const [igErr, setIgErr] = useState("");
  const [caps, setCaps] = useState({});      // clipId -> edited caption
  const [posting, setPosting] = useState({}); // clipId -> "posting"|"done"|"err"

  async function igStatus() {
    try { const r = await fetch("/api/instagram/status"); setIg(await r.json()); } catch {}
  }
  useEffect(() => { igStatus(); }, []);

  async function igLogin() {
    setIgBusy(true); setIgErr("");
    const r = await fetch("/api/instagram/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(creds),
    });
    const j = await r.json();
    setIgBusy(false);
    if (j.ok) { setNeedsCode(false); setCreds({ username: "", password: "", verification_code: "" }); igStatus(); }
    else { setIgErr(j.error || "Login failed"); if (j.needs_code) setNeedsCode(true); }
  }
  async function igLogout() { await fetch("/api/instagram/logout", { method: "POST" }); igStatus(); }

  async function postClip(c) {
    setPosting((p) => ({ ...p, [c.id]: "posting" }));
    const caption = caps[c.id] ?? c.caption ?? "";
    const r = await fetch("/api/instagram/post", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: c.file, caption }),
    });
    const j = await r.json();
    setPosting((p) => ({ ...p, [c.id]: j.ok ? "done" : "err" }));
    if (!j.ok) alert("Instagram post failed:\n" + (j.error || "unknown error"));
  }

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
    if (running) {
      if (!liveSrc) setLiveSrc("on");
    } else if (["stopped", "idle", "ended", "error"].includes(status)) {
      if (liveSrc) setLiveSrc(null);
    }
  }, [running, status, liveSrc]);

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

      {liveSrc && <LivePlayer />}
      {liveSrc && (
        <div className="feedhint">
          Ad-free preview from ClipMind’s own capture (~10–20s behind live) — no Twitch ad breaks.
        </div>
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

          <div className="card">
            <h3>📸 Instagram</h3>
            {ig.logged_in ? (
              <div>
                <div style={{ fontSize: 14, marginBottom: 10 }}>
                  Connected as <b>@{ig.username}</b> <span className="dot live" style={{ display: "inline-block" }} />
                </div>
                <button className="btn-ghost" onClick={igLogout} style={{ width: "100%" }}>Disconnect</button>
              </div>
            ) : (
              <div className="iglogin">
                <input placeholder="Instagram username" value={creds.username}
                  onChange={(e) => setCreds({ ...creds, username: e.target.value })} />
                <input placeholder="Password" type="password" value={creds.password}
                  onChange={(e) => setCreds({ ...creds, password: e.target.value })} />
                {needsCode && (
                  <input placeholder="2FA / verification code" value={creds.verification_code}
                    onChange={(e) => setCreds({ ...creds, verification_code: e.target.value })} />
                )}
                <button className="btn-go" onClick={igLogin}
                  disabled={igBusy || !creds.username || !creds.password} style={{ width: "100%" }}>
                  {igBusy ? "Connecting…" : "Connect Instagram"}
                </button>
                {igErr && <div style={{ color: "var(--red)", fontSize: 12 }}>{igErr}</div>}
                <div className="igwarn">Use a dedicated clip account — this is Instagram’s private API.</div>
              </div>
            )}
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

                    <details className="post" open={false}>
                      <summary>📸 Post to Instagram</summary>
                      <textarea
                        className="capbox"
                        value={caps[c.id] ?? c.caption ?? ""}
                        onChange={(e) => setCaps((m) => ({ ...m, [c.id]: e.target.value }))}
                        rows={6}
                      />
                      {c.posted || posting[c.id] === "done" ? (
                        <a className="mini" style={{ display: "block" }}
                          href={c.post_url || "#"} target="_blank" rel="noreferrer">✓ Posted — view</a>
                      ) : (
                        <button className="mini"
                          disabled={!ig.logged_in || posting[c.id] === "posting"}
                          onClick={() => postClip(c)} style={{ width: "100%" }}>
                          {posting[c.id] === "posting" ? "Posting…"
                            : !ig.logged_in ? "Connect Instagram first" : "Post this clip"}
                        </button>
                      )}
                    </details>
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
