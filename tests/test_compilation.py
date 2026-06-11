"""Characterization tests for compilation detection in library_manager.py.

Pins the false-positive fix: short keywords ("va", "ost", "mega") must match
whole words only — "Creedence Clearwater Revival" contains "va" as a substring
and was wrongly flagged before the fix.
"""

import pytest

from library_manager import _is_compilation, group_library_by_album


# (artist, albumartist, album) -> expected
FALSE_POSITIVE_CASES = [
    # The original bug reports: CCR albums flagged because of "va" in "revival"
    ("Creedence Clearwater Revival", "Creedence Clearwater Revival", "Bayou Country"),
    ("Creedence Clearwater Revival", "Creedence Clearwater Revival", "Cosmo's Factory"),
    ("Creedence Clearwater Revival", "Creedence Clearwater Revival", "Willy and the Poor Boys"),
    # Other artists containing compilation keywords as substrings
    ("Nirvana", "Nirvana", "Nevermind"),
    ("Van Halen", "Van Halen", "1984"),
    ("Boston", "Boston", "Boston"),           # "ost" inside "Boston"
    ("Megadeth", "Megadeth", "Rust in Peace"),  # "mega" inside "Megadeth"
]

TRUE_POSITIVE_CASES = [
    ("Various Artists", "Various Artists", "Pure 80s"),
    ("", "VA", "Best Hits 2000"),
    ("", "Various Artists", "Now That's What I Call Music! 12"),
    ("Queen", "Queen", "Greatest Hits"),
    ("Eagles", "Eagles", "The Best of Eagles"),
    ("", "", "Top Gun: Original Motion Picture Soundtrack"),
    ("", "", "Pulp Fiction OST"),
    ("ABBA", "ABBA", "Gold: Greatest Hits"),
    ("", "Various", "Mega Hits 2003"),
]


@pytest.mark.parametrize("artist,albumartist,album", FALSE_POSITIVE_CASES)
def test_not_flagged_as_compilation(artist, albumartist, album):
    assert not _is_compilation(artist, albumartist, album), \
        f"{albumartist} - {album} wrongly flagged as compilation"


@pytest.mark.parametrize("artist,albumartist,album", TRUE_POSITIVE_CASES)
def test_flagged_as_compilation(artist, albumartist, album):
    assert _is_compilation(artist, albumartist, album), \
        f"{albumartist} - {album} should be flagged as compilation"


def _file(artist, albumartist, album, title, track, **over):
    entry = {
        "path": f"X:\\{albumartist}\\{album}\\{track:02d} - {title}.flac",
        "relative_path": f"{albumartist}\\{album}\\{track:02d} - {title}.flac",
        "filename": f"{track:02d} - {title}.flac",
        "size": 1,
        "artist": artist, "albumartist": albumartist, "album": album,
        "title": title, "tracknumber": str(track), "discnumber": "1",
        "date": "1999", "genre": "Rock",
        "musicbrainz_albumid": "", "musicbrainz_trackid": "", "musicbrainz_artistid": "",
        "has_art": False, "completeness": 50, "missing_fields": [],
        "is_compilation": False, "all_tags": {},
    }
    entry.update(over)
    return entry


class TestGroupLibraryByAlbum:
    def test_multi_artist_album_flagged(self):
        """3+ distinct track artists differing from albumartist => compilation."""
        files = [
            _file("Artist A", "Various", "Mix", "S1", 1),
            _file("Artist B", "Various", "Mix", "S2", 2),
            _file("Artist C", "Various", "Mix", "S3", 3),
        ]
        # Clear keyword effects: use non-keyword albumartist
        for f in files:
            f["albumartist"] = "Mixtape"
            f["album"] = "Roadtrip"
        albums = group_library_by_album(files)
        assert albums[0]["is_compilation"]
        assert all(f["is_compilation"] for f in albums[0]["files"])

    def test_featured_artists_not_flagged(self):
        """Only 1-2 differing artists (features/credits) must NOT flag."""
        files = [
            _file("Santana", "Santana", "Supernatural", "S1", 1),
            _file("Santana feat. Rob Thomas", "Santana", "Supernatural", "S2", 2),
            _file("Santana", "Santana", "Supernatural", "S3", 3),
        ]
        albums = group_library_by_album(files)
        assert not albums[0]["is_compilation"]

    def test_album_level_fields_carried(self):
        files = [_file("A", "A", "L", "T", 1,
                       genre="Jazz", musicbrainz_albumid="mb-1", has_art=True,
                       all_tags={"ORGANIZATION": "Blue Note", "CATALOGNUMBER": "BN-1"})]
        album = group_library_by_album(files)[0]
        assert album["genre"] == "Jazz"
        assert album["label"] == "Blue Note"
        assert album["catalog_number"] == "BN-1"
        assert album["musicbrainz_albumid"] == "mb-1"
        assert album["has_art"] is True
        assert album["disc_count"] == 1

    def test_disc_count_from_discnumbers(self):
        files = [
            _file("A", "A", "L", "T1", 1, discnumber="1"),
            _file("A", "A", "L", "T2", 1, discnumber="2"),
        ]
        assert group_library_by_album(files)[0]["disc_count"] == 2

    def test_tracks_sorted_by_disc_then_track(self):
        files = [
            _file("A", "A", "L", "D2T1", 1, discnumber="2"),
            _file("A", "A", "L", "D1T2", 2, discnumber="1"),
            _file("A", "A", "L", "D1T1", 1, discnumber="1"),
        ]
        titles = [f["title"] for f in group_library_by_album(files)[0]["files"]]
        assert titles == ["D1T1", "D1T2", "D2T1"]

    def test_compilations_sort_first(self):
        files = [
            _file("Aardvark", "Aardvark", "Album", "T", 1),
            _file("Zeta", "Various Artists", "Pure 80s", "T", 1, is_compilation=True),
        ]
        albums = group_library_by_album(files)
        assert albums[0]["is_compilation"]
