"""Plex metadata completeness scoring. Moved from app.py (Phase 1)."""

from config import (
    PLEX_DISPLAY_FIELDS, PLEX_MATCH_FIELDS, PLEX_OPTIONAL_FIELDS, PLEX_ALL_FIELDS,
)
from tagger import build_metadata_from_release


def calculate_metadata_completeness(metadata: dict, has_art: bool = False) -> dict:
    """Calculate metadata completeness percentage based on Plex-supported fields.

    Returns: {percentage, filled, total, fields: {name: {status, category}}, has_art}
    """
    fields = {}
    filled = 0
    total = 0

    meta_upper = {k.upper(): v for k, v in metadata.items()}

    for field_list, category in (
        (PLEX_DISPLAY_FIELDS, "display"),
        (PLEX_MATCH_FIELDS, "match"),
        (PLEX_OPTIONAL_FIELDS, "optional"),
    ):
        for field in field_list:
            total += 1
            val = meta_upper.get(field, "")
            is_filled = bool(val and str(val).strip())
            if is_filled:
                filled += 1
            fields[field] = {"status": "filled" if is_filled else "missing",
                             "category": category}

    # Album art counts as a field
    total += 1
    if has_art:
        filled += 1
    fields["COVER_ART"] = {"status": "filled" if has_art else "missing",
                           "category": "display"}

    return {
        "percentage": round((filled / total) * 100) if total > 0 else 0,
        "filled": filled,
        "total": total,
        "fields": fields,
        "has_art": has_art,
    }


def compute_album_completeness(release_details: dict | None,
                               cue_metadata: dict | None,
                               has_art: bool) -> dict:
    """Per-track completeness for a release (or CUE-only metadata) + album summary."""
    tracks_result = []

    if release_details and release_details.get("discs"):
        for disc in release_details["discs"]:
            for track in disc["tracks"]:
                meta = build_metadata_from_release(release_details, disc["position"], track["position"])

                # Merge ISRC from CUE if the provider didn't have it
                if not meta.get("isrc") and cue_metadata:
                    idx = track["position"] - 1
                    if idx < len(cue_metadata.get("tracks", [])):
                        cue_isrc = cue_metadata["tracks"][idx].get("isrc", "")
                        if cue_isrc:
                            meta["isrc"] = cue_isrc

                completeness = calculate_metadata_completeness(meta, has_art=has_art)
                tracks_result.append({
                    "track_number": track["position"],
                    "disc_number": disc["position"],
                    "title": track.get("title", ""),
                    "artist": track.get("artist", ""),
                    **completeness,
                })
    elif cue_metadata:
        for i, cue_track in enumerate(cue_metadata.get("tracks", [])):
            meta = {
                "title": cue_track.get("title", ""),
                "artist": cue_track.get("artist", ""),
                "album": cue_metadata["album"].get("album", ""),
                "albumartist": cue_metadata["album"].get("artist", ""),
                "tracknumber": cue_track.get("tracknumber", str(i + 1)),
                "discnumber": cue_metadata["album"].get("discnumber", "1"),
                "date": cue_metadata["album"].get("date", ""),
                "genre": cue_metadata["album"].get("genre", ""),
                "isrc": cue_track.get("isrc", ""),
                "tracktotal": str(cue_metadata["track_count"]),
                "disctotal": cue_metadata["album"].get("disctotal", "1"),
            }
            completeness = calculate_metadata_completeness(meta, has_art=has_art)
            tracks_result.append({
                "track_number": i + 1,
                "disc_number": int(cue_metadata["album"].get("discnumber", "1") or "1"),
                "title": cue_track.get("title", ""),
                "artist": cue_track.get("artist", ""),
                **completeness,
            })

    avg_pct = round(sum(t["percentage"] for t in tracks_result) / len(tracks_result)) if tracks_result else 0

    return {
        "tracks": tracks_result,
        "album_average": avg_pct,
        "plex_field_count": len(PLEX_ALL_FIELDS) + 1,  # +1 for cover art
    }
