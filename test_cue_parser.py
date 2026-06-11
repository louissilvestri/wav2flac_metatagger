"""Quick test for the CUE parser and disc ID calculation."""

import tempfile
import os
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

tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.cue', delete=False, encoding='utf-8')
tmp.write(SAMPLE_CUE)
tmp.close()

try:
    data = parse_cue_file(tmp.name)
    assert data["performer"] == "Pink Floyd", f"Expected 'Pink Floyd', got '{data['performer']}'"
    assert data["title"] == "The Dark Side of the Moon"
    assert data["catalog"] == "0724382101826"
    assert len(data["tracks"]) == 3
    assert data["tracks"][0]["title"] == "Speak to Me"
    assert data["tracks"][0]["isrc"] == "GBDJQ7300001"
    assert data["tracks"][1]["indices"][0] == (1 * 60 + 6) * 75 + 0  # INDEX 00
    assert data["tracks"][1]["indices"][1] == (1 * 60 + 8) * 75 + 17  # INDEX 01
    assert data["rem"]["GENRE"] == "Rock"
    assert data["rem"]["DATE"] == "1973"
    assert data["rem"]["DISCID"] == "370B8A08"

    meta = cue_to_metadata(data)
    assert meta["album"]["artist"] == "Pink Floyd"
    assert meta["album"]["album"] == "The Dark Side of the Moon"
    assert meta["album"]["barcode"] == "0724382101826"
    assert meta["track_count"] == 3
    assert meta["tracks"][0]["isrc"] == "GBDJQ7300001"

    disc_id = calculate_musicbrainz_discid(data, 200000)
    assert len(disc_id) == 28, f"Disc ID should be 28 chars, got {len(disc_id)}: {disc_id}"

    print("All CUE parser tests PASSED")
    print(f"  Performer: {data['performer']}")
    print(f"  Title: {data['title']}")
    print(f"  Catalog: {data['catalog']}")
    print(f"  Tracks: {len(data['tracks'])}")
    print(f"  Track 1 ISRC: {data['tracks'][0]['isrc']}")
    print(f"  Disc ID (test): {disc_id}")
finally:
    os.unlink(tmp.name)
