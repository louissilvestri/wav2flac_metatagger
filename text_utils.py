"""Shared text normalization for search queries.

Tags, folder names, and provider catalogs disagree on typography: an album
folder may be named "Go‐Go's" (figure-dash U+2010 + curly apostrophe U+2019)
while MusicBrainz/Discogs store "Go-Go's" with ASCII hyphen and straight
quote. Searching with the fancy characters returns zero matches. We fold
typographic punctuation to ASCII before querying so the two line up.

Two folds, ONE shared base (normalize_punctuation -> strip accents -> lower):
  - fold_for_compare: for titles. Unifies separators (, / ;); keeps other
    punctuation so distinct titles stay distinct.
  - fold_loose: for artist / folder names that may have been sanitized for the
    filesystem. Additionally removes remaining punctuation and a leading/
    trailing "the" ("The Beatles" == "Beatles", "AC/DC" == "ACDC").
Query building (normalize_punctuation / lucene_phrase) deliberately PRESERVES
accents — providers index them, so we must not fold accents out of a query.
"""

import re
import unicodedata

# Typographic → ASCII. Covers the characters that actually show up in music
# metadata (smart quotes, the dash family, ellipsis, non-breaking space).
_PUNCT_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",   # ‘ ’ ‚ ‛
    "ʼ": "'", "´": "'", "`": "'",                   # ʼ ´ `
    "“": '"', "”": '"', "„": '"', "‟": '"',   # “ ” „ ‟
    "‐": "-", "‑": "-", "‒": "-", "–": "-",   # ‐ ‑ ‒ –
    "—": "-", "―": "-", "−": "-",                   # — ― −
    "…": "...",                                               # …
    " ": " ", " ": " ", " ": " ",                  # nbsp variants
}

_PUNCT_TABLE = {ord(k): v for k, v in _PUNCT_MAP.items()}


def normalize_punctuation(s: str) -> str:
    """Fold typographic punctuation to ASCII. Leaves letters (accents) intact."""
    if not s:
        return s
    return s.translate(_PUNCT_TABLE)


def lucene_phrase(s: str) -> str:
    """Normalize punctuation and escape for use inside a quoted Lucene phrase
    (MusicBrainz search). A bare double-quote or backslash would otherwise
    break the phrase and the whole query."""
    s = normalize_punctuation(s or "")
    return s.replace("\\", "\\\\").replace('"', '\\"')


_VARIOUS_ARTIST = {"various artists", "various"}


def strip_various_artist(artist: str | None) -> str:
    """Drop a "Various Artists" placeholder so the album title carries the
    search — providers index compilations under the album, not the artist.
    Shared by every provider search path so they behave identically."""
    if artist and artist.strip().lower() in _VARIOUS_ARTIST:
        return ""
    return artist or ""


def strip_accents(s: str) -> str:
    """Fold accented letters to their base form (Motörhead -> Motorhead).
    For COMPARISON only — never for queries (providers index the accents)."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def _fold_base(s: str) -> str:
    """Shared foundation for both compare folds: typographic punctuation -> ASCII,
    accents stripped, lowercased, and "&" unified to "and". Keeps the two folds
    consistent — "Rock & Roll" and "Rock and Roll" compare equal everywhere."""
    s = strip_accents(normalize_punctuation(s or "")).lower()
    return s.replace("&", " and ")


def fold_for_compare(s: str) -> str:
    """Fold for title equality/contains checks: punctuation-insensitive.

    Shared base (typography, accents, case, & → and), then apostrophes are
    dropped (so "She's" == "Shes") and every other punctuation/symbol becomes a
    space before whitespace is collapsed. This makes matching tolerant of the
    ways providers disagree on titles — "&" vs "and", parentheses, slashes,
    commas, hyphens, etc. — without joining separate words.
    Use on BOTH sides of a comparison."""
    s = _fold_base(s)
    s = s.replace("'", "")            # contractions/possessives: She's == Shes
    s = re.sub(r"[^\w\s]", " ", s)    # any other punctuation/symbol -> space (keeps unicode letters)
    return " ".join(s.split())


def fold_loose(s: str) -> str:
    """Aggressive fold for artist / folder-name matching, where the name may
    have been sanitized for the filesystem. Same base as fold_for_compare, then
    removes ALL remaining punctuation and a leading/trailing "the":
    "The Beatles" == "Beatles", "AC/DC" == "ACDC", "Motörhead" == "Motorhead".
    Use fold_for_compare for titles, where punctuation/accents are meaningful."""
    s = _fold_base(s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"\s+the$", "", s)
    return s
