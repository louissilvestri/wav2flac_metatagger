"""Multi-provider metadata aggregation (Phase 2).

One identify() call queries every enabled provider, normalizes the results,
and merges them per-field by configurable precedence — with provenance on
every value so the UI can show where each fact came from.
"""
