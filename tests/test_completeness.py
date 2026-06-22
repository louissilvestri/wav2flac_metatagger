"""Completeness scoring — source-agnostic (12 slots).

8 display + 2 optional + cover art + 1 identifier credit (any provider ID).
Pins the fix for: a fully-tagged album scoring 87% because it lacked
MusicBrainz-specific artist IDs even though it was tagged from other sources.
"""

from services.completeness import calculate_metadata_completeness
from config import PLEX_SCORED_SLOTS

FULL_META = {
    "TITLE": "Test", "ARTIST": "Artist", "ALBUMARTIST": "Artist",
    "ALBUM": "Album", "TRACKNUMBER": "1", "DISCNUMBER": "1",
    "DATE": "2024", "GENRE": "Rock",
    "MUSICBRAINZ_ALBUMID": "abc",   # one identifier is enough
    "TRACKTOTAL": "10", "DISCTOTAL": "1",
}


def test_slot_count():
    # 8 display + 2 optional + cover art + identifier
    assert PLEX_SCORED_SLOTS == 12


def test_full_metadata_with_art_is_100():
    result = calculate_metadata_completeness(FULL_META, has_art=True)
    assert result["percentage"] == 100
    assert result["filled"] == result["total"] == 12


def test_artist_ids_not_required():
    """REGRESSION: the Beauty and the Beat case — full display tags, art,
    totals, and a MusicBrainz ALBUM id, but NO MusicBrainz artist IDs. Must
    be 100%, not 87%."""
    meta = dict(FULL_META)  # has MUSICBRAINZ_ALBUMID, no ARTISTID/ALBUMARTISTID
    result = calculate_metadata_completeness(meta, has_art=True)
    assert result["percentage"] == 100


def test_discogs_id_satisfies_identifier():
    """An album tagged from Discogs (no MusicBrainz IDs) still gets the
    identifier credit."""
    meta = {k: v for k, v in FULL_META.items() if not k.startswith("MUSICBRAINZ")}
    meta["DISCOGS_ALBUMID"] = "12345"
    result = calculate_metadata_completeness(meta, has_art=True)
    assert result["fields"]["IDENTIFIER"]["status"] == "filled"
    assert result["percentage"] == 100


def test_no_identifier_costs_one_slot():
    meta = {k: v for k, v in FULL_META.items() if not k.startswith("MUSICBRAINZ")}
    result = calculate_metadata_completeness(meta, has_art=True)
    assert result["fields"]["IDENTIFIER"]["status"] == "missing"
    assert result["filled"] == 11
    assert result["percentage"] == 92  # round(11/12*100)


def test_partial_metadata():
    partial = {"TITLE": "T", "ARTIST": "A", "ALBUM": "L", "TRACKNUMBER": "1"}
    result = calculate_metadata_completeness(partial, has_art=False)
    assert result["filled"] == 4
    assert result["total"] == 12
    assert result["percentage"] == 33  # round(4/12*100)


def test_art_counts_as_slot():
    result = calculate_metadata_completeness({}, has_art=True)
    assert result["filled"] == 1
    assert result["fields"]["COVER_ART"]["status"] == "filled"


def test_whitespace_values_count_as_missing():
    result = calculate_metadata_completeness({"TITLE": "   "}, has_art=False)
    assert result["fields"]["TITLE"]["status"] == "missing"


def test_lowercase_keys_accepted():
    result = calculate_metadata_completeness({"title": "T"}, has_art=False)
    assert result["fields"]["TITLE"]["status"] == "filled"
