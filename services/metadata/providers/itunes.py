"""iTunes Search provider — no key, reliable dates, art upsizable to 3000px."""

import requests

from services.metadata import cache, ratelimit

_UA = {"User-Agent": "MusicManager/2.0 (louissilvestri@hotmail.com)"}


def search_album(artist: str, album: str) -> dict | None:
    """Best album match: {title, artist, date, art_url, art_thumb_url}."""
    if not album:
        return None
    key = f"album|{(artist or '').lower()}|{album.lower()}"

    def fetch():
        ratelimit.wait("itunes")
        r = requests.get("https://itunes.apple.com/search", params={
            "term": f"{artist} {album}".strip(),
            "entity": "album", "limit": 5,
        }, headers=_UA, timeout=15)
        results = r.json().get("results", [])
        if not results:
            return {}

        # Prefer a result whose collection name matches the album
        album_l = album.lower()
        best = next((x for x in results
                     if album_l in x.get("collectionName", "").lower()), results[0])

        art100 = best.get("artworkUrl100", "")
        return {
            "title": best.get("collectionName", ""),
            "artist": best.get("artistName", ""),
            "date": (best.get("releaseDate") or "")[:10],
            "genre": best.get("primaryGenreName", ""),
            # The CDN serves arbitrary sizes via URL rewrite
            "art_url": art100.replace("100x100bb", "3000x3000bb") if art100 else "",
            "art_thumb_url": art100.replace("100x100bb", "250x250bb") if art100 else "",
            "track_count": best.get("trackCount", 0),
        }

    result = cache.cached("itunes", key, cache.TTL_RELEASE, fetch)
    return result or None


def extract_fields(result: dict | None) -> dict[str, dict]:
    if not result:
        return {}
    src = "itunes"
    fields = {}
    if result.get("title"):
        fields["title"] = {"value": result["title"], "source": src}
    if result.get("artist"):
        fields["artist"] = {"value": result["artist"], "source": src}
    if result.get("date"):
        # iTunes releaseDate is the ORIGINAL release date for most albums
        fields["original_date"] = {"value": result["date"], "source": src}
    if result.get("genre"):
        fields["genre"] = {"value": result["genre"], "source": src}
    return fields
