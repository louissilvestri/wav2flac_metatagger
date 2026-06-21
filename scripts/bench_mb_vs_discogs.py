"""Head-to-head: MusicBrainz vs Discogs on a random sample of the user's library.

Measures, per album:
  - completeness: how many of 10 common release fields each provider fills
  - raw API latency: time spent in the actual search + detail calls (the
    mandated ~1/sec rate-limit sleeps are taken OUTSIDE the timed sections, so
    this reflects provider/network speed, not our throttle policy)

Run: python scripts/bench_mb_vs_discogs.py [N]
"""
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import musicbrainzngs
from config import load_settings
from metadata_lookup import init_musicbrainz, _rate_limit as mb_sleep
from tagger import read_metadata
import discogs_lookup
from discogs_lookup import _get_client, _rate_limit as dg_sleep

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12

# 10 common release fields both providers *could* supply.
FIELDS = ["date", "orig_date", "country", "barcode", "label",
          "catalog", "genre_style", "tracklist", "track_len", "isrc"]


def sample_albums(output_folder, n):
    root = Path(output_folder)
    flacs = []
    for i, p in enumerate(root.rglob("*.flac")):
        flacs.append(p)
        if i > 8000:  # enough to sample from without enumerating forever
            break
    random.shuffle(flacs)
    seen, picks = set(), []
    for p in flacs:
        tags = read_metadata(str(p)).get("tags", {})
        artist = (tags.get("ALBUMARTIST") or tags.get("ARTIST") or "")
        album = tags.get("ALBUM") or ""
        if isinstance(artist, list): artist = artist[0] if artist else ""
        if isinstance(album, list): album = album[0] if album else ""
        key = (artist.lower().strip(), album.lower().strip())
        if not artist or not album or key in seen:
            continue
        seen.add(key)
        picks.append((artist, album))
        if len(picks) >= n:
            break
    return picks


def mb_eval(artist, album):
    """Returns (fields_dict, latency_seconds) or (None, latency)."""
    init_musicbrainz()
    from text_utils import lucene_phrase
    q = f'artist:"{lucene_phrase(artist)}" AND release:"{lucene_phrase(album)}"'
    mb_sleep()
    t = time.time()
    res = musicbrainzngs.search_releases(query=q, limit=5)
    lat = time.time() - t
    rels = res.get("release-list", [])
    if not rels:
        return None, lat
    rid = rels[0]["id"]
    mb_sleep()
    t = time.time()
    try:
        full = musicbrainzngs.get_release_by_id(
            rid, includes=["artists", "recordings", "labels",
                           "release-groups", "media", "isrcs", "genres"]).get("release", {})
    except Exception:
        mb_sleep()
        t = time.time()
        full = musicbrainzngs.get_release_by_id(
            rid, includes=["artists", "recordings", "labels",
                           "release-groups", "media", "isrcs"]).get("release", {})
    lat += time.time() - t

    rg = full.get("release-group", {})
    mediums = full.get("medium-list", [])
    tracks = [tr for m in mediums for tr in m.get("track-list", [])]
    genres = full.get("genre-list", []) or rg.get("genre-list", [])
    f = {
        "date": bool(full.get("date")),
        "orig_date": bool(rg.get("first-release-date")),
        "country": bool(full.get("country")),
        "barcode": bool(full.get("barcode")),
        "label": bool(full.get("label-info-list") and
                      full["label-info-list"][0].get("label", {}).get("name")),
        "catalog": bool(full.get("label-info-list") and
                        full["label-info-list"][0].get("catalog-number")),
        "genre_style": bool(genres),
        "tracklist": bool(tracks),
        "track_len": any(tr.get("recording", {}).get("length") or tr.get("length")
                         for tr in tracks),
        "isrc": any(tr.get("recording", {}).get("isrc-list") for tr in tracks),
    }
    return f, lat


def dg_eval(artist, album):
    client = _get_client()
    from text_utils import normalize_punctuation
    dg_sleep()
    t = time.time()
    results = client.search(type="release", artist=normalize_punctuation(artist),
                            release_title=normalize_punctuation(album))
    page = results.page(1)
    lat = time.time() - t
    if not page:
        return None, lat
    rid = page[0].id
    dg_sleep()
    t = time.time()
    rel = client.release(int(rid))
    # touch fields (discogs_client lazy-loads on access)
    year = rel.year
    labels = rel.labels
    genres = rel.genres or []
    styles = rel.styles or []
    tracklist = rel.tracklist
    identifiers = rel.data.get("identifiers", []) if hasattr(rel, "data") else []
    orig = ""
    try:
        orig = rel.master.year if rel.master else ""
    except Exception:
        pass
    lat += time.time() - t

    barcode = any(i.get("type") == "Barcode" for i in identifiers)
    f = {
        "date": bool(year),
        "orig_date": bool(orig),
        "country": bool(rel.country),
        "barcode": barcode,
        "label": bool(labels and labels[0].name),
        "catalog": bool(labels and labels[0].data.get("catno")),
        "genre_style": bool(genres or styles),
        "tracklist": bool(tracklist),
        "track_len": any(getattr(tr, "duration", "") for tr in tracklist),
        "isrc": False,  # Discogs API does not expose ISRC
    }
    return f, lat


def main():
    s = load_settings()
    albums = sample_albums(s.get("output_folder", ""), N)
    print(f"Sampled {len(albums)} albums\n")

    mb_tot = {k: 0 for k in FIELDS}
    dg_tot = {k: 0 for k in FIELDS}
    mb_lat, dg_lat = [], []
    mb_hits = dg_hits = 0

    print(f"{'#':<3}{'artist — album':<48}{'MB':>6}{'DG':>6}{'MBs':>7}{'DGs':>7}")
    for i, (artist, album) in enumerate(albums, 1):
        label = f"{artist} — {album}"[:46]
        try:
            mf, ml = mb_eval(artist, album)
        except Exception as e:
            mf, ml = None, 0.0
        try:
            df, dl = dg_eval(artist, album)
        except Exception as e:
            df, dl = None, 0.0
        mb_n = sum(mf.values()) if mf else 0
        dg_n = sum(df.values()) if df else 0
        if mf:
            mb_hits += 1; mb_lat.append(ml)
            for k in FIELDS: mb_tot[k] += int(mf[k])
        if df:
            dg_hits += 1; dg_lat.append(dl)
            for k in FIELDS: dg_tot[k] += int(df[k])
        print(f"{i:<3}{label:<48}{mb_n:>6}{dg_n:>6}{ml:>6.2f}s{dl:>6.2f}s")

    def avg(x): return sum(x) / len(x) if x else 0.0
    print("\n— Per-field fill rate (count across albums found) —")
    print(f"{'field':<14}{'MB':>6}{'DG':>6}")
    for k in FIELDS:
        print(f"{k:<14}{mb_tot[k]:>6}{dg_tot[k]:>6}")

    print("\n— Summary —")
    print(f"albums matched:     MB {mb_hits}/{len(albums)}   DG {dg_hits}/{len(albums)}")
    print(f"avg fields filled:  MB {avg([sum(1 for k in FIELDS if mb_tot)]) if False else sum(mb_tot.values())/max(mb_hits,1):.1f}/10   "
          f"DG {sum(dg_tot.values())/max(dg_hits,1):.1f}/10")
    print(f"avg API latency:    MB {avg(mb_lat):.2f}s   DG {avg(dg_lat):.2f}s  (raw, excl. rate-limit sleeps)")


if __name__ == "__main__":
    main()
