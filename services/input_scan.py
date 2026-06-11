"""Input-folder scanning for the Convert flow. Moved from app.py (Phase 1)."""

from pathlib import Path

from cue_parser import parse_cue_file, cue_to_metadata
from file_manager import scan_wav_files, get_folder_album_info, group_files_by_album


def scan_input_folder(folder_path: str) -> dict:
    """Scan a folder for WAV files and auto-detect CUE sheet(s).

    Handles multiple albums in the same folder by detecting multiple CUE sheets
    or grouping by parsed album names / track number resets.
    """
    if not folder_path or not Path(folder_path).exists():
        return {"error": "Input folder not set or does not exist", "files": []}

    files = scan_wav_files(folder_path)
    album_info = get_folder_album_info(folder_path)

    folder_p = Path(folder_path)
    cue_files = sorted(folder_p.glob("*.cue"), key=lambda p: p.name.lower())
    parsed_cues = []
    for cp in cue_files:
        try:
            parsed_cues.append(parse_cue_file(str(cp)))
        except Exception:
            pass

    album_groups = group_files_by_album(files, parsed_cues if parsed_cues else None)

    cue_metadata = None
    if len(parsed_cues) == 1 and len(album_groups) <= 1:
        cue_data = parsed_cues[0]
        cue_metadata = cue_to_metadata(cue_data)

        if cue_metadata["album"].get("artist"):
            album_info["artist"] = cue_metadata["album"]["artist"]
        if cue_metadata["album"].get("album"):
            album_info["album"] = cue_metadata["album"]["album"]
        if cue_metadata["album"].get("date"):
            album_info["year"] = cue_metadata["album"]["date"]

        for i, f in enumerate(files):
            if i < len(cue_metadata["tracks"]):
                cue_track = cue_metadata["tracks"][i]
                if cue_track.get("title"):
                    f["parsed_title"] = cue_track["title"]
                if cue_track.get("artist"):
                    f["parsed_artist"] = cue_track["artist"]
                if cue_track.get("tracknumber"):
                    try:
                        f["parsed_track_number"] = int(cue_track["tracknumber"])
                    except ValueError:
                        pass
                f["isrc"] = cue_track.get("isrc", "")
            if cue_metadata["album"].get("album"):
                f["parsed_album"] = cue_metadata["album"]["album"]
    elif len(album_groups) > 1:
        # Multiple albums: use the first group's info for the header,
        # flatten enriched files back for the file list display
        first = album_groups[0]
        if first.get("artist"):
            album_info["artist"] = first["artist"]
        if first.get("album"):
            album_info["album"] = first["album"]
        files = []
        for g in album_groups:
            files.extend(g["files"])

    return {
        "files": files,
        "album_info": album_info,
        "folder": folder_path,
        "cue_found": len(parsed_cues) > 0,
        "cue_path": str(cue_files[0]) if cue_files else None,
        "cue_metadata": cue_metadata,
        "album_groups": [
            {
                "album": g["album"],
                "artist": g["artist"],
                "file_count": len(g["files"]),
                "cue_metadata": g.get("cue_metadata"),
            }
            for g in album_groups
        ] if len(album_groups) > 1 else None,
        "multi_album": len(album_groups) > 1,
    }
