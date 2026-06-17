"""File management: Plex folder structure, naming, and network copy."""

import re
import shutil
from pathlib import Path

from config import load_settings
# Single shared implementation — folder/artist matching uses the same fold as
# the rest of the app (see text_utils for the fold_for_compare/fold_loose split).
from text_utils import fold_loose as _normalize_for_compare


def sanitize_filename(name: str) -> str:
    """Remove or replace characters invalid in Windows filenames."""
    invalid = r'<>:"/\|?*'
    for ch in invalid:
        name = name.replace(ch, "")
    name = name.strip(". ")
    name = re.sub(r"\s+", " ", name)
    return name[:200]  # Limit length


def find_existing_folder(parent: Path, target_name: str) -> str | None:
    """Find an existing subfolder that fuzzy-matches target_name.

    Returns the actual folder name on disk if found, otherwise None.
    """
    if not parent.is_dir():
        return None

    target_norm = _normalize_for_compare(target_name)
    if not target_norm:
        return None

    for entry in parent.iterdir():
        if entry.is_dir():
            if _normalize_for_compare(entry.name) == target_norm:
                return entry.name

    return None


def build_output_path(
    output_root: str,
    artist: str,
    album: str,
    year: str = "",
    disc_number: int = 1,
    total_discs: int = 1,
    track_number: int = 1,
    title: str = "Unknown",
    multi_disc_style: str = "subfolder",
) -> Path:
    """Build the full output path following Plex conventions.

    Structure: Artist/Album (Year)/[Disc N/]NN - Title.flac

    Uses fuzzy matching to reuse existing artist/album folders instead
    of creating duplicates with slightly different naming.
    """
    root = Path(output_root)

    # Artist folder — check for fuzzy match first
    artist_sanitized = sanitize_filename(artist) if artist else "Unknown Artist"
    existing_artist = find_existing_folder(root, artist_sanitized)
    artist_folder = existing_artist if existing_artist else artist_sanitized

    # Album folder with year
    album_name = sanitize_filename(album) if album else "Unknown Album"
    if year:
        year_str = year[:4]
        album_with_year = f"{album_name} ({year_str})"
    else:
        album_with_year = album_name

    artist_path = root / artist_folder
    existing_album = find_existing_folder(artist_path, album_with_year)
    # Also check without year in case existing folder doesn't have it
    if not existing_album:
        existing_album = find_existing_folder(artist_path, album_name)
    album_folder = existing_album if existing_album else album_with_year

    # Track filename: zero-padded number - title
    track_num_str = f"{track_number:02d}"
    track_title = sanitize_filename(title) if title else f"Track {track_num_str}"
    filename = f"{track_num_str} - {track_title}.flac"

    # Build path
    base = root / artist_folder / album_folder

    if total_discs > 1 and multi_disc_style == "subfolder":
        base = base / f"Disc {disc_number}"

    return base / filename


def copy_to_network(source_path: str, dest_path: str, overwrite: bool = False) -> dict:
    """Copy a file to the network/output location."""
    src = Path(source_path)
    dst = Path(dest_path)

    if not src.exists():
        return {"success": False, "dest_path": str(dst), "bytes_copied": 0, "error": "Source file not found"}

    if dst.exists() and not overwrite:
        return {"success": False, "dest_path": str(dst), "bytes_copied": 0, "error": "Destination file already exists"}

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return {
            "success": True,
            "dest_path": str(dst),
            "bytes_copied": dst.stat().st_size,
            "error": None,
        }
    except Exception as e:
        return {"success": False, "dest_path": str(dst), "bytes_copied": 0, "error": str(e)}


def scan_wav_files(folder: str) -> list[dict]:
    """Scan a folder for WAV files, attempting to parse EAC naming patterns.

    EAC typically names files like: "Artist - Album - 01 - Track Title.wav"
    or just the track name if configured differently.
    """
    folder_path = Path(folder)
    if not folder_path.exists():
        return []

    wav_files = sorted(folder_path.glob("*.wav"), key=lambda p: p.name.lower())
    results = []

    for wav in wav_files:
        info = {
            "path": str(wav),
            "filename": wav.name,
            "size": wav.stat().st_size,
            "parsed_artist": "",
            "parsed_album": "",
            "parsed_track_number": 0,
            "parsed_title": "",
        }

        stem = wav.stem
        # Try EAC pattern: "Artist - Album - NN - Title"
        parts = [p.strip() for p in stem.split(" - ")]
        if len(parts) == 4:
            info["parsed_artist"] = parts[0]
            info["parsed_album"] = parts[1]
            try:
                info["parsed_track_number"] = int(parts[2])
            except ValueError:
                pass
            info["parsed_title"] = parts[3]
        elif len(parts) == 3:
            try:
                info["parsed_track_number"] = int(parts[0])
                info["parsed_title"] = parts[1]
            except ValueError:
                info["parsed_artist"] = parts[0]
                info["parsed_album"] = parts[1]
                info["parsed_title"] = parts[2]
        elif len(parts) == 2:
            try:
                info["parsed_track_number"] = int(parts[0])
                info["parsed_title"] = parts[1]
            except ValueError:
                info["parsed_title"] = stem
        else:
            # "NN - Title", "NN. Title", "NN_Title", or "NN Title" (space only)
            match = re.match(r"^(\d+)[\s\-._]+(.+)$", stem)
            if match:
                info["parsed_track_number"] = int(match.group(1))
                info["parsed_title"] = match.group(2).strip()
            else:
                info["parsed_title"] = stem

        results.append(info)

    return results


def group_files_by_album(files: list[dict], cue_sheets: list[dict] = None) -> list[dict]:
    """Group WAV files into separate albums when multiple are in the same folder.

    Grouping strategy:
    1. If CUE sheets exist, each CUE defines an album
    2. If files have parsed_album from EAC naming, group by album name
    3. If track numbers reset (e.g. 1 appears twice), split into groups
    4. Otherwise treat as single album

    Returns list of album groups:
    [{
        "album": str, "artist": str,
        "files": [file_info, ...],
        "cue_data": parsed_cue or None,
        "cue_metadata": cue_to_metadata result or None,
    }, ...]
    """
    if not files:
        return []

    # Strategy 1: Multiple CUE sheets → one album per CUE
    if cue_sheets and len(cue_sheets) > 1:
        from cue_parser import cue_to_metadata
        groups = []
        assigned = set()

        for cue_data in cue_sheets:
            cue_meta = cue_to_metadata(cue_data)
            album_name = cue_meta["album"].get("album", "")
            artist_name = cue_meta["album"].get("artist", "")
            cue_track_titles = [t.get("title", "").lower() for t in cue_meta["tracks"]]

            group_files = []
            for f in files:
                if f["path"] in assigned:
                    continue
                # Match by title or by sequential assignment
                ftitle = f.get("parsed_title", "").lower()
                falbum = f.get("parsed_album", "").lower()
                if ftitle and ftitle in cue_track_titles:
                    group_files.append(f)
                    assigned.add(f["path"])
                elif falbum and falbum.lower() == album_name.lower():
                    group_files.append(f)
                    assigned.add(f["path"])

            # If title matching didn't work, assign by track count
            if not group_files:
                expected = cue_meta["track_count"]
                for f in files:
                    if f["path"] not in assigned:
                        group_files.append(f)
                        assigned.add(f["path"])
                        if len(group_files) >= expected:
                            break

            if group_files:
                # Enrich files with CUE metadata
                for i, f in enumerate(group_files):
                    if i < len(cue_meta["tracks"]):
                        ct = cue_meta["tracks"][i]
                        if ct.get("title"):
                            f["parsed_title"] = ct["title"]
                        if ct.get("artist"):
                            f["parsed_artist"] = ct["artist"]
                        if ct.get("tracknumber"):
                            try:
                                f["parsed_track_number"] = int(ct["tracknumber"])
                            except ValueError:
                                pass
                        f["isrc"] = ct.get("isrc", "")
                    f["parsed_album"] = album_name

                groups.append({
                    "album": album_name,
                    "artist": artist_name,
                    "files": group_files,
                    "cue_data": cue_data,
                    "cue_metadata": cue_meta,
                })

        # Any unassigned files go in a catch-all group
        unassigned = [f for f in files if f["path"] not in assigned]
        if unassigned:
            groups.append({
                "album": unassigned[0].get("parsed_album", "Unknown Album"),
                "artist": unassigned[0].get("parsed_artist", "Unknown Artist"),
                "files": unassigned,
                "cue_data": None,
                "cue_metadata": None,
            })

        return groups

    # Strategy 2: Group by parsed_album from filenames
    albums_seen = {}
    for f in files:
        album = f.get("parsed_album", "")
        if album:
            albums_seen.setdefault(album, []).append(f)

    if len(albums_seen) > 1:
        groups = []
        for album_name, album_files in albums_seen.items():
            artist = album_files[0].get("parsed_artist", "")
            groups.append({
                "album": album_name,
                "artist": artist,
                "files": album_files,
                "cue_data": None,
                "cue_metadata": None,
            })
        return groups

    # Strategy 3: Detect track number resets (1, 2, ..., N, 1, 2, ..., M)
    track_nums = [f.get("parsed_track_number", 0) for f in files]
    if track_nums and any(n > 0 for n in track_nums):
        split_points = []
        for i in range(1, len(track_nums)):
            if track_nums[i] > 0 and track_nums[i] <= track_nums[i - 1] and track_nums[i] == 1:
                split_points.append(i)

        if split_points:
            groups = []
            boundaries = [0] + split_points + [len(files)]
            for g_idx in range(len(boundaries) - 1):
                group_files = files[boundaries[g_idx]:boundaries[g_idx + 1]]
                album = group_files[0].get("parsed_album", f"Album {g_idx + 1}")
                artist = group_files[0].get("parsed_artist", "")
                groups.append({
                    "album": album,
                    "artist": artist,
                    "files": group_files,
                    "cue_data": None,
                    "cue_metadata": None,
                })
            return groups

    # Strategy 4: Single album
    album = files[0].get("parsed_album", "") if files else ""
    artist = files[0].get("parsed_artist", "") if files else ""
    return [{
        "album": album,
        "artist": artist,
        "files": files,
        "cue_data": None,
        "cue_metadata": None,
    }]


def get_folder_album_info(folder: str) -> dict:
    """Try to determine album info from folder name and parent structure."""
    folder_path = Path(folder)
    name = folder_path.name
    parent = folder_path.parent.name

    info = {"artist": "", "album": "", "year": ""}

    if " - " in name:
        parts = name.split(" - ", 1)
        info["artist"] = parts[0].strip()
        info["album"] = parts[1].strip()
    else:
        info["album"] = name
        if parent and parent not in ("", ".", "/", "\\"):
            info["artist"] = parent

    year_match = re.search(r"[\(\[]((?:19|20)\d{2})[\)\]]", info["album"])
    if year_match:
        info["year"] = year_match.group(1)
        info["album"] = re.sub(r"\s*[\(\[](?:19|20)\d{2}[\)\]]\s*", "", info["album"]).strip()

    return info


def cleanup_source_files(folder: str, wav_files: list[str]):
    """Delete WAV, CUE, and art files from the source folder after conversion.

    Only called when delete_wav_after_convert is enabled and all files succeeded.
    """
    folder_path = Path(folder)

    # Delete the specific WAV files that were converted
    for wav in wav_files:
        p = Path(wav)
        if p.exists():
            p.unlink()

    # Delete CUE files
    for cue in folder_path.glob("*.cue"):
        cue.unlink()

    # Delete all image files (art is already embedded in the FLAC files)
    art_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".tif"}
    for f in folder_path.iterdir():
        if f.is_file() and f.suffix.lower() in art_extensions:
            f.unlink()

    # Delete EAC log files
    for log in folder_path.glob("*.log"):
        log.unlink()
