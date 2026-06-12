"""WAV→FLAC conversion pipeline. Moved from app.py (Phase 1).

The loop is transport-agnostic: progress flows through injected callbacks so
the Eel app (v1) and the FastAPI job queue (v2) share one implementation.
"""

import tempfile
from pathlib import Path
from typing import Callable

from config import load_settings
from database import log_conversion, update_conversion
from encoder import encode_to_flac, get_wav_info
from tagger import embed_metadata, build_metadata_from_release
from file_manager import build_output_path, copy_to_network, cleanup_source_files
from services.art import select_best_art, prepare_art


def _download_art(url: str, max_size: int, quality: int) -> bytes | None:
    """Download a user-selected art URL and prepare it for embedding."""
    import requests
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "MusicManager/2.0 (louissilvestri@hotmail.com)"})
        if resp.status_code != 200:
            return None
        return prepare_art(resp.content, max_size, quality)
    except Exception:
        return None


def run_conversion(
    files: list[dict],
    release_details: dict | None,
    options: dict | None,
    on_progress: Callable[[dict], None],
    on_file_done: Callable[[dict], None],
    is_cancelled: Callable[[], bool],
) -> dict:
    """Convert a batch of WAV files to tagged FLAC in the output library.

    Returns {completed, failed, cancelled, total}.
    """
    settings = load_settings()
    if options:
        settings.update(options)

    output_folder = settings.get("output_folder", "")
    if not output_folder:
        on_progress({"status": "error", "error": "Output folder not configured"})
        return {"completed": 0, "failed": 0, "cancelled": False, "total": len(files)}

    # Fetch album art once. If the user picked a specific image in the UI
    # (options.art_url), honor it; otherwise compare all sources and pick
    # the highest resolution.
    album_art = None
    if settings.get("embed_album_art"):
        art_url = settings.get("art_url", "")
        if art_url:
            album_art = _download_art(art_url,
                                      settings.get("art_max_size", 1200),
                                      settings.get("art_quality", 90))
        if album_art is None:
            art_result = select_best_art(
                release_id=release_details.get("id") if release_details else None,
                folder=settings.get("input_folder", ""),
                max_size=settings.get("art_max_size", 1200),
                quality=settings.get("art_quality", 90),
            )
            album_art = art_result.get("bytes")

    total = len(files)
    completed = 0
    failed = 0
    cancelled = False

    for idx, file_info in enumerate(files):
        if is_cancelled():
            cancelled = True
            on_progress({"status": "cancelled", "current": idx, "total": total})
            break

        wav_path = file_info["path"]
        # Safety net: a 0/missing track number must never collapse every file
        # onto "00 - Track 00.flac" and overwrite each other. Fall back to the
        # 1-based position in the batch.
        track_number = file_info.get("track_number") or (idx + 1)
        disc_number = file_info.get("disc_number") or 1

        on_progress({
            "status": "encoding",
            "current": idx + 1,
            "total": total,
            "file": Path(wav_path).name,
        })

        try:
            wav_info = get_wav_info(wav_path)
        except Exception as e:
            log_conversion(source_path=wav_path, status="failed", error_message=str(e))
            on_file_done({"file": wav_path, "success": False, "error": str(e)})
            failed += 1
            continue

        # Build metadata
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
        # (prevents duplicates when re-ripping with a different metadata source).
        # Guarded by track_number > 0 so a degenerate batch can never chain-
        # delete every previous track via a shared "00 - " prefix.
        dest_folder = dest_path.parent
        if dest_folder.exists() and track_number > 0:
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
            on_file_done({"file": wav_path, "success": False, "error": encode_result["error"]})
            failed += 1
            continue

        tag_result = embed_metadata(str(temp_flac), metadata, album_art)

        copy_result = copy_to_network(str(temp_flac), str(dest_path), overwrite=True)

        if not copy_result["success"]:
            update_conversion(row_id, status="failed", error_message=copy_result["error"],
                              duration_ms=encode_result["duration_ms"])
            on_file_done({"file": wav_path, "success": False, "error": copy_result["error"]})
            temp_flac.unlink(missing_ok=True)
            failed += 1
            continue

        temp_flac.unlink(missing_ok=True)

        update_conversion(
            row_id,
            status="completed",
            dest_path=str(dest_path),
            duration_ms=encode_result["duration_ms"],
            verify_passed=encode_result["verify_passed"],
            file_size_after=encode_result["file_size"],
        )

        completed += 1
        on_file_done({
            "file": wav_path,
            "success": True,
            "dest": str(dest_path),
            "compression_ratio": round(encode_result["file_size"] / wav_info["file_size"], 3) if wav_info["file_size"] > 0 else 0,
            "duration_ms": encode_result["duration_ms"],
            "tags_written": tag_result.get("fields_written", 0),
        })

    # Post-conversion cleanup: delete source WAV, CUE, and art files —
    # only when every file converted successfully and nothing was cancelled
    if not cancelled and failed == 0 and completed == total and settings.get("delete_wav_after_convert"):
        input_folder = settings.get("input_folder", "")
        wav_paths = [f["path"] for f in files]
        try:
            cleanup_source_files(input_folder, wav_paths)
            on_file_done({
                "file": "cleanup", "success": True, "dest": "",
                "compression_ratio": 0, "duration_ms": 0, "tags_written": 0,
                "message": f"Cleaned up {len(wav_paths)} WAV + CUE + art files",
            })
        except Exception as e:
            on_file_done({"file": "cleanup", "success": False,
                          "error": f"Cleanup failed: {e}"})

    on_progress({"status": "done", "current": total, "total": total})
    return {"completed": completed, "failed": failed, "cancelled": cancelled, "total": total}
