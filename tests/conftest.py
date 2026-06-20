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


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch, tmp_path):
    """Point config at a throwaway dir so tests never read (or write) the
    developer's real settings.json / secrets.json. Without this, results depend
    on the machine — e.g. a custom `merge_precedence` in the user's settings
    silently flips precedence-sensitive assertions in test_merge/test_aggregator.

    load_settings() reads the module-global CONFIG_FILE at call time, so patching
    these names isolates every caller (they all share config.load_settings).
    """
    import json
    import config
    from encoder import find_flac_exe

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "settings.json"
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(config, "SECRETS_FILE", cfg_dir / "secrets.json")

    # Seed only the FLAC encoder path so conversion tests can still encode;
    # everything else falls back to defaults (no machine-specific overrides).
    flac = find_flac_exe()
    if flac:
        cfg_file.write_text(json.dumps({"flac_exe_path": flac}), encoding="utf-8")


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
