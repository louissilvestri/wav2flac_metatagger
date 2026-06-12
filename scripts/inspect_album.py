"""Inspect actual embedded tags + pictures of an album's FLAC files.

Usage: python scripts/inspect_album.py "<folder path>"
"""
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mutagen.flac import FLAC
from PIL import Image

folder = Path(sys.argv[1] if len(sys.argv) > 1 else
              "//192.168.10.245/Music/Orchestral Manoeuvres in the Dark/"
              "Orchestral Manoeuvres in the Dark")

print(f"FOLDER: {folder}")
print("sidecar files:",
      [p.name for p in folder.iterdir() if not p.suffix.lower() == ".flac"])

flacs = sorted(folder.glob("*.flac"))
print(f"FLAC files: {len(flacs)}\n")

for p in flacs[:3]:
    a = FLAC(str(p))
    info = a.info
    line = (f"{p.name:40s} tags={len(a.tags or []):2d} pics={len(a.pictures)} "
            f"{info.bits_per_sample}bit/{info.sample_rate}")
    if a.pictures:
        pic = a.pictures[0]
        try:
            img = Image.open(BytesIO(pic.data))
            fmt = f"{img.format} {img.width}x{img.height}"
        except Exception as e:
            fmt = f"UNREADABLE ({e})"
        line += (f" | pic: type={pic.type} mime={pic.mime!r} "
                 f"declared={pic.width}x{pic.height} actual={fmt} "
                 f"depth={pic.depth} {len(pic.data)}B")
    print(line)

# Tag key comparison on the first file
if flacs:
    a = FLAC(str(flacs[0]))
    print(f"\ntag keys ({flacs[0].name}):")
    print(" ", sorted(a.tags.keys()) if a.tags else "NONE")
