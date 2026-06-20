"""Library operations: scan, delete, reassign, batch reassign, previews.

Moved from app.py (Phase 1). All functions take explicit folder arguments so
they're testable without user settings.
"""

import os
from pathlib import Path

from config import load_settings
from services.art import fetch_art_for_provider

# Last full scan's flat file list, keyed by normalized output folder. Lets a
# library edit re-read only the touched files instead of the whole share
# (grouping/duplicate/stat computation is cheap; the network tag reads aren't).
# Cleared on process restart, which simply falls back to a full scan.
_scan_cache: dict[str, list[dict]] = {}


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _build_scan_result(files: list[dict], output_folder: str) -> dict:
    """Group + summarize a flat file list into the library payload. Pure CPU —
    no disk/network I/O — so it's cheap to re-run after a partial re-read."""
    from library_manager import group_library_by_album, find_duplicates

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


def scan_library_full(output_folder: str) -> dict:
    """Scan a library folder: albums, duplicates, summary stats."""
    from library_manager import scan_library

    if not output_folder or not Path(output_folder).exists():
        return {"error": "Output folder not configured or doesn't exist",
                "albums": [], "total_files": 0}

    files = scan_library(output_folder)
    _scan_cache[_norm(output_folder)] = files
    return _build_scan_result(files, output_folder)


def rescan_paths(output_folder: str, paths: list[str]) -> dict:
    """Partial rescan: re-read only `paths` (changed/moved/deleted files) and
    recompute the library payload from the cached file set. Falls back to a full
    scan when there's no cached baseline (e.g. after a server restart).

    Pass both the old and new path for a move/reassign so the stale entry is
    dropped and the new one picked up.
    """
    from library_manager import scan_library, _scan_single_file

    if not output_folder or not Path(output_folder).exists():
        return {"error": "Output folder not configured or doesn't exist",
                "albums": [], "total_files": 0}

    key = _norm(output_folder)
    cached = _scan_cache.get(key)
    if cached is None:
        files = scan_library(output_folder)
        _scan_cache[key] = files
        return _build_scan_result(files, output_folder)

    root = Path(output_folder)
    by_path = {_norm(f["path"]): f for f in cached}

    for p in paths:
        pth = Path(p)
        npath = _norm(pth)
        # A file that's gone (deleted, or the source side of a move) is dropped.
        if not (pth.exists() and pth.suffix.lower() == ".flac"):
            by_path.pop(npath, None)
            continue
        try:
            pth.relative_to(root)
        except ValueError:
            by_path.pop(npath, None)  # outside the library — ignore
            continue
        entry = _scan_single_file(pth, root)
        if entry:
            by_path[_norm(entry["path"])] = entry
        else:
            by_path.pop(npath, None)

    files = list(by_path.values())
    _scan_cache[key] = files
    return _build_scan_result(files, output_folder)


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


def update_track_tags(flac_path: str, changes: dict, output_folder: str) -> dict:
    """Set/delete arbitrary tags on one library file (advanced tag editor).

    Safety: only edits files inside output_folder.
    """
    from tagger import update_raw_tags

    src = Path(flac_path)
    if not src.exists():
        return {"success": False, "error": "File not found", "tags": {}}
    try:
        src.relative_to(Path(output_folder))
    except ValueError:
        return {"success": False, "error": "File is not inside the output folder", "tags": {}}
    return update_raw_tags(str(src), changes)


def add_replay_gain_paths(paths: list[str], output_folder: str) -> dict:
    """Compute ReplayGain tags for a set of library files (e.g. one album).

    Safety: only analyzes FLACs inside output_folder.
    """
    from encoder import add_replay_gain

    root = Path(output_folder)
    valid = []
    for p in paths:
        pth = Path(p)
        try:
            pth.relative_to(root)
        except ValueError:
            continue
        if pth.exists() and pth.suffix.lower() == ".flac":
            valid.append(str(pth))
    if not valid:
        return {"success": False, "processed": 0,
                "errors": ["No valid FLAC files inside the library"]}
    return add_replay_gain(valid)


def reassign_track_with_art(flac_path: str, new_metadata: dict,
                            output_folder: str, move_file: bool = True,
                            art_release_id: str | None = None,
                            settings: dict | None = None,
                            art_url: str | None = None) -> dict:
    """Re-tag a FLAC file, optionally fetch/replace album art, and move it.

    Art selection (mirrors batch_reassign_album):
      art_url set          = download that specific image (user-picked in UI)
      "__keep__"/None      = keep existing embedded art (don't touch it)
      "__none__"           = explicitly skip artwork (leaves any existing art)
      otherwise            = fetch art from this release ID
    """
    from library_manager import reassign_track

    settings = settings or load_settings()

    album_art = None
    if art_url:
        from services.conversion import _download_art
        album_art = _download_art(art_url, settings.get("art_max_size", 1200),
                                  settings.get("art_quality", 90))
    elif art_release_id not in (None, "__keep__", "__none__"):
        if settings.get("embed_album_art", True):
            album_art = fetch_art_for_provider(art_release_id, settings)

    return reassign_track(flac_path, new_metadata, output_folder, move_file,
                          album_art=album_art)


def batch_reassign_album(tracks: list[dict], album_metadata: dict,
                         output_folder: str,
                         art_release_id: str | None = None,
                         settings: dict | None = None,
                         art_url: str | None = None) -> dict:
    """Re-tag and move multiple FLAC files at once (Quick Clean Up).

    Art selection:
      art_url set          = download that specific image (user-picked in UI)
      art_release_id None  = keep existing art (don't touch)
      "__none__"           = explicitly skip artwork
      otherwise            = fetch art from this release ID once for all tracks
    """
    from library_manager import reassign_track

    settings = settings or load_settings()

    album_art = None
    if art_url:
        from services.conversion import _download_art
        album_art = _download_art(art_url, settings.get("art_max_size", 1200),
                                  settings.get("art_quality", 90))
    elif art_release_id != "__none__":
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
