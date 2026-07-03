"""Caption + hashtag generation for social posts (heuristic, no API key).

Builds an Instagram-Reels-friendly caption from a clip's title/hook plus a set
of platform-appropriate hashtags mixed from a general viral pool and a
game/stream pool. Deterministic-ish but varied per clip id.
"""
from __future__ import annotations

CTA = [
    "Follow for more 🎯", "Which moment was better? 👇", "Tag someone who needs to see this",
    "Sound on 🔊", "Wait for it… 😅", "Drop a 🔥 if you'd have done the same",
]

CORE_TAGS = [
    "#twitch", "#twitchclips", "#streamer", "#livestream", "#gaming", "#gamer",
    "#clips", "#viral", "#fyp", "#foryou", "#reels", "#reelsinstagram",
    "#gamingclips", "#twitchstreamer", "#funnymoments", "#highlights",
    "#gamingcommunity", "#stream", "#clipoftheday", "#trending",
]
HYPE_TAGS = [
    "#clutch", "#insane", "#nohit", "#rage", "#pog", "#w", "#gg", "#epicmoment",
    "#1v1", "#ranked", "#victory", "#comeback", "#unlucky", "#nowaythishappened",
]


def generate(title: str, hook: str, platform_name: str | None, clip_id: str,
             score: float | None = None) -> dict:
    seed = sum(ord(c) for c in clip_id)  # stable per clip
    cta = CTA[seed % len(CTA)]
    core = _rotate(CORE_TAGS, seed, 12)
    hype = _rotate(HYPE_TAGS, seed // 3, 6)
    game = f"#{(platform_name or 'twitch').lower()}"
    tags = _dedupe([game] + core + hype)[:20]

    line = title or hook or "Insane stream moment"
    caption = (
        f"{line} 🎬\n\n"
        f"{hook}\n\n"
        f"{cta}\n\n"
        + " ".join(tags)
    )
    return {"caption": caption, "hashtags": tags}


def _rotate(pool: list[str], seed: int, n: int) -> list[str]:
    i = seed % len(pool)
    return [pool[(i + k) % len(pool)] for k in range(n)]


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out
