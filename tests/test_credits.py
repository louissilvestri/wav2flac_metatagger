"""Performer/writer credit enrichment from MusicBrainz relationships."""

import metadata_lookup
import musicbrainzngs


REC = {
    "artist-relation-list": [
        {"type": "conductor", "artist": {"name": "A Conductor"}},
        {"type": "performer", "artist": {"name": "Adam Ant"}},
        {"type": "vocal", "artist": {"name": "Backing Singer"}},
        {"type": "performer", "artist": {"name": "Adam Ant"}},   # dupe
    ],
    "work-relation-list": [{"work": {"id": "work1"}}],
}
WORK = {
    "artist-relation-list": [
        {"type": "composer", "artist": {"name": "Adam Ant"}},
        {"type": "lyricist", "artist": {"name": "Marco Pirroni"}},
    ],
}


def _patch(monkeypatch, rec=REC, work=WORK):
    monkeypatch.setattr(metadata_lookup, "init_musicbrainz", lambda: None)
    monkeypatch.setattr(metadata_lookup, "_rate_limit", lambda: None)
    monkeypatch.setattr(musicbrainzngs, "get_recording_by_id",
                        lambda rid, includes=None: {"recording": rec})
    monkeypatch.setattr(musicbrainzngs, "get_work_by_id",
                        lambda wid, includes=None: {"work": work})
    metadata_lookup._cache_recording_credits.clear()


def test_parses_recording_and_work_relationships(monkeypatch):
    _patch(monkeypatch)
    c = metadata_lookup.get_recording_credits("rec1")
    assert c["conductor"] == ["A Conductor"]
    assert c["performer"] == ["Adam Ant", "Backing Singer"]   # deduped, ordered
    assert c["composer"] == ["Adam Ant"]
    assert c["lyricist"] == ["Marco Pirroni"]


def test_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(metadata_lookup, "init_musicbrainz", lambda: None)
    monkeypatch.setattr(metadata_lookup, "_rate_limit", lambda: None)
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(musicbrainzngs, "get_recording_by_id", boom)
    metadata_lookup._cache_recording_credits.clear()
    assert metadata_lookup.get_recording_credits("recX") == {}


def test_empty_recording_id_short_circuits():
    assert metadata_lookup.get_recording_credits("") == {}


def test_merge_credits_disabled_does_nothing(monkeypatch):
    monkeypatch.setattr(metadata_lookup, "get_recording_credits",
                        lambda rid: {"composer": ["X"]})
    meta = {"musicbrainz_trackid": "r1"}
    metadata_lookup.merge_credits(meta, settings={"fetch_performer_credits": False})
    assert "composer" not in meta


def test_merge_credits_fills_when_enabled(monkeypatch):
    monkeypatch.setattr(metadata_lookup, "get_recording_credits",
                        lambda rid: {"composer": ["X"], "conductor": ["Y"]})
    meta = {"musicbrainz_trackid": "r1"}
    metadata_lookup.merge_credits(meta, settings={"fetch_performer_credits": True})
    assert meta["composer"] == ["X"] and meta["conductor"] == ["Y"]


def test_merge_credits_does_not_overwrite_existing(monkeypatch):
    monkeypatch.setattr(metadata_lookup, "get_recording_credits",
                        lambda rid: {"composer": ["New"]})
    meta = {"musicbrainz_trackid": "r1", "composer": "Existing"}
    metadata_lookup.merge_credits(meta, settings={"fetch_performer_credits": True})
    assert meta["composer"] == "Existing"


def test_merge_credits_no_trackid_noop(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(metadata_lookup, "get_recording_credits",
                        lambda rid: called.update(n=called["n"] + 1) or {})
    meta = {}
    metadata_lookup.merge_credits(meta, settings={"fetch_performer_credits": True})
    assert called["n"] == 0 and meta == {}
