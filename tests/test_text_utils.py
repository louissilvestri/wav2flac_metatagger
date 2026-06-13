"""Typographic punctuation folding for search (text_utils)."""

from text_utils import normalize_punctuation, lucene_phrase, fold_for_compare


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
