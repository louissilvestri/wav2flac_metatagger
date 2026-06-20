"use client";

/** Library: scan, stats, filters, albums, duplicates, Quick Clean Up.
 * Quick Clean Up uses the same MetadataCompare/ArtPicker as the Convert
 * wizard, fed by the aggregator (fingerprints work even on blank tags).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, LibraryAlbum, LibraryFile, LibraryScan, IdentifyResult, ReleaseCandidate, ReleaseDetails, FieldValue } from "@/lib/api";
import { foldForCompare, normalizeArtistForSearch } from "@/lib/text";
import { Panel, Button, Input, Field, StatCard, Spinner, Tag, Dialog, Drawer, Terminal, TermLine, Checkbox, PendingSummary, useToast, cx } from "@/components/ui";
import { MetadataCompare, CompareRow, Choices, defaultChoices, asText } from "@/components/MetadataCompare";
import { ArtPicker, ArtOption } from "@/components/ArtPicker";
import { ManualSearch } from "@/components/ManualSearch";
import { EditionPicker } from "@/components/EditionPicker";
import { embeddedArtOption, candidateArtOptions, autoArtOption, noneArtOption } from "@/lib/artOptions";

type Filter = "all" | "compilations" | "incomplete" | "duplicates";

export default function LibraryPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  const scan = useQuery({
    queryKey: ["library"],
    queryFn: api.libraryScan,
    enabled: false,           // scanning 1000+ network files is explicit
    staleTime: Infinity,
    gcTime: Infinity,         // keep results across tab switches for the session
  });

  const data = scan.data;
  const albums = useMemo(() => {
    if (!data?.albums) return [];
    const q = foldForCompare(search);
    return data.albums.filter((a) => {
      if (filter === "compilations" && !a.is_compilation) return false;
      if (filter === "incomplete" && a.avg_completeness >= 100) return false;
      if (q) {
        const hay = foldForCompare(
          `${a.albumartist} ${a.album} ${a.files.map((f) => f.title).join(" ")}`);
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [data, filter, search]);

  return (
    <div className="space-y-3">
      <header className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-text">Library</h1>
        <Button variant="solid" disabled={scan.isFetching} onClick={() => scan.refetch()}>
          {scan.isFetching ? "Scanning…" : data ? "Rescan" : "Scan Library"}
        </Button>
      </header>

      {scan.isFetching && <Spinner label="reading FLAC tags from the output folder…" />}
      {data?.error && <p className="font-mono text-sm text-alert">{data.error}</p>}

      {data && !data.error && (
        <>
          {/* Tier 1 — library KPIs (totals, not interactive). */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatCard label="Tracks" value={data.total_files} />
            <StatCard label="Albums" value={data.albums.length} />
            <StatCard label="Incomplete tracks" value={data.incomplete_tracks} />
            <StatCard label="Duplicate sets" value={data.duplicate_count} />
          </div>

          {/* Explicit filters — each chip is a clearly-labelled toggle (not a
              stat that secretly filters), with its subset count. */}
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter albums">
            <span className="mr-1 text-xs text-muted">Filter</span>
            {([
              ["all", "All albums", data.albums.length],
              ["incomplete", "Incomplete", data.incomplete_tracks],
              ["compilations", "Compilations", data.compilation_tracks],
              ["duplicates", "Duplicates", data.duplicate_count],
            ] as const).map(([id, label, count]) => (
              <button
                key={id}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
                className={cx(
                  "rounded-full border px-3 py-1 text-xs transition-colors",
                  filter === id
                    ? "border-accent bg-accent/12 text-accent"
                    : "border-border text-muted hover:border-muted hover:text-text",
                )}
              >
                {label} <span className="tabular-nums opacity-70">{count}</span>
              </button>
            ))}
          </div>

          {/* Active-filter readout + escape hatch. */}
          {filter !== "all" && (
            <p className="text-xs text-muted">
              Showing {filter === "duplicates" ? data.duplicates.length : albums.length}{" "}
              {filter === "duplicates" ? "duplicate set(s)" : filter === "incomplete" ? "incomplete album(s)" : "compilation(s)"}
              {" · "}
              <button onClick={() => setFilter("all")} className="text-accent hover:underline">Clear</button>
            </p>
          )}

          {filter !== "duplicates" && (
            <Input
              placeholder="Filter by artist, album, or track…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          )}

          {filter === "duplicates"
            ? <DuplicatesView data={data} />
            : albums.map((album) => (
                <AlbumRow key={`${album.albumartist}|${album.album}`} album={album} />
              ))}
        </>
      )}
    </div>
  );
}

// ── Album row with expandable tracks + Quick Clean Up ────────────────────────

function AlbumRow({ album }: { album: LibraryAlbum }) {
  const [open, setOpen] = useState(false);
  const [cleanup, setCleanup] = useState(false);
  const [detail, setDetail] = useState<LibraryFile | null>(null);
  const pct = Math.round(album.avg_completeness);
  const qc = useQueryClient();
  const toast = useToast();

  // ReplayGain: analyze every track in the album so it carries loudness tags.
  const replayGain = useMutation({
    mutationFn: () => api.replayGain(album.files.map((f) => f.path)),
    onSuccess: async (r) => {
      if (r.success) {
        const updated = await api.rescanLibraryPaths(album.files.map((f) => f.path));
        qc.setQueryData(["library"], updated);
        toast({ tone: "ok", title: "ReplayGain applied",
                msg: `${r.processed} track(s) in ${album.album || "album"}` });
      } else {
        toast({ tone: "error", title: "ReplayGain failed", msg: r.errors.join("; ") });
      }
    },
    onError: (e) => toast({ tone: "error", title: "ReplayGain failed",
                            msg: String((e as Error)?.message ?? e) }),
  });

  return (
    <div className="chamfer border border-accent/20 bg-surface">
      <button
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left hover:bg-accent/5"
        onClick={() => setOpen(!open)}
      >
        <span className="font-display text-sm text-text">{album.album || "Unknown Album"}</span>
        <span className="text-sm text-muted">{album.albumartist || "Unknown Artist"}</span>
        {album.date && <span className="font-mono text-xs text-muted">{album.date}</span>}
        {album.is_compilation && <Tag tone="warn">Compilation</Tag>}
        <span className="ml-auto font-mono text-xs text-muted">
          {album.track_count} trk ·{" "}
          <span className={pct >= 90 ? "text-ok" : pct >= 50 ? "text-accent-2" : "text-alert"}>
            {pct}%
          </span>
        </span>
        <span className="text-accent">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="border-t border-white/10 px-4 py-2">
          <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs text-muted">
            {album.date && <span>Released: <b className="text-text">{album.date}</b></span>}
            {album.genre && <span>Genre: <b className="text-text">{album.genre}</b></span>}
            {album.label && <span>Label: <b className="text-text">{album.label}</b></span>}
            <span>Art: {album.has_art ? <b className="text-ok">✓</b> : <b className="text-alert">missing</b>}</span>
            {album.musicbrainz_albumid && (
              <a className="text-accent hover:underline" target="_blank"
                 href={`https://musicbrainz.org/release/${album.musicbrainz_albumid}`}>
                MusicBrainz ↗
              </a>
            )}
          </div>

          {album.files.map((f) => (
            <button
              key={f.path}
              onClick={() => setDetail(f)}
              className="flex w-full cursor-pointer items-center gap-3 border-b border-white/5 px-1 py-1 text-left font-mono text-[0.78rem] hover:bg-accent/5"
            >
              <span className="w-8 text-muted">{f.tracknumber || "?"}</span>
              <span className="truncate">{f.title || f.filename}</span>
              {f.missing_fields.length > 0 && (
                <span className="text-[0.62rem] text-accent-2">{f.missing_fields.length} missing</span>
              )}
              <span className={cx("ml-auto",
                f.completeness >= 90 ? "text-ok" : f.completeness >= 50 ? "text-accent-2" : "text-alert")}>
                {f.completeness}%
              </span>
            </button>
          ))}

          <div className="mt-2 flex gap-2">
            <Button variant="outline" onClick={() => setCleanup(!cleanup)}>
              Quick Clean Up
            </Button>
            {album.has_replay_gain ? (
              <Tag tone="ok">ReplayGain present</Tag>
            ) : (
              <Button variant="ghost" disabled={replayGain.isPending}
                      onClick={() => replayGain.mutate()}>
                {replayGain.isPending ? "Analyzing…" : "Add ReplayGain"}
              </Button>
            )}
          </div>
          {cleanup && <QuickCleanup album={album} onClose={() => setCleanup(false)} />}
        </div>
      )}

      <TrackDetail file={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

// ── Quick Clean Up (aggregator-powered) ───────────────────────────────────────

function QuickCleanup({ album, onClose }: { album: LibraryAlbum; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [result, setResult] = useState<IdentifyResult | null>(null);
  const [choices, setChoices] = useState<Choices>({});
  const [artChoice, setArtChoice] = useState<string>(album.has_art ? "keep" : "auto");
  // Edition picker: chosen provider+release and its fetched tracklist.
  const [editionId, setEditionId] = useState<string | null>(null);
  const [editionDetails, setEditionDetails] = useState<ReleaseDetails | null>(null);
  // Per-file: true = keep current title instead of the edition's (path-keyed).
  const [titleExcluded, setTitleExcluded] = useState<Record<string, boolean>>({});
  // Compilation flag: auto-set from the provider, overridable by the user.
  const [markComp, setMarkComp] = useState(album.is_compilation);

  // Thumbnail of the currently embedded art for the "Current" option
  const fileWithArt = album.files.find((f) => f.has_art);
  const embThumb = useQuery({
    queryKey: ["embedded-art", fileWithArt?.path],
    queryFn: () => api.embeddedArt(fileWithArt!.path),
    enabled: !!fileWithArt && !!result,
    staleTime: Infinity,
  });

  const identify = useMutation({
    mutationFn: () => api.identify({
      artist: album.albumartist,
      album: album.album,
      // Fingerprint up to 3 tracks — works even when tags are blank/wrong
      file_paths: album.files.slice(0, 3).map((f) => f.path),
    }),
    onSuccess: (r) => {
      setResult(r);
      setChoices(defaultChoices(rowsFor(r, null)));
      setEditionId(null);          // a fresh identify invalidates any chosen edition
      setEditionDetails(null);
      if (r.compilation) setMarkComp(true);  // provider says compilation → default on
    },
  });

  // Auto-identify on open — opening the drawer IS the intent, so don't make the
  // user click "Identify" first (matches the Convert wizard's Identify step).
  const autoRan = useRef(false);
  useEffect(() => {
    if (!autoRan.current && identify.isIdle) { autoRan.current = true; identify.mutate(); }
  }, [identify]);

  // Candidate editions from every provider (track count = this album's files).
  // Default to the album's own tags; a manual search overrides the terms.
  const [searchSpec, setSearchSpec] = useState<{ artist: string; album: string; track_count: number }>(
    { artist: album.albumartist, album: album.album, track_count: album.files.length });
  const candidates = useQuery({
    queryKey: ["release-candidates", searchSpec],
    queryFn: () => api.releaseCandidates(searchSpec),
    enabled: !!result,
    staleTime: Infinity,
  });

  const chooseEdition = useMutation({
    mutationFn: (c: ReleaseCandidate) => api.getRelease(c.id),
    onSuccess: (details, c) => {
      if (details.error || !result) return;
      setEditionId(`${c.provider}:${c.id}`);
      setEditionDetails(details);
      // Re-seed album-field choices from the chosen edition; default every real
      // change to checked (the user picked this edition deliberately).
      const rows = rowsFor(result, details, c.provider);
      const ch = defaultChoices(rows);
      for (const row of rows) {
        const v = ch[row.key]?.value ?? "";
        if (ch[row.key]) ch[row.key].include = !!v && v !== row.current;
      }
      setChoices(ch);
      if (details.compilation) setMarkComp(true);  // chosen edition is a compilation
    },
  });

  // The tracklist that drives matching: chosen edition overrides identify.
  const effTracks: MatchTrack[] = editionDetails
    ? editionDetails.discs.flatMap((d) => d.tracks.map((t) => ({
        position: t.position, title: t.title, artist: t.artist,
        disc_number: d.position, recording_id: t.recording_id })))
    : (result?.tracks ?? []);
  const activeId = editionId
    ?? (result?.ids.musicbrainz_release ? `musicbrainz:${result.ids.musicbrainz_release}` : null);

  // Per-file mapping to the chosen tracklist, for the side-by-side preview.
  const trackPairs = album.files.map((f) => ({ file: f, match: matchTrack(effTracks, f) }));

  // When an edition is chosen, its values become the "new" side (and a
  // candidate, so the source dropdown can still switch back to a provider value).
  const fv = (value: string, source: string, base?: FieldValue): FieldValue => {
    const cands = [{ value, source } as { value: string | string[]; source: string }];
    if (base) for (const c of base.candidates) if (asText(c.value) !== value) cands.push(c);
    return { value, source, candidates: cands };
  };
  // Current album value for a row key (what's on disk now).
  const currentFor = (key: string): string => ({
    artist: album.albumartist, title: album.album, original_date: album.date,
    genre: album.genre, label: album.label, catalog_number: album.catalog_number,
    country: album.country, barcode: album.barcode,
  } as Record<string, string>)[key] ?? "";

  const rowsFor = (r: IdentifyResult, ed: ReleaseDetails | null, edProvider = ""): CompareRow[] => {
    const merged = (key: string, edVal: string): FieldValue | undefined =>
      ed && edVal ? fv(edVal, edProvider || "edition", r.fields[key]) : r.fields[key];
    // Every taggable field is listed — even when both sides are blank — so the
    // user can see what's missing and choose to fill it.
    return [
      { key: "artist", label: "Album Artist", current: currentFor("artist"), merged: merged("artist", ed?.artist ?? "") },
      { key: "title", label: "Album", current: currentFor("title"), merged: merged("title", ed?.title ?? "") },
      { key: "original_date", label: "Date", current: currentFor("original_date"),
        merged: merged("original_date", ed ? (ed.first_release_date || ed.date || "") : "") },
      { key: "genre", label: "Genre", current: currentFor("genre"), merged: merged("genre", ed?.genre ?? "") },
      { key: "label", label: "Label", current: currentFor("label"), merged: merged("label", ed?.label ?? "") },
      { key: "catalog_number", label: "Catalog #", current: currentFor("catalog_number"), merged: merged("catalog_number", ed?.catalog_number ?? "") },
      { key: "barcode", label: "Barcode", current: currentFor("barcode"), merged: merged("barcode", ed?.barcode ?? "") },
      { key: "country", label: "Country", current: currentFor("country"), merged: merged("country", ed?.country ?? "") },
    ];
  };

  // Row key -> tag name. Path fields are always sent (kept, never blanked).
  const ROW_TAG: Record<string, string> = {
    artist: "albumartist", title: "album", original_date: "date",
    genre: "genre", label: "label", catalog_number: "catalognumber",
    barcode: "barcode", country: "country",
  };
  const PATH_FIELDS = new Set(["albumartist", "album", "date"]);

  const apply = useMutation({
    mutationFn: () => {
      if (!result) throw new Error("no identification");

      // Only stamp a MusicBrainz album ID when the active edition is from MB.
      const mbAlbumId = editionDetails
        ? (editionId?.startsWith("musicbrainz:") ? editionDetails.id : "")
        : (result.ids.musicbrainz_release ?? "");

      const meta: Record<string, string> = {
        musicbrainz_albumid: mbAlbumId,
        disctotal: String(Math.max(1, ...effTracks.map((t) => t.disc_number || 1))),
      };
      // Every album field the user can see is honored: path fields are always
      // sent (checked value, else keep current — never blank); other fields are
      // sent only when checked AND non-empty (so the merge keeps existing tags).
      for (const key of Object.keys(ROW_TAG)) {
        const tag = ROW_TAG[key];
        const ch = choices[key];
        const chosen = ch?.include && ch.value ? ch.value : "";
        if (PATH_FIELDS.has(tag)) meta[tag] = chosen || currentFor(key);
        else if (chosen) meta[tag] = chosen;
      }
      // Write the flag both ways so unchecking is an authoritative override
      // (COMPILATION=0), not just a no-op that leaves the album flagged.
      meta.compilation = markComp ? "1" : "0";

      // Per-disc track counts from the chosen tracklist → TRACKTOTAL. Falls
      // back to the album's file count so even unmatched tracks get a total.
      const perDisc: Record<number, number> = {};
      for (const t of effTracks) perDisc[t.disc_number || 1] = (perDisc[t.disc_number || 1] || 0) + 1;

      const currentTitle = (f: LibraryFile) =>
        f.title || f.filename.replace(/^\d+[\s\-._]+/, "").replace(/\.flac$/i, "");

      const tracks = album.files.map((f) => {
        const match = matchTrack(effTracks, f);
        const disc = match?.disc_number ?? Number(f.discnumber || "1") ?? 1;
        const tracktotal = perDisc[disc] || effTracks.length || album.files.length;
        // Title respects the per-track checkbox; numbers/ids follow the match.
        const useEditionTitle = !!match && !titleExcluded[f.path];
        return {
          path: f.path,
          title: useEditionTitle ? match!.title : currentTitle(f),
          artist: match?.artist ?? f.artist,
          tracknumber: String(match?.position ?? f.tracknumber ?? "1"),
          discnumber: String(disc),
          tracktotal: String(tracktotal),
          musicbrainz_trackid: match?.recording_id ?? "",
        };
      });

      // "Auto" art follows the chosen edition when one is picked.
      const autoArtId = editionDetails?.id ?? result.ids.musicbrainz_release ?? null;

      return api.batchReassign({
        tracks,
        album_metadata: meta,
        art_release_id: artChoice === "keep" ? null
          : artChoice === "none" ? "__none__"
          : artChoice === "auto" ? autoArtId
          : null,
        art_url: artChoice.startsWith("url:") ? artChoice.slice(4) : null,
      });
    },
    onSuccess: async (res) => {
      // Partial rescan: only the touched files (old + new paths), not the share
      const paths = res.results.flatMap((r) => [r.path, r.new_path].filter(Boolean));
      const updated = await api.rescanLibraryPaths(paths);
      qc.setQueryData(["library"], updated);
      toast({ tone: "ok", title: "Album updated", msg: `${album.files.length} tracks in ${album.album || "album"}` });
      onClose();
    },
    onError: (e) => toast({ tone: "error", title: "Couldn’t update album", msg: String((e as Error)?.message ?? e) }),
  });

  const lines: TermLine[] = result
    ? Object.entries(result.providers).map(([name, status]) => ({
        tone: status === "ok" ? "ok" as const : status.startsWith("failed") ? "err" as const : "warn" as const,
        text: `[${status === "ok" ? " OK " : "----"}] ${name}: ${status}`,
      }))
    : [];

  const artOptions: ArtOption[] = result ? [
    ...(album.has_art
      ? [embeddedArtOption("keep", "Current", embThumb.data, "keep embedded art")]
      : []),
    autoArtOption("best provider art"),
    ...candidateArtOptions(result.art_candidates),
    noneArtOption("skip"),
  ] : [];

  // Pending-changes readout for the footer (always visible at the commit point).
  const rows = result ? rowsFor(result, editionDetails, editionId?.split(":")[0] ?? "") : [];
  const fieldChanges = rows.filter((row) => {
    const c = choices[row.key];
    return !!c?.include && !!c.value && c.value !== row.current;
  }).length;
  const titleChanges = trackPairs.filter(({ file, match }) => !!match && !titleExcluded[file.path]).length;
  const artLabel = artOptions.find((o) => o.id === artChoice)?.label;
  const ready = !!result && result.identity.method !== "none";

  return (
    <Drawer
      open
      title={`Clean Up — ${album.album || "Unknown Album"}`}
      subtitle={album.albumartist || "Unknown Artist"}
      onClose={onClose}
      footer={
        <div className="flex items-center justify-between gap-3">
          <PendingSummary fields={fieldChanges} tracks={titleChanges} art={artLabel} />
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="solid" disabled={!ready || apply.isPending} onClick={() => apply.mutate()}>
              {apply.isPending ? "Applying…" : `Apply to ${album.files.length} tracks`}
            </Button>
          </div>
        </div>
      }
    >
      {!result ? (
        <div className="space-y-3">
          {identify.error ? (
            <>
              <p className="font-mono text-sm text-alert">{String(identify.error)}</p>
              <Button variant="solid" disabled={identify.isPending} onClick={() => identify.mutate()}>
                Retry identify
              </Button>
            </>
          ) : (
            <Spinner label="fingerprinting + querying providers…" />
          )}
        </div>
      ) : result.identity.method === "none" ? (
        <p className="font-mono text-sm text-alert">
          No identification found — try the single-track “Find Original Album” instead.
        </p>
      ) : (
        <div className="space-y-5">
          {/* Context — how it was identified. */}
          <div>
            <p className="mb-1 font-mono text-xs text-muted">
              Identified via <b className="text-accent">{result.identity.method}</b>
              {result.identity.confidence_note && ` (${result.identity.confidence_note})`} ·{" "}
              {effTracks.length} tracks vs {album.files.length} files
            </p>
            <Terminal lines={lines} className="max-h-28 overflow-y-auto" />
          </div>

          {/* 1 · Edition (source) — drives everything below it. */}
          <section>
            <h4 className="font-display mb-1 text-sm text-text">1 · Edition — the source</h4>
            <p className="mb-2 text-xs text-muted">
              Pick the release this album is from; the fields, track titles, and art below update to match.
            </p>
            <div className="mb-2">
              <ManualSearch
                defaultArtist={album.albumartist}
                defaultAlbum={album.album}
                pending={candidates.isFetching}
                onSearch={({ artist, album: alb }) =>
                  setSearchSpec({ artist, album: alb, track_count: album.files.length })}
              />
            </div>
            {candidates.isLoading && <Spinner label="searching all providers for editions…" />}
            {candidates.data && candidates.data.length > 0 && (
              <EditionPicker
                candidates={candidates.data}
                activeId={activeId}
                expectedTracks={album.files.length}
                pending={chooseEdition.isPending}
                note={`Pick the edition matching this album (${album.files.length} tracks).`}
                onPick={(c) => chooseEdition.mutate(c)}
              />
            )}
          </section>

          {/* 2 · Album metadata — re-seeded by the edition above. */}
          <section>
            <h4 className="font-display mb-1 text-sm text-text">2 · Album metadata</h4>
            {editionDetails && (
              <p aria-live="polite" className="mb-1 text-xs text-accent">
                Fields updated from the {editionId?.split(":")[0]} edition.
              </p>
            )}
            <MetadataCompare rows={rows} choices={choices} onChange={setChoices} />
            <div className="mt-2">
              <Checkbox
                label={`Mark as compilation${result.compilation ? " (detected)" : ""}`}
                checked={markComp}
                onChange={(e) => setMarkComp(e.target.checked)}
              />
            </div>
          </section>

          {/* 3 · Track titles. */}
          <section>
            <h4 className="font-display mb-1 text-sm text-text">
              3 · Track titles <span className="text-muted">— current vs edition (check to apply)</span>
            </h4>
            <div className="max-h-60 overflow-y-auto">
              <table className="w-full font-mono text-[0.72rem]">
                <thead>
                  <tr className="border-b border-white/15 text-left text-[0.6rem] uppercase text-muted">
                    <th className="w-8 p-1" />
                    <th className="w-8 p-1">#</th>
                    <th className="p-1">Current</th>
                    <th className="p-1">Edition</th>
                  </tr>
                </thead>
                <tbody>
                  {trackPairs.map(({ file: f, match }) => {
                    const willApply = !!match && !titleExcluded[f.path];
                    return (
                      <tr key={f.path} className="border-b border-white/5">
                        <td className="p-1 text-center">
                          <input type="checkbox" className="size-3.5 accent-accent"
                            checked={willApply}
                            disabled={!match}
                            onChange={(e) => setTitleExcluded({ ...titleExcluded, [f.path]: !e.target.checked })} />
                        </td>
                        <td className="p-1 text-muted">{match?.position ?? f.tracknumber ?? "?"}</td>
                        <td className="max-w-[210px] truncate p-1 text-muted" title={f.title}>
                          {f.title || f.filename}
                        </td>
                        <td className={cx("max-w-[210px] truncate p-1",
                            !match ? "text-alert" : willApply ? "text-ok" : "text-muted")}
                            title={match?.title ?? ""}>
                          {match?.title ?? "— no match —"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {trackPairs.some((p) => !p.match) && (
              <p className="mt-1 font-mono text-[0.66rem] text-alert">
                ⚠ {trackPairs.filter((p) => !p.match).length} file(s) didn’t match a track in this
                edition — try a different edition, or fix the track title first.
              </p>
            )}
          </section>

          {/* 4 · Album art. */}
          <section>
            <h4 className="font-display mb-1 text-sm text-text">4 · Album art</h4>
            <ArtPicker options={artOptions} selectedId={artChoice} onSelect={setArtChoice} />
          </section>
        </div>
      )}
    </Drawer>
  );
}

/** Match a library file to an identified track by title (fingerprint-grade
 * matching happens upstream; this is just alignment for track numbers). */
type MatchTrack = { position: number; title: string; artist: string;
                    disc_number?: number; recording_id?: string };

function matchTrack(tracks: MatchTrack[], f: LibraryFile) {
  // foldForCompare unifies separators (, / ;) and typographic punctuation so a
  // title isn't missed just because providers disagree on the separator.
  const title = foldForCompare(f.title || f.filename.replace(/^\d+[\s\-._]+/, "").replace(/\.flac$/i, ""));
  if (!title) return null;
  let best = null, bestScore = 0;
  for (const t of tracks) {
    const tt = foldForCompare(t.title);
    let score = 0;
    if (tt === title) score = 3;
    else if (tt.includes(title) || title.includes(tt)) score = 2;
    else {
      const clean = (s: string) => s.replace(/\s*\(.*?\)\s*/g, "").trim();
      if (clean(tt) === clean(title)) score = 1;
    }
    if (score > bestScore) { bestScore = score; best = t; }
  }
  return best;
}

// ── Duplicates ────────────────────────────────────────────────────────────────

function DuplicatesView({ data }: { data: LibraryScan }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState<LibraryFile | null>(null);

  const del = useMutation({
    mutationFn: (path: string) => api.deleteLibraryFile(path),
    onSuccess: (res, path) => {
      if (!res.success) { toast({ tone: "error", title: "Delete failed", msg: res.error }); return; }
      toast({ tone: "ok", title: "Duplicate deleted", msg: path.split(/[\\/]/).pop() });
      // Optimistic local update — no full network rescan for one delete
      qc.setQueryData<LibraryScan>(["library"], (old) => {
        if (!old) return old;
        const albums = old.albums
          .map((a) => ({ ...a, files: a.files.filter((f) => f.path !== path) }))
          .filter((a) => a.files.length > 0);
        const duplicates = old.duplicates
          .map((d) => ({ ...d, copies: d.copies.filter((c) => c.path !== path) }))
          .filter((d) => d.copies.length >= 2);
        return { ...old, albums, duplicates, duplicate_count: duplicates.length,
                 total_files: old.total_files - 1 };
      });
      setConfirm(null);
    },
  });

  if (data.duplicates.length === 0) {
    return <p className="font-mono text-sm text-muted">No duplicate tracks found.</p>;
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">
        Same track title + artist found across more than one album. Keep the copy you want and delete
        the rest — each delete is confirmed first.
      </p>
      {data.duplicates.map((dup) => (
        <Panel key={`${dup.artist}|${dup.title}`}
               title={<span className="text-sm">{dup.title} <span className="text-muted">— {dup.artist}</span></span>}>
          {dup.copies.map((copy) => (
            <div key={copy.path}
                 className="flex items-center gap-3 border-b border-white/5 py-1 font-mono text-[0.78rem]">
              <span className="truncate">{copy.album || "Unknown Album"}</span>
              <span className="text-muted">{copy.is_compilation ? "Compilation" : "Studio"}</span>
              <span className="ml-auto truncate text-xs text-muted">{copy.path.split(/[\\/]/).slice(-2).join("/")}</span>
              <Button variant="alert" className="!px-2 !py-0.5 !text-[0.66rem]"
                      onClick={() => setConfirm(copy)}>
                Delete
              </Button>
            </div>
          ))}
        </Panel>
      ))}

      <Dialog open={!!confirm} title="Delete file?" onClose={() => setConfirm(null)}>
        <p className="mb-4 font-mono text-sm text-muted">{confirm?.path}</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="alert" disabled={del.isPending}
                  onClick={() => confirm && del.mutate(confirm.path)}>
            {del.isPending ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

// ── Track detail dialog with single-track reassign ────────────────────────────

function TrackDetail({ file, onClose }: { file: LibraryFile | null; onClose: () => void }) {
  const [mode, setMode] = useState<null | "reassign" | "cleanup" | "tags">(null);
  const art = useQuery({
    queryKey: ["embedded-art", file?.path],
    queryFn: () => api.embeddedArt(file!.path),
    enabled: !!file?.has_art,
  });

  if (!file) return null;
  const ROWS: [string, string][] = [
    ["Title", file.title], ["Artist", file.artist], ["Album Artist", file.albumartist],
    ["Album", file.album], ["Track", file.tracknumber], ["Disc", file.discnumber],
    ["Year", file.date], ["Genre", file.genre],
    ["MB Album ID", file.musicbrainz_albumid],
  ];

  return (
    <Drawer open title={file.title || file.filename}
            subtitle={`${file.artist || "?"} — ${file.album || "?"}`} onClose={onClose}>
      <div className="flex gap-4">
        <div className="size-28 shrink-0 overflow-hidden rounded-[var(--radius)] border border-border bg-surface-2">
          {art.data?.success && art.data.data ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`data:image/jpeg;base64,${art.data.data}`} alt="" className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full items-center justify-center font-mono text-xs text-muted">no art</div>
          )}
        </div>
        <table className="w-full font-mono text-[0.74rem]">
          <tbody>
            {ROWS.map(([label, value]) => (
              <tr key={label} className="border-b border-white/5">
                <td className="py-0.5 pr-3 text-muted">{label}</td>
                <td className="max-w-[420px] truncate py-0.5" title={value}>{value || "—"}</td>
              </tr>
            ))}
            <tr>
              <td className="py-0.5 pr-3 text-muted">Completeness</td>
              <td className={cx("py-0.5",
                file.completeness >= 90 ? "text-ok" : "text-accent-2")}>
                {file.completeness}% {file.missing_fields.length > 0 && `(missing: ${file.missing_fields.join(", ")})`}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-3 break-all font-mono text-[0.66rem] text-muted">{file.path}</p>

      {/* Pick what to do with this track — one dominant action, one secondary. */}
      {mode === null && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="solid" onClick={() => setMode("cleanup")}>
            Auto Clean Up
          </Button>
          <Button variant="outline" onClick={() => setMode("reassign")}>
            Find Original Album…
          </Button>
          <Button variant="ghost" onClick={() => setMode("tags")}>
            Edit Tags…
          </Button>
        </div>
      )}
      {mode === "cleanup" && <TrackAutoCleanup file={file} onDone={onClose} />}
      {mode === "reassign" && <TrackReassign file={file} onDone={onClose} />}
      {mode === "tags" && <TrackRawTags file={file} onDone={onClose} />}
    </Drawer>
  );
}

/** Advanced raw-tag editor: edit/add/delete arbitrary Vorbis comments on one
 * file. Renaming a key moves its value; clearing a key deletes it. Cover art is
 * managed separately and never shown here. */
function TrackRawTags({ file, onDone }: { file: LibraryFile; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  type Row = { id: number; key: string; value: string };
  const idRef = useRef(0);
  const [rows, setRows] = useState<Row[]>(() =>
    Object.entries(file.all_tags || {})
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => ({ id: idRef.current++, key: k,
                          value: Array.isArray(v) ? v.join("; ") : String(v) })));

  const origKeys = useMemo(
    () => Object.keys(file.all_tags || {}).map((k) => k.toUpperCase()),
    [file.all_tags]);

  const setRow = (id: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const removeRow = (id: number) => setRows((rs) => rs.filter((r) => r.id !== id));
  const addRow = () => setRows((rs) => [...rs, { id: idRef.current++, key: "", value: "" }]);

  const save = useMutation({
    mutationFn: () => {
      const changes: Record<string, string | null> = {};
      const nextKeys = new Set(rows.map((r) => r.key.trim().toUpperCase()).filter(Boolean));
      // Any original key no longer present (deleted or renamed away) → delete.
      for (const k of origKeys) if (!nextKeys.has(k)) changes[k] = null;
      // Every present row → set its value (idempotent for unchanged rows).
      for (const r of rows) {
        const k = r.key.trim().toUpperCase();
        if (k && k !== "METADATA_BLOCK_PICTURE") changes[k] = r.value;
      }
      return api.updateTrackTags(file.path, changes);
    },
    onSuccess: async () => {
      const updated = await api.rescanLibraryPaths([file.path]);
      qc.setQueryData(["library"], updated);
      toast({ tone: "ok", title: "Tags saved", msg: file.title || file.filename });
      onDone();
    },
    onError: (e) => toast({ tone: "error", title: "Couldn’t save tags",
                            msg: String((e as Error)?.message ?? e) }),
  });

  return (
    <div className="mt-4 space-y-2">
      <p className="font-mono text-[0.68rem] text-muted">
        Advanced: edit raw FLAC tags directly. Renaming a key moves its value;
        clearing a key deletes it. Cover art is managed separately.
      </p>
      <div className="max-h-72 space-y-1 overflow-y-auto">
        {rows.map((r) => (
          <div key={r.id} className="flex items-center gap-1.5">
            <Input value={r.key} placeholder="TAG"
                   onChange={(e) => setRow(r.id, { key: e.target.value })}
                   className="w-44 px-2 py-1 text-[0.72rem] uppercase" />
            <Input value={r.value} placeholder="value"
                   onChange={(e) => setRow(r.id, { value: e.target.value })}
                   className="flex-1 px-2 py-1 text-[0.72rem]" />
            <button onClick={() => removeRow(r.id)} title="Delete tag"
                    className="px-2 text-muted hover:text-alert">✕</button>
          </div>
        ))}
        {rows.length === 0 && (
          <p className="font-mono text-[0.7rem] text-muted">No tags. Add one below.</p>
        )}
      </div>
      <div className="flex gap-2">
        <Button variant="ghost" onClick={addRow}>+ Add tag</Button>
        <Button variant="solid" disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save Tags"}
        </Button>
      </div>
    </div>
  );
}

/** Single-track Auto Clean Up: fingerprint THIS file, fill in whatever is
 * missing. Defaults check only empty fields — existing values stay put
 * unless you opt in. */
function TrackAutoCleanup({ file, onDone }: { file: LibraryFile; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [result, setResult] = useState<IdentifyResult | null>(null);
  const [choices, setChoices] = useState<Choices>({});

  const identify = useMutation({
    mutationFn: () => api.identify({
      artist: normalizeArtistForSearch(file.artist || file.albumartist),
      album: file.album,
      file_paths: [file.path],
    }),
    onSuccess: (r) => {
      setResult(r);
      const rows = buildTrackRows(r, file);
      const defaults = defaultChoices(rows);
      // Fill-missing semantics: only pre-check fields that are currently empty
      for (const row of rows) {
        if (row.current && defaults[row.key]) defaults[row.key].include = false;
      }
      setChoices(defaults);
    },
  });

  // Auto-identify on open — choosing "Auto Clean Up" is the intent; don't make
  // the user click again to start the fingerprint + provider lookup.
  const autoRan = useRef(false);
  useEffect(() => {
    if (!autoRan.current && identify.isIdle) { autoRan.current = true; identify.mutate(); }
  }, [identify]);

  const apply = useMutation({
    mutationFn: () => {
      if (!result) throw new Error("not identified");
      const match = matchTrack(result.tracks, file);
      const pick = (key: string, fallback: string) =>
        choices[key]?.include ? choices[key].value : fallback;

      const metadata: Record<string, string> = {
        // Path fields always present (fallback = current value)
        title: pick("title", file.title),
        artist: pick("artist", file.artist),
        albumartist: pick("albumartist", file.albumartist),
        album: pick("album", file.album),
        date: pick("date", file.date),
        tracknumber: file.tracknumber || String(match?.position ?? "1"),
        discnumber: file.discnumber || String(match?.disc_number ?? "1"),
      };
      if (choices.genre?.include) metadata.genre = choices.genre.value;
      if (result.ids.musicbrainz_release) metadata.musicbrainz_albumid = result.ids.musicbrainz_release;
      if (match?.recording_id) metadata.musicbrainz_trackid = match.recording_id;

      return api.reassignTrack({
        path: file.path, metadata, move_file: true, art_release_id: null,
      });
    },
    onSuccess: async (res) => {
      if (res.success) {
        const updated = await api.rescanLibraryPaths([file.path, res.new_path].filter(Boolean));
        qc.setQueryData(["library"], updated);
        toast({ tone: "ok", title: "Track cleaned up", msg: file.title || file.filename });
        onDone();
      }
    },
  });

  const rows = result ? buildTrackRows(result, file) : [];

  return (
    <div className="mt-3 space-y-3 border-t border-white/10 pt-3">
      {!result ? (
        <div className="flex items-center gap-3">
          {identify.error ? (
            <>
              <span className="font-mono text-xs text-alert">{String(identify.error)}</span>
              <Button variant="solid" disabled={identify.isPending} onClick={() => identify.mutate()}>
                Retry
              </Button>
            </>
          ) : (
            <Spinner label="fingerprint + providers…" />
          )}
        </div>
      ) : result.identity.method === "none" ? (
        <p className="font-mono text-sm text-alert">
          No match found — try “Find Original Album” with adjusted search terms.
        </p>
      ) : (
        <>
          <p className="font-mono text-xs text-muted">
            Identified via <b className="text-accent">{result.identity.method}</b>
            {result.identity.confidence_note && ` (${result.identity.confidence_note})`} —
            empty fields are pre-checked; check others to overwrite.
          </p>
          <MetadataCompare rows={rows} choices={choices} onChange={setChoices} />
          <div className="flex gap-2">
            <Button variant="solid" disabled={apply.isPending} onClick={() => apply.mutate()}>
              {apply.isPending ? "Applying…" : "Apply"}
            </Button>
            {apply.data && !apply.data.success && (
              <span className="font-mono text-xs text-alert">{apply.data.error}</span>
            )}
            {apply.error && <span className="font-mono text-xs text-alert">{String(apply.error)}</span>}
          </div>
        </>
      )}
    </div>
  );
}

function buildTrackRows(r: IdentifyResult, file: LibraryFile): CompareRow[] {
  const match = matchTrack(r.tracks, file);
  const trackField = (value?: string): FieldValue | undefined =>
    value ? { value, source: r.track_source || "musicbrainz",
              candidates: [{ value, source: r.track_source || "musicbrainz" }] } : undefined;
  return [
    { key: "title", label: "Title", current: file.title, merged: trackField(match?.title) },
    { key: "artist", label: "Artist", current: file.artist, merged: trackField(match?.artist) },
    { key: "albumartist", label: "Album Artist", current: file.albumartist, merged: r.fields.artist },
    { key: "album", label: "Album", current: file.album, merged: r.fields.title },
    { key: "date", label: "Date", current: file.date, merged: r.fields.original_date },
    { key: "genre", label: "Genre", current: file.genre, merged: r.fields.genre },
  ];
}

/** Single-track reassign: multi-provider edition candidates for the track's
 * album; the user picks the exact edition, the file is aligned to a track
 * within it, then a per-field diff preview before applying. Album/edition-based
 * so bonus/expanded-edition tracks resolve (MB track search alone misses them). */
function TrackReassign({ file, onDone }: { file: LibraryFile; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  // Use the SONG's artist, not the album artist: the point of this lookup is to
  // move a track off a compilation (often "Various Artists") to its original
  // album by the actual performer.
  const [artist, setArtist] = useState(normalizeArtistForSearch(file.artist || file.albumartist));
  // Default blank: "find the original album" works best as a song search.
  // The field stays editable for when the user knows the album name.
  const [album, setAlbum] = useState("");
  const [title, setTitle] = useState(file.title);  // used to align within the edition
  const [selected, setSelected] = useState<ReleaseCandidate | null>(null);
  const [metadata, setMetadata] = useState<Record<string, string> | null>(null);
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  // Default to keeping whatever art is already embedded, per "embedded first".
  const [artChoice, setArtChoice] = useState<string>(file.has_art ? "keep" : "auto");

  // Album given → edition search; album blank → song search (albums the track
  // appears on), so the user can find a song's original album without the name.
  const search = useMutation({
    mutationFn: () => api.releaseCandidates({ artist, album, title }),
  });

  // Thumbnail of the art already on this file (the "Current" / first option).
  const embThumb = useQuery({
    queryKey: ["embedded-art", file.path],
    queryFn: () => api.embeddedArt(file.path),
    enabled: file.has_art,
    staleTime: Infinity,
  });

  // Multi-provider art candidates for the chosen album — same engine Quick
  // Clean Up uses, so the art choices match. Keyed by artist+album so flipping
  // between candidates reuses the cache.
  const artCands = useQuery({
    queryKey: ["art-candidates", selected?.artist, selected?.title],
    queryFn: () => api.identify({ artist: selected!.artist, album: selected!.title }),
    enabled: !!selected,
    staleTime: Infinity,
  });

  const choose = useMutation({
    mutationFn: async (cand: ReleaseCandidate) => {
      const details = await api.getRelease(cand.id);
      if (details.error) throw new Error(details.error);
      // Align this file to a track in the chosen edition by title (separator-
      // and punctuation-insensitive, so , vs / vs ; don't break the match).
      let match = null;
      for (const disc of details.discs) {
        for (const t of disc.tracks) {
          const a = foldForCompare(t.title), b = foldForCompare(title || "");
          if (a && b && (a === b || a.includes(b) || b.includes(a))) {
            match = { ...t, disc_number: disc.position, track_total: disc.tracks.length };
            break;
          }
        }
        if (match) break;
      }
      const meta: Record<string, string> = {
        title: match?.title ?? title,
        artist: match?.artist || details.artist || file.artist,
        albumartist: details.artist ?? "",
        album: details.title ?? "",
        tracknumber: String(match?.position ?? file.tracknumber ?? "1"),
        discnumber: String(match?.disc_number ?? 1),
        ...(match?.track_total ? { tracktotal: String(match.track_total) } : {}),
        date: cand.date || details.first_release_date || details.date || "",
        genre: details.genre ?? "",
        ...(details.compilation ? { compilation: "1" } : {}),
        // Only stamp a MusicBrainz ID when the edition actually came from MB.
        ...(cand.provider === "musicbrainz" ? {
          musicbrainz_albumid: cand.id,
          musicbrainz_trackid: match?.recording_id ?? "",
        } : {}),
      };
      const preview = await api.reassignPreview(file.path, meta);
      return { cand, meta, preview, matched: !!match };
    },
    onSuccess: ({ cand, meta, preview }) => {
      setSelected(cand);
      setMetadata(meta);
      const inc: Record<string, boolean> = {};
      for (const c of preview.changes) inc[c.key.toLowerCase()] = true;
      setIncluded(inc);
    },
  });

  const apply = useMutation({
    mutationFn: () => {
      const chosen: Record<string, string> = {};
      for (const [key, value] of Object.entries(metadata!)) {
        // ID fields ride along; visible fields respect the checkboxes
        if (key.startsWith("musicbrainz_") || included[key] !== false) chosen[key] = value;
      }
      return api.reassignTrack({
        path: file.path, metadata: chosen, move_file: true,
        // keep = leave embedded art untouched; none = skip; auto = the chosen
        // release's art; url: = a specific provider image.
        art_release_id: artChoice === "keep" ? "__keep__"
          : artChoice === "none" ? "__none__"
          : artChoice === "auto" ? (selected?.id ?? "__keep__")
          : null,
        art_url: artChoice.startsWith("url:") ? artChoice.slice(4) : null,
      });
    },
    onSuccess: async (res) => {
      if (res.success) {
        const updated = await api.rescanLibraryPaths([file.path, res.new_path].filter(Boolean));
        qc.setQueryData(["library"], updated);
        toast({ tone: "ok", title: "Track reassigned", msg: `${selected?.title ?? "album"} · ${file.title || file.filename}` });
        onDone();
      } else {
        toast({ tone: "error", title: "Reassign failed", msg: res.error });
      }
    },
  });

  const preview = choose.data?.preview;

  return (
    <div className="mt-3 space-y-3 border-t border-white/10 pt-3">
      <div className="flex items-end gap-2">
        <Field label="Album Artist" className="flex-1">
          <Input value={artist} onChange={(e) => setArtist(e.target.value)} />
        </Field>
        <Field label="Album (blank = search by song)" className="flex-1">
          <Input value={album} onChange={(e) => setAlbum(e.target.value)} placeholder="leave blank to find by song" />
        </Field>
        <Field label="Song Title (to match)" className="flex-1">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Button variant="solid" disabled={search.isPending || !artist || (!album && !title)}
                onClick={() => search.mutate()}>
          {search.isPending ? "Searching…" : "Search"}
        </Button>
      </div>

      {search.data && search.data.length === 0 && (
        <p className="font-mono text-xs text-muted">
          No matching {album ? "editions" : "albums"} found. Adjust the search terms.
        </p>
      )}

      {search.data && search.data.length > 0 && (
        <EditionPicker
          candidates={search.data}
          activeId={selected ? `${selected.provider}:${selected.id}` : null}
          pending={choose.isPending}
          note="Click an album to preview its changes below; the list stays so you can compare. Pick another any time."
          onPick={(c) => choose.mutate(c)}
        />
      )}
      {choose.error && <p className="font-mono text-xs text-alert">{String(choose.error)}</p>}

      {preview && metadata && (
        <>
          <table className="w-full font-mono text-[0.74rem]">
            <thead>
              <tr className="border-b border-white/15 text-left text-[0.62rem] uppercase text-muted">
                <th className="w-8 p-1" /><th className="p-1">Field</th>
                <th className="p-1">Current</th><th className="p-1">New</th>
              </tr>
            </thead>
            <tbody>
              {preview.changes.map((c) => (
                <tr key={c.key} className="border-b border-white/5">
                  <td className="p-1 text-center">
                    <input type="checkbox" className="size-3.5 accent-accent"
                      checked={included[c.key.toLowerCase()] !== false}
                      onChange={(e) => setIncluded({ ...included, [c.key.toLowerCase()]: e.target.checked })} />
                  </td>
                  <td className="p-1">{c.field}</td>
                  <td className="max-w-[200px] truncate p-1 text-muted" title={c.old}>{c.old || "—"}</td>
                  <td className="max-w-[200px] truncate p-1 text-ok" title={c.new}>{c.new}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.path_changed && (
            <p className="break-all font-mono text-[0.66rem] text-muted">
              → {preview.new_path}
            </p>
          )}
          <div>
            <h4 className="font-display mb-1 text-xs text-accent-2">Album Art</h4>
            <ArtPicker
              options={[
                ...(file.has_art
                  ? [embeddedArtOption("keep", "Current", embThumb.data, "keep embedded art")]
                  : []),
                autoArtOption("best provider art"),
                ...candidateArtOptions(artCands.data?.art_candidates),
                noneArtOption("skip"),
              ]}
              selectedId={artChoice}
              onSelect={setArtChoice}
            />
          </div>
          <div className="flex items-center gap-2">
            <Button variant="solid" disabled={apply.isPending} onClick={() => apply.mutate()}>
              {apply.isPending ? "Applying…" : `Apply Reassign — ${selected?.title ?? ""}`}
            </Button>
            {apply.data && !apply.data.success && (
              <span className="font-mono text-xs text-alert">{apply.data.error}</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
