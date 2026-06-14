"""Picking a release within a release group must respect the disc's track count
so expanded/special editions aren't replaced by the standard album.

REGRESSION: Depeche Mode "Black Celebration" — a 14-track rip was matched to a
12-track release because the fingerprint resolved the group to the "canonical"
(US/CD/earliest) release, ignoring track count.
"""

from services.metadata.providers.musicbrainz import _rank_release, _release_track_count


def _rel(rid, country, date, fmt, tracks):
    return {
        "id": rid, "country": country, "date": date,
        "medium-list": [{"format": fmt, "track-count": tracks}],
    }


def _best(releases, track_count):
    return min(releases, key=lambda r: _rank_release(r, track_count))["id"]


GROUP = [
    _rel("std-us", "US", "1986", "CD", 11),   # would win on US+CD+earliest
    _rel("twelve", "US", "1986", "CD", 12),
    _rel("expanded-fr", "FR", "1986", "CD", 14),
    _rel("expanded-gb", "GB", "1986-03-17", "CD", 14),
]


def test_track_count_match_beats_us_cd_earliest():
    assert _best(GROUP, 14) in ("expanded-fr", "expanded-gb")


def test_no_track_count_falls_back_to_us_cd_earliest():
    # Without a disc track count, the US+CD release wins as before.
    assert _best(GROUP, None) == "std-us"


def test_track_count_match_prefers_us_cd_among_matches():
    matches = [
        _rel("m-fr", "FR", "1986", "CD", 14),
        _rel("m-us", "US", "1986", "CD", 14),
    ]
    assert _best(matches, 14) == "m-us"


def test_multi_disc_track_count_summed():
    rel = {"medium-list": [{"track-count": 10}, {"track-count": 8}]}
    assert _release_track_count(rel) == 18
