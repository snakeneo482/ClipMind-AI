"""Instagram posting via instagrapi (private API, user login).

Posts clips as Reels from local files (uses the thumbnail we already generate,
so no extra video deps). Session settings are cached to disk so we don't have to
re-login every run; the password is never persisted.

NOTE: this uses Instagram's private API. Use a dedicated/clip account; automated
posting can get accounts flagged. Login only happens when the user submits creds.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import config

_SESSION_FILE = config.DATA / "ig_session.json"


class InstagramPoster:
    def __init__(self):
        self._cl = None
        self._lock = threading.Lock()
        self.username: str | None = None
        self.logged_in = False
        self.last_error: str | None = None

    def _client(self):
        if self._cl is None:
            from instagrapi import Client  # lazy import (heavy)
            self._cl = Client()
            self._cl.delay_range = [1, 3]
        return self._cl

    def status(self) -> dict:
        return {"logged_in": self.logged_in, "username": self.username,
                "error": self.last_error}

    # -- auth ---------------------------------------------------------------
    def restore(self) -> bool:
        """Try to restore a cached session at startup (no password needed)."""
        if not _SESSION_FILE.exists():
            return False
        try:
            cl = self._client()
            cl.load_settings(_SESSION_FILE)
            cl.get_timeline_feed()  # validates the session
            self.username = cl.username or (cl.account_info().username if cl.user_id else None)
            self.logged_in = True
            return True
        except Exception as e:  # noqa
            self.last_error = f"session expired: {e}"
            self.logged_in = False
            return False

    def login(self, username: str, password: str, verification_code: str = "") -> dict:
        with self._lock:
            self.last_error = None
            try:
                cl = self._client()
                if _SESSION_FILE.exists():
                    try:
                        cl.load_settings(_SESSION_FILE)
                    except Exception:
                        pass
                cl.login(username, password,
                         verification_code=verification_code.strip() or "")
                cl.dump_settings(_SESSION_FILE)
                self.username = username
                self.logged_in = True
                return {"ok": True, "username": username}
            except Exception as e:  # noqa
                msg = str(e)
                self.logged_in = False
                self.last_error = msg
                needs_code = "two_factor" in msg.lower() or "verification" in msg.lower() \
                    or "challenge" in msg.lower()
                return {"ok": False, "error": msg, "needs_code": needs_code}

    def logout(self) -> dict:
        self.logged_in = False
        self.username = None
        try:
            _SESSION_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        self._cl = None
        return {"ok": True}

    # -- posting ------------------------------------------------------------
    def post_reel(self, video: Path, caption: str, thumbnail: Path | None) -> dict:
        if not self.logged_in:
            return {"ok": False, "error": "Not logged in to Instagram"}
        if not video.exists():
            return {"ok": False, "error": "Clip file not found"}
        with self._lock:
            try:
                cl = self._client()
                kwargs = {}
                if thumbnail and thumbnail.exists():
                    kwargs["thumbnail"] = thumbnail
                media = cl.clip_upload(video, caption, **kwargs)
                code = getattr(media, "code", None)
                return {"ok": True, "url": f"https://www.instagram.com/reel/{code}/" if code else None}
            except Exception as e:  # noqa
                return {"ok": False, "error": str(e)}


POSTER = InstagramPoster()
