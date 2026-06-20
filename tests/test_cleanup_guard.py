"""REGRESSION: source cleanup (delete WAV/CUE/art) must only run after a real,
fully-successful conversion — never for an empty/no-op run.

The bug: `completed == total` is also true when both are 0, so a conversion
invoked with no files satisfied the guard and the glob-based cleanup wiped the
folder's .cue/art even though nothing was converted.
"""

from services.conversion import run_conversion


def _noop(*_a, **_k):
    pass


def test_empty_conversion_does_not_delete_cue(tmp_path):
    cue = tmp_path / "album.cue"
    cue.write_text("REM nothing\n", encoding="utf-8")
    art = tmp_path / "folder.jpg"
    art.write_bytes(b"\xff\xd8\xff")

    result = run_conversion(
        files=[],
        release_details=None,
        options={
            "output_folder": str(tmp_path),
            "input_folder": str(tmp_path),
            "delete_wav_after_convert": True,
        },
        on_progress=_noop,
        on_file_done=_noop,
        is_cancelled=lambda: False,
    )

    assert result["completed"] == 0 and result["total"] == 0
    assert cue.exists(), "empty conversion wrongly deleted the CUE"
    assert art.exists(), "empty conversion wrongly deleted the art"
