# Music Manager 2.0 — Refactor Plan

## Why refactor

The current app works but has four structural problems that patches can't fix:

1. **Repeated information / tangled state.** The Convert tab renders artist/album/date/art in four separate places (release header, art comparison, completeness panel, cascade log), each fed by its own module-level global (`currentReleaseDetails`, `albumArtData`, `currentCueMetadata`, `manualDiscOverride`, …). Every bug fix this session involved re-synchronizing copies of the same data. `app.js` is ~2,900 lines of vanilla JS with no component model.

2. **Fragile server lifecycle.** Eel (the Python↔browser bridge) was archived in June 2025 and is unmaintained. It runs on gevent with a WebSocket that dies on sleep/wake; the current "fix" is a hand-rolled heartbeat that force-reloads the page, plus `shutdown_delay=999999` to stop the server killing itself. Worse: stale-server bugs (three times this session, a code change didn't take effect because the old process was still running).

3. **No real frontend stack.** Vanilla JS + hand-written CSS means no types, no components, no dev server with hot reload, and no way to apply the Cyan Command style guide systematically.

4. **Metadata is provider-locked and inconsistent.** Provider routing (`if provider == "discogs"`) is duplicated across six endpoints in `app.py`. MusicBrainz and Discogs return different shapes that get massaged in different places. You pick ONE provider — there's no way to take the date from MusicBrainz, the styles from Discogs, and the best art from anywhere. Caching is per-module in-memory dicts that die on restart.

---

## Target architecture

```
┌─────────────────────────────────────────────────────┐
│  Next.js frontend (TypeScript, Tailwind w/ Cyan      │
│  Command tokens, React Query, static export)         │
└──────────────┬──────────────────────────────────────┘
               │ REST + Server-Sent Events (progress)
┌──────────────┴──────────────────────────────────────┐
│  FastAPI backend (Python)                            │
│  ├─ routers/      (thin HTTP layer)                  │
│  ├─ services/                                        │
│  │   ├─ conversion.py   (job queue, flac.exe)        │
│  │   ├─ library.py      (scan, dupes, reassign)      │
│  │   ├─ tagging.py      (mutagen, merge-not-delete)  │
│  │   └─ metadata/       (aggregation layer, below)   │
│  └─ db.py        (SQLite: jobs, logs, metadata cache)│
└──────────────────────────────────────────────────────┘
```

**Why keep Python for the backend:** mutagen (FLAC tagging), the flac.exe encoder pipeline, CUE parsing, and disc-ID math are all working Python. Node's FLAC tag-writing story is weak. Next.js is the UI; it never touches files directly.

**Deployment shape:** `next build` with `output: 'export'` → static files served by FastAPI. One process, one port, same launch experience as today (run script → browser opens in app mode). No SSR needed since all data comes from the API.

**Sleep/shutdown resilience (fixes issue #2 by design):**
- REST instead of a stateful WebSocket — every request is independent; nothing to "reconnect."
- React Query retries failed requests automatically with backoff and refetches on window focus — wake from sleep just works.
- Conversion jobs live in SQLite with status (`queued/running/done/failed`), not in a Python global. Progress streams over SSE; if the stream drops, the UI falls back to polling the job endpoint. If the server is killed mid-batch, on restart it marks orphaned `running` jobs as `interrupted` and offers resume.
- Single-instance guard: on startup, if the port is taken, health-check it — if it's a stale/older version (health endpoint returns app version + git hash), kill and replace instead of silently deferring to it. (This directly fixes the "restarted but old code still running" trap.)

---

## Metadata aggregation layer (fixes issue #4)

### Canonical model

One internal shape, regardless of source. Every field carries provenance:

```python
@dataclass
class FieldValue:
    value: str | int | None
    source: str          # "musicbrainz" | "discogs" | "lastfm" | ...
    confidence: float    # provider match score, normalized

@dataclass
class CanonicalRelease:
    title: FieldValue
    artist: FieldValue
    original_date: FieldValue      # always release-group/master level
    release_date: FieldValue       # this specific edition
    genre: FieldValue
    styles: list[FieldValue]
    label: FieldValue
    catalog_number: FieldValue
    barcode: FieldValue
    country: FieldValue
    tracks: list[CanonicalTrack]
    art_candidates: list[ArtCandidate]   # url/bytes, source, WxH
    ids: dict[str, str]            # {"musicbrainz": ..., "discogs": ...}
```

### Provider plugins

Common interface; each provider implements what it can:

| Provider | Key needed | Strengths | Use for |
|---|---|---|---|
| **MusicBrainz** (keep) | UA string | Disc ID exact match, release groups, first-release-date, ISRCs | Identity, original dates, track listings |
| **Discogs** (keep) | token ✓ have | Styles, labels, catalog #s, pressing detail | Styles/genre detail, label info |
| **AcoustID / Chromaprint** (NEW) | free key | Audio fingerprinting — identifies a track from its *audio*, ignoring tags entirely | Library cleanup of badly/un-tagged FLACs; maps straight to MusicBrainz recording IDs |
| **Cover Art Archive** (keep) | none | Per-release scans | Art |
| **fanart.tv** (NEW) | free key | Curated high-res album art | Art upgrades |
| **iTunes Search API** (NEW) | none | Reliable dates, art upsizable to 3000×3000 via URL rewrite | Art + date corroboration, zero setup |
| **Deezer API** (NEW, optional) | none | Art, dates | Corroboration |
| **Last.fm** (NEW) | free key | Community genre tags (best genre source anywhere) | Genre |
| **TheAudioDB** (NEW, optional) | free tier | Bios, art, genre | Filler |

AcoustID is the headline addition: `fpcalc.exe` fingerprints the FLAC audio → AcoustID returns MusicBrainz recording IDs → exact identification even when tags are blank or wrong. This supersedes title-string matching for Quick Clean Up track matching.

### Merge engine

Replace "pick a provider" with "query several, merge by precedence":

```
original_date:  musicbrainz.first_release_date > discogs.master_year > itunes.date
genre:          lastfm.top_tags > discogs.styles > musicbrainz.tags
label/catno:    discogs > musicbrainz
artwork:        rank ALL candidates by resolution: fanart > CAA > itunes > discogs > local > embedded
track titles:   musicbrainz (via acoustid match) > discogs > existing tag
```

- Precedence is a config table, editable in Settings (provider on/off + drag priority).
- The merged record keeps per-field provenance, which feeds directly into the side-by-side compare UI you already have: each "New" value shows a source chip ("MB", "DG", "FM") and a checkbox — the pattern built for Quick Clean Up this session becomes the *only* metadata-apply pattern, used by Convert and Library alike.
- Provider responses cached in SQLite (`metadata_cache` table, keyed by provider+query, TTL ~30 days for releases, ~7 for searches) — replaces the four in-memory dicts; survives restarts.
- Rate limiters per provider (MB 1/s, Discogs 60/min, AcoustID 3/s) in one place instead of scattered `_rate_limit()` calls.

---

## Frontend (fixes issues #1 and #3)

**Stack:** Next.js (App Router, static export) + TypeScript + Tailwind CSS v4 + React Query + Zustand (only for the convert wizard's cross-step state).

**Cyan Command integration** (`C:\Claude\design-preview\style-guide.html` → Tailwind theme):
- Tokens: `--bg #0a0e12`, `--surface`, `--accent #22d3ee` (cyan), `--accent-2 #f6a609` (amber), `--alert`, `--ok`, glow shadows, 240ms `cubic-bezier(.16,1,.3,1)` motion.
- Fonts: Audiowide (display/nav/panel titles), Inter (body), JetBrains Mono (data tables, paths, logs).
- Components built once, used everywhere: chamfered `<Panel>` (the `--chamfer` clip-path), `<NavRail>`, pill tabs, glow buttons, terminal-style log view (the cascade log becomes a proper `[ OK ]`-style terminal panel — it already wants to be one), scrim+chamfered dialogs.
- `prefers-reduced-motion` respected (already in the guide).
- Implementation detail: invoke the `ui-ux-expert` skill when building the component library to keep decisions consistent with the vault.

**Information architecture — Convert tab de-duplication:**

One store, one render of each fact:

```
ConvertWizard (Zustand store: files, cueMeta, candidates, selection, mergedMeta, artChoice)
 ├─ Step 1: Source        (folder scan, file list, CUE status — terminal panel)
 ├─ Step 2: Identify      (cascade log + candidate list; auto-runs aggregated lookup)
 ├─ Step 3: Review        (ONE side-by-side compare: CUE/EAC vs merged provider data,
 │                         per-field checkboxes + source chips; art candidate strip;
 │                         track table with match status — no duplicated headers)
 └─ Step 4: Convert       (job progress via SSE, per-file results, log)
```

Artist/album/date/art each appear exactly once, in Step 3. The completeness meter becomes a column in the compare table instead of a separate panel.

**Library tab** reuses the same `<MetadataCompare>` and `<ArtPicker>` components for track reassign and Quick Clean Up — ending the Convert/Library logic drift that caused several of this session's bugs.

---

## Phases

### Phase 0 — Safety net (do first, small)
- `git init` + initial commit. **The project is not currently a git repo** — this refactor should not start without history.
- Characterization tests (pytest) for the logic that must not regress: `tagger.embed_metadata` merge behavior, `build_output_path`, compilation detection matrix (CCR cases), duplicate finder, CUE disc-ID math, `_normalize_for_compare`.
- Pin current behavior of the worst earlier bugs (tag deletion, date regression) as explicit tests.

### Phase 1 — Backend extraction (Python, no UI change yet)
- New `server/` package: FastAPI app, routers mirroring today's `@eel.expose` functions.
- Move business logic out of `app.py` into `services/` (most modules — tagger, library_manager, file_manager, cue_parser — are already clean; `app.py`'s 1,200 lines shrink to glue).
- SQLite job queue for conversions; SSE progress endpoint; orphan-job recovery on startup.
- Single-instance health/version guard.
- Exit criteria: every current Eel endpoint has a REST equivalent with tests; conversion of a real album works end-to-end via `curl`.

### Phase 2 — Metadata aggregation
- Canonical model + provider interface; port MusicBrainz and Discogs clients onto it (deleting the six `if provider ==` branches in app.py).
- Add AcoustID (ship `fpcalc.exe` alongside `flac.exe`), iTunes Search, Last.fm; fanart.tv/Deezer/TheAudioDB as fast-follow toggles.
- Merge engine + precedence config + SQLite cache + unified rate limiting.
- Exit criteria: one `/api/metadata/identify` call returns a merged record with provenance for: a CUE'd rip, a tagged library album, and a *blank-tagged* FLAC (via fingerprint).

### Phase 3 — Next.js frontend
- Scaffold `web-next/`: Next + TS + Tailwind with Cyan Command tokens; build the component library first (Panel, NavRail, Buttons, Terminal, Dialog, MetadataCompare, ArtPicker, JobProgress) as a Storybook-style gallery page checked against the style guide.
- Port tabs in order of payoff: **Convert wizard → Library (incl. Quick Clean Up + duplicates) → History/Dashboard → Settings**.
- React Query everywhere; no module globals.
- Exit criteria: full parity checklist (below) passes against the FastAPI backend.

### Phase 4 — Cutover
- Launcher: start FastAPI (serving the static Next export), open Edge in app mode — same UX as today.
- Parity checklist run on the real library (1,010 files): scan, convert one album, reassign one track, Quick Clean Up one split album, delete one duplicate, sleep/wake the machine mid-session, kill the server mid-conversion and restart.
- Delete `web/`, Eel dependency, and old `app.py` glue. Tag `v2.0.0`.

### Sequencing notes
- Phases 1–2 leave the existing Eel UI untouched and runnable — you keep a working app throughout.
- Phase 3 is the long pole. The wizard (Step 3 Review) is the most valuable single screen; build it first inside the new shell.
- Rough effort: P0 a session; P1 2–3 sessions; P2 2–3 sessions; P3 4–6 sessions; P4 one session.

---

## Decisions made (flag if you disagree)

1. **FastAPI Python backend, not full-TypeScript** — preserves mutagen/flac.exe/CUE logic; Node FLAC tagging is inferior.
2. **Static-export Next served by FastAPI** — one process, no SSR complexity, same desktop-app feel.
3. **AcoustID fingerprinting is in scope** — it's the single biggest metadata-quality win for a library with imperfect tags.
4. **Per-field provenance + user-editable precedence** rather than a hard-coded "best provider per field" — matches how you've been making field-level decisions in the compare UI.
5. **SQLite for metadata cache and job queue** — already a dependency (activity log), survives restarts, no new infra.

## Open items needing your input (not blocking P0/P1)
- Fill in the blank keys in `.env` (created; Discogs token already migrated from settings.json): AcoustID, Last.fm, fanart.tv — registration links are in the file comments.
- Whether History/Dashboard carries over as-is or gets rethought during Phase 3.
