"""Strip prepended ID3 tags from FLAC files in the library.

Files with an ID3 tag before the 'fLaC' marker are non-spec: Windows Explorer
and Plex show no metadata or art for them. This re-saves each affected file as
clean FLAC (Vorbis comments and embedded art preserved).

Usage:
  python scripts/repair_id3.py            # dry run on the configured output folder
  python scripts/repair_id3.py --apply    # actually repair
  python scripts/repair_id3.py "<folder>" --apply
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mutagen.flac import FLAC
from config import load_settings


def has_prepended_id3(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(3) == b"ID3"
    except OSError:
        return False


def main():
    args = [a for a in sys.argv[1:]]
    apply = "--apply" in args
    args = [a for a in args if a != "--apply"]
    root = Path(args[0]) if args else Path(load_settings().get("output_folder", ""))

    if not root or not root.exists():
        print(f"Output folder not found: {root}")
        return 1

    print(f"Scanning {root} ...")
    flacs = list(root.rglob("*.flac"))
    affected = [p for p in flacs if has_prepended_id3(p)]

    print(f"  {len(flacs)} FLAC files, {len(affected)} with a prepended ID3 tag")
    if not affected:
        print("Nothing to repair.")
        return 0

    if not apply:
        print("\nDRY RUN — files that would be repaired:")
        for p in affected[:40]:
            print(f"  {p}")
        if len(affected) > 40:
            print(f"  ... and {len(affected) - 40} more")
        print("\nRe-run with --apply to repair them.")
        return 0

    fixed = failed = 0
    for p in affected:
        try:
            FLAC(str(p)).save(deleteid3=True)  # re-emit clean FLAC
            if not has_prepended_id3(p):
                fixed += 1
            else:
                failed += 1
                print(f"  STILL DIRTY: {p}")
        except Exception as e:
            failed += 1
            print(f"  FAILED: {p} — {e}")

    print(f"\nRepaired {fixed}/{len(affected)} files ({failed} failed).")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
