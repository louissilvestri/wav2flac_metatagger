"""Discogs provider — styles, labels, catalog numbers, pressing detail."""

from text_utils import strip_various_artist
from services.metadata import cache, ratelimit


def search_best_release(artist: str = "", album: str = "") -> dict | None:
    key = f"search|{(artist or '').lower()}|{(album or '').lower()}"

    def fetch():
        from discogs_lookup import search_release
        ratelimit.wait("discogs")
        results = search_release(artist=strip_various_artist(artist), album=album)
        if results and not results[0].get("error"):
            return results
        return []

    results = cache.cached("discogs", key, cache.TTL_SEARCH, fetch)
    return results[0] if results else None


def get_release(release_id: str) -> dict | None:
    def fetch():
        from discogs_lookup import get_release_details
        ratelimit.wait("discogs")
        details = get_release_details(release_id)
        return None if details.get("error") else details

    return cache.cached("discogs", f"release|{release_id}", cache.TTL_RELEASE, fetch)


def get_art_urls(release_id: str) -> list[dict]:
    """Image candidates for a Discogs release: [{url, thumb_url, width, height}]."""
    def fetch():
        from discogs_lookup import _get_client
        client = _get_client()
        if not client:
            return []
        ratelimit.wait("discogs")
        release = client.release(int(release_id))
        out = []
        for img in (release.images or []):
            out.append({
                "url": img.get("uri", ""),
                "thumb_url": img.get("uri150", ""),
                "width": img.get("width", 0),
                "height": img.get("height", 0),
                "primary": img.get("type") == "primary",
            })
        out.sort(key=lambda i: (not i["primary"],))
        return out

    return cache.cached("discogs", f"art|{release_id}", cache.TTL_RELEASE, fetch) or []


def extract_fields(details: dict) -> dict[str, dict]:
    """Normalize Discogs release details into {field: {value, source}}."""
    src = "discogs"
    fields = {}

    def put(name, value):
        if value:
            fields[name] = {"value": value, "source": src}

    put("title", details.get("title"))
    put("artist", details.get("artist"))
    put("original_date", details.get("first_release_date"))  # master-release year
    put("release_date", details.get("date"))
    put("genre", details.get("genre"))
    if details.get("styles"):
        fields["styles"] = {"value": details["styles"], "source": src}
    put("label", details.get("label"))
    put("catalog_number", details.get("catalog_number"))
    put("barcode", details.get("barcode"))
    put("country", details.get("country"))
    return fields
