"""Test fuzzy matching, multi-album grouping, and cleanup."""
from file_manager import _normalize_for_compare, find_existing_folder, group_files_by_album

# Test fuzzy matching normalization
assert _normalize_for_compare("The Beatles") == "beatles"
assert _normalize_for_compare("Beatles, The") == "beatles"
assert _normalize_for_compare("AC/DC") == "acdc"
assert _normalize_for_compare("Motörhead") == "motorhead"
assert _normalize_for_compare("  Pink Floyd  ") == "pink floyd"
print("Fuzzy normalization: PASSED")

# Test grouping by track number reset
files = [
    {"path": "a1.wav", "parsed_track_number": 1, "parsed_album": "", "parsed_artist": "", "parsed_title": "T1"},
    {"path": "a2.wav", "parsed_track_number": 2, "parsed_album": "", "parsed_artist": "", "parsed_title": "T2"},
    {"path": "a3.wav", "parsed_track_number": 3, "parsed_album": "", "parsed_artist": "", "parsed_title": "T3"},
    {"path": "b1.wav", "parsed_track_number": 1, "parsed_album": "", "parsed_artist": "", "parsed_title": "T4"},
    {"path": "b2.wav", "parsed_track_number": 2, "parsed_album": "", "parsed_artist": "", "parsed_title": "T5"},
]
groups = group_files_by_album(files)
assert len(groups) == 2, f"Expected 2 groups, got {len(groups)}"
assert len(groups[0]["files"]) == 3
assert len(groups[1]["files"]) == 2
print(f"Track reset detection: {len(groups)} groups PASSED")

# Test grouping by album name
files2 = [
    {"path": "1.wav", "parsed_track_number": 1, "parsed_album": "Album A", "parsed_artist": "X", "parsed_title": ""},
    {"path": "2.wav", "parsed_track_number": 2, "parsed_album": "Album A", "parsed_artist": "X", "parsed_title": ""},
    {"path": "3.wav", "parsed_track_number": 1, "parsed_album": "Album B", "parsed_artist": "Y", "parsed_title": ""},
]
groups2 = group_files_by_album(files2)
assert len(groups2) == 2
print(f"Album name grouping: {len(groups2)} groups PASSED")

# Test single album (no split)
files3 = [
    {"path": "1.wav", "parsed_track_number": 1, "parsed_album": "Same", "parsed_artist": "A", "parsed_title": "T1"},
    {"path": "2.wav", "parsed_track_number": 2, "parsed_album": "Same", "parsed_artist": "A", "parsed_title": "T2"},
]
groups3 = group_files_by_album(files3)
assert len(groups3) == 1
print("Single album (no split): PASSED")

# Test full import chain
from app import scan_input_folder, _run_conversion
print("\nAll app imports OK")
print("All tests PASSED")
