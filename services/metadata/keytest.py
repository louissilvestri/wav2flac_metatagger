"""Lightweight 'does this API key actually work?' checks for the Settings page.

Each test makes one minimal authenticated call and reports {ok, message}. They
never raise — a network error or bad key returns ok=False with a readable note.
"""

import requests

from config import get_secret, PROVIDER_KEYS

_UA = {"User-Agent": "MusicManager/2.0"}
_TIMEOUT = 12


def _missing(provider: str) -> dict | None:
    """Return an error result if any required key for the provider is blank."""
    for name in PROVIDER_KEYS.get(provider, []):
        if not get_secret(name):
            return {"ok": False, "message": f"{name} not set"}
    return None


def _test_discogs() -> dict:
    from discogs_lookup import _get_client
    client = _get_client()
    if not client:
        return {"ok": False, "message": "Discogs token not configured"}
    # A trivial authenticated search; bad token raises an HTTP 401.
    results = client.search("Nevermind", type="release", per_page=1)
    _ = results.page(1)
    return {"ok": True, "message": "Token works"}


def _test_lastfm() -> dict:
    key = get_secret("LASTFM_API_KEY")
    r = requests.get("https://ws.audioscrobbler.com/2.0/", params={
        "method": "artist.getInfo", "artist": "Cher", "api_key": key, "format": "json",
    }, headers=_UA, timeout=_TIMEOUT)
    data = r.json()
    if data.get("error"):
        return {"ok": False, "message": data.get("message", "Invalid API key")}
    return {"ok": True, "message": "API key works"}


def _test_fanarttv() -> dict:
    key = get_secret("FANARTTV_API_KEY")
    # The Beatles — a known MusicBrainz artist ID.
    r = requests.get(
        f"https://webservice.fanart.tv/v3/music/b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
        params={"api_key": key}, headers=_UA, timeout=_TIMEOUT)
    if r.status_code == 401:
        return {"ok": False, "message": "Invalid API key"}
    if r.status_code >= 400:
        return {"ok": False, "message": f"HTTP {r.status_code}"}
    return {"ok": True, "message": "API key works"}


def _test_acoustid() -> dict:
    from services.metadata.providers.acoustid import find_fpcalc
    key = get_secret("ACOUSTID_API_KEY")
    if not find_fpcalc():
        return {"ok": False, "message": "Key set, but fpcalc binary not found"}
    # Call lookup with no fingerprint: a VALID key yields a "missing parameter"
    # error; an INVALID key yields "invalid API key". That distinguishes them.
    r = requests.get("https://api.acoustid.org/v2/lookup",
                     params={"client": key, "meta": "recordings"},
                     headers=_UA, timeout=_TIMEOUT)
    try:
        msg = (r.json().get("error", {}) or {}).get("message", "")
    except ValueError:
        msg = ""
    if "invalid" in msg.lower() and "api key" in msg.lower():
        return {"ok": False, "message": "Invalid API key"}
    return {"ok": True, "message": "API key works (fpcalc found)"}


_TESTS = {
    "discogs": _test_discogs,
    "lastfm": _test_lastfm,
    "fanarttv": _test_fanarttv,
    "acoustid": _test_acoustid,
}


def test_provider(provider: str) -> dict:
    """Return {ok: bool, message: str} for a provider's configured key."""
    if provider not in _TESTS:
        return {"ok": False, "message": "No key test for this provider"}
    missing = _missing(provider)
    if missing:
        return missing
    try:
        return _TESTS[provider]()
    except Exception as e:  # network/library errors → readable failure
        return {"ok": False, "message": str(e) or e.__class__.__name__}
