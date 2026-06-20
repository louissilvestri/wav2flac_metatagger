"""Regression: song/album search must never hide categories of results.

The bug: searching by track title returned only studio albums/EPs/singles —
compilations, live albums, soundtracks, and unknown-type release groups were
dropped entirely, so a heavily-compiled single ("Stand and Deliver") showed a
handful of results while an album-name search showed many.
"""

import library_manager
from library_manager import _filter_sort_candidates, _release_rank


def _cand(rg_id, rtype, secondary=None, date="1990"):
    return {
        "release_group_id": rg_id, "release_id": f"rel-{rg_id}",
        "album": rg_id.title(), "artist": "Adam and the Ants",
        "date": date, "first_release_date": "",
        "type": rtype, "secondary_types": secondary or [],
        "country": "GB", "is_original": False,
    }


def test_no_category_is_dropped(monkeypatch):
    """Every release group survives — comps, live, soundtrack, unknown types."""
    import metadata_lookup
    monkeypatch.setattr(metadata_lookup, "_rate_limit", lambda: None)
    import musicbrainzngs
    monkeypatch.setattr(musicbrainzngs, "get_release_group_by_id",
                        lambda rg: {"release-group": {"first-release-date": "1981"}})

    candidates = {
        "studio":     _cand("studio", "Album", date="1981"),
        "comp":       _cand("comp", "Album", ["Compilation"], date="1986"),
        "live":       _cand("live", "Album", ["Live"], date="1995"),
        "soundtrack": _cand("soundtrack", "Album", ["Soundtrack"]),
        "single":     _cand("single", "Single", date="1981"),
        "broadcast":  _cand("broadcast", "Broadcast"),
    }
    result = _filter_sort_candidates(dict(candidates))

    got = {c["release_group_id"] for c in result}
    assert got == set(candidates), f"results were dropped: {set(candidates) - got}"


def test_clean_studio_album_marked_original_and_first(monkeypatch):
    import metadata_lookup
    monkeypatch.setattr(metadata_lookup, "_rate_limit", lambda: None)
    import musicbrainzngs
    monkeypatch.setattr(musicbrainzngs, "get_release_group_by_id",
                        lambda rg: {"release-group": {"first-release-date": "1981"}})

    result = _filter_sort_candidates({
        "comp":   _cand("comp", "Album", ["Compilation"], date="1986"),
        "studio": _cand("studio", "Album", date="1981"),
    })
    assert result[0]["release_group_id"] == "studio"
    assert result[0]["is_original"] is True
    # The compilation is still present, just ranked after the original.
    assert any(c["release_group_id"] == "comp" for c in result)


def test_release_rank_prefers_official_then_earliest():
    official_old = {"status": "Official", "date": "1981"}
    official_new = {"status": "Official", "date": "1999"}
    bootleg = {"status": "Bootleg", "date": "1980"}
    assert _release_rank(official_old) < _release_rank(official_new)
    assert _release_rank(official_new) < _release_rank(bootleg)


def _recording_with(releases):
    return [{
        "id": "rec1", "title": "Stand and Deliver",
        "artist-credit": [{"name": "Adam and the Ants"}],
        "release-list": releases,
    }]


def _rel(rid, rg_id, rg_title, country, date, secondary=None, tracks=10, fmt="CD"):
    return {
        "id": rid, "status": "Official", "country": country, "date": date,
        "release-group": {"id": rg_id, "title": rg_title, "primary-type": "Album",
                          "secondary-type-list": secondary or []},
        "medium-list": [{"track-count": tracks, "format": fmt}],
    }


def test_find_track_editions_does_not_collapse_by_album(monkeypatch):
    """REGRESSION: a song search must surface every edition of an album, not one
    representative — the user needs to pick the right pressing (UK vs Spanish)."""
    releases = [
        _rel("relES", "rgPC", "Prince Charming", "ES", "1981", fmt="12\" Vinyl"),
        _rel("relGB", "rgPC", "Prince Charming", "GB", "1981-11-02", fmt="12\" Vinyl"),
        _rel("relComp", "rgHits", "Hits", "GB", "1986", secondary=["Compilation"], tracks=13),
    ]
    monkeypatch.setattr(library_manager, "_search_track_recordings",
                        lambda a, t: _recording_with(releases))
    library_manager._cache_track_editions.clear()

    editions = library_manager.find_track_editions("Adam and the Ants", "Stand and Deliver")
    ids = [e["release_id"] for e in editions]

    # Both Prince Charming pressings present — not collapsed to one.
    assert "relES" in ids and "relGB" in ids
    pc = [e for e in editions if e["album"] == "Prince Charming"]
    assert len(pc) == 2
    # Studio album sorts before the compilation.
    assert editions[0]["album"] == "Prince Charming"
    assert editions[-1]["album"] == "Hits"
    # Per-edition metadata is carried through for the UI filters.
    gb = next(e for e in editions if e["release_id"] == "relGB")
    assert gb["country"] == "GB" and gb["total_tracks"] == 10
