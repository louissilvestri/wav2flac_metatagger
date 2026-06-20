"""has_replay_gain on grouped albums drives the Library's ReplayGain indicator:
present only when every track carries a REPLAYGAIN_TRACK_GAIN tag."""

from library_manager import group_library_by_album


def _file(track, has_rg=True):
    return {
        "path": f"/lib/{track:02d}.flac",
        "albumartist": "Adam and the Ants",
        "album": "Prince Charming",
        "artist": "Adam and the Ants",
        "title": f"Track {track}",
        "date": "1981", "genre": "Rock",
        "tracknumber": str(track), "discnumber": "1",
        "completeness": 100, "is_compilation": False, "has_art": True,
        "all_tags": {"REPLAYGAIN_TRACK_GAIN": "-2.50 dB"} if has_rg else {},
    }


def test_present_when_every_track_has_track_gain():
    albums = group_library_by_album([_file(1), _file(2), _file(3)])
    assert len(albums) == 1
    assert albums[0]["has_replay_gain"] is True


def test_absent_when_any_track_missing_track_gain():
    albums = group_library_by_album([_file(1), _file(2, has_rg=False), _file(3)])
    assert albums[0]["has_replay_gain"] is False


def test_absent_when_no_tracks_have_it():
    albums = group_library_by_album([_file(1, has_rg=False), _file(2, has_rg=False)])
    assert albums[0]["has_replay_gain"] is False


def test_apply_replay_gain_library_only_processes_incomplete_folders(monkeypatch, tmp_path):
    """The bulk Settings action reprocesses whole folders missing track-gain and
    skips folders already complete."""
    import library_manager, encoder
    from services import library_service

    files = [
        {"path": str(tmp_path / "A" / "01.flac"), "all_tags": {"REPLAYGAIN_TRACK_GAIN": "-1 dB"}},
        {"path": str(tmp_path / "A" / "02.flac"), "all_tags": {"REPLAYGAIN_TRACK_GAIN": "-1 dB"}},
        {"path": str(tmp_path / "B" / "01.flac"), "all_tags": {}},  # missing → folder B needs it
        {"path": str(tmp_path / "B" / "02.flac"), "all_tags": {"REPLAYGAIN_TRACK_GAIN": "-1 dB"}},
    ]
    monkeypatch.setattr(library_manager, "scan_library", lambda f: files)
    captured = {}
    monkeypatch.setattr(encoder, "add_replay_gain",
                        lambda paths: captured.update(paths=paths) or
                        {"success": True, "processed": len(paths), "errors": []})

    res = library_service.apply_replay_gain_library(str(tmp_path))
    assert res["albums"] == 1 and res["skipped"] == 1 and res["processed"] == 2
    # Whole folder B is reanalyzed together (correct album gain), folder A untouched.
    assert set(captured["paths"]) == {str(tmp_path / "B" / "01.flac"),
                                      str(tmp_path / "B" / "02.flac")}
