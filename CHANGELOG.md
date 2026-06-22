# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-06-22

First production release. Complete rewrite from the v1 Eel desktop app to a
FastAPI server with a Next.js front end.

### Added
- WAV to FLAC conversion with bit-perfect verification and read-back confirmation.
- Multi-source metadata aggregation across MusicBrainz, Discogs, Last.fm, iTunes,
  Deezer, fanart.tv, AcoustID, and Cover Art Archive, with per-field precedence
  and user-confirmable choices.
- Release identification by MusicBrainz disc ID, AcoustID fingerprint, barcode,
  or text search; edition picker with country, media-type, and track-count filters.
- Cross-provider gap-fill (MusicBrainz primary, Discogs fallback) for album
  fields and per-track lengths.
- Performer and writer credits (composer, lyricist, conductor, performers) from
  MusicBrainz relationships.
- Album art comparison across providers and local folders, with rescale and
  missing-art reporting.
- ReplayGain (track and album), per-album and as a background library-wide job;
  a presence indicator on already-tagged albums.
- Library view: completeness scoring, compilation detection, duplicate
  detection, Quick Clean Up, and an advanced raw-tag editor.
- Persistent job queue with live progress over server-sent events.
- Rotating file logging, SQLite schema versioning, and a first-run setup banner.

### Changed
- Song search now returns every edition a track appears on, matching album-search
  granularity.
- Barcode and country are written and displayed correctly across conversion and
  reassign.

### Removed
- The retired v1 Eel UI (`app.py`, `web/`) and the `eel` dependency.
