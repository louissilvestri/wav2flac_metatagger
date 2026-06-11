"""Test metadata completeness calculation."""
from app import calculate_metadata_completeness, _PLEX_ALL_FIELDS

# Full metadata
full_meta = {
    "TITLE": "Test", "ARTIST": "Artist", "ALBUMARTIST": "Artist",
    "ALBUM": "Album", "TRACKNUMBER": "1", "DISCNUMBER": "1",
    "DATE": "2024", "GENRE": "Rock",
    "MUSICBRAINZ_ALBUMID": "abc", "MUSICBRAINZ_ARTISTID": "def",
    "MUSICBRAINZ_TRACKID": "ghi", "MUSICBRAINZ_ALBUMARTISTID": "jkl",
    "TRACKTOTAL": "10", "DISCTOTAL": "1",
}
result = calculate_metadata_completeness(full_meta, has_art=True)
print(f"Full metadata: {result['percentage']}% ({result['filled']}/{result['total']})")
assert result["percentage"] == 100

# Partial metadata
partial = {"TITLE": "Test", "ARTIST": "Artist", "ALBUM": "Album", "TRACKNUMBER": "1"}
result2 = calculate_metadata_completeness(partial, has_art=False)
print(f"Partial metadata: {result2['percentage']}% ({result2['filled']}/{result2['total']})")
assert result2["percentage"] < 100

# Field breakdown
for f, info in result2["fields"].items():
    status_icon = "Y" if info["status"] == "filled" else "."
    print(f"  [{status_icon}] {f:30s} ({info['category']})")

print(f"\nPlex fields tracked: {len(_PLEX_ALL_FIELDS) + 1} (incl. cover art)")
print("All tests PASSED")
