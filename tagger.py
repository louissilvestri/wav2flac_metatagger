"""Vorbis Comments metadata embedding for FLAC files."""

import struct
import base64
from pathlib import Path
from io import BytesIO

from mutagen.flac import FLAC, Picture


def embed_metadata(flac_path: str, metadata: dict, album_art: bytes = None) -> dict:
    """Embed Vorbis Comments and optional album art into a FLAC file.

    metadata dict keys map directly to Vorbis Comment field names.
    Multi-value fields should be passed as lists.

    Returns: {success: bool, error: str|None, fields_written: int}
    """
    try:
        audio = FLAC(flac_path)
    except Exception as e:
        return {"success": False, "error": f"Failed to open FLAC file: {e}", "fields_written": 0}

    # Standard Vorbis Comment field mapping
    FIELD_MAP = {
        "title": "TITLE",
        "artist": "ARTIST",
        "album": "ALBUM",
        "albumartist": "ALBUMARTIST",
        "tracknumber": "TRACKNUMBER",
        "tracktotal": "TRACKTOTAL",
        "discnumber": "DISCNUMBER",
        "disctotal": "DISCTOTAL",
        "date": "DATE",
        "year": "DATE",
        "genre": "GENRE",
        "composer": "COMPOSER",
        "performer": "PERFORMER",
        "conductor": "CONDUCTOR",
        "lyricist": "LYRICIST",
        "isrc": "ISRC",
        "barcode": "BARCODE",
        "catalognumber": "CATALOGNUMBER",
        "label": "ORGANIZATION",
        "organization": "ORGANIZATION",
        "media": "MEDIA",
        "copyright": "COPYRIGHT",
        "comment": "COMMENT",
        "encoder": "ENCODER",
        "musicbrainz_trackid": "MUSICBRAINZ_TRACKID",
        "musicbrainz_albumid": "MUSICBRAINZ_ALBUMID",
        "musicbrainz_artistid": "MUSICBRAINZ_ARTISTID",
        "musicbrainz_albumartistid": "MUSICBRAINZ_ALBUMARTISTID",
        "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID",
    }

    # Preserve existing tags — only overwrite fields where new value is non-empty.
    # This prevents MusicBrainz gaps (missing genre, composer, ISRC, etc.) from
    # deleting more complete EAC-sourced metadata.
    fields_written = 0

    for key, value in metadata.items():
        if value is None or value == "" or value == []:
            continue

        field_name = FIELD_MAP.get(key.lower(), key.upper())

        # Handle multi-value fields (lists become repeated Vorbis Comment entries)
        if isinstance(value, list):
            audio[field_name] = [str(v) for v in value if v]
        else:
            audio[field_name] = [str(value)]
        fields_written += 1

    # Always set encoder tag
    if "ENCODER" not in audio:
        audio["ENCODER"] = ["Music Manager 1.0.0 (FLAC reference encoder)"]
        fields_written += 1

    # Embed album art as METADATA_BLOCK_PICTURE
    if album_art:
        try:
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3  # Front cover
            pic.mime = "image/jpeg"
            pic.desc = "Front Cover"
            pic.data = album_art

            # Get dimensions from image data
            from PIL import Image
            img = Image.open(BytesIO(album_art))
            pic.width = img.width
            pic.height = img.height
            pic.depth = 24  # Assume 24-bit color

            audio.add_picture(pic)
            fields_written += 1
        except Exception:
            pass  # Non-fatal: metadata still written even if art fails

    try:
        audio.save()
        return {"success": True, "error": None, "fields_written": fields_written}
    except Exception as e:
        return {"success": False, "error": f"Failed to save tags: {e}", "fields_written": 0}


def read_metadata(flac_path: str) -> dict:
    """Read all Vorbis Comments from a FLAC file.

    Returns tags as {KEY: value} where value is a string (single) or list (multi).
    Keys are uppercased for consistent access.
    """
    try:
        audio = FLAC(flac_path)
        tags = {}
        if audio.tags:
            for key in audio.tags.keys():
                vals = audio.tags[key]  # Always a list in mutagen
                tags[key.upper()] = vals[0] if len(vals) == 1 else vals
        return {"success": True, "tags": tags, "has_picture": bool(audio.pictures)}
    except Exception as e:
        return {"success": False, "tags": {}, "error": str(e)}


def build_metadata_from_release(release_details: dict, disc_number: int, track_number: int) -> dict:
    """Build a metadata dict from MusicBrainz release details for a specific track."""
    meta = {}

    meta["album"] = release_details.get("title", "")
    meta["albumartist"] = release_details.get("artist", "")
    # Prefer original album date (from release group) over individual release date
    meta["date"] = release_details.get("first_release_date") or release_details.get("date", "")
    meta["genre"] = release_details.get("genre", "")
    meta["barcode"] = release_details.get("barcode", "")
    meta["catalognumber"] = release_details.get("catalog_number", "")
    meta["label"] = release_details.get("label", "")
    meta["media"] = "CD"
    meta["musicbrainz_albumid"] = release_details.get("id", "")
    meta["musicbrainz_albumartistid"] = release_details.get("artist_id", "")
    meta["musicbrainz_releasegroupid"] = release_details.get("release_group_id", "")

    total_discs = len(release_details.get("discs", []))
    meta["disctotal"] = str(total_discs)
    meta["discnumber"] = str(disc_number)

    # Find the specific track
    for disc in release_details.get("discs", []):
        if disc["position"] == disc_number:
            meta["tracktotal"] = str(len(disc["tracks"]))
            for track in disc["tracks"]:
                if track["position"] == track_number:
                    meta["title"] = track.get("title", "")
                    meta["artist"] = track.get("artist", "") or release_details.get("artist", "")
                    meta["tracknumber"] = str(track_number)
                    meta["isrc"] = track.get("isrc", "")
                    meta["musicbrainz_trackid"] = track.get("recording_id", "")
                    meta["musicbrainz_artistid"] = track.get("artist_id", "")
                    break
            break

    return {k: v for k, v in meta.items() if v}
