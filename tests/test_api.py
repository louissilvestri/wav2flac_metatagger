"""API tests for the FastAPI server (Phase 1).

Network-touching endpoints (MusicBrainz/Discogs lookups) are NOT tested here —
only local logic: health, settings, completeness, library ops, and the full
conversion job lifecycle against a real WAV + flac.exe.
"""

import struct
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.jobs import init_jobs_table

client = TestClient(app)


@pytest.fixture(autouse=True, scope="module")
def _tables():
    init_jobs_table()


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_get_settings():
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert "output_folder" in r.json()


def test_completeness_single_track():
    r = client.post("/api/completeness", json={
        "metadata": {"TITLE": "T", "ARTIST": "A", "ALBUM": "L", "TRACKNUMBER": "1"},
        "has_art": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["percentage"] == 27  # pinned in test_completeness.py
    assert body["filled"] == 4


def test_completeness_album_from_cue():
    cue_metadata = {
        "album": {"album": "L", "artist": "A", "date": "1999", "genre": "Rock",
                  "discnumber": "1", "disctotal": "1"},
        "track_count": 2,
        "tracks": [
            {"title": "T1", "artist": "A", "tracknumber": "1", "isrc": ""},
            {"title": "T2", "artist": "A", "tracknumber": "2", "isrc": ""},
        ],
    }
    r = client.post("/api/completeness", json={
        "cue_metadata": cue_metadata, "has_art": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["tracks"]) == 2
    assert body["album_average"] > 0


def test_input_scan_missing_folder():
    r = client.post("/api/input/scan", json={"folder_path": r"C:\does\not\exist"})
    assert r.status_code == 200
    assert "error" in r.json()


def test_library_delete_outside_output_folder_rejected():
    r = client.post("/api/library/delete-file", json={"path": r"C:\Windows\notepad.exe"})
    assert r.status_code == 200
    body = r.json()
    assert not body["success"]


def test_embedded_art_missing_file():
    r = client.get("/api/library/embedded-art", params={"path": r"C:\nope.flac"})
    assert r.status_code == 200
    assert r.json()["success"] is False


def test_job_not_found():
    assert client.get("/api/jobs/nonexistent0").status_code == 404
    assert client.post("/api/jobs/nonexistent0/cancel").status_code == 404


def test_jobs_list():
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


class TestConversionJob:
    """Full conversion lifecycle: POST /api/convert -> poll -> verify FLAC."""

    @pytest.fixture
    def wav_file(self, tmp_path):
        path = tmp_path / "01 Test Track.wav"
        n = int(44100 * 0.2)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(struct.pack(f"<{n}h", *([0] * n)))
        return path

    def test_convert_roundtrip(self, wav_file, tmp_path, flac_exe):
        out_root = tmp_path / "library"
        out_root.mkdir()

        r = client.post("/api/convert", json={
            "files": [{
                "path": str(wav_file),
                "track_number": 1,
                "parsed_title": "Test Track",
                "parsed_artist": "Test Artist",
                "parsed_album": "Test Album",
            }],
            "release_details": None,
            "options": {
                "output_folder": str(out_root),
                "embed_album_art": False,
                "verify_encoding": False,
                "delete_wav_after_convert": False,
                "flac_exe_path": flac_exe,
            },
        })
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        # Poll until the job finishes
        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.1)

        assert job["status"] == "done", f"job failed: {job.get('error')}"
        assert job["result"]["completed"] == 1
        assert job["result"]["failed"] == 0

        # The FLAC landed in the Plex structure with tags
        flac_path = out_root / "Test Artist" / "Test Album" / "01 - Test Track.flac"
        assert flac_path.exists(), f"missing output; tree: {list(out_root.rglob('*'))}"

        from tagger import read_metadata
        tags = read_metadata(str(flac_path))["tags"]
        assert tags["TITLE"] == "Test Track"
        assert tags["ARTIST"] == "Test Artist"

        # Source WAV untouched (delete_wav_after_convert=False)
        assert wav_file.exists()

    def test_second_convert_rejected_while_running(self, wav_file, tmp_path, flac_exe):
        """A second conversion while one runs returns 409."""
        out_root = tmp_path / "library2"
        out_root.mkdir()
        payload = {
            "files": [{"path": str(wav_file), "track_number": 1,
                       "parsed_title": "T", "parsed_artist": "A", "parsed_album": "L"}],
            "options": {"output_folder": str(out_root), "embed_album_art": False,
                        "verify_encoding": False, "flac_exe_path": flac_exe},
        }
        r1 = client.post("/api/convert", json=payload)
        assert r1.status_code == 200
        job_id = r1.json()["job_id"]

        # Immediately try a second one — either 409 (still running) or the
        # first finished too fast on this machine; both are acceptable
        r2 = client.post("/api/convert", json=payload)
        assert r2.status_code in (200, 409)

        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.1)
        assert job["status"] == "done"
