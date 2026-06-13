"""Show, per track, exactly which completeness fields are filled vs missing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from library_manager import _scan_single_file
from config import PLEX_DISPLAY_FIELDS, PLEX_OPTIONAL_FIELDS

arg = sys.argv[1]
folder = Path(arg)
if not folder.exists():
    # Fall back to a glob from the library root (handles Unicode path chars)
    root = Path("//192.168.10.245/Music")
    matches = [d for d in root.glob("*/*") if d.is_dir() and arg.lower() in d.name.lower()]
    if matches:
        folder = matches[0]
flacs = sorted(folder.glob("*.flac"))
print(f"{folder.name} — {len(flacs)} tracks\n")

for p in flacs:
    entry = _scan_single_file(p, folder.parent)
    print(f"{p.name}: {entry['completeness']}%  missing={entry['missing_fields']}")

# Field-by-field breakdown for the first track
if flacs:
    entry = _scan_single_file(flacs[0], folder.parent)
    tags = entry["all_tags"]
    print(f"\n=== field breakdown ({flacs[0].name}) ===")
    for label, group in (("DISPLAY", PLEX_DISPLAY_FIELDS),
                         ("OPTIONAL", PLEX_OPTIONAL_FIELDS)):
        print(f"  {label}:")
        for f in group:
            v = tags.get(f, "")
            mark = "OK " if v else "-- "
            print(f"    [{mark}] {f} = {v[:40] if v else '(missing)'}")
    print(f"  COVER_ART: {'OK' if entry['has_art'] else '--'}")
