"""Provider routing for metadata lookups (MusicBrainz vs Discogs).

Moved from app.py (Phase 1). This is a transitional layer: Phase 2 replaces
the either/or routing with the multi-source aggregation engine.
"""

from pathlib import Path

from config import load_settings
from cue_parser import (
    parse_cue_file, find_cue_file, cue_to_metadata,
    calculate_musicbrainz_discid, get_leadout_from_cue_and_wavs,
    get_toc_for_musicbrainz,
)


def _normalize_va_for_discogs(artist: str | None) -> str:
    """Discogs uses 'Various', not 'Various Artists' — drop it entirely so the
    album title carries the search."""
    if artist and artist.lower().strip() in ("various artists", "various"):
        return ""
    return artist or ""


def search_releases(artist=None, album=None, track_count=None, settings=None) -> list[dict]:
    """Search for a release using the configured metadata provider."""
    settings = settings or load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")

    if provider == "discogs":
        from discogs_lookup import search_release as discogs_search
        return discogs_search(artist=_normalize_va_for_discogs(artist),
                              album=album, tracks=track_count)
    else:
        from metadata_lookup import search_release
        return search_release(artist=artist, album=album, tracks=track_count)


def get_release(release_id: str, settings=None) -> dict:
    """Get full release details (track listing etc.) from the active provider."""
    settings = settings or load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")

    if provider == "discogs":
        from discogs_lookup import get_release_details as discogs_details
        return discogs_details(release_id)
    else:
        from metadata_lookup import get_release_details
        return get_release_details(release_id)


def find_album_by_name(artist: str, album_name: str, settings=None):
    """Search for release-group candidates by album name (Quick Clean Up).

    MusicBrainz: sorted by year, 'Likely Original' on earliest studio album.
    Discogs: search results converted to the same candidate shape.
    Returns a list of candidates, or {"error": ...} on failure.
    """
    try:
        settings = settings or load_settings()
        provider = settings.get("metadata_provider", "musicbrainz")

        if provider == "discogs":
            from discogs_lookup import search_release as discogs_search
            results = discogs_search(artist=_normalize_va_for_discogs(artist),
                                     album=album_name)
            if results and not results[0].get("error"):
                candidates = []
                for r in results:
                    candidates.append({
                        "release_group_id": "",
                        "release_id": r["id"],
                        "album": r["title"],
                        "artist": r["artist"],
                        "date": r.get("date", ""),
                        "first_release_date": r.get("date", ""),
                        "type": "Album",
                        "secondary_types": [],
                        "country": r.get("country", ""),
                        "total_tracks": r.get("total_tracks", 0),
                        "is_original": False,
                        "format": r.get("format", ""),
                        "label": r.get("label", ""),
                    })
                if candidates:
                    candidates[0]["is_original"] = True
                return candidates
            if results and results[0].get("error"):
                return {"error": results[0]["error"]}
            return []
        else:
            from library_manager import find_original_album_by_name as _find
            return _find(artist, album_name)
    except Exception as e:
        return {"error": str(e)}


def automated_cue_lookup(folder_path: str, settings=None) -> dict:
    """Full automated metadata lookup cascade from a folder's CUE sheet.

    MusicBrainz: disc ID → barcode → GnuDB → fuzzy TOC → text search
    Discogs:     barcode → text search
    """
    settings = settings or load_settings()

    cue_path = find_cue_file(folder_path)
    if not cue_path:
        return {"error": "No CUE sheet found", "cascade_log": [], "releases": []}

    try:
        cue_data = parse_cue_file(cue_path)
    except Exception as e:
        return {"error": f"Failed to parse CUE: {e}", "cascade_log": [], "releases": []}

    cue_meta = cue_to_metadata(cue_data)
    provider = settings.get("metadata_provider", "musicbrainz")

    if provider == "discogs":
        from discogs_lookup import automated_lookup as discogs_lookup
        result = discogs_lookup(
            artist=cue_meta["album"].get("artist"),
            album=cue_meta["album"].get("album"),
            barcode=cue_meta["album"].get("barcode", ""),
            track_count=cue_meta["track_count"],
        )
        result["disc_id"] = None
        result["cue_metadata"] = cue_meta
        return result

    # MusicBrainz cascade
    from metadata_lookup import automated_lookup

    disc_id = None
    toc_data = None
    leadout = get_leadout_from_cue_and_wavs(cue_data, folder_path)

    if leadout:
        try:
            disc_id = calculate_musicbrainz_discid(cue_data, leadout, cue_folder=folder_path)
        except Exception:
            disc_id = None
        toc_data = get_toc_for_musicbrainz(cue_data, leadout, cue_folder=folder_path)

    freedb_disc_id = cue_data.get("rem", {}).get("DISCID", "")
    total_seconds = (leadout // 75) if leadout else None

    result = automated_lookup(
        disc_id=disc_id,
        barcode=cue_meta["album"].get("barcode"),
        track_count=cue_meta["track_count"],
        track_offsets=toc_data["track_offsets"] if toc_data else None,
        leadout_offset=toc_data["leadout_offset"] if toc_data else None,
        artist=cue_meta["album"].get("artist"),
        album=cue_meta["album"].get("album"),
        freedb_disc_id=freedb_disc_id if freedb_disc_id else None,
        total_seconds=total_seconds,
    )

    result["disc_id"] = disc_id
    result["cue_metadata"] = cue_meta
    return result
