"""Art/release routing must follow the release ID's shape, not a global
setting. REGRESSION: with metadata_provider='discogs', a MusicBrainz release
UUID was sent to the Discogs API, silently returned no art, and tracks were
embedded with nothing — the app's core purpose, broken.
"""

import services.art as art
import services.providers as providers


def test_is_discogs_id():
    assert art.is_discogs_id("27376014")        # Discogs = integer
    assert art.is_discogs_id("9456831")
    assert not art.is_discogs_id("aacae183-fd7c-4340-996f-95aa722e74b1")  # MB = UUID
    assert not art.is_discogs_id("")
    assert not art.is_discogs_id("c3ba8429-749f-4724-8878-ffd213f8dbd2")


def test_fetch_art_routes_mb_id_to_caa(monkeypatch):
    """A MusicBrainz UUID must hit Cover Art Archive even if the legacy
    provider setting says discogs."""
    calls = {"caa": 0, "discogs": 0}

    import metadata_lookup
    import discogs_lookup
    monkeypatch.setattr(metadata_lookup, "get_cover_art",
                        lambda rid, **kw: (calls.__setitem__("caa", calls["caa"] + 1), b"\xff\xd8\xffDATA")[1])
    monkeypatch.setattr(discogs_lookup, "get_cover_art",
                        lambda rid, **kw: calls.__setitem__("discogs", calls["discogs"] + 1))

    art.fetch_art_for_provider("aacae183-fd7c-4340-996f-95aa722e74b1",
                               settings={"metadata_provider": "discogs"})
    assert calls["caa"] == 1
    assert calls["discogs"] == 0


def test_fetch_art_routes_discogs_id_to_discogs(monkeypatch):
    calls = {"caa": 0, "discogs": 0}
    import metadata_lookup
    import discogs_lookup
    monkeypatch.setattr(metadata_lookup, "get_cover_art",
                        lambda rid, **kw: calls.__setitem__("caa", calls["caa"] + 1))
    monkeypatch.setattr(discogs_lookup, "get_cover_art",
                        lambda rid, **kw: (calls.__setitem__("discogs", calls["discogs"] + 1), b"\xff\xd8\xffDATA")[1])

    art.fetch_art_for_provider("27376014",
                               settings={"metadata_provider": "musicbrainz"})
    assert calls["discogs"] == 1
    assert calls["caa"] == 0


def test_get_release_routes_by_id_shape(monkeypatch):
    """get_release ignores the provider setting and routes by ID shape."""
    seen = {}
    import metadata_lookup
    import discogs_lookup
    monkeypatch.setattr(metadata_lookup, "get_release_details",
                        lambda rid: seen.update(mb=rid) or {"id": rid})
    monkeypatch.setattr(discogs_lookup, "get_release_details",
                        lambda rid: seen.update(dg=rid) or {"id": rid})

    providers.get_release("c3ba8429-749f-4724-8878-ffd213f8dbd2",
                          settings={"metadata_provider": "discogs"})
    assert seen.get("mb") and "dg" not in seen

    seen.clear()
    providers.get_release("27376014", settings={"metadata_provider": "musicbrainz"})
    assert seen.get("dg") and "mb" not in seen
