"""FLAC encoding via the reference flac.exe encoder."""

import subprocess
import time
import wave
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

    try:
        result = subprocess.run(
            ["where", "flac"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0].strip()
    except Exception:
        pass
    return None
