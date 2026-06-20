"""Guards for the art-download helpers shared by conversion and library reassign.

REGRESSION: renaming _download_art -> _download_art_raw broke library_service's
lazy `from services.conversion import _download_art` and 500'd track reassign
with user-picked art. Both names must stay importable with their signatures.
"""

import services.conversion as conv


def test_download_art_symbol_and_signature(monkeypatch):
    # The exact call library_service makes (url, max_size, quality).
    from services.conversion import _download_art
    monkeypatch.setattr(conv, "_download_art_raw", lambda url: None)
    assert _download_art("http://example/none.jpg", 1200, 90) is None


def test_download_art_prepares_when_bytes_present(monkeypatch):
    from services.conversion import _download_art
    captured = {}
    monkeypatch.setattr(conv, "_download_art_raw", lambda url: b"rawbytes")
    monkeypatch.setattr(conv, "prepare_art",
                        lambda data, max_size, quality: captured.setdefault("out", b"jpeg"))
    assert _download_art("http://example/cover.jpg", 800, 85) == b"jpeg"
