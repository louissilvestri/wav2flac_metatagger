"""Tests for the conversion success gate (_verify_embedded).

A track must never be reported as converted unless its tags — and art, when
requested — are actually embedded on disk. This gate is also what protects the
source WAV + CUE from cleanup when something went wrong.
"""

from PIL import Image
from io import BytesIO

from tagger import embed_metadata
from services.conversion import _verify_embedded, _build_track_metadata


# Mirrors the real Rebel Yell case: a 14-track expanded rip matched against a
# 9-track MusicBrainz release. Bonus tracks (10+) aren't in the release.
RELEASE_9 = {
    "id": "rel-1", "title": "Rebel Yell", "artist": "Billy Idol",
    "first_release_date": "1983",
    "discs": [{
        "position": 1,
        "tracks": [
            {"position": n, "title": f"Song {n}", "artist": "",
             "isrc": "", "recording_id": ""} for n in range(1, 10)
        ],
    }],
}


class TestBuildTrackMetadataBackfill:
    def test_in_release_track_uses_release_title(self):
        f = {"parsed_title": "cue title", "parsed_artist": "Billy Idol"}
        meta = _build_track_metadata(RELEASE_9, f, track_number=3, disc_number=1)
        assert meta["title"] == "Song 3"
        assert meta["tracknumber"] == "3"

    def test_bonus_track_backfills_cue_title(self):
        """REGRESSION: track 10 absent from the release must NOT lose its name."""
        f = {"parsed_title": "Rebel Yell (session take)", "parsed_artist": "Billy Idol",
             "parsed_album": "Rebel Yell"}
        meta = _build_track_metadata(RELEASE_9, f, track_number=10, disc_number=1)
        assert meta["title"] == "Rebel Yell (session take)"
        assert meta["tracknumber"] == "10"
        assert meta["artist"] == "Billy Idol"
        # album-level fields still come from the release
        assert meta["album"] == "Rebel Yell"

    def test_bonus_track_artist_falls_back_to_albumartist(self):
        f = {"parsed_title": "Some Demo"}  # no parsed_artist
        meta = _build_track_metadata(RELEASE_9, f, track_number=11, disc_number=1)
        assert meta["artist"] == "Billy Idol"  # from release albumartist

    def test_no_release_uses_cue_entirely(self):
        f = {"parsed_title": "T", "parsed_artist": "A", "parsed_album": "Alb"}
        meta = _build_track_metadata(None, f, track_number=2, disc_number=1)
        assert meta == {"title": "T", "artist": "A", "album": "Alb",
                        "tracknumber": "2", "discnumber": "1"}


def _jpeg_bytes(size=(64, 64)):
    buf = BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


META = {"title": "Song", "artist": "Band", "album": "Disc", "tracknumber": "1"}


def test_passes_when_tags_present(flac_file):
    embed_metadata(flac_file, META)
    v = _verify_embedded(flac_file, META, expect_art=False)
    assert v["ok"]
    assert v["missing_tags"] == []
    assert not v["art_missing"]


def test_fails_when_core_tag_missing(flac_file):
    # Only write part of the metadata, but verify against the full set
    embed_metadata(flac_file, {"artist": "Band", "album": "Disc", "tracknumber": "1"})
    v = _verify_embedded(flac_file, META, expect_art=False)
    assert not v["ok"]
    assert "TITLE" in v["missing_tags"]


def test_unreadable_file_fails():
    v = _verify_embedded(r"C:\nope\missing.flac", META, expect_art=True)
    assert not v["ok"]
    assert v["art_missing"]


def test_art_missing_is_soft_warning(flac_file):
    """Tags present but art expected & absent → ok=True with art_missing flag."""
    embed_metadata(flac_file, META)  # no art
    v = _verify_embedded(flac_file, META, expect_art=True)
    assert v["ok"], "missing art must not hard-fail the track"
    assert v["art_missing"]


def test_art_present_clears_warning(flac_file):
    embed_metadata(flac_file, META, album_art=_jpeg_bytes())
    v = _verify_embedded(flac_file, META, expect_art=True)
    assert v["ok"]
    assert not v["art_missing"]


def test_core_tags_required_unconditionally(flac_file):
    """REGRESSION (Rebel Yell bonus tracks): a file missing ALBUM/TRACKNUMBER
    must fail even if those weren't in the metadata we tried to write — an
    untitled, untracked file is broken no matter what we intended."""
    embed_metadata(flac_file, {"title": "Song", "artist": "Band"})
    v = _verify_embedded(flac_file, {"title": "Song", "artist": "Band"}, expect_art=False)
    assert not v["ok"]
    assert "ALBUM" in v["missing_tags"]
    assert "TRACKNUMBER" in v["missing_tags"]
