"""Unified, multi-provider release-candidate search.

Every "which album/edition is this?" lookup in the app funnels through here so
no single provider is treated as authoritative. It returns a ranked list of
candidate releases drawn from every enabled provider that can supply an
edition-level tracklist (MusicBrainz + Discogs today); the UI lets the user
pick the exact edition. Field/art enrichment still happens in aggregator.py.

Discogs is deliberately included because it carries the special/regional/
expanded editions MusicBrainz often lacks (e.g. the 14-track Black Celebration
that MB only had as a 12-track release).
"""

from config import load_settings
from text_utils import strip_various_artist
from services.metadata.aggregator import DEFAULT_ENABLED

# Tie-break order when track counts are equal (or unknown).
_PROVIDER_RANK = {"musicbrainz": 0, "discogs": 1, "itunes": 2, "deezer": 3}


def _candidate(provider, rid, title, artist, date, country="", fmt="",
               label="", track_count=0, disc_count=1) -> dict:
    return {
        "provider": provider,
        "id": str(rid),
        "title": title or "",
        "artist": artist or "",
        "date": str(date or ""),
        "country": country or "",
        "format": fmt or "",
        "label": label or "",
        "track_count": int(track_count or 0),
        "disc_count": int(disc_count or 1),
        "recommended": False,
    }


def rank_candidates(candidates: list[dict], track_count: int | None) -> list[dict]:
    """Sort so a release whose track count matches the disc floats to the top,
    then by provider preference, then earliest date. Marks the winner
    `recommended`. Pure function — unit-tested without network."""
    def key(c):
        match = (track_count is not None and track_count > 0
                 and c["track_count"] == track_count)
        return (
            0 if match else 1,
            _PROVIDER_RANK.get(c["provider"], 9),
            c["date"] or "9999",
        )

    ordered = sorted(candidates, key=key)
    for c in ordered:
        c["recommended"] = False
    if ordered:
        ordered[0]["recommended"] = True
    return ordered


def find_release_candidates(artist: str = "", album: str = "",
                            track_count: int | None = None,
                            disc_id: str | None = None,
                            title: str = "",
                            settings: dict | None = None) -> list[dict]:
    """Search every enabled edition-capable provider and return a ranked,
    de-duplicated candidate list for the user to choose from.

    When `album` is blank but `title` is given, this becomes a SONG search:
    find the albums a recording appears on (so the user can hunt for a track's
    original album without knowing the album name)."""
    from config import provider_has_keys
    settings = settings or load_settings()
    # Drop providers whose required API key is missing — they won't be used.
    enabled = {p for p in settings.get("metadata_providers_enabled", DEFAULT_ENABLED)
               if provider_has_keys(p)}
    out: list[dict] = []

    # ── Song search: no album, find which editions contain this track ────────
    if not album.strip() and title.strip():
        # MusicBrainz recording search is the only provider that answers "which
        # releases is this song on?". Return every edition (not one per album) so
        # the user can pick the exact pressing — same granularity as an album
        # search, with the country/media/track-count filters to narrow it.
        from library_manager import find_track_editions
        for c in find_track_editions(artist, title):
            out.append(_candidate(
                "musicbrainz", c.get("release_id"), c.get("album"), c.get("artist"),
                c.get("date"), c.get("country"), c.get("format", ""),
                "", c.get("total_tracks", 0), c.get("disc_count", 1)))
        deduped, seen = [], set()
        for c in out:
            if c["id"] and c["id"] not in seen:
                seen.add(c["id"]); deduped.append(c)
        return rank_candidates(deduped, track_count)

    if "musicbrainz" in enabled:
        # Exact disc-ID releases first (when a CUE gave us a disc ID).
        if disc_id:
            try:
                from services.metadata.providers import musicbrainz as mb
                for m in (mb.lookup_discid(disc_id) or []):
                    out.append(_candidate(
                        "musicbrainz", m.get("id"), m.get("title"), m.get("artist"),
                        m.get("date"), m.get("country"),
                        track_count=m.get("total_tracks", 0)))
            except Exception:
                pass
        # Text search.
        try:
            from metadata_lookup import search_release as mb_search
            for r in (mb_search(artist=artist or None, album=album or None,
                                tracks=track_count) or []):
                if r.get("error"):
                    break
                out.append(_candidate(
                    "musicbrainz", r.get("id"), r.get("title"), r.get("artist"),
                    r.get("date"), r.get("country"), r.get("format", ""),
                    r.get("label", ""), r.get("total_tracks", 0),
                    r.get("disc_count", 1)))
        except Exception:
            pass

    if "discogs" in enabled:
        try:
            from discogs_lookup import search_release as dg_search
            for r in (dg_search(artist=strip_various_artist(artist) or None,
                                album=album or None) or []):
                if r.get("error"):
                    break
                out.append(_candidate(
                    "discogs", r.get("id"), r.get("title"), r.get("artist"),
                    r.get("date"), r.get("country"), r.get("format", ""),
                    r.get("label", ""), r.get("total_tracks", 0)))
        except Exception:
            pass

    # De-duplicate within a provider (across providers we keep distinct editions).
    seen = set()
    deduped = []
    for c in out:
        if not c["id"]:
            continue
        k = (c["provider"], c["id"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(c)

    return rank_candidates(deduped, track_count)
