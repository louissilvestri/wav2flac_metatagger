"""Library Manager: scan FLAC library, detect compilations, find original albums."""

import shutil
from pathlib import Path

from tagger import read_metadata
from file_manager import sanitize_filename, find_existing_folder, _normalize_for_compare

# Session-level caches (cleared on app restart)
_cache_original_album = {}   # (artist_lower, title_lower) -> list of candidates
_cache_original_album_by_name = {}  # (artist_lower, album_lower) -> list of candidates
_cache_track_editions = {}   # (artist_lower, title_lower) -> list of editions
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
    explicit_comp = _explicit_compilation(tags)
    is_comp = _is_compilation(artist, albumartist, album, tags)

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
        "explicit_compilation": explicit_comp,  # True/False = user override; None = heuristic
        "all_tags": tags,
    }


def _explicit_compilation(tags: dict) -> bool | None:
    """Authoritative compilation signal from tags, BOTH ways:
    True  — COMPILATION=1 (Picard/iTunes) or a release-type containing
            "compilation" (catches single-artist greatest-hits like "Ramones Mania").
    False — COMPILATION=0, an explicit "not a compilation" override.
    None  — no explicit signal; fall back to keyword/multi-artist heuristics.
    """
    val = str(tags.get("COMPILATION", "")).strip().lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    album_type = " ".join(str(tags.get(k, "")) for k in (
        "RELEASETYPE", "ALBUMTYPE", "MUSICBRAINZ_ALBUMTYPE",
    )).lower()
    if "compilation" in album_type:
        return True
    return None


def _is_compilation(artist: str, albumartist: str, album: str,
                    tags: dict | None = None) -> bool:
    """Detect if a track belongs to a compilation album.

    Order of signals:
    1. An explicit tag (see _explicit_compilation) — authoritative both ways.
    2. Title/album-artist keywords ("greatest hits", "best of", "anthology"…).
    Multi-artist detection is handled at the album level in group_library_by_album.

    NOTE: artist≠albumartist mismatch is intentionally NOT used here (too many
    false positives for bands with songwriter credits, featured artists, etc.).
    """
    explicit = _explicit_compilation(tags or {})
    if explicit is not None:
        return explicit

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
                "barcode": tags.get("BARCODE", ""),
                # RELEASECOUNTRY is the Picard standard; fall back to legacy COUNTRY.
                "country": tags.get("RELEASECOUNTRY", tags.get("COUNTRY", "")),
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
        # Skipped when the user explicitly tagged it "not a compilation".
        explicitly_not_comp = any(f.get("explicit_compilation") is False for f in group["files"])
        if not group["is_compilation"] and not explicitly_not_comp and group["track_count"] >= 3:
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

        # ReplayGain is "present" only when every track carries a track-gain tag
        # (a partially-analyzed album still offers the Add ReplayGain action).
        group["has_replay_gain"] = bool(group["files"]) and all(
            "REPLAYGAIN_TRACK_GAIN" in (f.get("all_tags") or {})
            for f in group["files"])

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


def _filter_sort_candidates(all_candidates: dict) -> list[dict]:
    """Sort candidate release groups for display — NEVER drops any.

    Every release group a track/album maps to is returned. Clean studio albums
    (primary type Album with no compilation/live/soundtrack/etc. secondary type)
    sort first and the earliest is marked the likely original; compilations, live
    albums, EPs, singles, and everything else follow but are always included.
    Nothing is filtered out — the user wants to see every album a track is on.
    """
    import musicbrainzngs
    from metadata_lookup import _rate_limit

    if not all_candidates:
        return []

    def is_clean_album(info: dict) -> bool:
        return (info["type"] == "Album"
                and not _SKIP_SECONDARY.intersection(info["secondary_types"]))

    # Look up first-release-date for clean studio albums so originals order
    # correctly (compilations/singles sort by their own release date).
    for info in all_candidates.values():
        if is_clean_album(info):
            _rate_limit()
            try:
                rg_detail = musicbrainzngs.get_release_group_by_id(info["release_group_id"])
                info["first_release_date"] = (
                    rg_detail.get("release-group", {}).get("first-release-date", ""))
            except Exception:
                pass

    type_priority = {"Album": 0, "EP": 1, "Single": 2}
    candidates = sorted(all_candidates.values(), key=lambda c: (
        0 if is_clean_album(c) else 1,            # clean studio albums first
        type_priority.get(c["type"], 3),          # then Album / EP / Single / other
        c["first_release_date"] or c["date"] or "9999",
    ))

    # Mark the earliest clean studio album as the likely original.
    for c in candidates:
        if is_clean_album(c):
            c["is_original"] = True
            break

    return candidates


def _release_rank(rel: dict) -> tuple:
    """Pick a sensible representative release within a release group: prefer an
    Official status, then the earliest date. Keeps a region-specific reissue
    (e.g. a Spanish pressing) from masquerading as the album when a canonical
    official release exists."""
    status = (rel.get("status") or "").lower()
    return (0 if status == "official" else 1, rel.get("date") or "9999")


def _artist_loosely_matches(a: str, b: str) -> bool:
    """True if two artist names plausibly refer to the same act, allowing for
    regional name variants (e.g. "The Beat" vs "The English Beat")."""
    from text_utils import fold_for_compare

    def norm(s):
        s = fold_for_compare(s)
        return s[4:] if s.startswith("the ") else s

    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    return a in b or b in a


def _search_track_recordings(artist: str, title: str) -> list[dict]:
    """Find MusicBrainz recordings matching a track (artist + title).

    Runs a strict artist+recording query, then a title-only query whose hits are
    kept only when the artist credit loosely matches — this rescues releases
    credited under a regional name variant ("The Beat" vs "The English Beat").
    Shared by find_original_album (one album per group) and find_track_editions
    (every edition), so both see the same recording set.
    """
    import musicbrainzngs
    from metadata_lookup import init_musicbrainz, _rate_limit
    from text_utils import lucene_phrase

    init_musicbrainz()
    _rate_limit()
    try:
        result = musicbrainzngs.search_recordings(
            query=f'artist:"{lucene_phrase(artist)}" AND recording:"{lucene_phrase(title)}"',
            limit=100,
        )
    except Exception:
        return []

    recordings = result.get("recording-list", [])

    _rate_limit()
    try:
        title_only_result = musicbrainzngs.search_recordings(
            query=f'recording:"{lucene_phrase(title)}"',
            limit=100,
        )
    except Exception:
        title_only_result = {}

    seen_rec_ids = {rec.get("id") for rec in recordings}
    for rec in title_only_result.get("recording-list", []):
        if rec.get("id") in seen_rec_ids:
            continue
        if any(
            _artist_loosely_matches(artist, ac.get("name", "") or ac.get("artist", {}).get("name", ""))
            for ac in rec.get("artist-credit", []) if isinstance(ac, dict)
        ):
            recordings.append(rec)
            seen_rec_ids.add(rec.get("id"))

    return recordings


def find_original_album(artist: str, title: str) -> list[dict]:
    """Search MusicBrainz for the original studio album a track appeared on.

    Searches by recording (artist + track title), groups by release group,
    sorts originals first. One entry per album (release group). Cached by
    (artist, title). For every individual edition, see find_track_editions.
    """
    cache_key = (artist.lower().strip(), title.lower().strip())
    if cache_key in _cache_original_album:
        return _cache_original_album[cache_key]

    from text_utils import fold_for_compare
    recordings = _search_track_recordings(artist, title)
    if not recordings:
        _cache_original_album[cache_key] = []
        return []

    # Collect one entry per release group. When a track appears on several
    # releases of the same album, keep the best representative (Official first,
    # then earliest) rather than whichever happened to be seen first — otherwise
    # a regional reissue can stand in for the canonical album.
    all_candidates = {}
    title_lower = fold_for_compare(title)

    for rec in recordings:
        rec_title = fold_for_compare(rec.get("title", ""))
        if title_lower not in rec_title and rec_title not in title_lower:
            continue

        for rel in rec.get("release-list", []):
            rg = rel.get("release-group", {})
            rg_id = rg.get("id")
            if not rg_id:
                continue

            rank = _release_rank(rel)
            existing = all_candidates.get(rg_id)
            if existing is not None and existing["_rank"] <= rank:
                continue

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
                "_rank": rank,
            }

    for c in all_candidates.values():
        c.pop("_rank", None)
    candidates = _filter_sort_candidates(all_candidates)
    _cache_original_album[cache_key] = candidates
    return candidates


def find_track_editions(artist: str, title: str) -> list[dict]:
    """Every release (edition) a track appears on — not collapsed to one per
    album. This is the song-search counterpart to an album-name search: it lets
    the user pick the exact edition (e.g. the UK vs Spanish pressing of
    "Prince Charming") instead of a single arbitrary representative.

    Deduped by release id, sorted clean studio albums first, then by album,
    Official editions, and date. Cached by (artist, title).
    """
    cache_key = (artist.lower().strip(), title.lower().strip())
    if cache_key in _cache_track_editions:
        return _cache_track_editions[cache_key]

    from text_utils import fold_for_compare
    recordings = _search_track_recordings(artist, title)
    if not recordings:
        _cache_track_editions[cache_key] = []
        return []

    title_lower = fold_for_compare(title)
    by_release: dict[str, dict] = {}

    for rec in recordings:
        rec_title = fold_for_compare(rec.get("title", ""))
        if title_lower not in rec_title and rec_title not in title_lower:
            continue

        rec_artist = ""
        if rec.get("artist-credit"):
            ac = rec["artist-credit"]
            if ac and isinstance(ac[0], dict):
                rec_artist = (ac[0].get("name", "")
                              or ac[0].get("artist", {}).get("name", ""))

        for rel in rec.get("release-list", []):
            rel_id = rel.get("id")
            if not rel_id or rel_id in by_release:
                continue

            rg = rel.get("release-group", {})
            medium_list = rel.get("medium-list", [])
            total_tracks = sum(int(m.get("track-count", 0)) for m in medium_list)
            fmt = medium_list[0].get("format", "") if medium_list else ""

            by_release[rel_id] = {
                "release_id": rel_id,
                "release_group_id": rg.get("id", ""),
                "album": rg.get("title", rel.get("title", "")),
                "artist": rec_artist or artist,
                "date": rel.get("date", ""),
                "country": rel.get("country", ""),
                "format": fmt,
                "type": rg.get("primary-type", rg.get("type", "")),
                "secondary_types": sorted(set(rg.get("secondary-type-list", []))),
                "status": rel.get("status", ""),
                "total_tracks": total_tracks,
                "disc_count": len(medium_list) or 1,
            }

    def is_clean_album(info: dict) -> bool:
        return (info["type"] == "Album"
                and not _SKIP_SECONDARY.intersection(info["secondary_types"]))

    editions = sorted(by_release.values(), key=lambda c: (
        0 if is_clean_album(c) else 1,             # studio albums first
        c["album"].lower(),                         # editions of an album grouped
        0 if (c.get("status", "").lower() == "official") else 1,
        c["date"] or "9999",
    ))
    _cache_track_editions[cache_key] = editions
    return editions


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

    # Group by release group, keeping the best representative release per group
    # (Official first, then earliest) rather than whichever sorted highest.
    all_candidates = {}

    for rel in releases:
        rg = rel.get("release-group", {})
        rg_id = rg.get("id")
        if not rg_id:
            continue

        rank = _release_rank(rel)
        existing = all_candidates.get(rg_id)
        if existing is not None and existing["_rank"] <= rank:
            continue

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
            "_rank": rank,
        }

    # Never exclude compilations/live/etc. — show every album that matches.
    for c in all_candidates.values():
        c.pop("_rank", None)
    candidates = _filter_sort_candidates(all_candidates)
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

    # Enrich with MusicBrainz performer/writer credits (gated by setting,
    # best-effort) so reassign/clean-up populate the same fields as conversion.
    from metadata_lookup import merge_credits
    merge_credits(new_metadata)

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
