"""Characterization tests for Plex metadata completeness scoring (app.py)."""

from app import calculate_metadata_completeness
from config import PLEX_ALL_FIELDS

FULL_META = {
    "TITLE": "Test", "ARTIST": "Artist", "ALBUMARTIST": "Artist",
    "ALBUM": "Album", "TRACKNUMBER": "1", "DISCNUMBER": "1",
    "DATE": "2024", "GENRE": "Rock",
    "MUSICBRAINZ_ALBUMID": "abc", "MUSICBRAINZ_ARTISTID": "def",
    "MUSICBRAINZ_TRACKID": "ghi", "MUSICBRAINZ_ALBUMARTISTID": "jkl",
    "TRACKTOTAL": "10", "DISCTOTAL": "1",
}


def test_field_count():
    # 14 tag fields + 1 for cover art
    assert len(PLEX_ALL_FIELDS) == 14


def test_full_metadata_with_art_is_100():
    result = calculate_metadata_completeness(FULL_META, has_art=True)
    assert result["percentage"] == 100
    assert result["filled"] == result["total"] == 15


def test_full_metadata_without_art():
    result = calculate_metadata_completeness(FULL_META, has_art=False)
    assert result["filled"] == 14
    assert result["percentage"] == 93  # round(14/15*100)


def test_partial_metadata_pinned():
    partial = {"TITLE": "T", "ARTIST": "A", "ALBUM": "L", "TRACKNUMBER": "1"}
    result = calculate_metadata_completeness(partial, has_art=False)
    assert result["filled"] == 4
    assert result["total"] == 15
    assert result["percentage"] == 27


def test_art_counts_as_field():
    result = calculate_metadata_completeness({}, has_art=True)
    assert result["filled"] == 1
    assert result["fields"]["COVER_ART"]["status"] == "filled"


def test_whitespace_values_count_as_missing():
    result = calculate_metadata_completeness({"TITLE": "   "}, has_art=False)
    assert result["fields"]["TITLE"]["status"] == "missing"


def test_lowercase_keys_accepted():
    result = calculate_metadata_completeness({"title": "T"}, has_art=False)
    assert result["fields"]["TITLE"]["status"] == "filled"
