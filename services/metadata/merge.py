"""Merge engine: combine per-provider field values by configurable precedence.

Every merged field keeps its provenance and the full candidate list, so the UI
can show a source chip and offer alternates.
"""

from config import load_settings

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
