"""Tests for the metadata merge engine — all offline."""

from services.metadata.merge import merge_fields, DEFAULT_PRECEDENCE


def fv(value, source):
    return {"value": value, "source": source}


class TestMergePrecedence:
    def test_winner_by_precedence(self):
        merged = merge_fields([
            {"genre": fv("Rock", "musicbrainz")},
            {"genre": fv("Progressive Rock", "lastfm")},
        ])
        # lastfm outranks musicbrainz for genre
        assert merged["genre"]["value"] == "Progressive Rock"
        assert merged["genre"]["source"] == "lastfm"

    def test_label_prefers_discogs(self):
        merged = merge_fields([
            {"label": fv("Fantasy", "musicbrainz")},
            {"label": fv("Fantasy Records", "discogs")},
        ])
        assert merged["label"]["source"] == "discogs"

    def test_empty_values_never_win(self):
        merged = merge_fields([
            {"genre": fv("", "lastfm")},
            {"genre": fv("Rock", "musicbrainz")},
        ])
        # Empty lastfm value is dropped before ranking
        assert merged["genre"]["value"] == "Rock"

    def test_missing_provider_falls_through(self):
        merged = merge_fields([
            {"genre": fv("Soundtrack", "itunes")},
        ])
        assert merged["genre"]["value"] == "Soundtrack"
        assert merged["genre"]["source"] == "itunes"

    def test_unknown_provider_goes_last(self):
        merged = merge_fields([
            {"genre": fv("Wrong", "randomprovider")},
            {"genre": fv("Rock", "musicbrainz")},
        ])
        assert merged["genre"]["source"] == "musicbrainz"

    def test_candidates_preserved_in_rank_order(self):
        merged = merge_fields([
            {"genre": fv("Rock", "musicbrainz")},
            {"genre": fv("Prog", "lastfm")},
            {"genre": fv("Classic Rock", "discogs")},
        ])
        sources = [c["source"] for c in merged["genre"]["candidates"]]
        assert sources == ["lastfm", "discogs", "musicbrainz"]


class TestDateSpecificity:
    """REGRESSION: '1999-06-29' must never be replaced by a bare '1999'."""

    def test_specific_date_beats_bare_year_same_year(self):
        merged = merge_fields([
            {"original_date": fv("1970", "musicbrainz")},
            {"original_date": fv("1970-07-08", "itunes")},
        ])
        # MB wins precedence but iTunes has the more specific same-year date
        assert merged["original_date"]["value"] == "1970-07-08"
        assert merged["original_date"]["source"] == "itunes"

    def test_different_year_does_not_override(self):
        merged = merge_fields([
            {"original_date": fv("1970", "musicbrainz")},
            {"original_date": fv("2008-09-02", "deezer")},  # reissue date
        ])
        # Deezer's full date is for a DIFFERENT year — precedence holds
        assert merged["original_date"]["value"] == "1970"
        assert merged["original_date"]["source"] == "musicbrainz"

    def test_specific_winner_kept(self):
        merged = merge_fields([
            {"original_date": fv("1970-07-08", "musicbrainz")},
            {"original_date": fv("1970", "itunes")},
        ])
        assert merged["original_date"]["value"] == "1970-07-08"
        assert merged["original_date"]["source"] == "musicbrainz"


class TestMergeShape:
    def test_all_default_fields_have_precedence(self):
        for field in ("title", "artist", "original_date", "genre", "styles",
                      "label", "catalog_number", "barcode", "country"):
            assert field in DEFAULT_PRECEDENCE

    def test_styles_list_value(self):
        merged = merge_fields([
            {"styles": fv(["Grunge", "Alternative Rock"], "discogs")},
        ])
        assert merged["styles"]["value"] == ["Grunge", "Alternative Rock"]

    def test_empty_input(self):
        assert merge_fields([]) == {}
