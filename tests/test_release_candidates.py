"""Unified multi-provider candidate search: ranking must put the edition that
matches the disc's track count first, regardless of which provider supplied it.
"""

from services.metadata.search import rank_candidates, _candidate


def test_disc_count_match_ranked_first_across_providers():
    cands = [
        _candidate("musicbrainz", "mb-12", "Album", "X", "1986", track_count=12),
        _candidate("discogs", "dg-14", "Album", "X", "1986", track_count=14),
        _candidate("musicbrainz", "mb-11", "Album", "X", "1986", track_count=11),
    ]
    ranked = rank_candidates(cands, track_count=14)
    assert ranked[0]["id"] == "dg-14"
    assert ranked[0]["recommended"] is True
    assert all(not c["recommended"] for c in ranked[1:])


def test_provider_preference_breaks_ties():
    # Same (matching) track count from two providers → MusicBrainz wins the tie.
    cands = [
        _candidate("discogs", "dg", "A", "X", "1986", track_count=14),
        _candidate("musicbrainz", "mb", "A", "X", "1986", track_count=14),
    ]
    ranked = rank_candidates(cands, track_count=14)
    assert ranked[0]["provider"] == "musicbrainz"


def test_no_track_count_falls_back_to_provider_then_date():
    cands = [
        _candidate("discogs", "dg", "A", "X", "1990", track_count=0),
        _candidate("musicbrainz", "mb", "A", "X", "1992", track_count=0),
    ]
    ranked = rank_candidates(cands, track_count=None)
    assert ranked[0]["provider"] == "musicbrainz"  # provider rank wins


def test_unknown_track_count_does_not_falsely_match():
    # track_count 0 (unknown) must never count as a match against a real count.
    cands = [
        _candidate("discogs", "dg-unknown", "A", "X", "1986", track_count=0),
        _candidate("musicbrainz", "mb-14", "A", "X", "1986", track_count=14),
    ]
    ranked = rank_candidates(cands, track_count=14)
    assert ranked[0]["id"] == "mb-14"


def test_empty_list():
    assert rank_candidates([], track_count=14) == []
