"""Per-provider rate limiting, in one place instead of scattered sleep calls."""

import threading
import time


class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            elapsed = time.time() - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.time()


# Documented or polite limits per provider
_LIMITERS = {
    "musicbrainz": RateLimiter(1.1),    # 1 req/s official
    "discogs": RateLimiter(1.05),       # 60 req/min authenticated
    "acoustid": RateLimiter(0.34),      # 3 req/s
    "lastfm": RateLimiter(0.25),        # ~5 req/s tolerated
    "fanarttv": RateLimiter(0.5),       # polite
    "itunes": RateLimiter(3.0),         # ~20 req/min unofficial
    "deezer": RateLimiter(0.15),        # 50 req / 5 s
    "coverartarchive": RateLimiter(0.0),  # no limit
}


def wait(provider: str):
    limiter = _LIMITERS.get(provider)
    if limiter:
        limiter.wait()
