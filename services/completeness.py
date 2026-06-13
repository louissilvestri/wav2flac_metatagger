"""Plex metadata completeness scoring — the single source of truth.

Both the library scan (library_manager) and the conversion preview use this
one function, so the two can never disagree (they used to: a conversion would
report 100% while the library reported 87% for the same album).
"""

from config import (
    PLEX_DISPLAY_FIELDS, PLEX_OPTIONAL_FIELDS, PLEX_IDENTIFIER_FIELDS,
)
from tagger import build_metadata_from_release


def calculate_metadata_completeness(metadata: dict, has_art: bool = False) -> dict:
    """Score how well-tagged a track is, source-agnostically.

    Slots: each display field, each optional field, cover art, and ONE
    "identifier" credit satisfied by any external ID (MusicBrainz OR Discogs).
    Returns: {percentage, filled, total, fields: {name: {status, category}}, has_art}
    """
    meta_upper = {k.upper(): v for k, v in metadata.items()}

    def present(field: str) -> bool:
        val = meta_upper.get(field, "")
        return bool(val and str(val).strip())

    fields = {}
    filled = 0
    total = 0

    for field_list, category in (
        (PLEX_DISPLAY_FIELDS, "display"),
        (PLEX_OPTIONAL_FIELDS, "optional"),
    ):
        for field in field_list:
            total += 1
            is_filled = present(field)
            if is_filled:
                filled += 1
            fields[field] = {"status": "filled" if is_filled else "missing",
                             "category": category}

    # Album art
    total += 1
    if has_art:
        filled += 1
    fields["COVER_ART"] = {"status": "filled" if has_art else "missing",
                           "category": "display"}

    # One identifier credit — satisfied by ANY provider's album/track ID
    total += 1
    has_identifier = any(present(f) for f in PLEX_IDENTIFIER_FIELDS)
    if has_identifier:
        filled += 1
    fields["IDENTIFIER"] = {"status": "filled" if has_identifier else "missing",
                            "category": "match"}

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

    from config import PLEX_SCORED_SLOTS
    return {
        "tracks": tracks_result,
        "album_average": avg_pct,
        "plex_field_count": PLEX_SCORED_SLOTS,
    }
