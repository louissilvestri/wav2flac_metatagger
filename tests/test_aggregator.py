"""Aggregator orchestration tests — providers are monkeypatched, no network."""

import pytest

from services.metadata import aggregator
from services.metadata.providers import lastfm


MB_DETAILS = {
    "id": "mb-rel-1",
    "release_group_id": "mb-rg-1",
    "title": "Cosmo's Factory",
    "artist": "Creedence Clearwater Revival",
    "date": "2008-09-02",
    "first_release_date": "1970-07-08",
    "genre": "Rock",
    "genres": ["Rock"],
    "label": "Fantasy",
    "catalog_number": "8402",
    "barcode": "025218840224",
    "country": "US",
    "discs": [{"position": 1, "format": "CD", "tracks": [
        {"position": 1, "title": "Ramble Tamble", "artist": "CCR",
         "recording_id": "rec-1", "isrc": "", "artist_id": "", "length_ms": 425000},
    ]}],
}

DG_DETAILS = {
    "id": "123456",
    "title": "Cosmo's Factory",
    "artist": "Creedence Clearwater Revival",
    "date": "1970",
    "first_release_date": "1970",
    "genre": "Rock",
    "styles": ["Country Rock", "Swamp Rock"],
    "label": "Fantasy Records",
    "catalog_number": "F-8402",
    "barcode": "",
    "country": "US",
    "discs": [],
}


@pytest.fixture
def patched_providers(monkeypatch):
    # Enable every provider regardless of whether an API key is configured in the
    # environment — these tests monkeypatch the provider calls, so key-gating
    # must not silently drop them (it does on a keyless CI runner).
    import config
    monkeypatch.setattr(config, "provider_has_keys", lambda p: True)

    from services.metadata.providers import musicbrainz as mb_mod
    from services.metadata.providers import discogs as dg_mod
    from services.metadata.providers import itunes as it_mod
    from services.metadata.providers import deezer as dz_mod
    from services.metadata.providers import fanarttv as fa_mod

    monkeypatch.setattr(mb_mod, "search_best_release",
                        lambda artist="", album="", track_count=None: {"id": "mb-rel-1"})
    monkeypatch.setattr(mb_mod, "get_release", lambda rid: MB_DETAILS)
    monkeypatch.setattr(dg_mod, "search_best_release",
                        lambda artist="", album="": {"id": "123456"})
    monkeypatch.setattr(dg_mod, "get_release", lambda rid: DG_DETAILS)
    monkeypatch.setattr(dg_mod, "get_art_urls", lambda rid: [
        {"url": "https://dg/full.jpg", "thumb_url": "https://dg/t.jpg",
         "width": 600, "height": 600, "primary": True}])
    monkeypatch.setattr(lastfm, "get_album_tags", lambda a, b: [
        {"name": "swamp rock", "count": 100},
        {"name": "classic rock", "count": 80},
    ])
    monkeypatch.setattr(it_mod, "search_album", lambda a, b: {
        "title": "Cosmo's Factory", "artist": "Creedence Clearwater Revival",
        "date": "1970-07-08", "genre": "Rock",
        "art_url": "https://it/3000.jpg", "art_thumb_url": "https://it/250.jpg",
        "track_count": 11})
    monkeypatch.setattr(dz_mod, "search_album", lambda a, b: None)
    monkeypatch.setattr(fa_mod, "get_album_art", lambda rg: [
        {"url": "https://fa/c.jpg", "thumb_url": "https://fa/p.jpg", "likes": 5}])


def test_identify_text_search(patched_providers):
    result = aggregator.identify(artist="Creedence Clearwater Revival",
                                 album="Cosmo's Factory")

    assert result["identity"]["method"] == "text_search"
    f = result["fields"]

    # Original date from MB (already specific)
    assert f["original_date"]["value"] == "1970-07-08"
    # Genre from Last.fm by precedence
    assert f["genre"]["value"] == "Swamp Rock"
    assert f["genre"]["source"] == "lastfm"
    # Styles from Discogs by precedence
    assert f["styles"]["value"] == ["Country Rock", "Swamp Rock"]
    assert f["styles"]["source"] == "discogs"
    # Label from Discogs
    assert f["label"]["value"] == "Fantasy Records"
    # Barcode from MB (Discogs empty)
    assert f["barcode"]["value"] == "025218840224"

    # Tracks from MB skeleton
    assert result["track_source"] == "musicbrainz"
    assert result["tracks"][0]["title"] == "Ramble Tamble"

    # IDs captured for both providers
    assert result["ids"]["musicbrainz_release"] == "mb-rel-1"
    assert result["ids"]["discogs_release"] == "123456"

    # Art candidates from CAA + Discogs + iTunes + fanart.tv
    sources = {a["source"] for a in result["art_candidates"]}
    assert {"coverartarchive", "discogs", "itunes", "fanarttv"} <= sources

    # Provider status map
    assert result["providers"]["musicbrainz"] == "ok"
    assert result["providers"]["lastfm"] == "ok"
    assert result["providers"]["deezer"] == "no match"


def test_identify_provider_failure_tolerated(patched_providers, monkeypatch):
    """One provider exploding must not break the others."""
    from services.metadata.providers import discogs as dg_mod

    def boom(artist="", album=""):
        raise RuntimeError("discogs down")
    monkeypatch.setattr(dg_mod, "search_best_release", boom)

    result = aggregator.identify(artist="CCR", album="Cosmo's Factory")
    assert result["providers"]["discogs"].startswith("failed:")
    assert result["fields"]["title"]["value"] == "Cosmo's Factory"
    assert result["providers"]["musicbrainz"] == "ok"


def test_identify_nothing_found(monkeypatch):
    from services.metadata.providers import musicbrainz as mb_mod
    from services.metadata.providers import discogs as dg_mod
    from services.metadata.providers import itunes as it_mod
    from services.metadata.providers import deezer as dz_mod

    monkeypatch.setattr(mb_mod, "search_best_release", lambda **kw: None)
    monkeypatch.setattr(dg_mod, "search_best_release", lambda artist="", album="": None)
    monkeypatch.setattr(lastfm, "get_album_tags", lambda a, b: [])
    monkeypatch.setattr(it_mod, "search_album", lambda a, b: None)
    monkeypatch.setattr(dz_mod, "search_album", lambda a, b: None)

    result = aggregator.identify(artist="zzz", album="zzz")
    assert result["identity"]["method"] == "none"
    assert result["fields"] == {}
    assert result["tracks"] == []


def test_lastfm_junk_tag_filtering(monkeypatch):
    """Junk tags ('seen live', decades, counts<10) never become genres."""
    raw = [
        {"name": "seen live", "count": 500},
        {"name": "70s", "count": 200},
        {"name": "swamp rock", "count": 100},
        {"name": "obscuretag", "count": 3},
    ]
    monkeypatch.setattr(
        lastfm, "get_album_tags",
        lambda a, b: [t for t in raw
                      if t["count"] >= 10 and t["name"].lower() not in lastfm._JUNK_TAGS
                      and not lastfm._is_decade(t["name"])])
    fields = lastfm.extract_fields("CCR", "Cosmo's Factory")
    assert fields["genre"]["value"] == "Swamp Rock"
