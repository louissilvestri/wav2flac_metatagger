"""CUE sheet parser for EAC-generated .cue files.

Parses disc-level and track-level metadata, computes MusicBrainz disc IDs
from INDEX 01 frame offsets, and extracts CATALOG/ISRC codes.
"""

import re
import hashlib
import base64
import wave
from pathlib import Path


def parse_cue_file(cue_path: str) -> dict:
    """Parse a CUE sheet file into structured data.

    Returns:
        {
            "file_path": str,
            "performer": str,        # disc-level artist
            "title": str,            # album title
            "catalog": str,          # UPC/EAN barcode
            "rem": {                 # REM fields
                "GENRE": str,
                "DATE": str,
                "DISCID": str,       # freedb disc ID
                "DISCNUMBER": str,
                "TOTALDISCS": str,
                ...
            },
            "file_ref": str,         # FILE directive filename
            "file_type": str,        # WAVE, MP3, etc.
            "tracks": [
                {
                    "number": int,
                    "type": str,          # AUDIO, etc.
                    "title": str,
                    "performer": str,
                    "isrc": str,
                    "songwriter": str,
                    "indices": {0: frames, 1: frames, ...},
                    "pregap": int|None,   # frames
                    "flags": [str],
                },
                ...
            ],
        }
    """
    path = Path(cue_path)
    if not path.exists():
        raise FileNotFoundError(f"CUE file not found: {cue_path}")

    # EAC saves CUE files in Windows-1252 (ANSI) by default.
    # Try UTF-8 first (handles BOM too), fall back to Windows-1252.
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw[3:].decode("utf-8")
    else:
        try:
            text = raw.decode("utf-8")
            # Verify no replacement chars would be needed
            raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")

    disc = {
        "file_path": str(path),
        "performer": "",
        "title": "",
        "catalog": "",
        "songwriter": "",
        "rem": {},
        "file_ref": "",
        "file_type": "",
        "tracks": [],
    }

    current_track = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # REM lines
        m = re.match(r'REM\s+(\S+)\s+(.*)', line)
        if m:
            key = m.group(1).upper()
            value = m.group(2).strip().strip('"')
            disc["rem"][key] = value
            continue

        # CATALOG (13-digit UPC/EAN)
        m = re.match(r'CATALOG\s+(\d{13})', line)
        if m:
            disc["catalog"] = m.group(1)
            continue

        # FILE directive
        m = re.match(r'FILE\s+"(.+?)"\s+(\w+)', line)
        if m:
            disc["file_ref"] = m.group(1)
            disc["file_type"] = m.group(2)
            continue

        # PERFORMER (disc or track level)
        m = re.match(r'PERFORMER\s+"(.*?)"', line)
        if m:
            if current_track is None:
                disc["performer"] = m.group(1)
            else:
                current_track["performer"] = m.group(1)
            continue

        # TITLE (disc or track level)
        m = re.match(r'TITLE\s+"(.*?)"', line)
        if m:
            if current_track is None:
                disc["title"] = m.group(1)
            else:
                current_track["title"] = m.group(1)
            continue

        # SONGWRITER (disc or track level)
        m = re.match(r'SONGWRITER\s+"(.*?)"', line)
        if m:
            if current_track is None:
                disc["songwriter"] = m.group(1)
            else:
                current_track["songwriter"] = m.group(1)
            continue

        # TRACK
        m = re.match(r'TRACK\s+(\d+)\s+(\w+)', line)
        if m:
            current_track = {
                "number": int(m.group(1)),
                "type": m.group(2),
                "title": "",
                "performer": "",
                "isrc": "",
                "songwriter": "",
                "indices": {},
                "pregap": None,
                "flags": [],
            }
            disc["tracks"].append(current_track)
            continue

        # INDEX
        m = re.match(r'INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)', line)
        if m and current_track is not None:
            idx_num = int(m.group(1))
            mm = int(m.group(2))
            ss = int(m.group(3))
            ff = int(m.group(4))
            frames = (mm * 60 + ss) * 75 + ff
            current_track["indices"][idx_num] = frames
            continue

        # ISRC
        m = re.match(r'ISRC\s+(\w{12})', line)
        if m and current_track is not None:
            current_track["isrc"] = m.group(1)
            continue

        # FLAGS
        m = re.match(r'FLAGS\s+(.+)', line)
        if m and current_track is not None:
            current_track["flags"] = m.group(1).split()
            continue

        # PREGAP
        m = re.match(r'PREGAP\s+(\d+):(\d+):(\d+)', line)
        if m and current_track is not None:
            mm = int(m.group(1))
            ss = int(m.group(2))
            ff = int(m.group(3))
            current_track["pregap"] = (mm * 60 + ss) * 75 + ff
            continue

    # Inherit disc-level performer to tracks that don't have their own
    for track in disc["tracks"]:
        if not track["performer"]:
            track["performer"] = disc["performer"]

    disc["tracks"].sort(key=lambda t: t["number"])
    return disc


def _is_multi_wav_cue(cue_data: dict) -> bool:
    """Check if all track INDEX 01 values are 00:00:00 (multi-WAV CUE)."""
    tracks = cue_data.get("tracks", [])
    if len(tracks) < 2:
        return False
    for track in tracks:
        idx01 = track.get("indices", {}).get(1, -1)
        if idx01 != 0:
            return False
    return True


def compute_offsets_from_wavs(cue_folder: str) -> list[int] | None:
    """Compute track frame offsets from WAV file durations.

    For multi-WAV CUE sheets where INDEX 01 is always 00:00:00,
    the real offsets must be calculated from cumulative WAV file lengths.
    Returns offsets in CD frames (75fps) including 150-frame lead-in.
    """
    folder = Path(cue_folder)
    wav_files = sorted(folder.glob("*.wav"), key=lambda p: p.name.lower())
    if not wav_files:
        return None

    offsets = []
    cumulative_frames = 150  # Start with lead-in

    for wav_path in wav_files:
        offsets.append(cumulative_frames)
        try:
            with wave.open(str(wav_path), "rb") as wf:
                sample_rate = wf.getframerate()
                num_samples = wf.getnframes()
                duration_seconds = num_samples / sample_rate
                cumulative_frames += int(duration_seconds * 75)
        except Exception:
            return None

    return offsets


def get_leadout_from_wav_files(cue_folder: str, wav_files: list[str]) -> int | None:
    """Calculate the lead-out offset from WAV file durations.

    For multi-file CUE sheets, the lead-out is the sum of all track durations
    in CD frames (1/75 second) plus the 150-frame lead-in offset.
    """
    total_frames = 0
    for wav_path in wav_files:
        full_path = Path(cue_folder) / wav_path if not Path(wav_path).is_absolute() else Path(wav_path)
        if not full_path.exists():
            return None
        try:
            with wave.open(str(full_path), "rb") as wf:
                sample_rate = wf.getframerate()
                num_samples = wf.getnframes()
                duration_seconds = num_samples / sample_rate
                total_frames += int(duration_seconds * 75)
        except Exception:
            return None
    return total_frames + 150  # Add lead-in offset


def get_leadout_from_cue_and_wavs(cue_data: dict, cue_folder: str) -> int | None:
    """Calculate lead-out by scanning the actual WAV files in the CUE folder.

    Tries multiple strategies:
    1. Sum all WAV file durations found in the folder
    2. Use the single WAV file referenced in the CUE
    """
    folder = Path(cue_folder)

    # Strategy 1: Find all WAV files matching the tracks
    wav_files = sorted(folder.glob("*.wav"), key=lambda p: p.name.lower())
    if wav_files:
        return get_leadout_from_wav_files(cue_folder, [str(f) for f in wav_files])

    # Strategy 2: Use the FILE reference from the CUE
    if cue_data.get("file_ref"):
        ref_path = folder / cue_data["file_ref"]
        if ref_path.exists():
            return get_leadout_from_wav_files(cue_folder, [str(ref_path)])

    return None


def calculate_musicbrainz_discid(cue_data: dict, leadout_offset: int, cue_folder: str = None) -> str:
    """Calculate a MusicBrainz disc ID from parsed CUE data.

    The disc ID is a SHA-1 hash (MusicBrainz-modified Base64) of:
    - First track number, last track number
    - Lead-out offset (in sectors, including 150 lead-in)
    - Track start offsets (INDEX 01 values + 150 lead-in)

    For multi-WAV CUE sheets, computes real offsets from WAV file durations.

    Args:
        cue_data: Parsed CUE sheet dict from parse_cue_file()
        leadout_offset: Lead-out position in frames (including 150 lead-in)
        cue_folder: Folder containing the WAV files (required for multi-WAV CUEs)

    Returns:
        28-character MusicBrainz disc ID string
    """
    tracks = cue_data["tracks"]
    if not tracks:
        raise ValueError("No tracks found in CUE data")

    first_track = tracks[0]["number"]
    last_track = tracks[-1]["number"]

    # Build the offset array: index 0 = lead-out, indices 1-99 = track offsets
    offsets = [0] * 100
    offsets[0] = leadout_offset

    # For multi-WAV CUEs, compute real offsets from WAV file durations
    if _is_multi_wav_cue(cue_data) and cue_folder:
        wav_offsets = compute_offsets_from_wavs(cue_folder)
        if wav_offsets and len(wav_offsets) == len(tracks):
            for i, track in enumerate(tracks):
                offsets[track["number"]] = wav_offsets[i]
        else:
            raise ValueError("Could not compute offsets from WAV files")
    else:
        for track in tracks:
            # INDEX 01 is the actual track start; add 150 for lead-in
            if 1 in track["indices"]:
                offset = track["indices"][1] + 150
            elif 0 in track["indices"]:
                offset = track["indices"][0] + 150
            else:
                raise ValueError(f"Track {track['number']} has no INDEX 01 or INDEX 00")
            offsets[track["number"]] = offset

    # Build hash input string
    hash_input = f"{first_track:02X}{last_track:02X}"
    for offset in offsets:
        hash_input += f"{offset:08X}"

    # SHA-1 hash
    sha1_digest = hashlib.sha1(hash_input.encode("ascii")).digest()

    # MusicBrainz-modified Base64 encoding
    b64 = base64.b64encode(sha1_digest).decode("ascii")
    disc_id = b64.replace("+", ".").replace("/", "_").replace("=", "-")

    return disc_id


def get_toc_for_musicbrainz(cue_data: dict, leadout_offset: int, cue_folder: str = None) -> dict:
    """Extract TOC data for MusicBrainz fuzzy lookup.

    For multi-WAV CUE sheets (all INDEX 01 at 00:00:00), computes real
    offsets from WAV file durations when cue_folder is provided.

    Returns:
        {
            "first_track": int,
            "last_track": int,
            "leadout_offset": int,
            "track_offsets": [int, ...],  # Frame offsets including 150 lead-in
            "track_count": int,
        }
    """
    tracks = cue_data["tracks"]

    # For multi-WAV CUEs, compute offsets from WAV file durations
    if _is_multi_wav_cue(cue_data) and cue_folder:
        wav_offsets = compute_offsets_from_wavs(cue_folder)
        if wav_offsets and len(wav_offsets) == len(tracks):
            return {
                "first_track": tracks[0]["number"] if tracks else 1,
                "last_track": tracks[-1]["number"] if tracks else 0,
                "leadout_offset": leadout_offset,
                "track_offsets": wav_offsets,
                "track_count": len(tracks),
            }

    # Single-WAV CUE: use INDEX 01 values directly
    track_offsets = []
    for track in tracks:
        if 1 in track["indices"]:
            offset = track["indices"][1] + 150
        elif 0 in track["indices"]:
            offset = track["indices"][0] + 150
        else:
            continue
        track_offsets.append(offset)

    return {
        "first_track": tracks[0]["number"] if tracks else 1,
        "last_track": tracks[-1]["number"] if tracks else 0,
        "leadout_offset": leadout_offset,
        "track_offsets": track_offsets,
        "track_count": len(tracks),
    }


def cue_to_metadata(cue_data: dict) -> dict:
    """Convert parsed CUE data to a metadata dict suitable for tagging.

    Returns album-level metadata and a list of per-track metadata.
    """
    album_meta = {
        "artist": cue_data.get("performer", ""),
        "album": cue_data.get("title", ""),
        "date": cue_data.get("rem", {}).get("DATE", ""),
        "genre": cue_data.get("rem", {}).get("GENRE", ""),
        "barcode": cue_data.get("catalog", ""),
        "discnumber": cue_data.get("rem", {}).get("DISCNUMBER", "1"),
        "disctotal": cue_data.get("rem", {}).get("TOTALDISCS", "1"),
        "freedb_discid": cue_data.get("rem", {}).get("DISCID", ""),
    }

    tracks_meta = []
    for track in cue_data.get("tracks", []):
        track_meta = {
            "tracknumber": str(track["number"]),
            "title": track.get("title", ""),
            "artist": track.get("performer", album_meta["artist"]),
            "isrc": track.get("isrc", ""),
            "songwriter": track.get("songwriter", ""),
        }
        tracks_meta.append(track_meta)

    return {
        "album": album_meta,
        "tracks": tracks_meta,
        "track_count": len(tracks_meta),
    }


def find_cue_file(folder: str) -> str | None:
    """Look for a .cue file in the given folder."""
    folder_path = Path(folder)
    cue_files = list(folder_path.glob("*.cue"))
    if not cue_files:
        return None
    # If multiple, prefer the one with the most content
    if len(cue_files) == 1:
        return str(cue_files[0])
    # Pick the largest CUE file (most likely the complete one)
    return str(max(cue_files, key=lambda f: f.stat().st_size))
