"""MusicBrainz and Cover Art Archive metadata lookup."""

import time
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

import musicbrainzngs
import requests
from PIL import Image
from io import BytesIO

from config import load_settings, CONFIG_DIR

_last_request_time = 0.0
_RATE_LIMIT_INTERVAL = 1.1  # slightly over 1 second to be safe
_musicbrainz_initialized = False


def _rate_limit():
    """Enforce MusicBrainz rate limit (1 req/sec). CAA has no rate limit."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _RATE_LIMIT_INTERVAL:
        time.sleep(_RATE_LIMIT_INTERVAL - elapsed)
    _last_request_time = time.time()


_cache_recording_credits = {}  # recording_id -> {composer, lyricist, conductor, performer}


def get_recording_credits(recording_id: str) -> dict:
    """Performer/writer credits for a recording, from MusicBrainz relationships.

    Conductor and performers come from the recording's artist relationships;
    composer and lyricist come from the linked work(s). Best-effort — returns {}
    on any failure so it can never break conversion. Cached by recording id.
    Note: this costs 1 + (number of works) rate-limited API calls per recording.
    """
    if not recording_id:
        return {}
    if recording_id in _cache_recording_credits:
        return _cache_recording_credits[recording_id]

    init_musicbrainz()
    out = {"composer": [], "lyricist": [], "conductor": [], "performer": []}
    try:
        _rate_limit()
        rec = musicbrainzngs.get_recording_by_id(
            recording_id, includes=["artist-rels", "work-rels"]).get("recording", {})
    except Exception:
        _cache_recording_credits[recording_id] = {}
        return {}

    for rel in rec.get("artist-relation-list", []):
        name = rel.get("artist", {}).get("name", "")
        if not name:
            continue
        rtype = rel.get("type", "")
        if rtype == "conductor":
            out["conductor"].append(name)
        elif rtype in ("performer", "vocal", "instrument", "performing orchestra"):
            out["performer"].append(name)

    work_ids = [rel.get("work", {}).get("id")
                for rel in rec.get("work-relation-list", [])
                if rel.get("work", {}).get("id")]
    for wid in work_ids:
        try:
            _rate_limit()
            work = musicbrainzngs.get_work_by_id(
                wid, includes=["artist-rels"]).get("work", {})
        except Exception:
            continue
        for rel in work.get("artist-relation-list", []):
            name = rel.get("artist", {}).get("name", "")
            if not name:
                continue
            rtype = rel.get("type", "")
            if rtype == "composer":
                out["composer"].append(name)
            elif rtype in ("lyricist", "writer"):
                out["lyricist"].append(name)

    # Drop empties; de-dupe each list preserving order.
    result = {k: list(dict.fromkeys(v)) for k, v in out.items() if v}
    _cache_recording_credits[recording_id] = result
    return result


def merge_credits(metadata: dict, settings: dict | None = None) -> None:
    """Fill composer/lyricist/conductor/performer on a track's metadata in place
    from MusicBrainz, when enabled and a recording id is present. Best-effort;
    only fills fields that are empty so existing/EAC values win."""
    settings = settings or load_settings()
    if not settings.get("fetch_performer_credits"):
        return
    rid = metadata.get("musicbrainz_trackid")
    if not rid:
        return
    credits = get_recording_credits(rid)
    for field in ("composer", "lyricist", "conductor", "performer"):
        if credits.get(field) and not metadata.get(field):
            metadata[field] = credits[field]


def init_musicbrainz():
    """Initialize musicbrainzngs user-agent (only runs once per session)."""
    global _musicbrainz_initialized
    if _musicbrainz_initialized:
        return
    settings = load_settings()
    ua = settings.get("musicbrainz_user_agent", "MusicManager/1.0.0")
    parts = ua.split("/", 1)
    app_name = parts[0] if parts else "MusicManager"
    app_version = parts[1].split(" ")[0] if len(parts) > 1 else "1.0.0"
    contact = settings.get("musicbrainz_user_agent", "")
    email_start = contact.find("(")
    email_end = contact.find(")")
    email = contact[email_start + 1:email_end] if email_start > -1 else ""
    musicbrainzngs.set_useragent(app_name, app_version, email)
    _musicbrainz_initialized = True


def search_release(artist: str = None, album: str = None, tracks: int = None, barcode: str = None) -> list[dict]:
    """Search MusicBrainz for matching releases."""
    init_musicbrainz()
    _rate_limit()

    from text_utils import lucene_phrase

    query_parts = []
    if artist:
        query_parts.append(f'artist:"{lucene_phrase(artist)}"')
    if album:
        query_parts.append(f'release:"{lucene_phrase(album)}"')
    if barcode:
        query_parts.append(f"barcode:{barcode}")

    query = " AND ".join(query_parts) if query_parts else ""

    try:
        result = musicbrainzngs.search_releases(query=query, limit=25)
        releases = []
        for rel in result.get("release-list", []):
            medium_list = rel.get("medium-list", [])
            total_tracks = sum(
                int(m.get("track-count", 0)) for m in medium_list
            )
            release_info = {
                "id": rel.get("id"),
                "title": rel.get("title"),
                "artist": rel.get("artist-credit-phrase", ""),
                "date": rel.get("date", ""),
                "country": rel.get("country", ""),
                "barcode": rel.get("barcode", ""),
                "status": rel.get("status", ""),
                "label": "",
                "catalog_number": "",
                "total_tracks": total_tracks,
                "disc_count": len(medium_list),
                "format": "",
                "score": int(rel.get("ext:score", 0)),
            }
            if rel.get("label-info-list"):
                li = rel["label-info-list"][0]
                release_info["label"] = li.get("label", {}).get("name", "")
                release_info["catalog_number"] = li.get("catalog-number", "")
            if medium_list:
                release_info["format"] = medium_list[0].get("format", "")

            # Prefer CD releases
            if tracks and total_tracks == tracks:
                release_info["score"] += 10
            if release_info["format"] == "CD":
                release_info["score"] += 5

            releases.append(release_info)

        releases.sort(key=lambda x: x["score"], reverse=True)
        return releases
    except Exception as e:
        return [{"error": str(e)}]


_cache_release_details = {}  # release_id -> details dict


def get_release_details(release_id: str) -> dict:
    """Get full release details including track listing. Cached per release_id."""
    if release_id in _cache_release_details:
        return _cache_release_details[release_id]

    init_musicbrainz()
    _rate_limit()

    try:
        result = musicbrainzngs.get_release_by_id(
            release_id,
            includes=["artists", "recordings", "labels", "release-groups", "media", "isrcs"]
        )
        release = result.get("release", {})

        details = {
            "id": release.get("id"),
            "title": release.get("title"),
            "artist": release.get("artist-credit-phrase", ""),
            "artist_id": "",
            "date": release.get("date", ""),
            "first_release_date": "",  # original album date from release group
            "country": release.get("country", ""),
            "barcode": release.get("barcode", ""),
            "status": release.get("status", ""),
            "label": "",
            "catalog_number": "",
            "release_group_id": "",
            "compilation": False,
            "discs": [],
        }

        if release.get("artist-credit"):
            ac = release["artist-credit"]
            if ac and isinstance(ac[0], dict) and "artist" in ac[0]:
                details["artist_id"] = ac[0]["artist"].get("id", "")

        if release.get("release-group"):
            rg_data = release["release-group"]
            details["release_group_id"] = rg_data.get("id", "")
            # Grab first-release-date if embedded (it often is)
            details["first_release_date"] = rg_data.get("first-release-date", "")
            # "Compilation" secondary type → authoritative compilation flag,
            # catches single-artist greatest-hits sets with no title keyword.
            secondary = [t.lower() for t in rg_data.get("secondary-type-list", [])]
            details["compilation"] = "compilation" in secondary

        if release.get("label-info-list"):
            li = release["label-info-list"][0]
            details["label"] = li.get("label", {}).get("name", "")
            details["catalog_number"] = li.get("catalog-number", "")

        for medium in release.get("medium-list", []):
            disc = {
                "position": int(medium.get("position", 1)),
                "format": medium.get("format", "CD"),
                "tracks": [],
            }
            for track in medium.get("track-list", []):
                recording = track.get("recording", {})
                track_info = {
                    "position": int(track.get("position", track.get("number", 0))),
                    "title": recording.get("title", track.get("title", "")),
                    "artist": "",
                    "artist_id": "",
                    "length_ms": None,
                    "isrc": "",
                    "recording_id": recording.get("id", ""),
                }
                if recording.get("artist-credit"):
                    ac = recording["artist-credit"]
                    if ac and isinstance(ac[0], dict):
                        if "artist" in ac[0]:
                            track_info["artist"] = ac[0].get("name", "") or ac[0]["artist"].get("name", "")
                            track_info["artist_id"] = ac[0]["artist"].get("id", "")
                        else:
                            track_info["artist"] = ac[0].get("name", "")
                if not track_info["artist"]:
                    track_info["artist"] = details["artist"]
                if recording.get("length"):
                    track_info["length_ms"] = int(recording["length"])
                if recording.get("isrc-list"):
                    track_info["isrc"] = recording["isrc-list"][0]
                disc["tracks"].append(track_info)
            disc["tracks"].sort(key=lambda t: t["position"])
            details["discs"].append(disc)

        details["discs"].sort(key=lambda d: d["position"])

        # Fetch genre from release-group tags (MusicBrainz stores genres here)
        rg_id = details.get("release_group_id")
        if rg_id:
            try:
                _rate_limit()
                rg_result = musicbrainzngs.get_release_group_by_id(
                    rg_id, includes=["tags"]
                )
                rg = rg_result.get("release-group", {})
                # Get authoritative first-release-date from the full RG lookup
                frd = rg.get("first-release-date", "")
                if frd:
                    details["first_release_date"] = frd
                tag_list = rg.get("tag-list", [])
                if tag_list:
                    # Pick the highest-voted tag(s), capitalize
                    sorted_tags = sorted(tag_list, key=lambda t: int(t.get("count", 0)), reverse=True)
                    # Use top genre (most voted)
                    details["genre"] = sorted_tags[0].get("name", "").title()
                    # Store all genres for multi-value support
                    details["genres"] = [t.get("name", "").title() for t in sorted_tags[:5] if int(t.get("count", 0)) > 0]
            except Exception:
                pass  # Genre is optional; don't fail the whole lookup

        _cache_release_details[release_id] = details
        return details
    except Exception as e:
        return {"error": str(e)}


def get_cover_art(release_id: str, max_size: int = 1200, quality: int = 90) -> bytes | None:
    """Fetch front cover art from Cover Art Archive, resize if needed.

    Note: CAA has no rate limit — only MusicBrainz API does.
    """
    art_cache_dir = CONFIG_DIR / "art_cache"
    art_cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = art_cache_dir / f"{release_id}.jpg"
    if cache_file.exists():
        return cache_file.read_bytes()

    url = f"https://coverartarchive.org/release/{release_id}/front"
    try:
        resp = requests.get(url, timeout=30, allow_redirects=True)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

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


def search_by_toc(track_count: int, track_offsets: list[int], leadout_offset: int) -> list[dict]:
    """Search MusicBrainz using a fuzzy TOC lookup."""
    init_musicbrainz()
    _rate_limit()

    try:
        toc_string = f"1 {track_count} {leadout_offset} {' '.join(str(o) for o in track_offsets)}"
        result = musicbrainzngs.get_releases_by_discid(
            id="", toc=toc_string, includes=["artists"]
        )
        releases = []
        if "release-list" in result.get("disc", {}):
            for rel in result["disc"]["release-list"]:
                releases.append({
                    "id": rel.get("id"),
                    "title": rel.get("title"),
                    "artist": rel.get("artist-credit-phrase", ""),
                    "date": rel.get("date", ""),
                    "country": rel.get("country", ""),
                    "barcode": rel.get("barcode", ""),
                })
        return releases
    except Exception:
        return []


def lookup_by_discid(disc_id: str) -> list[dict]:
    """Look up a MusicBrainz disc ID for exact release matching."""
    init_musicbrainz()
    _rate_limit()

    try:
        result = musicbrainzngs.get_releases_by_discid(
            disc_id, includes=["artists", "labels"]
        )
    except musicbrainzngs.ResponseError:
        return []
    except Exception:
        return []

    releases = []
    if "disc" in result and "release-list" in result["disc"]:
        for rel in result["disc"]["release-list"]:
            medium_list = rel.get("medium-list", [])
            total_tracks = sum(int(m.get("track-count", 0)) for m in medium_list)
            release_info = {
                "id": rel.get("id"),
                "title": rel.get("title"),
                "artist": rel.get("artist-credit-phrase", ""),
                "date": rel.get("date", ""),
                "country": rel.get("country", ""),
                "barcode": rel.get("barcode", ""),
                "status": rel.get("status", ""),
                "label": "",
                "catalog_number": "",
                "total_tracks": total_tracks,
                "disc_count": len(medium_list),
                "format": "",
                "score": 100,
                "match_method": "disc_id",
            }
            if rel.get("label-info-list"):
                li = rel["label-info-list"][0]
                release_info["label"] = li.get("label", {}).get("name", "")
                release_info["catalog_number"] = li.get("catalog-number", "")
            if medium_list:
                release_info["format"] = medium_list[0].get("format", "")
            releases.append(release_info)
    return releases


def lookup_by_barcode(barcode: str) -> list[dict]:
    """Search MusicBrainz by UPC/EAN barcode."""
    if not barcode or len(barcode) < 10:
        return []
    init_musicbrainz()
    _rate_limit()

    try:
        result = musicbrainzngs.search_releases(query=f"barcode:{barcode}", limit=5)
        releases = []
        for rel in result.get("release-list", []):
            medium_list = rel.get("medium-list", [])
            total_tracks = sum(int(m.get("track-count", 0)) for m in medium_list)
            releases.append({
                "id": rel.get("id"),
                "title": rel.get("title"),
                "artist": rel.get("artist-credit-phrase", ""),
                "date": rel.get("date", ""),
                "country": rel.get("country", ""),
                "barcode": rel.get("barcode", ""),
                "status": rel.get("status", ""),
                "total_tracks": total_tracks,
                "disc_count": len(medium_list),
                "format": medium_list[0].get("format", "") if medium_list else "",
                "score": 90,
                "match_method": "barcode",
            })
        return releases
    except Exception:
        return []


# ─── GnuDB/freedb Lookup ───────────────────────────────────────────────────────

_GNUDB_SERVER = "http://gnudb.gnudb.org/~cddb/cddb.cgi"
_GNUDB_PROTO = "6"


def _gnudb_request(cmd: str) -> str | None:
    """Send an HTTP request to GnuDB and return the response body.

    Uses the CDDB HTTP protocol format with + as separator (not URL-encoded spaces).
    GnuDB requires a recognized client name in the hello string.
    """
    # Build URL manually — CDDB protocol uses + as space in query params
    cmd_encoded = cmd.replace(" ", "+")
    url = (
        f"{_GNUDB_SERVER}"
        f"?cmd={cmd_encoded}"
        f"&hello=anonymous+localhost+xmcd+2.6"
        f"&proto={_GNUDB_PROTO}"
    )
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


def gnudb_query(freedb_disc_id: str, track_count: int, offsets: list[int], total_seconds: int) -> list[dict]:
    """Query GnuDB for a disc by its freedb disc ID and TOC.

    Args:
        freedb_disc_id: 8-char hex freedb disc ID (from CUE REM DISCID)
        track_count: number of tracks
        offsets: frame offsets for each track (in CD frames, 75fps)
        total_seconds: total disc length in seconds

    Returns list of matches: [{category, disc_id, artist, album}, ...]
    """
    # Build query: cddb query discid ntrks off1 off2 ... nsecs
    offsets_str = " ".join(str(o) for o in offsets)
    cmd = f"cddb query {freedb_disc_id} {track_count} {offsets_str} {total_seconds}"

    text = _gnudb_request(cmd)
    if not text:
        return []

    lines = text.strip().splitlines()
    if not lines:
        return []

    # Response codes:
    # 200 = exact match (single line: "200 category discid dtitle")
    # 211 = inexact matches (multiple lines, terminated by ".")
    # 202 = no match
    code = lines[0].split()[0] if lines[0] else ""
    results = []

    if code == "200":
        # Single exact match: "200 rock ab12cd34 Artist / Album"
        parts = lines[0].split(" ", 3)
        if len(parts) >= 4:
            category = parts[1]
            disc_id = parts[2]
            dtitle = parts[3]
            artist, _, album = dtitle.partition(" / ")
            results.append({"category": category, "disc_id": disc_id,
                          "artist": artist.strip(), "album": album.strip()})
    elif code in ("211", "210"):
        # Multiple matches: each line is "category discid dtitle"
        for line in lines[1:]:
            if line.strip() == ".":
                break
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                category = parts[0]
                disc_id = parts[1]
                dtitle = parts[2]
                artist, _, album = dtitle.partition(" / ")
                results.append({"category": category, "disc_id": disc_id,
                              "artist": artist.strip(), "album": album.strip()})

    return results


def gnudb_read(category: str, disc_id: str) -> dict | None:
    """Read full CD info from GnuDB.

    Returns parsed metadata: {artist, album, year, genre, tracks: [{title, artist}, ...]}
    """
    cmd = f"cddb read {category} {disc_id}"
    text = _gnudb_request(cmd)
    if not text:
        return None

    lines = text.strip().splitlines()
    if not lines or not lines[0].startswith("210"):
        return None

    # Parse XMCD response
    data = {}
    tracks = {}

    for line in lines[1:]:
        if line.strip() == ".":
            break
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if key == "DTITLE":
            data["dtitle"] = data.get("dtitle", "") + value
        elif key == "DYEAR":
            data["year"] = value
        elif key == "DGENRE":
            data["genre"] = value
        elif key.startswith("TTITLE"):
            try:
                track_num = int(key[6:])
                tracks[track_num] = tracks.get(track_num, "") + value
            except ValueError:
                pass

    if not data.get("dtitle"):
        return None

    # DTITLE format: "Artist / Album"
    dtitle = data["dtitle"]
    artist, _, album = dtitle.partition(" / ")
    if not album:
        album = artist
        artist = ""

    # Parse track titles (may contain "Artist / Title" for compilations)
    track_list = []
    for i in sorted(tracks.keys()):
        ttitle = tracks[i]
        track_artist, _, track_title = ttitle.partition(" / ")
        if not track_title:
            track_title = track_artist
            track_artist = artist
        track_list.append({"title": track_title.strip(), "artist": track_artist.strip()})

    return {
        "artist": artist.strip(),
        "album": album.strip(),
        "year": data.get("year", ""),
        "genre": data.get("genre", ""),
        "tracks": track_list,
    }


def lookup_gnudb(freedb_disc_id: str, track_count: int, offsets: list[int], total_seconds: int) -> dict | None:
    """Full GnuDB lookup: query then read.

    Returns full metadata or None if not found.
    """
    matches = gnudb_query(freedb_disc_id, track_count, offsets, total_seconds)
    if not matches:
        return None

    # Read the first (best) match
    best = matches[0]
    details = gnudb_read(best["category"], best["disc_id"])
    if details:
        details["match_method"] = "gnudb"
        details["gnudb_category"] = best["category"]
        details["gnudb_disc_id"] = best["disc_id"]
    return details


def _is_valid_barcode(barcode: str) -> bool:
    """Check if a barcode is valid (not a placeholder or all zeros)."""
    if not barcode:
        return False
    stripped = barcode.strip()
    # Must be digits only, 12-14 chars (UPC-A, EAN-13, EAN-14)
    if not stripped.isdigit() or len(stripped) < 12 or len(stripped) > 14:
        return False
    # Reject all-zeros or all-same-digit placeholders
    if len(set(stripped)) <= 1:
        return False
    return True


def automated_lookup(
    disc_id: str = None,
    barcode: str = None,
    track_count: int = None,
    track_offsets: list[int] = None,
    leadout_offset: int = None,
    artist: str = None,
    album: str = None,
    freedb_disc_id: str = None,
    total_seconds: int = None,
) -> dict:
    """Run the full automated lookup cascade.

    Order: MusicBrainz disc ID → barcode → GnuDB → fuzzy TOC → text search.
    Returns the best match with details, or reports which methods were tried.
    """
    cascade_log = []
    best_releases = []
    gnudb_result = None  # Stored separately (different format from MusicBrainz releases)

    # Step 1: MusicBrainz Disc ID lookup (most accurate)
    if disc_id:
        cascade_log.append({"method": "disc_id", "status": "searching", "query": disc_id})
        results = lookup_by_discid(disc_id)
        if results:
            cascade_log[-1]["status"] = "found"
            cascade_log[-1]["count"] = len(results)
            best_releases = results
        else:
            cascade_log[-1]["status"] = "no_match"

    # Step 2: Barcode lookup (skip invalid/placeholder barcodes)
    if not best_releases and _is_valid_barcode(barcode):
        cascade_log.append({"method": "barcode", "status": "searching", "query": barcode})
        results = lookup_by_barcode(barcode)
        if results:
            cascade_log[-1]["status"] = "found"
            cascade_log[-1]["count"] = len(results)
            best_releases = results
        else:
            cascade_log[-1]["status"] = "no_match"

    # Step 3: GnuDB/freedb lookup (uses same disc ID as EAC)
    if not best_releases and freedb_disc_id and track_count and track_offsets:
        disc_seconds = total_seconds or (leadout_offset // 75 if leadout_offset else 0)
        if disc_seconds:
            cascade_log.append({"method": "gnudb", "status": "searching", "query": freedb_disc_id})
            gnudb_result = lookup_gnudb(freedb_disc_id, track_count, track_offsets, disc_seconds)
            if gnudb_result:
                cascade_log[-1]["status"] = "found"
                cascade_log[-1]["count"] = 1
            else:
                cascade_log[-1]["status"] = "no_match"

    # Step 4: Fuzzy TOC lookup (MusicBrainz)
    if not best_releases and not gnudb_result and track_count and track_offsets and leadout_offset:
        cascade_log.append({"method": "toc", "status": "searching", "query": f"{track_count} tracks"})
        results = search_by_toc(track_count, track_offsets, leadout_offset)
        if results:
            cascade_log[-1]["status"] = "found"
            cascade_log[-1]["count"] = len(results)
            for r in results:
                r["score"] = 70
                r["match_method"] = "toc"
            best_releases = results
        else:
            cascade_log[-1]["status"] = "no_match"

    # Step 5: Text search (MusicBrainz)
    if not best_releases and not gnudb_result and (artist or album):
        cascade_log.append({"method": "text", "status": "searching", "query": f"{artist} - {album}"})
        results = search_release(artist=artist, album=album, tracks=track_count)
        if results and not results[0].get("error"):
            cascade_log[-1]["status"] = "found"
            cascade_log[-1]["count"] = len(results)
            for r in results:
                r["match_method"] = "text"
            best_releases = results
        else:
            cascade_log[-1]["status"] = "no_match"

    return {
        "cascade_log": cascade_log,
        "releases": best_releases,
        "best_match": best_releases[0] if best_releases else None,
        "match_method": best_releases[0].get("match_method", "none") if best_releases else "none",
        "gnudb_result": gnudb_result,
    }
