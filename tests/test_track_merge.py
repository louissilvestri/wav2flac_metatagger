"""Cross-provider per-track gap-fill: fill empty track fields from a second
provider, matched by disc+position, guarded by title compatibility."""

from services.metadata.merge import merge_tracks, merge_disc_tracks


def _t(pos, disc=1, title="", length=None, isrc="", artist=""):
    return {"position": pos, "disc_number": disc, "title": title,
            "length_ms": length, "isrc": isrc, "artist": artist}


def test_fills_empty_length_when_titles_match():
    primary = [_t(1, title="Stand and Deliver", length=None)]
    secondary = [_t(1, title="Stand and Deliver", length=215000)]
    merge_tracks(primary, secondary)
    assert primary[0]["length_ms"] == 215000


def test_does_not_overwrite_present_length():
    primary = [_t(1, title="Song", length=200000)]
    secondary = [_t(1, title="Song", length=999000)]
    merge_tracks(primary, secondary)
    assert primary[0]["length_ms"] == 200000


def test_title_mismatch_blocks_fill():
    # Same position but a different song (bonus-track shift) → do NOT borrow.
    primary = [_t(5, title="Real Song", length=None)]
    secondary = [_t(5, title="Totally Different Bonus Track", length=123000)]
    merge_tracks(primary, secondary)
    assert primary[0]["length_ms"] is None


def test_blank_primary_title_is_filled():
    primary = [_t(1, title="", length=None)]
    secondary = [_t(1, title="Recovered Title", length=180000)]
    merge_tracks(primary, secondary)
    assert primary[0]["title"] == "Recovered Title"
    assert primary[0]["length_ms"] == 180000


def test_no_match_by_position_leaves_unchanged():
    primary = [_t(1, title="A", length=None)]
    secondary = [_t(2, title="A", length=180000)]
    merge_tracks(primary, secondary)
    assert primary[0]["length_ms"] is None


def test_empty_secondary_is_safe():
    primary = [_t(1, title="A", length=None)]
    assert merge_tracks(primary, []) is primary


def test_disc_structured_merge_in_place():
    primary = [{"position": 1, "tracks": [
        {"position": 1, "title": "One", "length_ms": None, "isrc": ""},
        {"position": 2, "title": "Two", "length_ms": 100, "isrc": ""},
    ]}]
    secondary = [{"position": 1, "tracks": [
        {"position": 1, "title": "One", "length_ms": 211000},
        {"position": 2, "title": "Two", "length_ms": 999},
    ]}]
    merge_disc_tracks(primary, secondary)
    assert primary[0]["tracks"][0]["length_ms"] == 211000   # filled
    assert primary[0]["tracks"][1]["length_ms"] == 100       # kept
