"""Shared fixtures for characterization tests.

These tests pin the CURRENT behavior of Music Manager v1 so the v2 refactor
(see REFACTOR_PLAN.md) can prove it didn't regress anything.
"""

import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

# Make the project root importable when pytest runs from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_silent_wav(path: Path, seconds: float = 0.2):
    """Write a tiny 44.1kHz 16-bit mono silent WAV."""
    n_frames = int(44100 * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))


@pytest.fixture(scope="session")
def flac_exe():
    from encoder import find_flac_exe
    from config import load_settings

    path = load_settings().get("flac_exe_path") or find_flac_exe()
    if not path or not Path(path).exists():
        pytest.skip("flac.exe not available")
    return path


@pytest.fixture
def flac_file(tmp_path, flac_exe):
    """A real, freshly encoded FLAC file with no tags."""
    wav = tmp_path / "in.wav"
    out = tmp_path / "out.flac"
    _make_silent_wav(wav)
    subprocess.run(
        [flac_exe, "--totally-silent", "-f", "-o", str(out), str(wav)],
        check=True,
    )
    return str(out)
