"""MusicBrainz provider — identity backbone (release groups, disc IDs, tracks)."""

from services.metadata import cache, ratelimit


def search_best_release(artist: str = "", album: str = "",
                        track_count: int | None = None) -> dict | None:
    """Text search → best-scored release summary, or None."""
    key = f"search|{(artist or '').lower()}|{(album or '').lower()}|{track_count}"

    def fetch():
        from metadata_lookup import search_release
        ratelimit.wait("musicbrainz")
        results = search_release(artist=artist or None, album=album or None,
                                 tracks=track_count)
        if results and not results[0].get("error"):
            return results
        return []

    results = cache.cached("musicbrainz", key, cache.TTL_SEARCH, fetch)
    return results[0] if results else None


def get_release(release_id: str) -> dict | None:
    """Full release details incl. tracks, first_release_date, genre tags."""
    def fetch():
        from metadata_lookup import get_release_details
        # metadata_lookup handles its own MB rate limiting internally
        details = get_release_details(release_id)
        return None if details.get("error") else details

    return cache.cached("musicbrainz", f"release|{release_id}", cache.TTL_RELEASE, fetch)


def lookup_discid(disc_id: str) -> list[dict]:
    def fetch():
        from metadata_lookup import lookup_by_discid
        ratelimit.wait("musicbrainz")
        return lookup_by_discid(disc_id)

    return cache.cached("musicbrainz", f"discid|{disc_id}", cache.TTL_RELEASE, fetch) or []


def best_release_for_group(release_group_id: str) -> str | None:
    """Pick the canonical release in a release group (prefer US + CD, earliest)."""
    def fetch():
        import musicbrainzngs
        from metadata_lookup import init_musicbrainz
        init_musicbrainz()
        ratelimit.wait("musicbrainz")
        result = musicbrainzngs.browse_releases(
            release_group=release_group_id, includes=["media"], limit=50)
        releases = result.get("release-list", [])
        if not releases:
            return {"release_id": None}

        def score(rel):
            country = (rel.get("country") or "").upper()
            formats = [m.get("format", "") for m in rel.get("medium-list", [])]
            is_us = country in ("US", "XW")
            is_cd = any("CD" in f for f in formats if f)
            return (
                -(2 * is_us + is_cd),
                rel.get("date") or "9999",
            )

        releases.sort(key=score)
        return {"release_id": releases[0].get("id")}

    result = cache.cached("musicbrainz", f"best-release|{release_group_id}",
                          cache.TTL_RELEASE, fetch)
    return result.get("release_id") if result else None


def extract_fields(details: dict) -> dict[str, dict]:
    """Normalize MB release details into {field: {value, source}}."""
    src = "musicbrainz"
    fields = {}

    def put(name, value):
        if value:
            fields[name] = {"value": value, "source": src}

    put("title", details.get("title"))
    put("artist", details.get("artist"))
    put("original_date", details.get("first_release_date"))
    put("release_date", details.get("date"))
    put("genre", details.get("genre"))
    if details.get("genres"):
        fields["styles"] = {"value": details["genres"], "source": src}
    put("label", details.get("label"))
    put("catalog_number", details.get("catalog_number"))
    put("barcode", details.get("barcode"))
    put("country", details.get("country"))
    return fields
