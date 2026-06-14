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

    # Source 1: the release's provider art (routed by ID shape)
    if release_id:
        if is_discogs_id(release_id):
            from discogs_lookup import get_cover_art as discogs_art
            raw = discogs_art(release_id, max_size=9999, quality=95)
            source = "discogs"
        else:
            from metadata_lookup import get_cover_art
            raw = get_cover_art(release_id, max_size=9999, quality=95)
            source = "coverartarchive"
        if raw:
            w, h = get_image_resolution(raw)
            candidates.append({
                "source": source,
                "width": w, "height": h,
                "pixels": w * h,
                "raw": raw,
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


def is_discogs_id(release_id: str) -> bool:
    """Discogs release IDs are integers; MusicBrainz IDs are UUIDs."""
    return bool(release_id) and str(release_id).strip().isdigit()


def fetch_art_for_provider(release_id: str, settings: dict | None = None) -> bytes | None:
    """Fetch album art for a release ID, routing by the ID's OWN shape —
    never by the legacy metadata_provider setting. (A MusicBrainz UUID sent
    to Discogs fails silently and tracks end up with no art at all.)

    Returns prepared JPEG bytes ready for embedding, or None.
    """
    settings = settings or load_settings()
    max_size = settings.get("art_max_size", 1200)
    quality = settings.get("art_quality", 90)

    if is_discogs_id(release_id):
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
    """Art comparison for the UI (Convert tab / Quick Clean Up).

    select_best_art routes the release ID by its own shape (Discogs vs CAA)
    and also pulls local EAC art from `folder`, returning every candidate with
    a 200px thumb. Returns {success, data, source, width, height, candidates}.
    """
    settings = settings or load_settings()
    result = select_best_art(
        release_id=release_id, folder=folder,
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


def get_local_art_preview(folder: str) -> dict:
    """Thumbnail of the local EAC art in a rip folder (folder.jpg/cover.jpg/…),
    for the Convert art picker. Mirrors get_embedded_art's shape.

    Returns: {success, data (base64), width, height, source_file} or {success: False}
    """
    raw, name = find_local_art_raw(folder)
    if not raw:
        return {"success": False}
    try:
        w, h = get_image_resolution(raw)
        img = Image.open(BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        output = BytesIO()
        img.save(output, format="JPEG", quality=80, optimize=True)
        return {
            "success": True,
            "data": base64.b64encode(output.getvalue()).decode("ascii"),
            "width": w, "height": h,
            "source_file": name,
        }
    except Exception:
        return {"success": False}


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
