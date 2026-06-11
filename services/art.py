"""Album art: local discovery, provider fetching, comparison, embedding prep.

Moved from app.py (Phase 1).
"""

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from config import load_settings

# Common image filenames EAC and other tools save
_ART_FILENAMES = [
    "folder.jpg", "folder.png", "folder.bmp",
    "cover.jpg", "cover.png", "cover.bmp",
    "front.jpg", "front.png", "front.bmp",
    "album.jpg", "album.png", "album.bmp",
    "albumart.jpg", "albumart.png", "albumart.bmp",
    "albumartsmall.jpg",
]

_IMAGE_MAGIC = (b'\xff\xd8\xff', b'\x89PNG', b'BM', b'GIF8', b'RIFF')


def get_image_resolution(image_data: bytes) -> tuple[int, int]:
    """Get (width, height) from raw image bytes."""
    try:
        img = Image.open(BytesIO(image_data))
        return img.width, img.height
    except Exception:
        return 0, 0


def prepare_art(image_data: bytes, max_size: int, quality: int) -> bytes:
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
            return prepare_art(raw, max_size, quality)
        except Exception:
            return None
    return None


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
        "candidates": [{source, width, height, pixels, selected, thumb}, ...]
    }
    """
    candidates = []

    # Source 1: Cover Art Archive
    if release_id:
        from metadata_lookup import get_cover_art
        caa_raw = get_cover_art(release_id, max_size=9999, quality=95)
        if caa_raw:
            w, h = get_image_resolution(caa_raw)
            candidates.append({
                "source": "coverartarchive",
                "width": w, "height": h,
                "pixels": w * h,
                "raw": caa_raw,
            })

    # Source 2: Local folder (EAC art)
    if folder:
        local_raw, local_name = find_local_art_raw(folder)
        if local_raw:
            w, h = get_image_resolution(local_raw)
            candidates.append({
                "source": "local",
                "source_file": local_name,
                "width": w, "height": h,
                "pixels": w * h,
                "raw": local_raw,
            })

    return _pick_best(candidates, max_size, quality)


def _pick_best(candidates: list[dict], max_size: int, quality: int) -> dict:
    """Shared tail of art selection: rank, prepare winner, thumbnail everything."""
    if not candidates:
        return {
            "data": None, "bytes": None, "source": None,
            "width": 0, "height": 0, "candidates": [],
        }

    candidates.sort(key=lambda c: c["pixels"], reverse=True)
    best = candidates[0]

    try:
        prepared = prepare_art(best["raw"], max_size, quality)
    except Exception:
        prepared = None

    candidate_summary = []
    for c in candidates:
        thumb = None
        try:
            thumb_bytes = prepare_art(c["raw"], max_size=200, quality=70)
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


def fetch_art_for_provider(release_id: str, settings: dict | None = None) -> bytes | None:
    """Fetch album art using the active metadata provider.

    Returns prepared JPEG bytes ready for embedding, or None.
    """
    settings = settings or load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")
    max_size = settings.get("art_max_size", 1200)
    quality = settings.get("art_quality", 90)

    if provider == "discogs":
        from discogs_lookup import get_cover_art as discogs_art
        return discogs_art(release_id, max_size=max_size, quality=quality)
    else:
        art_result = select_best_art(
            release_id=release_id, folder=None,
            max_size=max_size, quality=quality,
        )
        return art_result.get("bytes")


def fetch_album_art_compared(release_id: str, folder: str | None,
                             settings: dict | None = None) -> dict:
    """Provider-aware art comparison for the UI (Convert tab / Quick Clean Up).

    Returns {success, data, source, width, height, candidates} where every
    candidate includes a 200px thumb.
    """
    settings = settings or load_settings()
    provider = settings.get("metadata_provider", "musicbrainz")
    max_size = settings.get("art_max_size", 1200)
    quality = settings.get("art_quality", 90)

    if provider == "discogs":
        from discogs_lookup import get_cover_art as discogs_art
        candidates = []

        discogs_raw = discogs_art(release_id, max_size=9999, quality=95)
        if discogs_raw:
            w, h = get_image_resolution(discogs_raw)
            candidates.append({"source": "discogs", "width": w, "height": h,
                               "pixels": w * h, "raw": discogs_raw})

        if folder:
            local_raw, _ = find_local_art_raw(folder)
            if local_raw:
                w, h = get_image_resolution(local_raw)
                candidates.append({"source": "local", "width": w, "height": h,
                                   "pixels": w * h, "raw": local_raw})

        result = _pick_best(candidates, max_size, quality)
    else:
        result = select_best_art(release_id=release_id, folder=folder,
                                 max_size=max_size, quality=quality)

    return {
        "success": result["data"] is not None,
        "data": result["data"],
        "source": result["source"],
        "width": result["width"],
        "height": result["height"],
        "candidates": result["candidates"],
    }


def get_embedded_art(flac_path: str) -> dict:
    """Extract embedded album art from a FLAC file as base64 JPEG thumbnail.

    Returns a 300px thumbnail for UI preview, plus the original dimensions.
    Returns: {success, data (base64), width, height} or {success: False}
    """
    try:
        from mutagen.flac import FLAC
        audio = FLAC(flac_path)
        if not audio.pictures:
            return {"success": False}
        raw = audio.pictures[0].data
        img = Image.open(BytesIO(raw))
        w, h = img.width, img.height
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
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
