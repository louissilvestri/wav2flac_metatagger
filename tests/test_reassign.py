"""REGRESSION: a partial reassign (e.g. genre only) must never move a track
to 'Unknown Album' — path fields fall back to the file's existing tags.

This bug shipped in the first v2 Quick Clean Up: unchecked compare fields
were omitted from album_metadata, and build_output_path defaulted them.
"""

import shutil

from tagger import embed_metadata
from library_manager import reassign_track


def _make_tagged_flac(flac_file, tmp_path):
    """Place a fully tagged FLAC at its correct Plex location."""
    root = tmp_path / "library"
    dest = root / "Steely Dan" / "Aja (1977)" / "01 - Black Cow.flac"
    dest.parent.mkdir(parents=True)
    shutil.copyfile(flac_file, dest)
    embed_metadata(str(dest), {
        "title": "Black Cow", "artist": "Steely Dan", "albumartist": "Steely Dan",
        "album": "Aja", "date": "1977", "genre": "Rock",
        "tracknumber": "1", "discnumber": "1",
    })
    return root, dest


def test_partial_metadata_does_not_relocate(flac_file, tmp_path):
    """Updating only the genre must keep the file exactly where it is."""
    root, dest = _make_tagged_flac(flac_file, tmp_path)

    result = reassign_track(str(dest), {"genre": "Jazz"}, str(root), move_file=True)

    assert result["success"], result.get("error")
    assert result["new_path"] == str(dest), \
        f"file moved to {result['new_path']} on a genre-only update"
    assert dest.exists()
    assert not (root / "Unknown Artist").exists()


def test_date_only_update_keeps_artist_and_album(flac_file, tmp_path):
    """Changing the year alone re-files under the same artist/album."""
    root, dest = _make_tagged_flac(flac_file, tmp_path)

    result = reassign_track(str(dest), {"date": "1978"}, str(root), move_file=True)

    assert result["success"], result.get("error")
    parts = result["new_path"].split("\\")
    assert "Steely Dan" in parts
    assert not (root / "Unknown Artist").exists()
    assert not any("Unknown Album" in p for p in parts)


def test_full_metadata_still_moves(flac_file, tmp_path):
    """A complete reassign still relocates to the new album folder."""
    root, dest = _make_tagged_flac(flac_file, tmp_path)

    result = reassign_track(str(dest), {
        "title": "Black Cow", "artist": "Steely Dan", "albumartist": "Steely Dan",
        "album": "Greatest Hits", "date": "1985", "tracknumber": "3",
    }, str(root), move_file=True)

    assert result["success"], result.get("error")
    assert "Greatest Hits" in result["new_path"]
    assert not dest.exists(), "source should have moved"
