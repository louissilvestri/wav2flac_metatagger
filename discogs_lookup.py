"""Discogs metadata lookup integration."""

import time
import requests
from io import BytesIO
from pathlib import Path

from config import load_settings, CONFIG_DIR

_last_request_time = 0.0
_RATE_LIMIT_INTERVAL = 1.05  # ~60 req/min authenticated


def _rate_limit():
    """Enforce Discogs rate limit (60 req/min authenticated)."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _RATE_LIMIT_INTERVAL:
        time.sleep(_RATE_LIMIT_INTERVAL - elapsed)
    _last_request_time = time.time()


def _get_client():
    """Create and return a Discogs client using the stored token."""
    import discogs_client
    settings = load_settings()
    token = settings.get("discogs_token", "")
    if not token:
        return None
    return discogs_client.Client("MusicManager/1.0", user_token=token)


# ─── Search ───────────────────────────────────────────────────────────────────

def search_release(artist: str = None, album: str = None, tracks: int = None) -> list[dict]:
    """Search Discogs for matching releases."""
    client = _get_client()
    if not client:
        return [{"error": "Discogs token not configured. Set it in Settings."}]

    _rate_limit()

    try:
        kwargs = {"type": "release"}
        if artist:
            kwargs["artist"] = artist
        if album:
            kwargs["release_title"] = album

        results = client.search(**kwargs)

        releases = []
        for item in results.page(1)[:10]:
            # Each item in search results is a Release object
            medium_info = item.data.get("format", [])
            format_str = ", ".join(medium_info) if isinstance(medium_info, list) else str(medium_info)

            release_info = {
                "id": str(item.id),
                "title": item.data.get("title", "").split(" - ", 1)[-1] if " - " in item.data.get("title", "") else item.data.get("title", ""),
                "artist": item.data.get("title", "").split(" - ", 1)[0] if " - " in item.data.get("title", "") else "",
                "date": str(item.data.get("year", "")),
                "country": item.data.get("country", ""),
                "barcode": "",
                "status": "",
                "label": item.data.get("label", [""])[0] if item.data.get("label") else "",
                "catalog_number": item.data.get("catno", ""),
                "total_tracks": 0,
                "disc_count": 1,
                "format": format_str,
                "score": 50,
                "match_method": "discogs_search",
            }

            # Boost score for CD format
            if "CD" in format_str:
                release_info["score"] += 5
            if tracks and item.data.get("tracklist"):
                # Can't easily get track count from search results
                pass

            releases.append(release_info)

        releases.sort(key=lambda x: x["score"], reverse=True)
        return releases
    except Exception as e:
        return [{"error": f"Discogs search failed: {e}"}]


def get_release_details(release_id: str) -> dict:
    """Get full Discogs release details including track listing."""
    client = _get_client()
    if not client:
        return {"error": "Discogs token not configured. Set it in Settings."}

    _rate_limit()

    try:
        release = client.release(int(release_id))

        # Get master release year (original release date)
        master_year = ""
        if release.master:
            _rate_limit()
            try:
                master_year = str(release.master.year or "")
            except Exception:
                pass

        details = {
            "id": str(release.id),
            "title": release.title or "",
            "artist": ", ".join(a.name for a in release.artists) if release.artists else "",
            "artist_id": str(release.artists[0].id) if release.artists else "",
            "date": str(release.year or ""),
            "first_release_date": master_year or str(release.year or ""),
            "country": release.country or "",
            "barcode": "",
            "status": "",
            "label": release.labels[0].name if release.labels else "",
            "catalog_number": release.labels[0].data.get("catno", "") if release.labels else "",
            "release_group_id": str(release.master.id) if release.master else "",
            "genre": release.genres[0] if release.genres else "",
            "genres": release.genres or [],
            "styles": release.styles or [],
            "discs": [],
            "provider": "discogs",
        }

        # Parse barcode from identifiers
        if hasattr(release, "data") and release.data.get("identifiers"):
            for ident in release.data["identifiers"]:
                if ident.get("type") == "Barcode":
                    details["barcode"] = ident.get("value", "")
                    break

        # Build disc/track structure
        # Discogs tracks can have position like "A1", "B2" (vinyl) or "1", "2" (CD)
        # or "1-1", "1-2" for multi-disc
        current_disc = 1
        disc_tracks = {}

        for track in release.tracklist:
            pos = track.position or ""

            # Determine disc number from position
            disc_num = 1
            track_pos = pos

            if "-" in pos and pos.split("-")[0].isdigit():
                # Format: "1-5" means disc 1, track 5
                parts = pos.split("-", 1)
                disc_num = int(parts[0])
                track_pos = parts[1]
            elif pos and pos[0].isalpha():
                # Vinyl: A1, B1 = sides, treat as single disc
                disc_num = 1
                track_pos = pos

            # Skip headings/subtracks (empty position or sub-tracks like "1.1")
            if not pos or track.data.get("type_") == "heading":
                continue

            if disc_num not in disc_tracks:
                disc_tracks[disc_num] = []

            # Parse track number from position
            try:
                track_number = len(disc_tracks[disc_num]) + 1
            except Exception:
                track_number = 1

            track_artist = ""
            if track.artists:
                track_artist = ", ".join(a.name for a in track.artists)

            disc_tracks[disc_num].append({
                "position": track_number,
                "title": track.title or "",
                "artist": track_artist or details["artist"],
                "artist_id": "",
                "length_ms": _parse_duration(track.duration) if track.duration else None,
                "isrc": "",
                "recording_id": "",
            })

        # Build discs array
        for disc_num in sorted(disc_tracks.keys()):
            details["discs"].append({
                "position": disc_num,
                "format": "CD",
                "tracks": disc_tracks[disc_num],
            })

        # If no tracks parsed, create single empty disc
        if not details["discs"]:
            details["discs"] = [{"position": 1, "format": "CD", "tracks": []}]

        return details
    except Exception as e:
        return {"error": f"Discogs lookup failed: {e}"}


def get_cover_art(release_id: str, max_size: int = 1200, quality: int = 90) -> bytes | None:
    """Fetch cover art from a Discogs release."""
    from PIL import Image

    art_cache_dir = CONFIG_DIR / "art_cache"
    art_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = art_cache_dir / f"discogs_{release_id}.jpg"

    if cache_file.exists():
        return cache_file.read_bytes()

    client = _get_client()
    if not client:
        return None

    _rate_limit()

    try:
        release = client.release(int(release_id))
        if not release.images:
            return None

        # Find primary image
        primary = None
        for img in release.images:
            if img.get("type") == "primary":
                primary = img
                break
        if not primary:
            primary = release.images[0]

        img_url = primary.get("uri") or primary.get("resource_url")
        if not img_url:
            return None

        # Download with auth header
        settings = load_settings()
        token = settings.get("discogs_token", "")
        headers = {
            "User-Agent": "MusicManager/1.0",
            "Authorization": f"Discogs token={token}",
        }
        resp = requests.get(img_url, timeout=30, headers=headers)
        if resp.status_code != 200:
            return None

        img = Image.open(BytesIO(resp.content))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        output = BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        art_bytes = output.getvalue()

        cache_file.write_bytes(art_bytes)
        return art_bytes
    except Exception:
        return None


def _parse_duration(duration_str: str) -> int | None:
    """Parse Discogs duration string (e.g., '4:32') to milliseconds."""
    if not duration_str:
        return None
    try:
        parts = duration_str.split(":")
        if len(parts) == 2:
            return (int(parts[0]) * 60 + int(parts[1])) * 1000
        elif len(parts) == 3:
            return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000
    except (ValueError, IndexError):
        return None
    return None


# ─── Automated Lookup ─────────────────────────────────────────────────────────

def automated_lookup(
    artist: str = None,
    album: str = None,
    barcode: str = None,
    track_count: int = None,
) -> dict:
    """Run Discogs lookup cascade: barcode → text search.

    Returns same structure as MusicBrainz automated_lookup for compatibility.
    """
    cascade_log = []
    best_releases = []

    client = _get_client()
    if not client:
        return {
            "cascade_log": [{"method": "discogs", "status": "error", "query": "No token configured"}],
            "releases": [],
            "best_match": None,
            "match_method": "none",
            "gnudb_result": None,
        }

    # Step 1: Barcode search
    if barcode and len(barcode) >= 10:
        cascade_log.append({"method": "discogs_barcode", "status": "searching", "query": barcode})
        _rate_limit()
        try:
            results = client.search(barcode=barcode, type="release")
            items = list(results.page(1)[:5])
            if items:
                cascade_log[-1]["status"] = "found"
                cascade_log[-1]["count"] = len(items)
                for item in items:
                    title_parts = item.data.get("title", "").split(" - ", 1)
                    best_releases.append({
                        "id": str(item.id),
                        "title": title_parts[-1] if len(title_parts) > 1 else title_parts[0],
                        "artist": title_parts[0] if len(title_parts) > 1 else "",
                        "date": str(item.data.get("year", "")),
                        "country": item.data.get("country", ""),
                        "score": 90,
                        "match_method": "discogs_barcode",
                    })
            else:
                cascade_log[-1]["status"] = "no_match"
        except Exception:
            cascade_log[-1]["status"] = "no_match"

    # Step 2: Text search
    if not best_releases and (artist or album):
        query_str = f"{artist} - {album}" if artist and album else (artist or album)
        cascade_log.append({"method": "discogs_text", "status": "searching", "query": query_str})
        results = search_release(artist=artist, album=album, tracks=track_count)
        if results and not results[0].get("error"):
            cascade_log[-1]["status"] = "found"
            cascade_log[-1]["count"] = len(results)
            best_releases = results
        else:
            cascade_log[-1]["status"] = "no_match"

    return {
        "cascade_log": cascade_log,
        "releases": best_releases,
        "best_match": best_releases[0] if best_releases else None,
        "match_method": best_releases[0].get("match_method", "none") if best_releases else "none",
        "gnudb_result": None,
    }
