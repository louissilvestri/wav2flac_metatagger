"""Deezer provider — no key; art + release-date corroboration."""

import requests

from services.metadata import cache, ratelimit

_UA = {"User-Agent": "MusicManager/2.0 (louissilvestri@hotmail.com)"}


def search_album(artist: str, album: str) -> dict | None:
    """Best album match: {title, artist, date, art_url, art_thumb_url}."""
    if not album:
        return None
    key = f"album|{(artist or '').lower()}|{album.lower()}"

    def fetch():
        ratelimit.wait("deezer")
        q = f'artist:"{artist}" album:"{album}"' if artist else f'album:"{album}"'
        r = requests.get("https://api.deezer.com/search/album",
                         params={"q": q, "limit": 1}, headers=_UA, timeout=15)
        items = r.json().get("data", [])
        if not items:
            return {}
        item = items[0]

        # Album details carry the release date
        ratelimit.wait("deezer")
        detail = requests.get(f"https://api.deezer.com/album/{item['id']}",
                              headers=_UA, timeout=15).json()
        return {
            "title": item.get("title", ""),
            "artist": item.get("artist", {}).get("name", ""),
            "date": detail.get("release_date", ""),
            "art_url": item.get("cover_xl", ""),
            "art_thumb_url": item.get("cover_medium", ""),
        }

    result = cache.cached("deezer", key, cache.TTL_RELEASE, fetch)
    return result or None


def extract_fields(result: dict | None) -> dict[str, dict]:
    if not result:
        return {}
    fields = {}
    if result.get("date"):
        fields["original_date"] = {"value": result["date"], "source": "deezer"}
    return fields
