"""Main application: Eel web UI backend."""

import eel
import os
import sys
import json
import subprocess
import threading
import tempfile
import time
import webbrowser
from pathlib import Path

from config import (
    load_settings, save_settings, APP_NAME, APP_VERSION,
    PLEX_DISPLAY_FIELDS, PLEX_MATCH_FIELDS, PLEX_OPTIONAL_FIELDS, PLEX_ALL_FIELDS,
)
from database import init_db, log_conversion, update_conversion, get_recent_logs, get_stats
from encoder import encode_to_flac, get_wav_info, find_flac_exe
from metadata_lookup import (
    search_release, get_release_details, get_cover_art,
    automated_lookup, lookup_by_discid,
)
from tagger import embed_metadata, build_metadata_from_release, read_metadata
from file_manager import (
    build_output_path,
    copy_to_network,
    scan_wav_files,
    get_folder_album_info,
    group_files_by_album,
    cleanup_source_files,
)
from cue_parser import (
    parse_cue_file, find_cue_file, cue_to_metadata,
    calculate_musicbrainz_discid, get_leadout_from_cue_and_wavs,
    get_toc_for_musicbrainz,
)
from PIL import Image
from io import BytesIO
import base64

# Initialize Eel with the web folder
eel.init(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

# Active conversion state
_conversion_active = False
_conversion_cancel = False

# Common image file extensions EAC and other tools save
_ART_FILENAMES = [
    "folder.jpg", "folder.png", "folder.bmp",
    "cover.jpg", "cover.png", "cover.bmp",
    "front.jpg", "front.png", "front.bmp",
    "album.jpg", "album.png", "album.bmp",
    "albumart.jpg", "albumart.png", "albumart.bmp",
    "albumartsmall.jpg",
]

# Aliases for backward compat within this module
_PLEX_DISPLAY_FIELDS = PLEX_DISPLAY_FIELDS
_PLEX_MATCH_FIELDS = PLEX_MATCH_FIELDS
_PLEX_OPTIONAL_FIELDS = PLEX_OPTIONAL_FIELDS
_PLEX_ALL_FIELDS = PLEX_ALL_FIELDS


def _get_image_resolution(image_data: bytes) -> tuple[int, int]:
    """Get (width, height) from raw image bytes."""
    try:
        img = Image.open(BytesIO(image_data))
        return img.width, img.height
    except Exception:
        return 0, 0


def _prepare_art(image_data: bytes, max_size: int, quality: int) -> bytes:
    """Resize and convert image to JPEG for embedding."""
    img = Image.open(BytesIO(image_data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if img.width > max_size or img.height > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    output = BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


def find_local_art_raw(folder: str) -> tuple[bytes | None, str | None]:
    """Find local album art and return raw bytes + filename. No resizing."""
    folder_path = Path(folder)
    if not folder_path.is_dir():
        return None, None

    all_files = {f.name.lower(): f for f in folder_path.iterdir() if f.is_file()}
    found = None
    for name in _ART_FILENAMES:
        if name in all_files:
            found = all_files[name]
            break

    if not found:
        for f in folder_path.iterdir():
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"):
                found = f
                break

    # Fallback: check extensionless files by reading magic bytes (EAC drops
    # the .jpg extension when the album title contains punctuation like ! or ')
    if not found:
        _IMAGE_MAGIC = {
            b'\xff\xd8\xff': 'jpeg',
            b'\x89PNG': 'png',
            b'BM': 'bmp',
            b'GIF8': 'gif',
            b'RIFF': 'webp',  # RIFF....WEBP
        }
        for f in folder_path.iterdir():
            if f.is_file() and f.suffix == '' and not f.name.endswith('.log'):
                try:
                    header = f.read_bytes()[:8]
                    if any(header.startswith(magic) for magic in _IMAGE_MAGIC):
                        found = f
                        break
                except Exception:
                    continue

    if not found:
        return None, None

    try:
        return found.read_bytes(), found.name
    except Exception:
        return None, None


def find_local_art(folder: str, max_size: int = 1200, quality: int = 90) -> bytes | None:
    """Find and prepare local art for embedding."""
    raw, _ = find_local_art_raw(folder)
    if raw:
        try:
            return _prepare_art(raw, max_size, quality)
        except Exception:
            return None
    return None


def _fetch_art_for_provider(release_id: str, settings: dict) -> bytes | None:
    """Fetch album art using the active metadata provider.

    Returns prepared JPEG bytes ready for embedding, or None.
    """
    provider = settings.get("metadata_provider", "musicbrainz")
    max_size = settings.get("art_max_size", 1200)
    quality = settings.get("art_quality", 90)

    if provider == "discogs":
        from discogs_lookup import get_cover_art as discogs_art
        return discogs_art(release_id, max_size=max_size, quality=quality)
    else:
        art_result = select_best_art(
            release_id=release_id,
            folder=None,
            max_size=max_size,
            quality=quality,
        )
        return art_result.get("bytes")


def select_best_art(
    release_id: str | None,
    folder: str | None,
    max_size: int = 1200,
    quality: int = 90,
) -> dict:
    """Compare album art from all sources and select the highest resolution.

    Returns: {
        "data": base64 string (ready for UI preview),
        "bytes": raw bytes (for embedding),
        "source": "coverartarchive" | "local" | None,
        "width": int, "height": int,
        "candidates": [{source, width, height, pixels}, ...]
    }
    """
    candidates = []

    # Source 1: Cover Art Archive
    caa_raw = None
    if release_id:
        from metadata_lookup import get_cover_art
        settings = load_settings()
        # Fetch at full resolution first (don't resize yet) for comparison
        caa_raw = get_cover_art(release_id, max_size=9999, quality=95)
        if caa_raw:
            w, h = _get_image_resolution(caa_raw)
            candidates.append({
                "source": "coverartarchive",
                "width": w, "height": h,
                "pixels": w * h,
                "raw": caa_raw,
            })

    # Source 2: Local folder (EAC art)
    local_raw = None
    if folder:
        local_raw, local_name = find_local_art_raw(folder)
        if local_raw:
            w, h = _get_image_resolution(local_raw)
            candidates.append({
                "source": "local",
                "source_file": local_name,
                "width": w, "height": h,
                "pixels": w * h,
                "raw": local_raw,
            })

    if not candidates:
        return {
            "data": None, "bytes": None, "source": None,
            "width": 0, "height": 0, "candidates": [],
        }

    # Pick highest resolution (by pixel count)
    candidates.sort(key=lambda c: c["pixels"], reverse=True)
    best = candidates[0]

    # Prepare the winner for embedding (resize to max_size, convert to JPEG)
    try:
        prepared = _prepare_art(best["raw"], max_size, quality)
    except Exception:
        prepared = None

    # Build candidate summary for UI — include a 200px thumbnail for each
    candidate_summary = []
    for c in candidates:
        thumb = None
        try:
            thumb_bytes = _prepare_art(c["raw"], max_size=200, quality=70)
            thumb = base64.b64encode(thumb_bytes).decode("ascii")
        except Exception:
            pass
        candidate_summary.append({
            "source": c["source"], "width": c["width"], "height": c["height"],
            "pixels": c["pixels"], "selected": c is best, "thumb": thumb,
        })

    return {
        "data": base64.b64encode(prepared).decode("ascii") if prepared else None,
        "bytes": prepared,
        "source": best["source"],
        "width": best["width"],
        "height": best["height"],
        "candidates": candidate_summary,
    }


def calculate_metadata_completeness(metadata: dict, has_art: bool = False) -> dict:
    """Calculate metadata completeness percentage based on Plex-supported fields.

    Returns: {
        "percentage": int (0-100),
        "filled": int,
        "total": int,
        "fields": {field_name: {"status": "filled"|"missing", "category": "display"|"match"|"optional"}, ...},
        "has_art": bool,
    }
    """
    fields = {}
    filled = 0
    total = 0

    # Normalize metadata keys to uppercase for comparison
    meta_upper = {k.upper(): v for k, v in metadata.items()}

    for field in _PLEX_DISPLAY_FIELDS:
        total += 1
        val = meta_upper.get(field, "")
        is_filled = bool(val and str(val).strip())
        if is_filled:
            filled += 1
        fields[field] = {"status": "filled" if is_filled else "missing", "category": "display"}

    for field in _PLEX_MATCH_FIELDS:
        total += 1
        val = meta_upper.get(field, "")
        is_filled = bool(val and str(val).strip())
        if is_filled:
            filled += 1
        fields[field] = {"status": "filled" if is_filled else "missing", "category": "match"}

    for field in _PLEX_OPTIONAL_FIELDS:
        total += 1
        val = meta_upper.get(field, "")
        is_filled = bool(val and str(val).strip())
        if is_filled:
            filled += 1
        fields[field] = {"status": "filled" if is_filled else "missing", "category": "optional"}

    # Album art counts as a field
    total += 1
    if has_art:
        filled += 1
    fields["COVER_ART"] = {"status": "filled" if has_art else "missing", "category": "display"}

    pct = round((filled / total) * 100) if total > 0 else 0

    return {
        "percentage": pct,
        "filled": filled,
        "total": total,
        "fields": fields,
        "has_art": has_art,
    }


@eel.expose
def get_app_info():
    return {"name": APP_NAME, "version": APP_VERSION}


@eel.expose
def get_settings():
    return load_settings()


@eel.expose
def update_settings(new_settings):
    settings = load_settings()
    settings.update(new_settings)
    save_settings(settings)
    return {"success": True}


@eel.expose
def browse_folder(dialog_type="folder"):
    """Open a folder/file browser dialog. Returns path or empty string."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    if dialog_type == "folder":
        path = filedialog.askdirectory(title="Select Folder")
    elif dialog_type == "exe":
        path = filedialog.askopenfilename(
            title="Select flac.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
    else:
        path = filedialog.askopenfilename(title="Select File")

    root.destroy()
    return path or ""


@eel.expose
def auto_detect_flac():
    """Try to find flac.exe automatically."""
    path = find_flac_exe()
    return path or ""


@eel.expose
def scan_input_folder(folder_path=None):
    """Scan the input folder for WAV files and auto-detect CUE sheet(s).

    Handles multiple albums in the same folder by detecting multiple CUE sheets
    or grouping by parsed album names / track number resets.
    """
    if not folder_path:
        settings = load_settings()
        folder_path = settings.get("input_folder", "")
    if not folder_path or not Path(folder_path).exists():
        return {"error": "Input folder not set or does not exist", "files": []}

    files = scan_wav_files(folder_path)
    album_info = get_folder_album_info(folder_path)

    # Find ALL CUE sheets in the folder
    folder_p = Path(folder_path)
    cue_files = sorted(folder_p.glob("*.cue"), key=lambda p: p.name.lower())
    parsed_cues = []
    for cp in cue_files:
        try:
            parsed_cues.append(parse_cue_file(str(cp)))
        except Exception:
            pass

    # Group files into albums
    album_groups = group_files_by_album(files, parsed_cues if parsed_cues else None)

    # If only one group and we have a single CUE, enrich as before
    cue_data = None
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
        # Multiple albums: each group already has enriched files from group_files_by_album
        # Use the first group's info for album_info header
        first = album_groups[0]
        if first.get("artist"):
            album_info["artist"] = first["artist"]
        if first.get("album"):
            album_info["album"] = first["album"]
        # Flatten enriched files back for the file list display
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


@eel.expose
def run_automated_lookup(folder_path):
    """Run the full automated metadata lookup cascade using CUE sheet data.

    Uses the configured provider:
    - MusicBrainz: disc ID → barcode → GnuDB → fuzzy TOC → text search
    - Discogs: barcode → text search
    """
    cue_path = find_cue_file(folder_path)
    if not cue_path:
        return {"error": "No CUE sheet found", "cascade_log": [], "releases": []}

    try:
        cue_data = parse_cue_file(cue_path)
    except Exception as e:
        return {"error": f"Failed to parse CUE: {e}", "cascade_log": [], "releases": []}

    cue_meta = cue_to_metadata(cue_data)

    settings = load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")

    if provider == "discogs":
        from discogs_lookup import automated_lookup as discogs_lookup
        barcode = cue_meta["album"].get("barcode", "")
        result = discogs_lookup(
            artist=cue_meta["album"].get("artist"),
            album=cue_meta["album"].get("album"),
            barcode=barcode,
            track_count=cue_meta["track_count"],
        )
        result["disc_id"] = None
        result["cue_metadata"] = cue_meta
        return result

    # MusicBrainz cascade
    disc_id = None
    toc_data = None
    leadout = get_leadout_from_cue_and_wavs(cue_data, folder_path)

    if leadout:
        try:
            disc_id = calculate_musicbrainz_discid(cue_data, leadout, cue_folder=folder_path)
        except Exception:
            disc_id = None

        toc_data = get_toc_for_musicbrainz(cue_data, leadout, cue_folder=folder_path)

    # Get freedb disc ID from CUE (EAC writes this as REM DISCID)
    freedb_disc_id = cue_data.get("rem", {}).get("DISCID", "")

    # Calculate total disc length in seconds for GnuDB query
    total_seconds = (leadout // 75) if leadout else None

    # Run the cascade
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


@eel.expose
def lookup_metadata(artist, album, track_count=None):
    """Search for a release using the configured metadata provider."""
    settings = load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")

    if provider == "discogs":
        from discogs_lookup import search_release as discogs_search
        # Discogs uses "Various" not "Various Artists"
        search_artist = artist
        if search_artist and search_artist.lower().strip() in ("various artists", "various"):
            search_artist = ""
        return discogs_search(artist=search_artist, album=album, tracks=track_count)
    else:
        results = search_release(artist=artist, album=album, tracks=track_count)
        return results


@eel.expose
def fetch_release_details(release_id):
    """Get full track listing using the configured metadata provider."""
    settings = load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")

    if provider == "discogs":
        from discogs_lookup import get_release_details as discogs_details
        return discogs_details(release_id)
    else:
        return get_release_details(release_id)


@eel.expose
def fetch_album_art(release_id, folder_path=None):
    """Compare art from all sources, select highest resolution."""
    settings = load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")
    search_folder = folder_path or settings.get("input_folder", "")

    if provider == "discogs":
        # For Discogs, use its own art fetcher alongside local art
        from discogs_lookup import get_cover_art as discogs_art
        max_size = settings.get("art_max_size", 1200)
        quality = settings.get("art_quality", 90)

        candidates = []

        # Discogs art
        discogs_raw = discogs_art(release_id, max_size=9999, quality=95)
        if discogs_raw:
            w, h = _get_image_resolution(discogs_raw)
            candidates.append({"source": "discogs", "width": w, "height": h, "pixels": w * h, "raw": discogs_raw})

        # Local art
        if search_folder:
            local_raw, _ = find_local_art_raw(search_folder)
            if local_raw:
                w, h = _get_image_resolution(local_raw)
                candidates.append({"source": "local", "width": w, "height": h, "pixels": w * h, "raw": local_raw})

        if not candidates:
            return {"success": False, "data": None, "source": None, "width": 0, "height": 0, "candidates": []}

        candidates.sort(key=lambda c: c["pixels"], reverse=True)
        best = candidates[0]
        try:
            prepared = _prepare_art(best["raw"], max_size, quality)
        except Exception:
            prepared = None

        # Build candidate summaries with thumbnails
        candidate_summary = []
        for c in candidates:
            thumb = None
            try:
                thumb_bytes = _prepare_art(c["raw"], max_size=200, quality=70)
                thumb = base64.b64encode(thumb_bytes).decode("ascii")
            except Exception:
                pass
            candidate_summary.append({
                "source": c["source"], "width": c["width"], "height": c["height"],
                "pixels": c["pixels"], "selected": c is best, "thumb": thumb,
            })

        return {
            "success": prepared is not None,
            "data": base64.b64encode(prepared).decode("ascii") if prepared else None,
            "source": best["source"],
            "width": best["width"],
            "height": best["height"],
            "candidates": candidate_summary,
        }
    else:
        result = select_best_art(
            release_id=release_id,
            folder=search_folder,
            max_size=settings.get("art_max_size", 1200),
            quality=settings.get("art_quality", 90),
        )
        return {
            "success": result["data"] is not None,
            "data": result["data"],
            "source": result["source"],
            "width": result["width"],
            "height": result["height"],
            "candidates": result["candidates"],
        }


@eel.expose
def start_conversion(files, release_details, options=None):
    """Start the conversion process for a batch of WAV files.

    files: list of {path, track_number, disc_number, ...}
    release_details: MusicBrainz release details dict (or manual metadata)
    options: override settings for this batch
    """
    global _conversion_active, _conversion_cancel
    if _conversion_active:
        return {"error": "Conversion already in progress"}

    _conversion_active = True
    _conversion_cancel = False

    thread = threading.Thread(
        target=_run_conversion,
        args=(files, release_details, options),
        daemon=True,
    )
    thread.start()
    return {"success": True, "message": "Conversion started"}


@eel.expose
def cancel_conversion():
    global _conversion_cancel
    _conversion_cancel = True
    return {"success": True}


@eel.expose
def get_conversion_status():
    return {"active": _conversion_active}


def _run_conversion(files, release_details, options):
    """Background conversion worker."""
    global _conversion_active, _conversion_cancel
    settings = load_settings()
    if options:
        settings.update(options)

    output_folder = settings.get("output_folder", "")
    if not output_folder:
        eel.on_conversion_error("Output folder not configured")()
        _conversion_active = False
        return

    # Fetch album art: compare all sources, pick highest resolution
    album_art = None
    if settings.get("embed_album_art"):
        art_result = select_best_art(
            release_id=release_details.get("id") if release_details else None,
            folder=settings.get("input_folder", ""),
            max_size=settings.get("art_max_size", 1200),
            quality=settings.get("art_quality", 90),
        )
        album_art = art_result.get("bytes")

    total = len(files)
    for idx, file_info in enumerate(files):
        if _conversion_cancel:
            eel.on_conversion_progress({"status": "cancelled", "current": idx, "total": total})()
            break

        wav_path = file_info["path"]
        track_number = file_info.get("track_number", idx + 1)
        disc_number = file_info.get("disc_number", 1)

        eel.on_conversion_progress({
            "status": "encoding",
            "current": idx + 1,
            "total": total,
            "file": Path(wav_path).name,
        })()

        # Get WAV info
        try:
            wav_info = get_wav_info(wav_path)
        except Exception as e:
            log_conversion(source_path=wav_path, status="failed", error_message=str(e))
            eel.on_conversion_file_done({"file": wav_path, "success": False, "error": str(e)})()
            continue

        # Build metadata
        metadata = {}
        if release_details and not release_details.get("error"):
            metadata = build_metadata_from_release(release_details, disc_number, track_number)
        else:
            metadata = {
                "title": file_info.get("parsed_title", f"Track {track_number:02d}"),
                "artist": file_info.get("parsed_artist", "Unknown Artist"),
                "album": file_info.get("parsed_album", "Unknown Album"),
                "tracknumber": str(track_number),
                "discnumber": str(disc_number),
            }

        # Log start
        row_id = log_conversion(
            source_path=wav_path,
            status="started",
            source_sample_rate=wav_info["sample_rate"],
            source_bit_depth=wav_info["bit_depth"],
            source_channels=wav_info["channels"],
            flac_compression_level=settings.get("compression_level", 8),
            file_size_before=wav_info["file_size"],
            artist=metadata.get("artist", ""),
            album=metadata.get("album", ""),
            title=metadata.get("title", ""),
            track_number=track_number,
            disc_number=disc_number,
            metadata_source="musicbrainz" if release_details and release_details.get("id") else "filename",
            musicbrainz_release_id=release_details.get("id", "") if release_details else "",
        )

        # Determine output path
        total_discs = int(metadata.get("disctotal", "1"))
        dest_path = build_output_path(
            output_root=output_folder,
            artist=metadata.get("albumartist", metadata.get("artist", "Unknown Artist")),
            album=metadata.get("album", "Unknown Album"),
            year=metadata.get("date", ""),
            disc_number=disc_number,
            total_discs=total_discs,
            track_number=track_number,
            title=metadata.get("title", ""),
            multi_disc_style=settings.get("multi_disc_style", "subfolder"),
        )

        # Remove any existing track with the same number but different title
        # (prevents duplicates when re-ripping with different metadata source)
        dest_folder = dest_path.parent
        if dest_folder.exists():
            track_prefix = f"{track_number:02d} - "
            for existing in dest_folder.glob(f"{track_prefix}*.flac"):
                if existing.name != dest_path.name:
                    existing.unlink()

        # Encode to temp first, then tag, then move
        temp_dir = Path(tempfile.gettempdir()) / "music_manager"
        temp_dir.mkdir(exist_ok=True)
        temp_flac = temp_dir / f"temp_{idx:04d}.flac"

        encode_result = encode_to_flac(
            wav_path=wav_path,
            output_path=str(temp_flac),
            compression_level=settings.get("compression_level", 8),
            verify=settings.get("verify_encoding", True),
        )

        if not encode_result["success"]:
            update_conversion(row_id, status="failed", error_message=encode_result["error"],
                              duration_ms=encode_result["duration_ms"])
            eel.on_conversion_file_done({
                "file": wav_path, "success": False, "error": encode_result["error"]
            })()
            continue

        # Embed metadata
        tag_result = embed_metadata(str(temp_flac), metadata, album_art)

        # Copy to final destination
        copy_result = copy_to_network(str(temp_flac), str(dest_path), overwrite=True)

        if not copy_result["success"]:
            update_conversion(row_id, status="failed", error_message=copy_result["error"],
                              duration_ms=encode_result["duration_ms"])
            eel.on_conversion_file_done({
                "file": wav_path, "success": False, "error": copy_result["error"]
            })()
            # Clean up temp
            temp_flac.unlink(missing_ok=True)
            continue

        # Clean up temp file
        temp_flac.unlink(missing_ok=True)

        # Update log
        update_conversion(
            row_id,
            status="completed",
            dest_path=str(dest_path),
            duration_ms=encode_result["duration_ms"],
            verify_passed=encode_result["verify_passed"],
            file_size_after=encode_result["file_size"],
        )

        eel.on_conversion_file_done({
            "file": wav_path,
            "success": True,
            "dest": str(dest_path),
            "compression_ratio": round(encode_result["file_size"] / wav_info["file_size"], 3) if wav_info["file_size"] > 0 else 0,
            "duration_ms": encode_result["duration_ms"],
            "tags_written": tag_result.get("fields_written", 0),
        })()

    # Post-conversion cleanup: delete source WAV, CUE, and art files
    if not _conversion_cancel and settings.get("delete_wav_after_convert"):
        # Only delete if ALL files succeeded
        all_succeeded = True
        for file_info in files:
            wav_p = Path(file_info["path"])
            if wav_p.exists():
                # Check if this file was actually converted (it would have a log entry)
                pass  # We track success via the loop completing without cancel

        if all_succeeded:
            input_folder = settings.get("input_folder", "")
            wav_paths = [f["path"] for f in files]
            try:
                cleanup_source_files(input_folder, wav_paths)
                eel.on_conversion_file_done({
                    "file": "cleanup",
                    "success": True,
                    "dest": "",
                    "compression_ratio": 0,
                    "duration_ms": 0,
                    "tags_written": 0,
                    "message": f"Cleaned up {len(wav_paths)} WAV + CUE + art files",
                })()
            except Exception as e:
                eel.on_conversion_file_done({
                    "file": "cleanup",
                    "success": False,
                    "error": f"Cleanup failed: {e}",
                })()

    _conversion_active = False
    eel.on_conversion_progress({"status": "done", "current": total, "total": total})()


@eel.expose
def get_log_history(limit=100):
    return get_recent_logs(limit)


@eel.expose
def get_dashboard_stats():
    return get_stats()


@eel.expose
def get_metadata_completeness(release_details, cue_metadata, has_art):
    """Calculate per-track metadata completeness for Plex.

    Returns a list of {track_number, title, percentage, filled, total, fields}
    plus an album-level summary.
    """
    tracks_result = []

    if release_details and release_details.get("discs"):
        for disc in release_details["discs"]:
            for track in disc["tracks"]:
                meta = build_metadata_from_release(release_details, disc["position"], track["position"])

                # Merge ISRC from CUE if MusicBrainz didn't have it
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

    # Album-level summary
    if tracks_result:
        avg_pct = round(sum(t["percentage"] for t in tracks_result) / len(tracks_result))
    else:
        avg_pct = 0

    return {
        "tracks": tracks_result,
        "album_average": avg_pct,
        "plex_field_count": len(_PLEX_ALL_FIELDS) + 1,  # +1 for cover art
    }


# ─── Library Manager API ────────────────────────────────────────────────────────

@eel.expose
def scan_library():
    """Scan the output folder and return all FLAC files with metadata."""
    from library_manager import scan_library as _scan, group_library_by_album, find_duplicates
    settings = load_settings()
    output_folder = settings.get("output_folder", "")
    if not output_folder or not Path(output_folder).exists():
        return {"error": "Output folder not configured or doesn't exist", "albums": [], "total_files": 0}

    files = _scan(output_folder)
    albums = group_library_by_album(files)
    duplicates = find_duplicates(files)

    # Summary stats
    total = len(files)
    compilations = sum(1 for f in files if f["is_compilation"])
    incomplete = sum(1 for f in files if f["completeness"] < 100)

    return {
        "albums": albums,
        "total_files": total,
        "compilation_tracks": compilations,
        "incomplete_tracks": incomplete,
        "duplicate_count": len(duplicates),
        "duplicates": duplicates,
        "output_folder": output_folder,
    }


@eel.expose
def delete_library_file(flac_path):
    """Delete a FLAC file and clean up empty parent directories."""
    settings = load_settings()
    output_folder = settings.get("output_folder", "")
    src = Path(flac_path)

    if not src.exists():
        return {"success": False, "error": "File not found"}

    # Safety: only delete files inside the output folder
    try:
        src.relative_to(Path(output_folder))
    except ValueError:
        return {"success": False, "error": "File is not inside the output folder"}

    try:
        src.unlink()
        # Clean up empty parent directories
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


@eel.expose
def get_embedded_art(flac_path):
    """Extract embedded album art from a FLAC file as base64 JPEG thumbnail.

    Returns a 300px thumbnail for UI preview, plus the original dimensions.
    Returns: {success, data (base64), width, height} or {success: False}
    """
    try:
        from mutagen.flac import FLAC
        audio = FLAC(flac_path)
        if not audio.pictures:
            return {"success": False}
        pic = audio.pictures[0]
        raw = pic.data
        img = Image.open(BytesIO(raw))
        w, h = img.width, img.height
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # Resize to 300px thumbnail for the preview UI
        img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, format="JPEG", quality=80, optimize=True)
        return {
            "success": True,
            "data": base64.b64encode(output.getvalue()).decode("ascii"),
            "width": w,
            "height": h,
        }
    except Exception:
        return {"success": False}


@eel.expose
def find_original_album(artist, title):
    """Search MusicBrainz for the original album a track appeared on."""
    from library_manager import find_original_album as _find
    return _find(artist, title)


@eel.expose
def find_original_album_by_name(artist, album_name):
    """Search for release groups matching an album name using configured provider.

    MusicBrainz: sorted by year, 'Likely Original' badge on earliest studio album.
    Discogs: search results with year and format info.
    """
    try:
        settings = load_settings()
        provider = settings.get("metadata_provider", "musicbrainz")

        if provider == "discogs":
            from discogs_lookup import search_release as discogs_search
            # Discogs uses "Various" not "Various Artists"
            search_artist = artist
            if search_artist and search_artist.lower().strip() in ("various artists", "various"):
                search_artist = ""  # Let Discogs find it by album name alone
            results = discogs_search(artist=search_artist, album=album_name)
            if results and not results[0].get("error"):
                # Convert Discogs results to candidate format for consistent UI
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
                # Mark the first result as likely original
                if candidates:
                    candidates[0]["is_original"] = True
                return candidates
            # Return error message if Discogs returned an error
            if results and results[0].get("error"):
                return {"error": results[0]["error"]}
            return []
        else:
            from library_manager import find_original_album_by_name as _find
            return _find(artist, album_name)
    except Exception as e:
        return {"error": str(e)}


@eel.expose
def get_art_options(release_group_id):
    """Get all available cover art options for a release group."""
    from library_manager import get_art_options as _get_art_options
    return _get_art_options(release_group_id)


@eel.expose
def get_release_for_reassign(release_id):
    """Get full release details for reassigning a track to a new album."""
    settings = load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")

    if provider == "discogs":
        from discogs_lookup import get_release_details as discogs_details
        return discogs_details(release_id)
    else:
        details = get_release_details(release_id)
        if details.get("error"):
            return details
        return details


@eel.expose
def reassign_track(flac_path, new_metadata, move_file=True, art_release_id=None):
    """Re-tag a FLAC file with new metadata, fetch new album art, and move it.

    Args:
        art_release_id: If provided, fetch art from this specific release
                        (user-selected from the artwork picker). Otherwise uses
                        the release in musicbrainz_albumid.
    """
    from library_manager import reassign_track as _reassign
    settings = load_settings()
    output_folder = settings.get("output_folder", "")

    # Fetch album art — prefer user-selected release, fallback to album release
    album_art = None
    fetch_release_id = art_release_id or new_metadata.get("musicbrainz_albumid", "")
    if fetch_release_id and settings.get("embed_album_art", True):
        album_art = _fetch_art_for_provider(fetch_release_id, settings)

    return _reassign(flac_path, new_metadata, output_folder, move_file,
                     album_art=album_art)


@eel.expose
def batch_reassign_album(tracks, album_metadata, art_release_id=None):
    """Re-tag and move multiple FLAC files at once (Quick Clean Up).

    Args:
        tracks: list of {path, tracknumber, discnumber, title, artist}
                — per-track fields that differ from the album-level metadata
        album_metadata: dict with album-level fields shared by all tracks
                        (albumartist, album, date, genre, musicbrainz_albumid, etc.)
        art_release_id: release ID to fetch artwork from (user-selected)

    Returns: {success, results: [{path, new_path, success, error}, ...], failed}
    """
    from library_manager import reassign_track as _reassign
    settings = load_settings()
    output_folder = settings.get("output_folder", "")

    # Fetch album art ONCE for all tracks
    # null/None = keep existing art (don't touch), '__none__' = explicitly skip
    album_art = None
    if art_release_id == "__none__":
        album_art = None  # Explicit skip — no art will be embedded
    else:
        fetch_release_id = art_release_id or album_metadata.get("musicbrainz_albumid", "")
        if fetch_release_id and settings.get("embed_album_art", True):
            album_art = _fetch_art_for_provider(fetch_release_id, settings)

    results = []
    failed = 0
    for track in tracks:
        # Merge album-level + track-level metadata
        merged = dict(album_metadata)
        merged["title"] = track.get("title", "")
        merged["artist"] = track.get("artist", merged.get("albumartist", ""))
        merged["tracknumber"] = str(track.get("tracknumber", "1"))
        merged["discnumber"] = str(track.get("discnumber", "1"))
        if track.get("musicbrainz_trackid"):
            merged["musicbrainz_trackid"] = track["musicbrainz_trackid"]
        if track.get("tracktotal"):
            merged["tracktotal"] = str(track["tracktotal"])

        result = _reassign(track["path"], merged, output_folder, move_file=True,
                           album_art=album_art)
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


@eel.expose
def preview_reassign(flac_path, new_metadata):
    """Preview what would change without actually doing it."""
    from file_manager import build_output_path
    from tagger import read_metadata

    settings = load_settings()
    output_folder = settings.get("output_folder", "")

    # Current metadata
    current = read_metadata(flac_path)
    current_tags = current.get("tags", {})

    # Build new path
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

    # Build diff
    changes = []
    field_names = {
        "TITLE": "Title", "ARTIST": "Artist", "ALBUMARTIST": "Album Artist",
        "ALBUM": "Album", "TRACKNUMBER": "Track", "DISCNUMBER": "Disc",
        "DATE": "Year", "GENRE": "Genre",
        "MUSICBRAINZ_ALBUMID": "MB Album ID", "MUSICBRAINZ_TRACKID": "MB Track ID",
        "MUSICBRAINZ_ARTISTID": "MB Artist ID", "MUSICBRAINZ_ALBUMARTISTID": "MB Album Artist ID",
        "TRACKTOTAL": "Total Tracks", "DISCTOTAL": "Total Discs",
    }
    for key, new_val in new_metadata.items():
        upper_key = key.upper()
        old_val = current_tags.get(upper_key, "")
        if str(new_val) != str(old_val):
            changes.append({
                "field": field_names.get(upper_key, upper_key),
                "key": upper_key,
                "old": str(old_val),
                "new": str(new_val),
            })

    path_changed = str(new_path) != flac_path

    # Check art availability for the new release
    art_available = False
    release_id = new_metadata.get("musicbrainz_albumid", "")
    if release_id:
        from metadata_lookup import get_cover_art
        try:
            art_bytes = get_cover_art(release_id, max_size=200, quality=50)
            art_available = art_bytes is not None
        except Exception:
            pass

    # Check if track currently has embedded art
    current_has_art = current.get("has_picture", False)

    return {
        "changes": changes,
        "current_path": flac_path,
        "new_path": str(new_path),
        "path_changed": path_changed,
        "art_available": art_available,
        "current_has_art": current_has_art,
    }


_APP_PORT = 8178


def _find_browser():
    """Find Edge or Chrome executable path."""
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in edge_paths:
        if os.path.exists(p):
            return p

    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            return p

    return None


def main():
    init_db()
    settings = load_settings()

    # Auto-detect flac.exe if not set
    if not settings.get("flac_exe_path"):
        detected = find_flac_exe()
        if detected:
            settings["flac_exe_path"] = detected
            save_settings(settings)

    url = f"http://localhost:{_APP_PORT}/index.html"
    browser_exe = _find_browser()

    # Launch browser ourselves in app mode, then run Eel's server with block=True.
    # Eel with mode=None + block=True starts the Bottle server and blocks forever
    # (it won't exit on WebSocket close because there's no browser to "close").
    # We launch the browser manually so the server lifecycle is decoupled.

    def _launch_browser_delayed():
        """Wait for server to be ready, then open the browser."""
        time.sleep(1.5)
        if browser_exe:
            subprocess.Popen([browser_exe, f"--app={url}", "--disable-extensions"])
        else:
            webbrowser.open(url)

    # Start browser launch in background (gives server time to bind)
    threading.Thread(target=_launch_browser_delayed, daemon=True).start()

    print(f"Music Manager running at {url}")
    print("Close this window to stop the server.\n")

    try:
        eel.start(
            "index.html",
            mode=None,
            block=True,
            port=_APP_PORT,
            shutdown_delay=999999.0,  # Never auto-shutdown on disconnect
        )
    except (KeyboardInterrupt, SystemExit):
        pass
    except OSError as e:
        if "address already in use" in str(e).lower() or "10048" in str(e):
            # Port already in use — maybe from a previous run. Open browser to existing server.
            print(f"Port {_APP_PORT} already in use. Opening browser to existing instance...")
            if browser_exe:
                subprocess.Popen([browser_exe, f"--app={url}", "--disable-extensions"])
            else:
                webbrowser.open(url)
        else:
            raise

    print("Music Manager stopped.")


if __name__ == "__main__":
    main()
