"""Library Manager: scan FLAC library, detect compilations, find original albums."""

import shutil
from pathlib import Path

from tagger import read_metadata
from file_manager import sanitize_filename, find_existing_folder, _normalize_for_compare

# Session-level caches (cleared on app restart)
_cache_original_album = {}   # (artist_lower, title_lower) -> list of candidates
_cache_original_album_by_name = {}  # (artist_lower, album_lower) -> list of candidates
_cache_release_details = {}  # release_id -> details dict
_cache_art_options = {}      # release_group_id -> list of art options

# Secondary types that indicate non-original releases
_SKIP_SECONDARY = {"Compilation", "Live", "DJ-mix", "Remix", "Soundtrack",
                   "Spokenword", "Audiobook", "Audio drama", "Demo"}


def _calculate_completeness(tags: dict, has_art: bool) -> dict:
    """Score a track's tags. Delegates to the single shared scorer so the
    library view and the conversion preview always agree."""
    from services.completeness import calculate_metadata_completeness
    return calculate_metadata_completeness(tags, has_art=has_art)


# Keywords that indicate a compilation/greatest-hits album.
# "phrase" keywords are matched as substrings (safe because they're long enough).
# "word" keywords are matched as whole words only (short, high false-positive risk).
import re

_COMPILATION_PHRASE_KEYWORDS = {
    "various artists", "greatest hits", "best of", "the best of",
    "collection", "anthology", "essential",
    "platinum", "ultimate",
    "20 greatest", "30 greatest",
    "classics", "legends",
    "soundtrack", "motion picture",
    "now that's what i call",
}

# These are matched with word boundaries: re.search(r'\bkeyword\b', s)
_COMPILATION_WORD_KEYWORDS = {
    "va", "v/a", "v.a.",
    "ost",
    "gold", "hits",
    "pure", "mega", "total",
}

# Pre-compile word-boundary patterns for speed
_COMPILATION_WORD_PATTERNS = {
    kw: re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
    for kw in _COMPILATION_WORD_KEYWORDS
}


def scan_library(output_folder: str) -> list[dict]:
    """Scan the output folder for all FLAC files and read their metadata.

    Returns a list of file entries, each with:
    - path, relative_path, filename
    - artist, album, albumartist, title, tracknumber, etc.
    - completeness percentage
    - is_compilation flag
    """
    root = Path(output_folder)
    if not root.exists():
        return []

    results = []
    for flac_path in sorted(root.rglob("*.flac")):
        entry = _scan_single_file(flac_path, root)
        if entry:
            results.append(entry)

    return results


def _scan_single_file(flac_path: Path, root: Path) -> dict | None:
    """Read metadata from a single FLAC file and assess it."""
    result = read_metadata(str(flac_path))
    if not result.get("success"):
        return None

    # Flatten multi-value tags to strings for display
    tags = {}
    for key, val in result["tags"].items():
        tags[key] = "; ".join(val) if isinstance(val, list) else str(val)
    has_art = result.get("has_picture", False)

    # Calculate completeness
    completeness = _calculate_completeness(tags, has_art=has_art)

    # Determine if this is a compilation track
    artist = tags.get("ARTIST", "")
    albumartist = tags.get("ALBUMARTIST", "")
    album = tags.get("ALBUM", "")
    is_comp = _is_compilation(artist, albumartist, album)

    return {
        "path": str(flac_path),
        "relative_path": str(flac_path.relative_to(root)),
        "filename": flac_path.name,
        "size": flac_path.stat().st_size,
        # Core metadata
        "artist": artist,
        "albumartist": albumartist,
        "album": album,
        "title": tags.get("TITLE", ""),
        "tracknumber": tags.get("TRACKNUMBER", ""),
        "discnumber": tags.get("DISCNUMBER", ""),
        "date": tags.get("DATE", ""),
        "genre": tags.get("GENRE", ""),
        # MusicBrainz IDs
        "musicbrainz_albumid": tags.get("MUSICBRAINZ_ALBUMID", ""),
        "musicbrainz_trackid": tags.get("MUSICBRAINZ_TRACKID", ""),
        "musicbrainz_artistid": tags.get("MUSICBRAINZ_ARTISTID", ""),
        # Status
        "has_art": has_art,
        "completeness": completeness["percentage"],
        "missing_fields": [f for f, info in completeness["fields"].items()
                          if info["status"] != "filled"],
        "is_compilation": is_comp,
        "all_tags": tags,
    }


def _is_compilation(artist: str, albumartist: str, album: str) -> bool:
    """Detect if a track belongs to a compilation album based on tag keywords.

    Only checks albumartist and album name for compilation indicators.
    Does NOT use artist≠albumartist mismatch (too many false positives for
    bands with songwriter credits, featured artists, etc.).
    Multi-artist detection is handled at the album level in group_library_by_album.
    """
    check_strings = [
        albumartist.lower(),
        album.lower(),
    ]
    for s in check_strings:
        if not s:
            continue
        # Phrase keywords: safe as substring match (long enough to avoid false hits)
        for keyword in _COMPILATION_PHRASE_KEYWORDS:
            if keyword in s:
                return True
        # Word keywords: require word boundaries to avoid "va" in "revival" etc.
        for keyword, pattern in _COMPILATION_WORD_PATTERNS.items():
            if pattern.search(s):
                return True

    return False


def group_library_by_album(files: list[dict]) -> list[dict]:
    """Group scanned files by album for the UI.

    Returns list of album groups:
    [{
        "album": str, "albumartist": str, "date": str,
        "track_count": int, "avg_completeness": float,
        "is_compilation": bool, "files": [file_entry, ...],
    }, ...]
    """
    albums = {}
    for f in files:
        key = f"{f['albumartist']}|||{f['album']}"
        if key not in albums:
            tags = f.get("all_tags", {})
            albums[key] = {
                "album": f["album"],
                "albumartist": f["albumartist"],
                "date": f["date"],
                "genre": f.get("genre", ""),
                "label": tags.get("ORGANIZATION", tags.get("LABEL", "")),
                "catalog_number": tags.get("CATALOGNUMBER", ""),
                "musicbrainz_albumid": f.get("musicbrainz_albumid", ""),
                "musicbrainz_releasegroupid": tags.get("MUSICBRAINZ_RELEASEGROUPID", ""),
                "has_art": f.get("has_art", False),
                "disc_count": 1,
                "track_count": 0,
                "total_completeness": 0,
                "is_compilation": False,
                "files": [],
            }
        albums[key]["files"].append(f)
        albums[key]["track_count"] += 1
        albums[key]["total_completeness"] += f["completeness"]
        if f["is_compilation"]:
            albums[key]["is_compilation"] = True
        if f.get("has_art"):
            albums[key]["has_art"] = True

    result = []
    for group in albums.values():
        group["avg_completeness"] = (
            group["total_completeness"] / group["track_count"]
            if group["track_count"] > 0 else 0
        )
        del group["total_completeness"]

        # Multi-artist detection: if 3+ distinct track artists differ from the
        # album artist, this is likely a compilation even if keywords didn't match.
        if not group["is_compilation"] and group["track_count"] >= 3:
            aa_norm = _normalize_for_compare(group["albumartist"])
            distinct_artists = set()
            for f in group["files"]:
                a_norm = _normalize_for_compare(f.get("artist", ""))
                if a_norm and a_norm != aa_norm:
                    distinct_artists.add(a_norm)
            if len(distinct_artists) >= 3:
                group["is_compilation"] = True
                for f in group["files"]:
                    f["is_compilation"] = True

        # Compute disc count from actual disc numbers in files
        disc_nums = set(int(f.get("discnumber") or "1") for f in group["files"])
        group["disc_count"] = len(disc_nums)

        # Sort files by disc/track number
        group["files"].sort(key=lambda f: (
            int(f.get("discnumber") or "1"),
            int(f.get("tracknumber") or "0"),
        ))
        result.append(group)

    # Sort: compilations first, then by artist/album
    result.sort(key=lambda g: (
        0 if g["is_compilation"] else 1,
        g["albumartist"].lower(),
        g["album"].lower(),
    ))
    return result


def _filter_sort_candidates(all_candidates: dict, exclude_compilations: bool = True) -> list[dict]:
    """Shared logic: filter, look up first-release-date, sort, mark 'Likely Original'.

    Takes a dict of {release_group_id: candidate_info} and returns a sorted list.
    If exclude_compilations=False, all album types are included (for direct album lookups).
    """
    import musicbrainzngs
    from metadata_lookup import _rate_limit

    if not all_candidates:
        return []

    skip_types = _SKIP_SECONDARY if exclude_compilations else set()

    # Separate studio albums (Album type with no disqualifying secondary types)
    studio = {}
    other = {}
    for rg_id, info in all_candidates.items():
        if info["type"] == "Album" and not skip_types.intersection(info["secondary_types"]):
            studio[rg_id] = info
        else:
            other[rg_id] = info

    # For studio albums, look up the release group to get first-release-date
    for rg_id, info in studio.items():
        _rate_limit()
        try:
            rg_detail = musicbrainzngs.get_release_group_by_id(rg_id)
            rg_info = rg_detail.get("release-group", {})
            info["first_release_date"] = rg_info.get("first-release-date", "")
        except Exception:
            pass

    # Build final list: studio albums first, then EPs, then singles
    type_priority = {"Album": 0, "EP": 1, "Single": 2}
    candidates = list(studio.values())

    for rg_id, info in other.items():
        if info["type"] in ("EP", "Single") and not skip_types.intersection(info["secondary_types"]):
            candidates.append(info)

    # Sort by type priority, then by first_release_date ascending
    candidates.sort(key=lambda c: (
        type_priority.get(c["type"], 3),
        c["first_release_date"] or c["date"] or "9999",
    ))

    # Mark the earliest studio album as the likely original
    for c in candidates:
        if c["type"] == "Album":
            c["is_original"] = True
            break

    return candidates


def find_original_album(artist: str, title: str) -> list[dict]:
    """Search MusicBrainz for the original studio album a track appeared on.

    Searches by recording (artist + track title), groups by release group,
    filters non-originals, sorts by original release date.
    Cached by (artist, title).
    """
    cache_key = (artist.lower().strip(), title.lower().strip())
    if cache_key in _cache_original_album:
        return _cache_original_album[cache_key]

    import musicbrainzngs
    from metadata_lookup import init_musicbrainz, _rate_limit

    init_musicbrainz()
    _rate_limit()

    from text_utils import lucene_phrase
    try:
        result = musicbrainzngs.search_recordings(
            query=f'artist:"{lucene_phrase(artist)}" AND recording:"{lucene_phrase(title)}"',
            limit=100,
        )
    except Exception:
        return []

    recordings = result.get("recording-list", [])
    if not recordings:
        _cache_original_album[cache_key] = []
        return []

    # Collect unique release groups from recording results
    seen_rg = set()
    all_candidates = {}
    title_lower = title.lower().strip()

    for rec in recordings:
        rec_title = rec.get("title", "").lower().strip()
        if title_lower not in rec_title and rec_title not in title_lower:
            continue

        for rel in rec.get("release-list", []):
            rg = rel.get("release-group", {})
            rg_id = rg.get("id")
            if not rg_id or rg_id in seen_rg:
                continue
            seen_rg.add(rg_id)

            rg_primary = rg.get("primary-type", rg.get("type", ""))
            rg_secondary = set(rg.get("secondary-type-list", []))

            rel_artist = ""
            if rel.get("artist-credit"):
                ac = rel["artist-credit"]
                if ac and isinstance(ac[0], dict):
                    rel_artist = (ac[0].get("name", "")
                                  or ac[0].get("artist", {}).get("name", ""))

            all_candidates[rg_id] = {
                "release_group_id": rg_id,
                "release_id": rel.get("id", ""),
                "album": rg.get("title", rel.get("title", "")),
                "artist": rel_artist or artist,
                "date": rel.get("date", ""),
                "first_release_date": "",
                "type": rg_primary,
                "secondary_types": sorted(rg_secondary),
                "country": rel.get("country", ""),
                "is_original": False,
            }

    candidates = _filter_sort_candidates(all_candidates)
    _cache_original_album[cache_key] = candidates
    return candidates


def find_original_album_by_name(artist: str, album_name: str) -> list[dict]:
    """Search MusicBrainz for release groups matching an album name.

    Same filtering/sorting as find_original_album but searches by album name
    instead of track title. Cached by (artist, album_name).
    """
    cache_key = (artist.lower().strip(), album_name.lower().strip())
    if cache_key in _cache_original_album_by_name:
        return _cache_original_album_by_name[cache_key]

    import musicbrainzngs
    from metadata_lookup import init_musicbrainz, _rate_limit

    init_musicbrainz()
    _rate_limit()

    from text_utils import lucene_phrase
    query_parts = []
    if artist:
        query_parts.append(f'artist:"{lucene_phrase(artist)}"')
    if album_name:
        query_parts.append(f'release:"{lucene_phrase(album_name)}"')
    query = " AND ".join(query_parts)

    try:
        result = musicbrainzngs.search_releases(query=query, limit=25)
    except Exception:
        return []

    releases = result.get("release-list", [])
    if not releases:
        _cache_original_album_by_name[cache_key] = []
        return []

    # Group by release group
    seen_rg = set()
    all_candidates = {}

    for rel in releases:
        rg = rel.get("release-group", {})
        rg_id = rg.get("id")
        if not rg_id or rg_id in seen_rg:
            continue
        seen_rg.add(rg_id)

        rg_primary = rg.get("primary-type", rg.get("type", ""))
        rg_secondary = set(rg.get("secondary-type-list", []))
        rel_artist = rel.get("artist-credit-phrase", artist)

        medium_list = rel.get("medium-list", [])
        total_tracks = sum(int(m.get("track-count", 0)) for m in medium_list)

        all_candidates[rg_id] = {
            "release_group_id": rg_id,
            "release_id": rel.get("id", ""),
            "album": rg.get("title", rel.get("title", "")),
            "artist": rel_artist,
            "date": rel.get("date", ""),
            "first_release_date": "",
            "type": rg_primary,
            "secondary_types": sorted(rg_secondary),
            "country": rel.get("country", ""),
            "total_tracks": total_tracks,
            "is_original": False,
        }

    # Don't exclude compilations — the user is deliberately searching for this album
    candidates = _filter_sort_candidates(all_candidates, exclude_compilations=False)
    _cache_original_album_by_name[cache_key] = candidates
    return candidates


def get_art_options(release_group_id: str) -> list[dict]:
    """Fetch all releases in a release group and check CAA for cover art.

    Returns a list of releases that have front cover art available, each with:
    - release_id, country, date, format, thumb_url, full_url, recommended
    Sorted with recommended (US + CD) first, then by country/format.
    Results are cached by release_group_id.
    """
    if release_group_id in _cache_art_options:
        return _cache_art_options[release_group_id]

    import musicbrainzngs
    import requests
    from metadata_lookup import init_musicbrainz, _rate_limit

    init_musicbrainz()
    _rate_limit()

    # Browse all releases in this release group with media info
    try:
        result = musicbrainzngs.browse_releases(
            release_group=release_group_id,
            includes=["media"],
            limit=50,
        )
    except Exception:
        return []

    releases = result.get("release-list", [])
    if not releases:
        return []

    art_options = []
    for rel in releases:
        rel_id = rel.get("id", "")
        country = rel.get("country", "")
        date = rel.get("date", "")

        # Get format from media list
        media = rel.get("medium-list", [])
        formats = []
        for m in media:
            fmt = m.get("format", "")
            if fmt and fmt not in formats:
                formats.append(fmt)
        format_str = " + ".join(formats) if formats else "Unknown"

        # Check CAA for front cover art (use the JSON index endpoint)
        # Note: CAA has no rate limit — only MusicBrainz API does
        try:
            caa_url = f"https://coverartarchive.org/release/{rel_id}"
            resp = requests.get(caa_url, timeout=15, allow_redirects=True)
            if resp.status_code != 200:
                continue
            caa_data = resp.json()
        except Exception:
            continue

        # Find the front image
        images = caa_data.get("images", [])
        front = None
        for img in images:
            if img.get("front", False):
                front = img
                break
        if not front:
            continue

        # Build thumbnail URL (250px)
        thumbs = front.get("thumbnails", {})
        thumb_url = thumbs.get("250", thumbs.get("small", ""))
        full_url = front.get("image", "")

        # Determine if this is the recommended option (US + CD preference)
        is_us = country.upper() in ("US", "XW")  # XW = worldwide
        is_cd = any("CD" in f for f in formats)
        # Score: US+CD=3, US+other=2, other+CD=1, other=0
        score = (2 if is_us else 0) + (1 if is_cd else 0)

        art_options.append({
            "release_id": rel_id,
            "country": country,
            "date": date,
            "format": format_str,
            "thumb_url": thumb_url,
            "full_url": full_url,
            "score": score,
            "recommended": False,  # Set below
        })

    if not art_options:
        _cache_art_options[release_group_id] = []
        return []

    # Sort by score descending, then by date ascending
    art_options.sort(key=lambda o: (-o["score"], o["date"] or "9999"))

    # Mark the top-scored one as recommended
    art_options[0]["recommended"] = True

    # Remove internal score before returning
    for opt in art_options:
        del opt["score"]

    _cache_art_options[release_group_id] = art_options
    return art_options


def find_duplicates(files: list[dict]) -> list[dict]:
    """Find duplicate tracks (same artist + title appearing in multiple files).

    A track is considered a duplicate if:
    - Same normalized artist + title exists across different albums, OR
    - Same normalized artist + title exists in multiple files (even within
      the same album — catches re-rips, split-folder leftovers, etc.)

    Returns a list of duplicate groups:
    [{
        "artist": str, "title": str,
        "copies": [{file entry}, ...],  # 2+ copies
    }, ...]
    """
    from collections import defaultdict

    by_track = defaultdict(list)
    for f in files:
        artist = _normalize_for_compare(f.get("artist", ""))
        title = _normalize_for_compare(f.get("title", ""))
        if artist and title:
            by_track[(artist, title)].append(f)

    duplicates = []
    for (artist, title), copies in by_track.items():
        if len(copies) >= 2:
            # Deduplicate by file path (same file shouldn't count twice)
            unique_paths = set()
            deduped = []
            for c in copies:
                p = c.get("path", "")
                if p not in unique_paths:
                    unique_paths.add(p)
                    deduped.append(c)
            if len(deduped) >= 2:
                duplicates.append({
                    "artist": deduped[0]["artist"],
                    "title": deduped[0]["title"],
                    "copies": deduped,
                })

    duplicates.sort(key=lambda d: (d["artist"].lower(), d["title"].lower()))
    return duplicates


def reassign_track(
    flac_path: str,
    new_metadata: dict,
    output_root: str,
    move_file: bool = True,
    album_art: bytes = None,
) -> dict:
    """Re-tag a FLAC file and optionally move it to the correct folder.

    Args:
        flac_path: Path to the existing FLAC file
        new_metadata: Dict of field_name -> value to write
        output_root: Root output folder (for building new path)
        move_file: If True, move the file to match new artist/album folders
        album_art: Raw JPEG bytes to embed as cover art (replaces existing art)

    Returns: {success, new_path, error}
    """
    from tagger import embed_metadata, read_metadata
    from file_manager import build_output_path

    src = Path(flac_path)
    if not src.exists():
        return {"success": False, "new_path": str(src), "error": "File not found"}

    # Read existing tags BEFORE re-tagging: path fields absent from
    # new_metadata must fall back to what the file already has — a partial
    # update (e.g. genre only) must never relocate a track to "Unknown Album".
    current = read_metadata(str(src)).get("tags", {})

    def _field(key: str, tag: str, default: str = "") -> str:
        val = new_metadata.get(key)
        if val:
            return str(val)
        cur = current.get(tag, "")
        if isinstance(cur, list):
            cur = cur[0] if cur else ""
        return str(cur) if cur else default

    # Re-tag in place (with optional new album art)
    tag_result = embed_metadata(str(src), new_metadata, album_art=album_art)
    if not tag_result["success"]:
        return {"success": False, "new_path": str(src), "error": tag_result["error"]}

    if not move_file:
        return {"success": True, "new_path": str(src), "error": None}

    # Build the new path from new metadata, falling back to existing tags
    new_path = build_output_path(
        output_root=output_root,
        artist=_field("albumartist", "ALBUMARTIST",
                      _field("artist", "ARTIST", "Unknown Artist")),
        album=_field("album", "ALBUM", "Unknown Album"),
        year=_field("date", "DATE"),
        disc_number=int(_field("discnumber", "DISCNUMBER", "1") or "1"),
        total_discs=int(_field("disctotal", "DISCTOTAL", "1") or "1"),
        track_number=int(_field("tracknumber", "TRACKNUMBER", "1") or "1"),
        title=_field("title", "TITLE", "Unknown"),
    )

    if new_path == src:
        return {"success": True, "new_path": str(src), "error": None}

    # Remove any existing file with the same track number in the target folder
    dest_folder = new_path.parent
    if dest_folder.exists():
        track_num = int(new_metadata.get("tracknumber", "0") or "0")
        if track_num > 0:
            track_prefix = f"{track_num:02d} - "
            for existing in dest_folder.glob(f"{track_prefix}*.flac"):
                if existing != src and existing.name != new_path.name:
                    existing.unlink()

    # Move the file
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(new_path))

        # Clean up empty source directories
        old_dir = src.parent
        while old_dir != Path(output_root):
            if old_dir.exists() and not any(old_dir.iterdir()):
                old_dir.rmdir()
                old_dir = old_dir.parent
            else:
                break

        return {"success": True, "new_path": str(new_path), "error": None}
    except Exception as e:
        return {"success": False, "new_path": str(new_path), "error": str(e)}
