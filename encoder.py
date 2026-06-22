"""FLAC encoding via the reference flac.exe encoder."""

import os
import subprocess
import time
import wave
from collections import defaultdict
from pathlib import Path

from config import load_settings


def get_wav_info(wav_path: str) -> dict:
    """Read WAV file properties."""
    path = Path(wav_path)
    if not path.exists():
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    with wave.open(str(path), "rb") as wf:
        return {
            "sample_rate": wf.getframerate(),
            "bit_depth": wf.getsampwidth() * 8,
            "channels": wf.getnchannels(),
            "frames": wf.getnframes(),
            "duration_seconds": wf.getnframes() / wf.getframerate(),
            "file_size": path.stat().st_size,
        }


def encode_to_flac(
    wav_path: str,
    output_path: str,
    compression_level: int = None,
    verify: bool = None,
) -> dict:
    """Encode a WAV file to FLAC using flac.exe.

    Returns dict with: success, output_path, duration_ms, file_size, verify_passed, error
    """
    settings = load_settings()
    flac_exe = settings.get("flac_exe_path", "flac")
    if compression_level is None:
        compression_level = settings.get("compression_level", 8)
    if verify is None:
        verify = settings.get("verify_encoding", True)

    compression_level = max(0, min(8, compression_level))

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [flac_exe]
    cmd.append(f"-{compression_level}")
    if verify:
        cmd.append("--verify")
    cmd.extend(["--force", "--silent"])
    cmd.extend(["-o", str(out_path)])
    cmd.append(str(wav_path))

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        duration_ms = int((time.time() - start_time) * 1000)

        if result.returncode != 0:
            return {
                "success": False,
                "output_path": str(out_path),
                "duration_ms": duration_ms,
                "file_size": 0,
                "verify_passed": False,
                "error": result.stderr.strip() or f"flac.exe exited with code {result.returncode}",
            }

        file_size = out_path.stat().st_size if out_path.exists() else 0
        return {
            "success": True,
            "output_path": str(out_path),
            "duration_ms": duration_ms,
            "file_size": file_size,
            "verify_passed": verify,
            "error": None,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "output_path": str(out_path),
            "duration_ms": 0,
            "file_size": 0,
            "verify_passed": False,
            "error": f"flac.exe not found at: {flac_exe}. Please set the correct path in settings.",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output_path": str(out_path),
            "duration_ms": 600000,
            "file_size": 0,
            "verify_passed": False,
            "error": "Encoding timed out after 10 minutes.",
        }
    except Exception as e:
        return {
            "success": False,
            "output_path": str(out_path),
            "duration_ms": 0,
            "file_size": 0,
            "verify_passed": False,
            "error": str(e),
        }


def find_metaflac_exe() -> str | None:
    """Locate metaflac (ships alongside flac in the FLAC tools). Derived from the
    configured flac.exe path first, then common locations, then PATH."""
    exe = "metaflac.exe" if os.name == "nt" else "metaflac"
    flac_exe = (load_settings().get("flac_exe_path", "") or "").strip()
    if flac_exe:
        cand = Path(flac_exe).with_name(exe)
        if cand.exists():
            return str(cand)

    common_paths = [
        r"C:\Program Files\FLAC\metaflac.exe",
        r"C:\Program Files (x86)\FLAC\metaflac.exe",
        r"C:\Program Files\Exact Audio Copy\Flac\metaflac.exe",
        r"C:\Program Files (x86)\Exact Audio Copy\Flac\metaflac.exe",
    ]
    for p in common_paths:
        if Path(p).exists():
            return p

    try:
        result = subprocess.run(["where", exe] if os.name == "nt" else ["which", exe],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0].strip()
    except Exception:
        pass
    return None


def add_replay_gain(flac_paths: list[str], metaflac_exe: str | None = None) -> dict:
    """Compute ReplayGain (loudness) tags for the given FLAC files via metaflac.

    Files are grouped by parent folder and each group is analyzed in one
    invocation, so every track gets REPLAYGAIN_TRACK_GAIN/PEAK and the folder
    shares a correct REPLAYGAIN_ALBUM_GAIN/PEAK. metaflac requires the files in a
    group to share sample rate; a mismatched group fails without affecting others.

    Returns {success, processed, errors}.
    """
    if not flac_paths:
        return {"success": True, "processed": 0, "errors": []}

    if metaflac_exe is None:
        metaflac_exe = find_metaflac_exe()
    if not metaflac_exe:
        return {"success": False, "processed": 0,
                "errors": ["metaflac not found — install the FLAC tools or set the flac.exe path in Settings"]}

    groups: dict[Path, list[str]] = defaultdict(list)
    for p in flac_paths:
        pth = Path(p)
        if pth.exists() and pth.suffix.lower() == ".flac":
            groups[pth.parent].append(str(pth))

    processed = 0
    errors = []
    for parent, files in groups.items():
        try:
            result = subprocess.run([metaflac_exe, "--add-replay-gain", *files],
                                    capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                errors.append(f"{parent.name or parent}: "
                              f"{result.stderr.strip() or 'metaflac failed'}")
            else:
                processed += len(files)
        except subprocess.TimeoutExpired:
            errors.append(f"{parent.name or parent}: ReplayGain timed out")
        except Exception as e:
            errors.append(f"{parent.name or parent}: {e}")

    return {"success": not errors, "processed": processed, "errors": errors}


def find_flac_exe() -> str | None:
    """Try to locate flac.exe on the system."""
    common_paths = [
        r"C:\Program Files\FLAC\flac.exe",
        r"C:\Program Files (x86)\FLAC\flac.exe",
        r"C:\Program Files\Exact Audio Copy\Flac\flac.exe",
        r"C:\Program Files (x86)\Exact Audio Copy\Flac\flac.exe",
    ]
    for p in common_paths:
        if Path(p).exists():
            return p

    import shutil
    found = shutil.which("flac")
    if found:
        return found
    return None
