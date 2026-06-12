"""fanart.tv provider — curated high-res album art, keyed by MB release group."""

import requests

from config import get_secret
from services.metadata import cache, ratelimit

_UA = {"User-Agent": "MusicManager/2.0 (louissilvestri@hotmail.com)"}


def get_album_art(release_group_mbid: str) -> list[dict]:
    """Cover candidates: [{url, thumb_url, likes}] sorted by community likes."""
    api_key = get_secret("FANARTTV_API_KEY")
    if not api_key or not release_group_mbid:
        return []

    def fetch():
        ratelimit.wait("fanarttv")
        r = requests.get(
            f"https://webservice.fanart.tv/v3/music/albums/{release_group_mbid}",
            params={"api_key": api_key}, headers=_UA, timeout=15)
        if r.status_code != 200:
            return []
        covers = []
        for album in r.json().get("albums", {}).values():
            for img in album.get("albumcover", []):
                url = img.get("url", "")
                covers.append({
                    "url": url,
                    # fanart.tv serves previews under /preview/
                    "thumb_url": url.replace("/fanart/", "/preview/") if url else "",
                    "likes": int(img.get("likes", 0)),
                })
        covers.sort(key=lambda c: -c["likes"])
        return covers

    return cache.cached("fanarttv", f"albums|{release_group_mbid}",
                        cache.TTL_RELEASE, fetch) or []
