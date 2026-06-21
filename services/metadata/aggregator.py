"""The aggregator: one identify() call, every enabled provider, one merged
record with per-field provenance.

Identity resolution order:
  1. MusicBrainz disc ID (exact, when a CUE is available)
  2. AcoustID audio fingerprints (exact-ish, when files are available)
  3. Text search (artist/album) on MusicBrainz

Then enrichment from Discogs, Last.fm, iTunes, Deezer, fanart.tv, and
Cover Art Archive — each optional, each failure-tolerant.
"""

from config import load_settings
from services.metadata import cache
from services.metadata.merge import merge_fields, get_precedence, merge_tracks
from services.metadata.providers import (
    musicbrainz as mb,
    discogs as dg,
    lastfm as fm,
    itunes as it,
    deezer as dz,
    fanarttv as fa,
    acoustid as ai,
)

DEFAULT_ENABLED = ["musicbrainz", "discogs", "lastfm", "itunes", "fanarttv",
                   "acoustid", "deezer"]


def identify(
    artist: str = "",
    album: str = "",
    disc_id: str | None = None,
    track_count: int | None = None,
    file_paths: list[str] | None = None,
    settings: dict | None = None,
) -> dict:
    """Identify an album and return a merged, provenance-tagged record.

    Returns: {
        identity: {method, confidence_note},
        fields: {name: {value, source, candidates}},
        tracks: [...], track_source: str,
        art_candidates: [{source, url, thumb_url, ...}],
        ids: {musicbrainz_release, musicbrainz_release_group, discogs_release},
        providers: {name: "ok" | "skipped" | "failed: ..."},
    }
    """
    from config import provider_has_keys
    settings = settings or load_settings()
    # A provider that's enabled but missing its required API key is silently
    # dropped — it simply isn't used (rather than failing on every lookup).
    enabled = {p for p in settings.get("metadata_providers_enabled", DEFAULT_ENABLED)
               if provider_has_keys(p)}
    cache.init_cache_table()

    providers_status: dict[str, str] = {}
    ids: dict[str, str] = {}
    identity = {"method": "none"}
    mb_details = None

    # ── Step 1: identity via MusicBrainz disc ID ─────────────────────────────
    if disc_id and "musicbrainz" in enabled:
        try:
            matches = mb.lookup_discid(disc_id)
            if matches:
                mb_details = mb.get_release(matches[0]["id"])
                if mb_details:
                    identity = {"method": "discid"}
        except Exception as e:
            providers_status["musicbrainz"] = f"failed: {e}"

    # ── Step 2: identity via audio fingerprints ──────────────────────────────
    if mb_details is None and file_paths and "acoustid" in enabled:
        if ai.is_available():
            try:
                hit = ai.identify_album(file_paths)
                if hit:
                    providers_status["acoustid"] = "ok"
                    release_id = mb.best_release_for_group(
                        hit["release_group_id"], track_count=track_count)
                    if release_id:
                        mb_details = mb.get_release(release_id)
                        if mb_details:
                            identity = {
                                "method": "fingerprint",
                                "confidence_note": f"{hit['votes']:.1f} votes from "
                                                   f"{hit['files_checked']} file(s)",
                            }
                            # Fingerprint ID can supply artist/album for enrichment
                            artist = artist or hit["artist"]
                            album = album or hit["album"]
                else:
                    providers_status["acoustid"] = "no match"
            except Exception as e:
                providers_status["acoustid"] = f"failed: {e}"
        else:
            providers_status["acoustid"] = "skipped (no fpcalc or key)"

    # ── Step 3: identity via text search ─────────────────────────────────────
    if mb_details is None and (artist or album) and "musicbrainz" in enabled:
        try:
            best = mb.search_best_release(artist, album, track_count)
            if best:
                mb_details = mb.get_release(best["id"])
                if mb_details:
                    identity = {"method": "text_search"}
        except Exception as e:
            providers_status.setdefault("musicbrainz", f"failed: {e}")

    field_sets = []
    tracks = []
    dg_tracks = []
    track_source = ""
    art_candidates = []

    if mb_details:
        providers_status.setdefault("musicbrainz", "ok")
        ids["musicbrainz_release"] = mb_details.get("id", "")
        ids["musicbrainz_release_group"] = mb_details.get("release_group_id", "")
        field_sets.append(mb.extract_fields(mb_details))
        tracks = [
            {**t, "disc_number": d["position"]}
            for d in mb_details.get("discs", [])
            for t in d.get("tracks", [])
        ]
        track_source = "musicbrainz"
        artist = artist or mb_details.get("artist", "")
        album = album or mb_details.get("title", "")
        # Cover Art Archive (keyed by MB release)
        if mb_details.get("id"):
            art_candidates.append({
                "source": "coverartarchive",
                "url": f"https://coverartarchive.org/release/{mb_details['id']}/front",
                "thumb_url": f"https://coverartarchive.org/release/{mb_details['id']}/front-250",
            })
    elif "musicbrainz" in enabled:
        providers_status.setdefault("musicbrainz", "no match")

    # ── Enrichment (each step independent and failure-tolerant) ──────────────

    if "discogs" in enabled and (artist or album):
        try:
            dg_hit = dg.search_best_release(artist, album)
            if dg_hit:
                dg_details = dg.get_release(dg_hit["id"])
                if dg_details:
                    providers_status["discogs"] = "ok"
                    ids["discogs_release"] = dg_details.get("id", "")
                    field_sets.append(dg.extract_fields(dg_details))
                    dg_tracks = [
                        {**t, "disc_number": d["position"]}
                        for d in dg_details.get("discs", [])
                        for t in d.get("tracks", [])
                    ]
                    if not tracks:
                        tracks = dg_tracks
                        track_source = "discogs"
                    for img in dg.get_art_urls(dg_details["id"])[:2]:
                        art_candidates.append({"source": "discogs", **img})
            else:
                providers_status["discogs"] = "no match"
        except Exception as e:
            providers_status["discogs"] = f"failed: {e}"

    if "lastfm" in enabled and artist and album:
        try:
            fm_fields = fm.extract_fields(artist, album)
            if fm_fields:
                providers_status["lastfm"] = "ok"
                field_sets.append(fm_fields)
            else:
                providers_status["lastfm"] = "no tags"
        except Exception as e:
            providers_status["lastfm"] = f"failed: {e}"

    if "itunes" in enabled and album:
        try:
            it_hit = it.search_album(artist, album)
            if it_hit:
                providers_status["itunes"] = "ok"
                field_sets.append(it.extract_fields(it_hit))
                if it_hit.get("art_url"):
                    art_candidates.append({
                        "source": "itunes",
                        "url": it_hit["art_url"],
                        "thumb_url": it_hit["art_thumb_url"],
                    })
            else:
                providers_status["itunes"] = "no match"
        except Exception as e:
            providers_status["itunes"] = f"failed: {e}"

    if "deezer" in enabled and album:
        try:
            dz_hit = dz.search_album(artist, album)
            if dz_hit:
                providers_status["deezer"] = "ok"
                field_sets.append(dz.extract_fields(dz_hit))
                if dz_hit.get("art_url"):
                    art_candidates.append({
                        "source": "deezer",
                        "url": dz_hit["art_url"],
                        "thumb_url": dz_hit["art_thumb_url"],
                    })
            else:
                providers_status["deezer"] = "no match"
        except Exception as e:
            providers_status["deezer"] = f"failed: {e}"

    if "fanarttv" in enabled and ids.get("musicbrainz_release_group"):
        try:
            covers = fa.get_album_art(ids["musicbrainz_release_group"])
            if covers:
                providers_status["fanarttv"] = "ok"
                for c in covers[:3]:
                    art_candidates.append({"source": "fanarttv", **c})
            else:
                providers_status["fanarttv"] = "no art"
        except Exception as e:
            providers_status["fanarttv"] = f"failed: {e}"

    # Cross-provider per-track gap-fill: when MusicBrainz drives the tracklist,
    # borrow empty per-track fields (e.g. lengths) from Discogs' tracklist.
    if track_source == "musicbrainz" and dg_tracks:
        merge_tracks(tracks, dg_tracks)

    merged = merge_fields(field_sets, get_precedence(settings))

    return {
        "identity": identity,
        "fields": merged,
        "tracks": tracks,
        "track_source": track_source,
        "art_candidates": art_candidates,
        "ids": ids,
        "providers": providers_status,
        "compilation": bool(mb_details and mb_details.get("compilation")),
    }
