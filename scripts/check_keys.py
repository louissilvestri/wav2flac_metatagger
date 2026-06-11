"""Validate every API key in .env with a real request to each provider."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import get_secret

UA = {"User-Agent": "MusicManager/2.0 (louissilvestri@hotmail.com)"}
results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"exception: {e}"
    results.append((name, ok, detail))


def discogs():
    token = get_secret("DISCOGS_TOKEN")
    if not token:
        return False, "no key set"
    r = requests.get(
        "https://api.discogs.com/database/search",
        params={"release_title": "Nevermind", "artist": "Nirvana", "type": "release", "per_page": 1},
        headers={**UA, "Authorization": f"Discogs token={token}"},
        timeout=15,
    )
    if r.status_code == 200:
        n = len(r.json().get("results", []))
        return True, f"search OK, {n} result(s), rate remaining: {r.headers.get('X-Discogs-Ratelimit-Remaining', '?')}"
    return False, f"HTTP {r.status_code}: {r.text[:120]}"


def acoustid():
    key = get_secret("ACOUSTID_API_KEY")
    if not key:
        return False, "no key set"
    # A deliberately invalid fingerprint: a VALID key gets a fingerprint error,
    # an INVALID key gets an authentication error.
    r = requests.get(
        "https://api.acoustid.org/v2/lookup",
        params={"client": key, "duration": 120, "fingerprint": "AQAAA0"},
        headers=UA, timeout=15,
    )
    data = r.json()
    if data.get("status") == "ok":
        return True, "lookup OK"
    err = data.get("error", {})
    code, msg = err.get("code"), err.get("message", "")
    if code == 4 or "invalid api key" in msg.lower():
        return False, f"key rejected: {msg}"
    return True, f"key accepted (expected fingerprint error: {msg})"


def lastfm():
    key = get_secret("LASTFM_API_KEY")
    if not key:
        return False, "no key set"
    r = requests.get(
        "https://ws.audioscrobbler.com/2.0/",
        params={"method": "album.gettoptags", "artist": "Pink Floyd",
                "album": "The Dark Side of the Moon", "api_key": key, "format": "json"},
        headers=UA, timeout=15,
    )
    data = r.json()
    if "error" in data:
        return False, f"error {data['error']}: {data.get('message', '')}"
    tags = [t["name"] for t in data.get("toptags", {}).get("tag", [])[:3]]
    return True, f"top tags: {', '.join(tags)}"


def fanarttv():
    key = get_secret("FANARTTV_API_KEY")
    if not key:
        return False, "no key set"
    # Dark Side of the Moon release-group MBID
    rg = "f5093c06-23e3-404f-aeaa-40f72885ee3a"
    r = requests.get(f"https://webservice.fanart.tv/v3/music/albums/{rg}",
                     params={"api_key": key}, headers=UA, timeout=15)
    if r.status_code == 200:
        albums = r.json().get("albums", {})
        covers = sum(len(v.get("albumcover", [])) for v in albums.values())
        return True, f"OK, {covers} cover(s) for DSOTM"
    return False, f"HTTP {r.status_code}: {r.text[:120]}"


def theaudiodb():
    key = get_secret("THEAUDIODB_API_KEY", "2")
    r = requests.get(f"https://www.theaudiodb.com/api/v1/json/{key}/search.php",
                     params={"s": "Pink Floyd"}, headers=UA, timeout=15)
    if r.status_code == 200 and r.json().get("artists"):
        return True, "artist search OK"
    return False, f"HTTP {r.status_code}: {r.text[:120]}"


def itunes():
    r = requests.get("https://itunes.apple.com/search",
                     params={"term": "Pink Floyd Dark Side", "entity": "album", "limit": 1},
                     headers=UA, timeout=15)
    if r.status_code == 200 and r.json().get("resultCount", 0) > 0:
        return True, "no key needed, search OK"
    return False, f"HTTP {r.status_code}"


def deezer():
    r = requests.get("https://api.deezer.com/search/album",
                     params={"q": "dark side of the moon", "limit": 1},
                     headers=UA, timeout=15)
    if r.status_code == 200 and r.json().get("data"):
        return True, "no key needed, search OK"
    return False, f"HTTP {r.status_code}"


check("Discogs", discogs)
check("AcoustID", acoustid)
check("Last.fm", lastfm)
check("fanart.tv", fanarttv)
check("TheAudioDB", theaudiodb)
check("iTunes Search", itunes)
check("Deezer", deezer)

print(f"{'Provider':<15} {'Status':<6} Detail")
print("-" * 70)
for name, ok, detail in results:
    print(f"{name:<15} {'OK' if ok else 'FAIL':<6} {detail}")

sys.exit(0 if all(ok for _, ok, _ in results) else 1)
