"""Typographic punctuation folding for search (text_utils)."""

from text_utils import (normalize_punctuation, lucene_phrase, fold_for_compare,
                        fold_loose, strip_various_artist)


class TestFoldLoose:
    """Aggressive fold for artist/folder matching — shares the base with
    fold_for_compare, adds punctuation removal + 'the' stripping."""

    def test_the_prefix_and_suffix(self):
        assert fold_loose("The Beatles") == "beatles"
        assert fold_loose("Beatles, The") == "beatles"

    def test_punctuation_joined(self):
        assert fold_loose("AC/DC") == "acdc"

    def test_accents_stripped(self):
        assert fold_loose("Motörhead") == "motorhead"

    def test_whitespace(self):
        assert fold_loose("  Pink Floyd  ") == "pink floyd"


class TestFoldsShareBase:
    """Both folds must agree on the shared base (typography + accents + case)."""

    def test_compare_is_accent_insensitive(self):
        assert fold_for_compare("Café del Mar") == fold_for_compare("Cafe del Mar")

    def test_both_handle_typography_the_same_way(self):
        # The shared base normalizes curly quotes / dashes identically
        assert fold_for_compare("Go‐Go’s").startswith("go-go")
        assert fold_loose("Go‐Go’s") == "gogos"


class TestStripVariousArtist:
    def test_drops_various_forms(self):
        assert strip_various_artist("Various Artists") == ""
        assert strip_various_artist("various") == ""
        assert strip_various_artist("  VARIOUS ARTISTS  ") == ""

    def test_keeps_real_artist(self):
        assert strip_various_artist("Pink Floyd") == "Pink Floyd"

    def test_handles_empty_and_none(self):
        assert strip_various_artist("") == ""
        assert strip_various_artist(None) == ""


class TestNormalizePunctuation:
    def test_curly_apostrophe(self):
        assert normalize_punctuation("Go‐Go’s") == "Go-Go's"

    def test_dash_family(self):
        # en, em, figure, non-breaking hyphen, minus -> ASCII hyphen
        assert normalize_punctuation("a–b—c‐d‑e−f") == "a-b-c-d-e-f"

    def test_smart_double_quotes(self):
        assert normalize_punctuation("“Weird”") == '"Weird"'

    def test_ellipsis(self):
        assert normalize_punctuation("wait…") == "wait..."

    def test_accents_preserved(self):
        # Accented LETTERS are real and providers index them — never fold
        assert normalize_punctuation("Motörhead") == "Motörhead"
        assert normalize_punctuation("Sigur Rós") == "Sigur Rós"

    def test_empty(self):
        assert normalize_punctuation("") == ""


class TestLucenePhrase:
    def test_escapes_double_quote(self):
        # An embedded quote must be escaped so it can't break the phrase query
        assert lucene_phrase('The "Weird" Band') == 'The \\"Weird\\" Band'

    def test_escapes_backslash(self):
        assert lucene_phrase("a\\b") == "a\\\\b"

    def test_folds_then_escapes(self):
        assert lucene_phrase("Go‐Go’s") == "Go-Go's"


class TestFoldForCompare:
    def test_case_and_punctuation(self):
        assert fold_for_compare("Go‐Go’S") == "go-go's"

    def test_whitespace_collapsed(self):
        assert fold_for_compare("  a   b  ") == "a b"

    def test_matches_across_typography(self):
        # A folder stored with fancy punctuation matches a plain-typed query
        assert fold_for_compare("Go‐Go’s") == fold_for_compare("Go-Go's")

    def test_separator_comma_slash_semicolon_unified(self):
        # Providers disagree on track-list separators — all must compare equal
        a = fold_for_compare("Whine & Grine / Stand Down Margaret")
        b = fold_for_compare("Whine & Grine , Stand Down Margaret")
        c = fold_for_compare("Whine & Grine ; Stand Down Margaret")
        assert a == b == c == "whine & grine stand down margaret"

    def test_separator_without_surrounding_spaces(self):
        assert fold_for_compare("A/B") == fold_for_compare("A, B") == "a b"
