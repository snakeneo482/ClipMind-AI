"""Live chat velocity reader.

Twitch is fully supported via anonymous IRC (justinfan). For YouTube/Kick the
reader degrades gracefully to "no chat signal" so audio-based detection still
works. Everything is exposed through a thread-safe rolling message counter.
"""
from __future__ import annotations

import re
import socket
import threading
import time
from collections import deque
from urllib.parse import urlparse

HYPE_WORDS = re.compile(
    r"\b(lol|lmao|lmfao|omg|wtf|pog|poggers|pogchamp|kekw|omegalul|ez|gg|"
    r"clutch|insane|no way|noway|holy|w|sheesh|letsgo|lets go|actual)\b",
    re.IGNORECASE,
)


def parse_twitch_channel(url: str) -> str | None:
    """Extract a twitch channel login from a URL or bare name."""
    if not url:
        return None
    u = url.strip()
    if "twitch.tv" not in u and "/" not in u and " " not in u:
        return u.lower().lstrip("#")
    host = urlparse(u if "://" in u else "https://" + u)
    if "twitch.tv" in (host.netloc or ""):
        parts = [p for p in host.path.split("/") if p]
        if parts:
            return parts[0].lower()
    return None


class ChatReader:
    """Rolling window of chat activity. `.stats()` returns (msgs_per_sec, hype)."""

    def __init__(self, url: str, window: float = 5.0):
        self.window = window
        self.channel = parse_twitch_channel(url)
        self._events: deque[tuple[float, int]] = deque()  # (ts, hype_weight)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self.channel:
            self._thread = threading.Thread(target=self._run_twitch, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -- data ---------------------------------------------------------------
    def _record(self, hype: int) -> None:
        with self._lock:
            self._events.append((time.time(), hype))

    def stats(self) -> tuple[float, float]:
        now = time.time()
        with self._lock:
            while self._events and now - self._events[0][0] > self.window:
                self._events.popleft()
            count = len(self._events)
            hype = sum(w for _, w in self._events)
        return count / self.window, hype / self.window

    # -- twitch irc ---------------------------------------------------------
    def _run_twitch(self) -> None:
        while not self._stop.is_set():
            try:
                sock = socket.socket()
                sock.settimeout(20)
                sock.connect(("irc.chat.twitch.tv", 6667))
                sock.send(b"PASS SCHMOOPIIE\r\n")
                sock.send(b"NICK justinfan12345\r\n")
                sock.send(f"JOIN #{self.channel}\r\n".encode())
                self.connected = True
                buf = ""
                while not self._stop.is_set():
                    try:
                        data = sock.recv(4096).decode("utf-8", "ignore")
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    buf += data
                    while "\r\n" in buf:
                        line, buf = buf.split("\r\n", 1)
                        if line.startswith("PING"):
                            sock.send(b"PONG :tmi.twitch.tv\r\n")
                        elif "PRIVMSG" in line:
                            msg = line.split("PRIVMSG", 1)[1]
                            hype = 1 + (2 if HYPE_WORDS.search(msg) else 0)
                            self._record(hype)
            except Exception:
                self.connected = False
                time.sleep(3)  # retry backoff
        self.connected = False
