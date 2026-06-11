"""Characterization tests for find_duplicates in library_manager.py.

Pins the "Mirror in the Bathroom" fix: duplicates within the SAME album
(re-rips, split-folder leftovers) must be detected, not just cross-album ones.
"""

from library_manager import find_duplicates


def _file(artist, title, album, path, albumartist=None):
    return {
        "path": path,
        "artist": artist, "title": title,
        "album": album, "albumartist": albumartist or artist,
        "tracknumber": "1", "is_compilation": False,
    }


def test_cross_album_duplicate():
    files = [
        _file("English Beat", "Mirror in the Bathroom", "I Just Can't Stop It", r"X:\a\1.flac"),
        _file("English Beat", "Mirror in the Bathroom", "Greatest Hits", r"X:\b\1.flac"),
    ]
    dups = find_duplicates(files)
    assert len(dups) == 1
    assert len(dups[0]["copies"]) == 2


def test_same_album_duplicate_detected():
    """REGRESSION: two files of the same track in the SAME album are duplicates."""
    files = [
        _file("English Beat", "Mirror in the Bathroom", "I Just Can't Stop It", r"X:\a\01.flac"),
        _file("English Beat", "Mirror in the Bathroom", "I Just Can't Stop It", r"X:\a\01 copy.flac"),
    ]
    dups = find_duplicates(files)
    assert len(dups) == 1, "same-album duplicate was missed"


def test_same_path_not_duplicate():
    """The same file entry appearing twice in a scan is not a duplicate."""
    f = _file("A", "T", "L", r"X:\a\1.flac")
    assert find_duplicates([f, dict(f)]) == []


def test_normalization_matches_variants():
    """'The English Beat' and 'English Beat' are the same artist."""
    files = [
        _file("The English Beat", "Mirror in the Bathroom", "Album A", r"X:\a\1.flac"),
        _file("English Beat", "Mirror In The Bathroom", "Album B", r"X:\b\1.flac"),
    ]
    assert len(find_duplicates(files)) == 1


def test_different_tracks_not_duplicates():
    files = [
        _file("A", "Song One", "L1", r"X:\a\1.flac"),
        _file("A", "Song Two", "L2", r"X:\b\1.flac"),
    ]
    assert find_duplicates(files) == []


def test_blank_fields_ignored():
    files = [
        _file("", "Song", "L1", r"X:\a\1.flac"),
        _file("", "Song", "L2", r"X:\b\1.flac"),
        _file("A", "", "L1", r"X:\a\2.flac"),
        _file("A", "", "L2", r"X:\b\2.flac"),
    ]
    assert find_duplicates(files) == []


def test_sorted_by_artist_then_title():
    files = [
        _file("Zeta", "Alpha Song", "L1", r"X:\a\1.flac"),
        _file("Zeta", "Alpha Song", "L2", r"X:\b\1.flac"),
        _file("Alpha", "Zeta Song", "L1", r"X:\a\2.flac"),
        _file("Alpha", "Zeta Song", "L2", r"X:\b\2.flac"),
    ]
    dups = find_duplicates(files)
    assert [d["artist"] for d in dups] == ["Alpha", "Zeta"]
