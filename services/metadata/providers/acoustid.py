"""AcoustID provider — identify tracks from the AUDIO itself via Chromaprint
fingerprints. Tags can be blank or wrong; the fingerprint doesn't care.

Requires tools/fpcalc.exe (or fpcalc on PATH).
"""

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import requests

from config import get_secret
from services.metadata import cache, ratelimit

_UA = {"User-Agent": "MusicManager/2.0 (louissilvestri@hotmail.com)"}


def find_fpcalc() -> str | None:
    bundled = Path(__file__).resolve().parents[3] / "tools" / "fpcalc.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("fpcalc")


def is_available() -> bool:
    return bool(find_fpcalc() and get_secret("ACOUSTID_API_KEY"))


def fingerprint_file(path: str) -> dict | None:
    """Chromaprint fingerprint: {duration, fingerprint} or None.

    fpcalc's FFmpeg build cannot open UNC paths (\\\\server\\share\\...), so
    network files are staged to a local temp copy first.
    """
    fpcalc = find_fpcalc()
    if not fpcalc:
        return None

    src = Path(path)
    temp_copy = None
    try:
        local_path = src
        if str(src).startswith("\\\\") or str(path).startswith("//"):
            import shutil as _shutil
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "music_manager"
            temp_dir.mkdir(exist_ok=True)
            temp_copy = temp_dir / f"fp_{abs(hash(path))}{src.suffix}"
            _shutil.copyfile(str(src), str(temp_copy))
            local_path = temp_copy

        result = subprocess.run(
            [fpcalc, "-json", str(local_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return {"duration": int(data["duration"]), "fingerprint": data["fingerprint"]}
    except Exception:
        return None
    finally:
        if temp_copy:
            temp_copy.unlink(missing_ok=True)


def lookup_recording(path: str) -> list[dict]:
    """Identify one audio file. Returns candidate recordings sorted by score:
    [{score, recording_id, title, artist, release_groups: [{id, title, type}]}]
    """
    api_key = get_secret("ACOUSTID_API_KEY")
    if not api_key:
        return []

    fp = fingerprint_file(path)
    if not fp:
        return []

    # Cache by fingerprint prefix (fingerprints are huge but unique enough)
    key = f"lookup|{fp['duration']}|{fp['fingerprint'][:64]}"

    def fetch():
        ratelimit.wait("acoustid")
        r = requests.post("https://api.acoustid.org/v2/lookup", data={
            "client": api_key,
            "duration": fp["duration"],
            "fingerprint": fp["fingerprint"],
            "meta": "recordings releasegroups",
        }, headers=_UA, timeout=30)
        data = r.json()
        if data.get("status") != "ok":
            return []

        candidates = []
        for result in data.get("results", []):
            score = result.get("score", 0)
            for rec in result.get("recordings", []) or []:
                rgs = []
                for rg in rec.get("releasegroups", []) or []:
                    rgs.append({
                        "id": rg.get("id", ""),
                        "title": rg.get("title", ""),
                        "type": rg.get("type", ""),
                        "secondary_types": rg.get("secondarytypes", []) or [],
                    })
                artists = rec.get("artists", []) or []
                candidates.append({
                    "score": score,
                    "recording_id": rec.get("id", ""),
                    "title": rec.get("title", ""),
                    "artist": "; ".join(a.get("name", "") for a in artists),
                    "release_groups": rgs,
                })
        candidates.sort(key=lambda c: -c["score"])
        return candidates

    return cache.cached("acoustid", key, cache.TTL_RELEASE, fetch) or []


def identify_album(paths: list[str], max_files: int = 3) -> dict | None:
    """Identify an album by fingerprinting up to max_files tracks and voting
    on the release group their recordings share.

    Returns {release_group_id, album, artist, votes, files_checked} or None.
    Prefers studio albums over compilations the recordings also appear on.
    """
    votes = Counter()
    rg_info: dict[str, dict] = {}
    checked = 0

    for path in paths[:max_files]:
        candidates = lookup_recording(path)
        checked += 1
        if not candidates:
            continue
        best = candidates[0]
        if best["score"] < 0.5:
            continue
        for rg in best["release_groups"]:
            if not rg["id"]:
                continue
            # Weight studio albums above compilations/live
            weight = 1.0
            if rg["type"] == "Album" and not rg["secondary_types"]:
                weight = 2.0
            elif "Compilation" in rg["secondary_types"] or rg["type"] in ("Single", "EP"):
                weight = 0.5
            votes[rg["id"]] += weight
            rg_info.setdefault(rg["id"], {
                "title": rg["title"],
                "artist": best["artist"],
            })

    if not votes:
        return None

    winner_id, vote_count = votes.most_common(1)[0]
    info = rg_info[winner_id]
    return {
        "release_group_id": winner_id,
        "album": info["title"],
        "artist": info["artist"],
        "votes": vote_count,
        "files_checked": checked,
    }
