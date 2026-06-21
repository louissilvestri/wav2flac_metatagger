"""Merge engine: combine per-provider field values by configurable precedence.

Every merged field keeps its provenance and the full candidate list, so the UI
can show a source chip and offer alternates.
"""

from config import load_settings
from text_utils import fold_for_compare


# ── Per-track cross-provider merge ────────────────────────────────────────────
# Track-level fields that can be borrowed from a second provider when the primary
# leaves them empty. (ISRC has no second source among our providers, but it's
# listed so a future provider that supplies it works for free.)
_TRACK_FILL_FIELDS = ("length_ms", "isrc", "title", "artist")


def _titles_compatible(a: str, b: str) -> bool:
    """Guard against cross-filling misaligned tracks (e.g. a bonus track shifting
    positions between editions). Empty/unknown titles can't be compared, so they
    pass — that's what lets a blank primary title be filled."""
    fa, fb = fold_for_compare(a or ""), fold_for_compare(b or "")
    if not fa or not fb:
        return True
    return fa == fb or fa in fb or fb in fa


def _fill_track(dst: dict, src: dict) -> None:
    if not _titles_compatible(dst.get("title", ""), src.get("title", "")):
        return
    for f in _TRACK_FILL_FIELDS:
        if not dst.get(f) and src.get(f):
            dst[f] = src[f]


def merge_tracks(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """Fill empty per-track fields on `primary` from `secondary`, matched by
    (disc_number, position). Primary values always win; tracks are never added or
    removed. Both lists are flat track dicts carrying 'disc_number'. In place."""
    if not primary or not secondary:
        return primary
    idx = {(t.get("disc_number", 1), t.get("position")): t for t in secondary}
    for t in primary:
        m = idx.get((t.get("disc_number", 1), t.get("position")))
        if m:
            _fill_track(t, m)
    return primary


def merge_disc_tracks(primary_discs: list[dict], secondary_discs: list[dict]) -> None:
    """merge_tracks for the disc-structured release shape (details['discs']).
    Mutates primary_discs in place."""
    if not primary_discs or not secondary_discs:
        return
    idx = {}
    for d in secondary_discs:
        dp = d.get("position", 1)
        for t in d.get("tracks", []):
            idx[(dp, t.get("position"))] = t
    for d in primary_discs:
        dp = d.get("position", 1)
        for t in d.get("tracks", []):
            m = idx.get((dp, t.get("position")))
            if m:
                _fill_track(t, m)

# Which provider wins each field, in order. Editable via settings
# ("merge_precedence" key) without code changes.
DEFAULT_PRECEDENCE = {
    "title":          ["musicbrainz", "discogs", "itunes"],
    "artist":         ["musicbrainz", "discogs", "itunes"],
    "original_date":  ["musicbrainz", "discogs", "itunes", "deezer"],
    "release_date":   ["musicbrainz", "discogs", "itunes", "deezer"],
    "genre":          ["lastfm", "discogs", "musicbrainz", "itunes"],
    "styles":         ["discogs", "lastfm", "musicbrainz"],
    "label":          ["discogs", "musicbrainz"],
    "catalog_number": ["discogs", "musicbrainz"],
    "barcode":        ["musicbrainz", "discogs"],
    "country":        ["musicbrainz", "discogs"],
}


def get_precedence(settings: dict | None = None) -> dict:
    settings = settings or load_settings()
    user = settings.get("merge_precedence", {})
    return {**DEFAULT_PRECEDENCE, **user}


def _date_specificity(value) -> int:
    """Length-as-specificity for dates: '1970-07-08' beats '1970'."""
    return len(str(value or ""))


def merge_fields(provider_fields: list[dict[str, dict]],
                 precedence: dict | None = None) -> dict[str, dict]:
    """Merge per-provider field dicts into one record with provenance.

    provider_fields: list of {field_name: {value, source}} dicts.

    Returns {field_name: {value, source, candidates: [{value, source}, ...]}}.
    The winner is the first provider in the field's precedence list that has a
    non-empty value — except dates, where a more specific date (full Y-M-D)
    from a lower-precedence source beats a bare year. That rule exists because
    of a real regression: replacing '1999-06-29' with '1999' is a downgrade no
    matter how authoritative the source.
    """
    precedence = precedence or get_precedence()

    # Collect candidates per field
    by_field: dict[str, list[dict]] = {}
    for fields in provider_fields:
        for name, fv in fields.items():
            if fv.get("value") in (None, "", []):
                continue
            by_field.setdefault(name, []).append(fv)

    merged = {}
    for name, candidates in by_field.items():
        order = precedence.get(name, [])

        def rank(fv):
            try:
                return order.index(fv["source"])
            except ValueError:
                return len(order)  # unknown providers go last, keeping input order

        ranked = sorted(candidates, key=rank)
        winner = ranked[0]

        # Date exception: prefer the most specific date among candidates whose
        # year agrees with the precedence winner
        if name in ("original_date", "release_date") and len(ranked) > 1:
            winner_year = str(winner["value"])[:4]
            same_year = [c for c in ranked if str(c["value"])[:4] == winner_year]
            if same_year:
                most_specific = max(same_year, key=lambda c: _date_specificity(c["value"]))
                if _date_specificity(most_specific["value"]) > _date_specificity(winner["value"]):
                    winner = most_specific

        merged[name] = {
            "value": winner["value"],
            "source": winner["source"],
            "candidates": [{"value": c["value"], "source": c["source"]} for c in ranked],
        }

    return merged
