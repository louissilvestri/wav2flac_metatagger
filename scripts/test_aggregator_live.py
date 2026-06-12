"""Live validation of the Phase 2 aggregator (exit criteria from REFACTOR_PLAN).

Run manually: python scripts/test_aggregator_live.py [flac_path_for_fingerprint]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.metadata.aggregator import identify


def show(label, result):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"Identity: {result['identity']}")
    print(f"Providers: {result['providers']}")
    print(f"IDs: {result['ids']}")
    print("Fields:")
    for name, fv in result["fields"].items():
        val = fv["value"]
        if isinstance(val, list):
            val = ", ".join(val)
        alts = len(fv["candidates"]) - 1
        print(f"  {name:<15} = {val!s:<40} [{fv['source']}]"
              + (f" (+{alts} alt)" if alts else ""))
    print(f"Tracks: {len(result['tracks'])} from {result['track_source'] or 'n/a'}")
    print(f"Art candidates: {[(a['source']) for a in result['art_candidates']]}")


# Scenario 1: text identification of a tagged library album
show("TEXT SEARCH: Creedence Clearwater Revival - Cosmo's Factory",
     identify(artist="Creedence Clearwater Revival", album="Cosmo's Factory"))

# Scenario 2: fingerprint identification with NO metadata at all
if len(sys.argv) > 1:
    flac = sys.argv[1]
    print(f"\nFingerprinting (ignoring all tags): {flac}")
    show("FINGERPRINT ONLY (blank metadata)",
         identify(file_paths=[flac]))
