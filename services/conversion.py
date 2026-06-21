"""WAV→FLAC conversion pipeline. Moved from app.py (Phase 1).

The loop is transport-agnostic: progress flows through injected callbacks so
the Eel app (v1) and the FastAPI job queue (v2) share one implementation.
"""

import tempfile
from pathlib import Path
from typing import Callable

from config import load_settings, APP_VERSION
from database import log_conversion, update_conversion
from encoder import encode_to_flac, get_wav_info
from tagger import embed_metadata, build_metadata_from_release
from file_manager import build_output_path, copy_to_network, cleanup_source_files
from services.art import (select_best_art, prepare_art, find_local_art_raw,
                          get_image_resolution)


def _download_art_raw(url: str) -> bytes | None:
    """Download a user-selected art URL as raw bytes (no resizing)."""
    import requests
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": f"MusicManager/{APP_VERSION}"})
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None


def _download_art(url: str, max_size: int, quality: int) -> bytes | None:
    """Download a user-selected art URL and prepare it for embedding (resize +
    JPEG). Used by library reassign/batch-reassign for user-picked art."""
    raw = _download_art_raw(url)
    if raw is None:
        return None
    try:
        return prepare_art(raw, max_size, quality)
    except Exception:
        return None


def _resolve_album_art(settings: dict, release_details: dict | None,
                       max_size: int, quality: int) -> tuple[bytes | None, dict]:
    """Fetch and prepare the album art, reporting what happened to it.

    Precedence:
      art_source == "local" → the input folder's own art (folder.jpg etc.)
      art_url               → a specific image the user picked in the UI
      otherwise             → compare all sources, pick the highest resolution
    Any choice that yields nothing falls back to the best available source so a
    missing local file never silently drops art.

    Returns (bytes|None, status), where status feeds the activity log:
        {source, original: (w, h), final: (w, h), rescaled: bool, missing: bool}
    """
    art_url = settings.get("art_url", "")
    art_source = settings.get("art_source", "")
    folder = settings.get("input_folder", "")

    raw: bytes | None = None
    source: str | None = None
    if art_source == "local":
        raw, name = find_local_art_raw(folder)
        source = f"local file ({name})" if name else "local folder"
    elif art_url:
        raw = _download_art_raw(art_url)
        source = "selected image"

    if raw is not None:
        ow, oh = get_image_resolution(raw)
        try:
            prepared = prepare_art(raw, max_size, quality)
        except Exception:
            prepared = None
        if prepared is not None:
            fw, fh = get_image_resolution(prepared)
            return prepared, {
                "source": source, "original": (ow, oh), "final": (fw, fh),
                "rescaled": ow > max_size or oh > max_size, "missing": False,
            }

    # Fallback: compare every available source and pick the largest.
    art_result = select_best_art(
        release_id=release_details.get("id") if release_details else None,
        folder=folder,
        max_size=max_size,
        quality=quality,
    )
    prepared = art_result.get("bytes")
    if prepared is None:
        return None, {"source": None, "original": (0, 0), "final": (0, 0),
                      "rescaled": False, "missing": True}
    ow, oh = art_result.get("width", 0), art_result.get("height", 0)
    fw, fh = get_image_resolution(prepared)
    return prepared, {
        "source": art_result.get("source"), "original": (ow, oh), "final": (fw, fh),
        "rescaled": ow > max_size or oh > max_size, "missing": False,
    }


def _art_status_line(status: dict, max_size: int) -> tuple[str | None, str]:
    """Turn an art status dict into an activity-log line. Returns (text, tone);
    text is None when the art needs no mention (embedded as-is). Only rescaling
    and missing art are surfaced."""
    if status["missing"]:
        return ("No album art found — files will be tagged without a cover.", "warn")
    if status["rescaled"]:
        ow, oh = status["original"]
        fw, fh = status["final"]
        src = status["source"] or "art"
        return (f"Album art rescaled from {ow}×{oh} to {fw}×{fh} "
                f"(max {max_size}px) — {src}.", "warn")
    return (None, "info")


def _build_track_metadata(release_details: dict | None, file_info: dict,
                          track_number: int, disc_number: int) -> dict:
    """Build a track's tag dict from the matched release, then backfill anything
    it didn't supply from the CUE/filename parse.

    Expanded-edition bonus tracks are frequently absent from the matched
    MusicBrainz release; the CUE still has their titles, so a release match must
    never throw those away (the "Track 10" bug, where bonus tracks landed with
    no title or track number at all).
    """
    metadata = {}
    if release_details and not release_details.get("error"):
        metadata = build_metadata_from_release(release_details, disc_number, track_number)

    if not metadata.get("title"):
        metadata["title"] = file_info.get("parsed_title", "")
    if not metadata.get("artist"):
        metadata["artist"] = (file_info.get("parsed_artist")
                              or metadata.get("albumartist") or "")
    if not metadata.get("album"):
        metadata["album"] = file_info.get("parsed_album", "")
    if not metadata.get("tracknumber"):
        metadata["tracknumber"] = str(track_number)
    if not metadata.get("discnumber"):
        metadata["discnumber"] = str(disc_number)
    # Stamp the compilation flag BOTH ways from the user's Review-step choice
    # (seeded from provider detection): "1" marks a compilation; "0" is an
    # authoritative "not a compilation" that overrides the library's keyword /
    # multi-artist heuristics — so deselecting it at convert time actually sticks.
    if release_details is not None and "compilation" in release_details:
        metadata["compilation"] = "1" if release_details.get("compilation") else "0"
    return metadata


def _verify_embedded(flac_path: str, metadata: dict, expect_art: bool) -> dict:
    """Read the written FLAC back from disk and confirm the metadata (and art,
    when requested) actually landed. This is the success gate: we never report a
    track as converted on the strength of the encode alone — Plex/Explorer only
    see what's truly embedded.

    Every track MUST carry TITLE, ARTIST, ALBUM, and TRACKNUMBER — a file
    missing any of these is broken regardless of what we meant to write, so the
    check is unconditional (this is what would have caught the untitled
    "Track 10" bonus tracks). Returns {ok, missing_tags, art_missing}: missing
    core tags are a hard failure; missing art is a soft warning.
    """
    from tagger import read_metadata

    result = read_metadata(flac_path)
    if not result.get("success"):
        return {"ok": False, "missing_tags": ["<file unreadable>"],
                "art_missing": expect_art}

    tags = result.get("tags", {})

    missing = []
    for tag in ("TITLE", "ARTIST", "ALBUM", "TRACKNUMBER"):
        got = tags.get(tag, "")
        if isinstance(got, list):
            got = got[0] if got else ""
        if str(got).strip() == "":
            missing.append(tag)

    art_missing = expect_art and not result.get("has_picture", False)
    return {"ok": len(missing) == 0, "missing_tags": missing, "art_missing": art_missing}


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

    # Fetch album art once, then report rescaling / missing art to the activity
    # window so the user knows what landed on their files before any track is
    # written (the art is shared across the whole batch).
    album_art = None
    if settings.get("embed_album_art"):
        max_size = settings.get("art_max_size", 1200)
        quality = settings.get("art_quality", 90)
        album_art, art_status = _resolve_album_art(
            settings, release_details, max_size, quality)
        note, tone = _art_status_line(art_status, max_size)
        if note:
            on_file_done({"file": "artwork", "note": note, "tone": tone})

    total = len(files)
    completed = 0
    failed = 0
    cancelled = False
    converted_paths: list[str] = []   # final FLACs, for ReplayGain analysis

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

        metadata = _build_track_metadata(release_details, file_info,
                                         track_number, disc_number)
        # Optionally enrich with performer/writer credits (composer, conductor,
        # …) from MusicBrainz. Best-effort and gated by a setting — it adds
        # rate-limited lookups per track.
        from metadata_lookup import merge_credits
        merge_credits(metadata, settings)

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
        if not tag_result["success"]:
            update_conversion(row_id, status="failed", error_message=tag_result["error"],
                              duration_ms=encode_result["duration_ms"])
            on_file_done({"file": wav_path, "success": False,
                          "error": f"Tagging failed: {tag_result['error']}"})
            temp_flac.unlink(missing_ok=True)
            failed += 1
            continue

        copy_result = copy_to_network(str(temp_flac), str(dest_path), overwrite=True)

        if not copy_result["success"]:
            update_conversion(row_id, status="failed", error_message=copy_result["error"],
                              duration_ms=encode_result["duration_ms"])
            on_file_done({"file": wav_path, "success": False, "error": copy_result["error"]})
            temp_flac.unlink(missing_ok=True)
            failed += 1
            continue

        temp_flac.unlink(missing_ok=True)

        # Success gate: read the file back from its final location and confirm
        # the tags (and art, when requested) are really embedded. Missing core
        # tags fail the track — which also blocks source-file cleanup below, so
        # the WAV + CUE survive for a retry. Missing art only warns.
        verify = _verify_embedded(str(dest_path), metadata, expect_art=album_art is not None)
        if not verify["ok"]:
            err = "Embedding verification failed: missing " + ", ".join(verify["missing_tags"])
            update_conversion(row_id, status="failed", error_message=err,
                              duration_ms=encode_result["duration_ms"])
            on_file_done({"file": wav_path, "success": False, "error": err})
            failed += 1
            continue

        update_conversion(
            row_id,
            status="completed",
            dest_path=str(dest_path),
            duration_ms=encode_result["duration_ms"],
            verify_passed=encode_result["verify_passed"],
            file_size_after=encode_result["file_size"],
        )

        completed += 1
        converted_paths.append(str(dest_path))
        done_payload = {
            "file": wav_path,
            "success": True,
            "dest": str(dest_path),
            "compression_ratio": round(encode_result["file_size"] / wav_info["file_size"], 3) if wav_info["file_size"] > 0 else 0,
            "duration_ms": encode_result["duration_ms"],
            "tags_written": tag_result.get("fields_written", 0),
        }
        if verify["art_missing"]:
            done_payload["warning"] = "tags embedded, but album art is missing"
        on_file_done(done_payload)

    # Post-conversion cleanup: delete source WAV, CUE, and art files — only when
    # at least one file actually converted and ALL of them succeeded. The
    # `completed > 0` guard is critical: without it an empty/no-op run (total==0,
    # e.g. convert invoked before a scan) satisfies `completed == total` and the
    # glob-based cleanup wipes the folder's CUE/art though nothing was converted.
    if (not cancelled and completed > 0 and failed == 0 and completed == total
            and settings.get("delete_wav_after_convert")):
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

    # ReplayGain: analyze the finished FLACs (per album folder) so the library
    # carries loudness tags. Non-fatal — a missing metaflac just warns.
    if settings.get("add_replay_gain") and converted_paths:
        from encoder import add_replay_gain
        on_file_done({"file": "replaygain",
                      "note": "Calculating ReplayGain (loudness) tags…", "tone": "info"})
        rg = add_replay_gain(converted_paths)
        if rg["success"]:
            on_file_done({"file": "replaygain",
                          "note": f"ReplayGain applied to {rg['processed']} file(s).",
                          "tone": "info"})
        else:
            on_file_done({"file": "replaygain",
                          "note": "ReplayGain skipped: " + "; ".join(rg["errors"]),
                          "tone": "warn"})

    on_progress({"status": "done", "current": total, "total": total})
    return {"completed": completed, "failed": failed, "cancelled": cancelled, "total": total}
