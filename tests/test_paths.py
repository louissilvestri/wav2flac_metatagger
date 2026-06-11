"""Characterization tests for file naming and output path building."""

import pytest

from file_manager import sanitize_filename, _normalize_for_compare, build_output_path


class TestSanitizeFilename:
    @pytest.mark.parametrize("raw,expected", [
        ("AC/DC: Back in Black?", "ACDC Back in Black"),
        ("  ...Trailing dots...  ", "Trailing dots"),
        ('He said "hi" <once>', "He said hi once"),
        ("normal name", "normal name"),
        ("a  b   c", "a b c"),
    ])
    def test_invalid_chars_removed(self, raw, expected):
        assert sanitize_filename(raw) == expected

    def test_length_capped_at_200(self):
        assert len(sanitize_filename("x" * 500)) == 200


class TestNormalizeForCompare:
    @pytest.mark.parametrize("raw,expected", [
        ("The Beatles", "beatles"),
        ("Beatles, The", "beatles"),
        ("AC/DC", "acdc"),
        ("Motörhead", "motorhead"),
        ("  Pink Floyd  ", "pink floyd"),
        ("R.E.M.", "rem"),
    ])
    def test_normalization(self, raw, expected):
        assert _normalize_for_compare(raw) == expected


class TestBuildOutputPath:
    def test_basic_structure(self, tmp_path):
        p = build_output_path(
            output_root=str(tmp_path), artist="Pink Floyd",
            album="The Wall", year="1979", track_number=1, title="In the Flesh?",
        )
        assert p == tmp_path / "Pink Floyd" / "The Wall (1979)" / "01 - In the Flesh.flac"

    def test_multi_disc_subfolder(self, tmp_path):
        p = build_output_path(
            output_root=str(tmp_path), artist="A", album="L", year="2000",
            disc_number=2, total_discs=2, track_number=3, title="T",
        )
        assert p == tmp_path / "A" / "L (2000)" / "Disc 2" / "03 - T.flac"

    def test_no_year(self, tmp_path):
        p = build_output_path(output_root=str(tmp_path), artist="A", album="L",
                              track_number=1, title="T")
        assert p.parent.name == "L"

    def test_year_truncated_to_4_chars(self, tmp_path):
        p = build_output_path(output_root=str(tmp_path), artist="A", album="L",
                              year="1979-11-30", track_number=1, title="T")
        assert p.parent.name == "L (1979)"

    def test_reuses_fuzzy_matched_artist_folder(self, tmp_path):
        """REGRESSION: 'Beatles, The' must reuse an existing 'The Beatles' folder,
        not create a duplicate."""
        existing = tmp_path / "The Beatles" / "Abbey Road (1969)"
        existing.mkdir(parents=True)
        p = build_output_path(output_root=str(tmp_path), artist="Beatles, The",
                              album="Abbey Road", year="1969",
                              track_number=1, title="Come Together")
        assert p.parts[-3] == "The Beatles"
        assert p.parts[-2] == "Abbey Road (1969)"

    def test_reuses_album_folder_with_different_year(self, tmp_path):
        """An existing album folder without a year suffix is reused."""
        (tmp_path / "A" / "Album").mkdir(parents=True)
        p = build_output_path(output_root=str(tmp_path), artist="A",
                              album="Album", year="1999", track_number=1, title="T")
        assert p.parent.name == "Album"
