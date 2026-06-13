"""Probe search paths with Unicode / special-character inputs.
Writes UTF-8 output to avoid the cp1252 console."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
out = io.StringIO()

import metadata_lookup
import library_manager
import discogs_lookup

TESTS = [
    ("Go-Go's", "Beauty and the Beat"),
    ("Go‐Go’s", "Beauty and the Beat"),   # figure-dash + curly quote
    ("Motörhead", "Ace of Spades"),            # umlaut
    ("AC/DC", "Back in Black"),                       # slash (Lucene special)
    ("Sigur Rós", "( )"),                       # parens (Lucene special)
    ("Beyoncé", "Lemonade"),                    # accent
    ('The "Weird" Band', "Test"),                    # embedded double-quote
]

def run(label, fn):
    for artist, album in TESTS:
        try:
            r = fn(artist, album)
            if isinstance(r, list):
                err = r[0].get("error") if r and isinstance(r[0], dict) else None
                status = f"{len(r)} results" + (f" ERROR={err}" if err else "")
            else:
                status = repr(r)
            out.write(f"[{label}] {artist!r}: {status}\n")
        except Exception as e:
            out.write(f"[{label}] {artist!r}: EXCEPTION {type(e).__name__}: {e}\n")

run("MB search_release", lambda a, b: metadata_lookup.search_release(artist=a, album=b))
run("MB find_original_album", lambda a, b: library_manager.find_original_album(a, b))
run("MB find_by_name", lambda a, b: library_manager.find_original_album_by_name(a, b))
run("Discogs search", lambda a, b: discogs_lookup.search_release(artist=a, album=b))

Path("scripts/_unicode_results.txt").write_text(out.getvalue(), encoding="utf-8")
print("done -> scripts/_unicode_results.txt")
