"""Partial library rescan: after an edit we re-read only the touched files and
recompute the payload from the cached set, instead of re-reading the whole share.

Verifies the cache stays accurate across an edit, a delete, and that a cold
cache (server restart) falls back to a full scan.
"""

import shutil

from tagger import embed_metadata
from services import library_service
from services.library_service import scan_library_full, rescan_paths, _scan_cache, _norm


def _flac(src, root, artist, album, track, title):
    dest = root / artist / f"{album} (1977)" / f"{track:02d} - {title}.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    embed_metadata(str(dest), {
        "title": title, "artist": artist, "albumartist": artist,
        "album": album, "date": "1977", "genre": "Rock",
        "tracknumber": str(track), "discnumber": "1",
    })
    return dest


def _albums(result):
    return {a["album"]: a for a in result["albums"]}


def test_full_scan_populates_cache(flac_file, tmp_path):
    root = tmp_path / "lib"
    _flac(flac_file, root, "Steely Dan", "Aja", 1, "Black Cow")
    res = scan_library_full(str(root))
    assert res["total_files"] == 1
    assert _norm(str(root)) in _scan_cache


def test_rescan_picks_up_edited_title(flac_file, tmp_path):
    root = tmp_path / "lib"
    a = _flac(flac_file, root, "Steely Dan", "Aja", 1, "Black Cow")
    b = _flac(flac_file, root, "Steely Dan", "Aja", 2, "Aja")
    scan_library_full(str(root))

    embed_metadata(str(a), {"title": "Black Cow (remaster)"})
    res = rescan_paths(str(root), [str(a)])

    assert res["total_files"] == 2  # unchanged count
    titles = {f["title"] for f in _albums(res)["Aja"]["files"]}
    assert "Black Cow (remaster)" in titles
    assert "Aja" in titles  # untouched file preserved from cache


def test_rescan_drops_deleted_file(flac_file, tmp_path):
    root = tmp_path / "lib"
    a = _flac(flac_file, root, "Steely Dan", "Aja", 1, "Black Cow")
    _flac(flac_file, root, "Steely Dan", "Aja", 2, "Aja")
    scan_library_full(str(root))

    a.unlink()
    res = rescan_paths(str(root), [str(a)])

    assert res["total_files"] == 1
    assert _albums(res)["Aja"]["track_count"] == 1


def test_rescan_handles_move_across_albums(flac_file, tmp_path):
    root = tmp_path / "lib"
    a = _flac(flac_file, root, "Steely Dan", "Aja", 1, "Black Cow")
    scan_library_full(str(root))

    # Simulate a reassign that moved the file to a different album folder
    new = root / "Steely Dan" / "Gaucho (1980)" / "01 - Babylon Sisters.flac"
    new.parent.mkdir(parents=True, exist_ok=True)
    a.rename(new)
    embed_metadata(str(new), {"title": "Babylon Sisters", "album": "Gaucho", "date": "1980"})

    res = rescan_paths(str(root), [str(a), str(new)])

    albums = _albums(res)
    assert "Aja" not in albums       # old album now empty -> gone
    assert "Gaucho" in albums
    assert res["total_files"] == 1


def test_cold_cache_falls_back_to_full_scan(flac_file, tmp_path):
    root = tmp_path / "lib"
    _flac(flac_file, root, "Steely Dan", "Aja", 1, "Black Cow")
    _scan_cache.clear()  # simulate a fresh process with no baseline

    res = rescan_paths(str(root), ["whatever"])
    assert res["total_files"] == 1  # rebuilt from a full scan
