"""Shared text normalization for search queries.

Tags, folder names, and provider catalogs disagree on typography: an album
folder may be named "Go‐Go's" (figure-dash U+2010 + curly apostrophe U+2019)
while MusicBrainz/Discogs store "Go-Go's" with ASCII hyphen and straight
quote. Searching with the fancy characters returns zero matches. We fold
typographic punctuation to ASCII before querying so the two line up.
"""

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


def fold_for_compare(s: str) -> str:
    """Aggressive fold for client-style equality/contains checks: punctuation
    normalized, lowercased, whitespace collapsed."""
    s = normalize_punctuation(s or "").lower()
    return " ".join(s.split())
