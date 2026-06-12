"""REGRESSION: a FLAC with a prepended ID3 tag is non-spec — Windows Explorer
and Plex show no tags/art for it, even though mutagen reads it fine. The app
re-tagged such files but left the ID3 in place. embed_metadata must strip it.
"""

from mutagen.id3 import ID3, TIT2
from mutagen.flac import FLAC

from tagger import embed_metadata, read_metadata


def _first4(path):
    with open(path, "rb") as f:
        return f.read(4)


def test_prepended_id3_is_stripped_on_save(flac_file):
    # Prepend an ID3v2 tag, the way some rippers do
    id3 = ID3()
    id3.add(TIT2(encoding=3, text="ghost"))
    id3.save(flac_file)
    assert _first4(flac_file) == b"ID3\x00" or _first4(flac_file).startswith(b"ID3"), \
        "precondition: file should start with an ID3 tag"

    # Our tagger must emit a spec-compliant FLAC
    result = embed_metadata(flac_file, {"title": "Real Title", "artist": "Band"})
    assert result["success"]
    assert _first4(flac_file) == b"fLaC", \
        "embed_metadata left a prepended ID3 tag — Windows/Plex can't read it"

    # And the Vorbis comments are intact
    tags = read_metadata(flac_file)["tags"]
    assert tags["TITLE"] == "Real Title"
    assert tags["ARTIST"] == "Band"


def test_clean_flac_stays_clean(flac_file):
    embed_metadata(flac_file, {"title": "T", "artist": "A"})
    assert _first4(flac_file) == b"fLaC"
    # FLAC still opens normally
    assert FLAC(flac_file) is not None
