"""Heuristic highlight detector.

Combines two live signals into a 0-100 "viral score":
  * Audio energy spike  — momentary loudness (LUFS) above a rolling baseline.
  * Chat velocity spike — messages/sec and hype-word density above baseline.

No ML/training required. Baselines adapt with an exponential moving average so
the detector self-calibrates to each stream's normal level.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class Detector:
    audio_weight: float = 0.55
    chat_weight: float = 0.45
    ema_alpha: float = 0.02          # baseline adaptation speed

    # adaptive baselines
    loud_baseline: float | None = None   # LUFS (negative; louder = closer to 0)
    chat_baseline: float = 0.5           # msgs/sec
    _last: dict = field(default_factory=dict)

    def update(self, loudness_lufs: float | None, chat_rate: float, chat_hype: float) -> dict:
        """Fold in one tick of signals and return the current scored state."""
        # --- audio -------------------------------------------------------
        audio_score = 0.0
        if loudness_lufs is not None and loudness_lufs > -70:  # -70 == silence
            if self.loud_baseline is None:
                self.loud_baseline = loudness_lufs
            delta = loudness_lufs - self.loud_baseline   # positive = louder spike
            # ~ +8 dB over baseline saturates the score (more sensitive)
            audio_score = _clamp(delta / 8.0 * 100.0)
            self.loud_baseline += self.ema_alpha * (loudness_lufs - self.loud_baseline)

        # --- chat --------------------------------------------------------
        # ratio of current rate to baseline; 3x baseline -> ~100
        ratio = chat_rate / max(self.chat_baseline, 0.2)
        chat_score = _clamp((ratio - 1.0) / 1.3 * 100.0)   # 2.3x baseline -> ~100
        chat_score = _clamp(chat_score + chat_hype * 12.0)  # hype words boost
        self.chat_baseline += self.ema_alpha * (chat_rate - self.chat_baseline)

        final = self.audio_weight * audio_score + self.chat_weight * chat_score
        self._last = {
            "ts": time.time(),
            "score": round(final, 1),
            "audio": round(audio_score, 1),
            "chat": round(chat_score, 1),
            "chat_rate": round(chat_rate, 2),
            "loudness": round(loudness_lufs, 1) if loudness_lufs is not None else None,
        }
        return self._last
