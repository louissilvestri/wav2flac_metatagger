"""Last.fm provider — the best community genre tags anywhere."""

import requests

from config import get_secret
from services.metadata import cache, ratelimit

_API = "https://ws.audioscrobbler.com/2.0/"
_UA = {"User-Agent": "MusicManager/2.0 (louissilvestri@hotmail.com)"}

# Tags that are popular but aren't genres
_JUNK_TAGS = {
    "seen live", "favorites", "favourite", "favourites", "albums i own",
    "vinyl", "cd", "beautiful", "awesome", "love", "loved", "check out",
    "favorite albums", "masterpiece", "classic", "british", "american",
    "usa", "uk", "male vocalists", "female vocalists", "under 2000 listeners",
}


def get_album_tags(artist: str, album: str) -> list[dict]:
    """Top community tags for an album: [{name, count}], junk filtered."""
    api_key = get_secret("LASTFM_API_KEY")
    if not api_key or not artist or not album:
        return []

    key = f"toptags|{artist.lower()}|{album.lower()}"

    def fetch():
        ratelimit.wait("lastfm")
        r = requests.get(_API, params={
            "method": "album.gettoptags", "artist": artist, "album": album,
            "api_key": api_key, "format": "json", "autocorrect": 1,
        }, headers=_UA, timeout=15)
        data = r.json()
        if "error" in data:
            return []
        tags = data.get("toptags", {}).get("tag", [])
        return [{"name": t["name"], "count": int(t.get("count", 0))} for t in tags]

    tags = cache.cached("lastfm", key, cache.TTL_RELEASE, fetch) or []
    return [t for t in tags
            if t["count"] >= 10 and t["name"].lower() not in _JUNK_TAGS
            and not t["name"].isdigit() and not _is_decade(t["name"])]


def _is_decade(tag: str) -> bool:
    t = tag.lower().strip()
    return len(t) in (3, 5) and t.endswith("s") and t[:-1].isdigit()


def extract_fields(artist: str, album: str) -> dict[str, dict]:
    """{genre, styles} from community tags."""
    tags = get_album_tags(artist, album)
    if not tags:
        return {}
    fields = {
        "genre": {"value": tags[0]["name"].title(), "source": "lastfm"},
    }
    if len(tags) > 1:
        fields["styles"] = {
            "value": [t["name"].title() for t in tags[:5]],
            "source": "lastfm",
        }
    return fields
