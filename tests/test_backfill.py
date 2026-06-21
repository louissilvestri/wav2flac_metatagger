"""Cross-provider gap-fill: MusicBrainz primary, Discogs fills empty fields."""

import metadata_lookup
import discogs_lookup
from services import providers


def _mb_details(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111", "title": "Prince Charming",
        "artist": "Adam and the Ants", "date": "1981", "first_release_date": "1981",
        "country": "GB", "barcode": "", "label": "CBS", "catalog_number": "",
        "genre": "", "discs": [{"position": 1, "format": "CD", "tracks": []}],
    }
    base.update(over)
    return base


def _dg_details(**over):
    base = {
        "id": "12345", "title": "Prince Charming", "artist": "Adam and the Ants",
        "date": "1981", "first_release_date": "1981", "country": "GB",
        "barcode": "5099746000000", "label": "CBS", "catalog_number": "CBS 85268",
        "genre": "Rock", "genres": ["Rock"], "styles": ["New Wave"], "discs": [],
    }
    base.update(over)
    return base


def test_mb_primary_filled_from_discogs(monkeypatch):
    monkeypatch.setattr(metadata_lookup, "get_release_details", lambda rid: _mb_details())
    monkeypatch.setattr(discogs_lookup, "search_release",
                        lambda artist=None, album=None, tracks=None: [{"id": "12345"}])
    monkeypatch.setattr(discogs_lookup, "get_release_details", lambda rid: _dg_details())

    out = providers.get_release("11111111-1111-1111-1111-111111111111",
                                settings={"cross_provider_backfill": True})
    # Empty MB fields filled from Discogs…
    assert out["genre"] == "Rock"
    assert out["barcode"] == "5099746000000"
    assert out["catalog_number"] == "CBS 85268"
    assert out["styles"] == ["New Wave"]


def test_mb_values_win_when_present(monkeypatch):
    monkeypatch.setattr(metadata_lookup, "get_release_details",
                        lambda rid: _mb_details(label="MusicBrainz Label", genre="Post-Punk",
                                                barcode="MB-BARCODE"))
    monkeypatch.setattr(discogs_lookup, "search_release",
                        lambda artist=None, album=None, tracks=None: [{"id": "12345"}])
    monkeypatch.setattr(discogs_lookup, "get_release_details", lambda rid: _dg_details())

    out = providers.get_release("11111111-1111-1111-1111-111111111111",
                                settings={"cross_provider_backfill": True})
    # Present MB fields are NOT overwritten…
    assert out["label"] == "MusicBrainz Label"
    assert out["genre"] == "Post-Punk"
    assert out["barcode"] == "MB-BARCODE"
    # …but a still-empty field is filled.
    assert out["catalog_number"] == "CBS 85268"


def test_disabled_setting_skips_backfill(monkeypatch):
    monkeypatch.setattr(metadata_lookup, "get_release_details", lambda rid: _mb_details())
    called = {"n": 0}
    monkeypatch.setattr(discogs_lookup, "search_release",
                        lambda **k: called.update(n=called["n"] + 1) or [])
    out = providers.get_release("11111111-1111-1111-1111-111111111111",
                                settings={"cross_provider_backfill": False})
    assert out["genre"] == "" and called["n"] == 0


def test_discogs_primary_filled_from_musicbrainz(monkeypatch):
    monkeypatch.setattr(discogs_lookup, "get_release_details",
                        lambda rid: _dg_details(barcode="", catalog_number=""))
    monkeypatch.setattr(metadata_lookup, "search_release",
                        lambda artist=None, album=None, tracks=None, barcode=None: [{"id": "mb-1"}])
    monkeypatch.setattr(metadata_lookup, "get_release_details",
                        lambda rid: _mb_details(barcode="MB-BC", catalog_number="MB-CAT"))

    out = providers.get_release("12345", settings={"cross_provider_backfill": True})
    assert out["barcode"] == "MB-BC"
    assert out["catalog_number"] == "MB-CAT"
