"""Library operations: scan, delete, reassign, batch reassign, previews.

Moved from app.py (Phase 1). All functions take explicit folder arguments so
they're testable without user settings.
"""

from pathlib import Path

from config import load_settings
from services.art import fetch_art_for_provider


def scan_library_full(output_folder: str) -> dict:
    """Scan a library folder: albums, duplicates, summary stats."""
    from library_manager import scan_library, group_library_by_album, find_duplicates

    if not output_folder or not Path(output_folder).exists():
        return {"error": "Output folder not configured or doesn't exist",
                "albums": [], "total_files": 0}

    files = scan_library(output_folder)
    albums = group_library_by_album(files)
    duplicates = find_duplicates(files)

    return {
        "albums": albums,
        "total_files": len(files),
        "compilation_tracks": sum(1 for f in files if f["is_compilation"]),
        "incomplete_tracks": sum(1 for f in files if f["completeness"] < 100),
        "duplicate_count": len(duplicates),
        "duplicates": duplicates,
        "output_folder": output_folder,
    }


def delete_library_file(flac_path: str, output_folder: str) -> dict:
    """Delete a FLAC file and clean up empty parent directories.

    Safety: only deletes files inside output_folder.
    """
    src = Path(flac_path)

    if not src.exists():
        return {"success": False, "error": "File not found"}

    try:
        src.relative_to(Path(output_folder))
    except ValueError:
        return {"success": False, "error": "File is not inside the output folder"}

    try:
        src.unlink()
        old_dir = src.parent
        while old_dir != Path(output_folder):
            if old_dir.exists() and not any(old_dir.iterdir()):
                old_dir.rmdir()
                old_dir = old_dir.parent
            else:
                break
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def reassign_track_with_art(flac_path: str, new_metadata: dict,
                            output_folder: str, move_file: bool = True,
                            art_release_id: str | None = None,
                            settings: dict | None = None) -> dict:
    """Re-tag a FLAC file, fetch new album art, and move it."""
    from library_manager import reassign_track

    settings = settings or load_settings()

    album_art = None
    fetch_release_id = art_release_id or new_metadata.get("musicbrainz_albumid", "")
    if fetch_release_id and settings.get("embed_album_art", True):
        album_art = fetch_art_for_provider(fetch_release_id, settings)

    return reassign_track(flac_path, new_metadata, output_folder, move_file,
                          album_art=album_art)


def batch_reassign_album(tracks: list[dict], album_metadata: dict,
                         output_folder: str,
                         art_release_id: str | None = None,
                         settings: dict | None = None) -> dict:
    """Re-tag and move multiple FLAC files at once (Quick Clean Up).

    art_release_id semantics:
      None       = keep existing art (don't touch)
      "__none__" = explicitly skip artwork
      otherwise  = fetch art from this release ID once for all tracks
    """
    from library_manager import reassign_track

    settings = settings or load_settings()

    album_art = None
    if art_release_id != "__none__":
        fetch_release_id = art_release_id or album_metadata.get("musicbrainz_albumid", "")
        if fetch_release_id and settings.get("embed_album_art", True):
            album_art = fetch_art_for_provider(fetch_release_id, settings)

    results = []
    failed = 0
    for track in tracks:
        merged = dict(album_metadata)
        merged["title"] = track.get("title", "")
        merged["artist"] = track.get("artist", merged.get("albumartist", ""))
        merged["tracknumber"] = str(track.get("tracknumber", "1"))
        merged["discnumber"] = str(track.get("discnumber", "1"))
        if track.get("musicbrainz_trackid"):
            merged["musicbrainz_trackid"] = track["musicbrainz_trackid"]
        if track.get("tracktotal"):
            merged["tracktotal"] = str(track["tracktotal"])

        result = reassign_track(track["path"], merged, output_folder,
                                move_file=True, album_art=album_art)
        results.append({
            "path": track["path"],
            "new_path": result.get("new_path", ""),
            "success": result["success"],
            "error": result.get("error"),
        })
        if not result["success"]:
            failed += 1

    return {"success": failed == 0, "results": results, "failed": failed,
            "total": len(tracks)}


_FIELD_DISPLAY_NAMES = {
    "TITLE": "Title", "ARTIST": "Artist", "ALBUMARTIST": "Album Artist",
    "ALBUM": "Album", "TRACKNUMBER": "Track", "DISCNUMBER": "Disc",
    "DATE": "Year", "GENRE": "Genre",
    "MUSICBRAINZ_ALBUMID": "MB Album ID", "MUSICBRAINZ_TRACKID": "MB Track ID",
    "MUSICBRAINZ_ARTISTID": "MB Artist ID", "MUSICBRAINZ_ALBUMARTISTID": "MB Album Artist ID",
    "TRACKTOTAL": "Total Tracks", "DISCTOTAL": "Total Discs",
}


def preview_reassign(flac_path: str, new_metadata: dict, output_folder: str) -> dict:
    """Preview what a reassign would change without doing it."""
    from file_manager import build_output_path
    from tagger import read_metadata

    current = read_metadata(flac_path)
    current_tags = current.get("tags", {})

    new_path = build_output_path(
        output_root=output_folder,
        artist=new_metadata.get("albumartist", new_metadata.get("artist", "Unknown Artist")),
        album=new_metadata.get("album", "Unknown Album"),
        year=new_metadata.get("date", ""),
        disc_number=int(new_metadata.get("discnumber", "1") or "1"),
        total_discs=int(new_metadata.get("disctotal", "1") or "1"),
        track_number=int(new_metadata.get("tracknumber", "1") or "1"),
        title=new_metadata.get("title", "Unknown"),
    )

    changes = []
    for key, new_val in new_metadata.items():
        upper_key = key.upper()
        old_val = current_tags.get(upper_key, "")
        if str(new_val) != str(old_val):
            changes.append({
                "field": _FIELD_DISPLAY_NAMES.get(upper_key, upper_key),
                "key": upper_key,
                "old": str(old_val),
                "new": str(new_val),
            })

    art_available = False
    release_id = new_metadata.get("musicbrainz_albumid", "")
    if release_id:
        from metadata_lookup import get_cover_art
        try:
            art_available = get_cover_art(release_id, max_size=200, quality=50) is not None
        except Exception:
            pass

    return {
        "changes": changes,
        "current_path": flac_path,
        "new_path": str(new_path),
        "path_changed": str(new_path) != flac_path,
        "art_available": art_available,
        "current_has_art": current.get("has_picture", False),
    }
