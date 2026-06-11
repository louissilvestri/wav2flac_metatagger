"""Characterization tests for CUE parsing and MusicBrainz disc-ID math."""

import pytest

from cue_parser import parse_cue_file, cue_to_metadata, calculate_musicbrainz_discid

SAMPLE_CUE = (
    'REM GENRE Rock\n'
    'REM DATE 1973\n'
    'REM DISCID 370B8A08\n'
    'CATALOG 0724382101826\n'
    'PERFORMER "Pink Floyd"\n'
    'TITLE "The Dark Side of the Moon"\n'
    'FILE "test.wav" WAVE\n'
    '  TRACK 01 AUDIO\n'
    '    TITLE "Speak to Me"\n'
    '    PERFORMER "Pink Floyd"\n'
    '    ISRC GBDJQ7300001\n'
    '    INDEX 01 00:00:00\n'
    '  TRACK 02 AUDIO\n'
    '    TITLE "Breathe"\n'
    '    PERFORMER "Pink Floyd"\n'
    '    ISRC GBDJQ7300002\n'
    '    INDEX 00 01:06:00\n'
    '    INDEX 01 01:08:17\n'
    '  TRACK 03 AUDIO\n'
    '    TITLE "On the Run"\n'
    '    PERFORMER "Pink Floyd"\n'
    '    ISRC GBDJQ7300003\n'
    '    INDEX 01 03:58:00\n'
)


@pytest.fixture
def cue_data(tmp_path):
    cue = tmp_path / "album.cue"
    cue.write_text(SAMPLE_CUE, encoding="utf-8")
    return parse_cue_file(str(cue))


def test_album_fields(cue_data):
    assert cue_data["performer"] == "Pink Floyd"
    assert cue_data["title"] == "The Dark Side of the Moon"
    assert cue_data["catalog"] == "0724382101826"
    assert cue_data["rem"]["GENRE"] == "Rock"
    assert cue_data["rem"]["DATE"] == "1973"
    assert cue_data["rem"]["DISCID"] == "370B8A08"


def test_tracks_and_isrcs(cue_data):
    assert len(cue_data["tracks"]) == 3
    assert cue_data["tracks"][0]["title"] == "Speak to Me"
    assert cue_data["tracks"][0]["isrc"] == "GBDJQ7300001"


def test_index_frame_math(cue_data):
    # MM:SS:FF at 75 frames/second
    assert cue_data["tracks"][1]["indices"][0] == (1 * 60 + 6) * 75
    assert cue_data["tracks"][1]["indices"][1] == (1 * 60 + 8) * 75 + 17


def test_cue_to_metadata(cue_data):
    meta = cue_to_metadata(cue_data)
    assert meta["album"]["artist"] == "Pink Floyd"
    assert meta["album"]["album"] == "The Dark Side of the Moon"
    assert meta["album"]["barcode"] == "0724382101826"
    assert meta["track_count"] == 3
    assert meta["tracks"][0]["isrc"] == "GBDJQ7300001"


def test_discid_exact_value(cue_data):
    """Pin the exact disc ID for this TOC — any change to the SHA-1/base64
    pipeline must be caught."""
    disc_id = calculate_musicbrainz_discid(cue_data, 200000)
    assert disc_id == "ucnLK5annVS.iy9I0GpWjpCTHHc-"
