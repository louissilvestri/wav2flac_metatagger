"use client";

/** Library: scan, stats, filters, albums, duplicates, Quick Clean Up.
 * Quick Clean Up uses the same MetadataCompare/ArtPicker as the Convert
 * wizard, fed by the aggregator (fingerprints work even on blank tags).
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, LibraryAlbum, LibraryFile, LibraryScan, IdentifyResult, ReleaseCandidate, ReleaseDetails, FieldValue } from "@/lib/api";
import { foldForCompare, normalizeArtistForSearch } from "@/lib/text";
import { Panel, Button, Input, Field, StatCard, Spinner, Tag, Dialog, Terminal, TermLine, cx } from "@/components/ui";
import { MetadataCompare, CompareRow, Choices, defaultChoices, asText } from "@/components/MetadataCompare";
import { ArtPicker, ArtOption } from "@/components/ArtPicker";

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
        <h1 className="font-display text-2xl text-accent glow-accent">Library</h1>
        <Button variant="solid" disabled={scan.isFetching} onClick={() => scan.refetch()}>
          {scan.isFetching ? "Scanning…" : data ? "Rescan" : "Scan Library"}
        </Button>
      </header>

      {scan.isFetching && <Spinner label="reading FLAC tags across the network share…" />}
      {data?.error && <p className="font-mono text-sm text-alert">{data.error}</p>}

      {data && !data.error && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            <StatCard label="Tracks" value={data.total_files}
              onClick={() => setFilter("all")} active={filter === "all"} />
            <StatCard label="Albums" value={data.albums.length}
              onClick={() => setFilter("all")} />
            <StatCard label="Compilation Trks" value={data.compilation_tracks}
              onClick={() => setFilter("compilations")} active={filter === "compilations"} />
            <StatCard label="Incomplete" value={data.incomplete_tracks}
              onClick={() => setFilter("incomplete")} active={filter === "incomplete"} />
            <StatCard label="Duplicates" value={data.duplicate_count}
              onClick={() => setFilter("duplicates")} active={filter === "duplicates"} />
          </div>

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

  return (
    <div className="chamfer border border-accent/20 bg-surface">
      <button
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

          <div className="mt-2">
            <Button variant="outline" onClick={() => setCleanup(!cleanup)}>
              Quick Clean Up
            </Button>
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
  const [result, setResult] = useState<IdentifyResult | null>(null);
  const [choices, setChoices] = useState<Choices>({});
  const [artChoice, setArtChoice] = useState<string>(album.has_art ? "keep" : "auto");
  // Edition picker: chosen provider+release and its fetched tracklist.
  const [editionId, setEditionId] = useState<string | null>(null);
  const [editionDetails, setEditionDetails] = useState<ReleaseDetails | null>(null);

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
      setChoices(defaultChoices(rowsFor(r)));
      setEditionId(null);          // a fresh identify invalidates any chosen edition
      setEditionDetails(null);
    },
  });

  // Candidate editions from every provider (track count = this album's files).
  const candidates = useQuery({
    queryKey: ["release-candidates", album.albumartist, album.album, album.files.length],
    queryFn: () => api.releaseCandidates({
      artist: album.albumartist, album: album.album, track_count: album.files.length }),
    enabled: !!result,
    staleTime: Infinity,
  });

  const chooseEdition = useMutation({
    mutationFn: (c: ReleaseCandidate) => api.getRelease(c.id),
    onSuccess: (details, c) => {
      if (!details.error) { setEditionId(`${c.provider}:${c.id}`); setEditionDetails(details); }
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

  const rowsFor = (r: IdentifyResult): CompareRow[] => [
    { key: "artist", label: "Album Artist", current: album.albumartist, merged: r.fields.artist },
    { key: "title", label: "Album", current: album.album, merged: r.fields.title },
    { key: "original_date", label: "Date", current: album.date, merged: r.fields.original_date },
    { key: "genre", label: "Genre", current: album.genre, merged: r.fields.genre },
    { key: "label", label: "Label", current: album.label, merged: r.fields.label },
  ];

  const apply = useMutation({
    mutationFn: () => {
      if (!result) throw new Error("no identification");
      const pick = (key: string, fallback: string) =>
        choices[key]?.include ? choices[key].value : fallback;

      // Only stamp a MusicBrainz album ID when the active edition is from MB.
      const mbAlbumId = editionDetails
        ? (editionId?.startsWith("musicbrainz:") ? editionDetails.id : "")
        : (result.ids.musicbrainz_release ?? "");

      const meta: Record<string, string> = {
        // Path-building fields are ALWAYS sent: unchecked = keep the current
        // value, never blank (a blank album becomes "Unknown Album" on disk)
        albumartist: pick("artist", album.albumartist),
        album: pick("title", album.album),
        date: pick("original_date", album.date),
        musicbrainz_albumid: mbAlbumId,
        disctotal: String(Math.max(1, ...effTracks.map((t) => t.disc_number || 1))),
      };
      // Non-path fields: only send when checked (merge keeps existing tags)
      for (const key of ["genre", "label"] as const) {
        if (choices[key]?.include) meta[key] = choices[key].value;
      }

      // Per-disc track counts from the chosen tracklist → TRACKTOTAL. Falls
      // back to the album's file count so even unmatched tracks get a total.
      const perDisc: Record<number, number> = {};
      for (const t of effTracks) perDisc[t.disc_number || 1] = (perDisc[t.disc_number || 1] || 0) + 1;

      const tracks = album.files.map((f) => {
        const match = matchTrack(effTracks, f);
        const disc = match?.disc_number ?? Number(f.discnumber || "1") ?? 1;
        const tracktotal = perDisc[disc] || effTracks.length || album.files.length;
        return {
          path: f.path,
          title: match?.title ?? (f.title || f.filename.replace(/^\d+[\s\-._]+/, "").replace(/\.flac$/i, "")),
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
      onClose();
    },
  });

  const lines: TermLine[] = result
    ? Object.entries(result.providers).map(([name, status]) => ({
        tone: status === "ok" ? "ok" as const : status.startsWith("failed") ? "err" as const : "warn" as const,
        text: `[${status === "ok" ? " OK " : "----"}] ${name}: ${status}`,
      }))
    : [];

  const artOptions: ArtOption[] = result ? [
    ...(album.has_art ? [{
      id: "keep",
      label: "Current",
      sublabel: embThumb.data?.success
        ? `${embThumb.data.width}×${embThumb.data.height}`
        : "keep embedded art",
      thumbSrc: embThumb.data?.success && embThumb.data.data
        ? `data:image/jpeg;base64,${embThumb.data.data}`
        : undefined,
    }] : []),
    { id: "auto", label: "Auto", sublabel: "best provider art" },
    ...result.art_candidates.map((a) => ({
      id: `url:${a.url}`,
      label: a.source,
      sublabel: a.width ? `${a.width}×${a.height}` : (a.likes != null ? `${a.likes} likes` : ""),
      thumbSrc: a.thumb_url || a.url,
    })),
    { id: "none", label: "No Art", sublabel: "skip" },
  ] : [];

  return (
    <div className="chamfer mt-2 border border-accent/30 bg-surface-2 p-3">
      {!result ? (
        <div className="flex items-center gap-3">
          <Button variant="solid" disabled={identify.isPending} onClick={() => identify.mutate()}>
            {identify.isPending ? "Identifying…" : "Identify Album"}
          </Button>
          {identify.isPending && <Spinner label="fingerprinting + querying providers…" />}
          {identify.error && <span className="font-mono text-xs text-alert">{String(identify.error)}</span>}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      ) : (
        <div className="space-y-3">
          <Terminal lines={lines} className="max-h-36 overflow-y-auto" />
          {result.identity.method === "none" ? (
            <p className="font-mono text-sm text-alert">No identification found.</p>
          ) : (
            <>
              <p className="font-mono text-xs text-muted">
                Identified via <b className="text-accent">{result.identity.method}</b>
                {result.identity.confidence_note && ` (${result.identity.confidence_note})`} ·{" "}
                {effTracks.length} tracks vs {album.files.length} files
              </p>
              <MetadataCompare rows={rowsFor(result)} choices={choices} onChange={setChoices} />

              <div>
                <h4 className="font-display mb-1 text-xs text-accent-2">Edition</h4>
                {candidates.isLoading && <Spinner label="searching all providers for editions…" />}
                {candidates.data && candidates.data.length > 0 && (
                  <div className="max-h-44 space-y-1 overflow-y-auto">
                    <p className="font-mono text-[0.68rem] text-muted">
                      Pick the edition matching this album ({album.files.length} tracks).
                    </p>
                    {candidates.data.map((c) => {
                      const key = `${c.provider}:${c.id}`;
                      const active = key === activeId;
                      const countMatches = c.track_count > 0 && c.track_count === album.files.length;
                      return (
                        <button
                          key={key}
                          disabled={chooseEdition.isPending}
                          onClick={() => chooseEdition.mutate(c)}
                          className={cx(
                            "flex w-full cursor-pointer items-center gap-2 border px-3 py-1.5 text-left font-mono text-[0.72rem]",
                            "transition-colors hover:border-accent/60",
                            active ? "border-accent box-glow" : "border-white/10",
                          )}
                        >
                          <Tag tone={c.provider === "musicbrainz" ? "ok" : "warn"}>{c.provider}</Tag>
                          <span className={cx("tabular-nums", countMatches ? "text-ok" : "text-muted")}>
                            {c.track_count > 0 ? `${c.track_count} trk` : "? trk"}
                          </span>
                          <span className="text-muted">{c.date || "—"}</span>
                          {c.country && <span className="text-muted">{c.country}</span>}
                          {c.format && <span className="truncate text-accent-2">{c.format}</span>}
                          <span className="ml-auto flex items-center gap-1.5">
                            {c.recommended && <Tag tone="ok">Recommended</Tag>}
                            {active && <span className="text-accent">●</span>}
                          </span>
                        </button>
                      );
                    })}
                    {chooseEdition.isPending && <Spinner label="loading edition tracklist…" />}
                  </div>
                )}
              </div>

              <div>
                <h4 className="font-display mb-1 text-xs text-accent-2">
                  Tracks — your file → edition
                </h4>
                <div className="max-h-60 overflow-y-auto">
                  <table className="w-full font-mono text-[0.72rem]">
                    <thead>
                      <tr className="border-b border-white/15 text-left text-[0.6rem] uppercase text-muted">
                        <th className="w-8 p-1">#</th>
                        <th className="p-1">Your file</th>
                        <th className="p-1">Edition track</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trackPairs.map(({ file: f, match }) => (
                        <tr key={f.path} className="border-b border-white/5">
                          <td className="p-1 text-muted">{match?.position ?? f.tracknumber ?? "?"}</td>
                          <td className="max-w-[230px] truncate p-1 text-muted" title={f.title}>
                            {f.title || f.filename}
                          </td>
                          <td className={cx("max-w-[230px] truncate p-1", match ? "text-ok" : "text-alert")}
                              title={match?.title ?? ""}>
                            {match?.title ?? "— no match —"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {trackPairs.some((p) => !p.match) && (
                  <p className="mt-1 font-mono text-[0.66rem] text-alert">
                    ⚠ {trackPairs.filter((p) => !p.match).length} file(s) didn’t match a track in this
                    edition — try a different edition, or fix the track title first.
                  </p>
                )}
              </div>

              <div>
                <h4 className="font-display mb-1 text-xs text-accent-2">Album Art</h4>
                <ArtPicker options={artOptions} selectedId={artChoice} onSelect={setArtChoice} />
              </div>
              <div className="flex gap-2">
                <Button variant="solid" disabled={apply.isPending} onClick={() => apply.mutate()}>
                  {apply.isPending ? "Applying…" : `Apply to ${album.files.length} tracks`}
                </Button>
                <Button variant="ghost" onClick={onClose}>Cancel</Button>
                {apply.error && <span className="font-mono text-xs text-alert">{String(apply.error)}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Match a library file to an identified track by title (fingerprint-grade
 * matching happens upstream; this is just alignment for track numbers). */
type MatchTrack = { position: number; title: string; artist: string;
                    disc_number?: number; recording_id?: string };

function matchTrack(tracks: MatchTrack[], f: LibraryFile) {
  const title = (f.title || f.filename.replace(/^\d+[\s\-._]+/, "").replace(/\.flac$/i, "")).toLowerCase().trim();
  if (!title) return null;
  let best = null, bestScore = 0;
  for (const t of tracks) {
    const tt = t.title.toLowerCase().trim();
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
  const [confirm, setConfirm] = useState<LibraryFile | null>(null);

  const del = useMutation({
    mutationFn: (path: string) => api.deleteLibraryFile(path),
    onSuccess: (res, path) => {
      if (!res.success) return;
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
  const [mode, setMode] = useState<null | "reassign" | "cleanup">(null);
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
    <Dialog open wide title={file.title || file.filename} onClose={onClose}>
      <div className="flex gap-4">
        <div className="size-28 shrink-0 overflow-hidden border border-white/15 bg-[#05080b]">
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

      {mode === null && (
        <div className="mt-3 flex gap-2">
          <Button variant="solid" onClick={() => setMode("cleanup")}>
            Auto Clean Up
          </Button>
          <Button variant="outline" onClick={() => setMode("reassign")}>
            Find Original Album…
          </Button>
        </div>
      )}
      {mode === "cleanup" && <TrackAutoCleanup file={file} onDone={onClose} />}
      {mode === "reassign" && <TrackReassign file={file} onDone={onClose} />}
    </Dialog>
  );
}

/** Single-track Auto Clean Up: fingerprint THIS file, fill in whatever is
 * missing. Defaults check only empty fields — existing values stay put
 * unless you opt in. */
function TrackAutoCleanup({ file, onDone }: { file: LibraryFile; onDone: () => void }) {
  const qc = useQueryClient();
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
        onDone();
      }
    },
  });

  const rows = result ? buildTrackRows(result, file) : [];

  return (
    <div className="mt-3 space-y-3 border-t border-white/10 pt-3">
      {!result ? (
        <div className="flex items-center gap-3">
          <Button variant="solid" disabled={identify.isPending} onClick={() => identify.mutate()}>
            {identify.isPending ? "Fingerprinting…" : "Identify This Track"}
          </Button>
          {identify.isPending && <Spinner label="fingerprint + providers…" />}
          {identify.error && <span className="font-mono text-xs text-alert">{String(identify.error)}</span>}
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
  const [artist, setArtist] = useState(normalizeArtistForSearch(file.albumartist || file.artist));
  const [album, setAlbum] = useState(file.album);
  const [title, setTitle] = useState(file.title);  // used to align within the edition
  const [selected, setSelected] = useState<ReleaseCandidate | null>(null);
  const [metadata, setMetadata] = useState<Record<string, string> | null>(null);
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  // Default to keeping whatever art is already embedded, per "embedded first".
  const [artChoice, setArtChoice] = useState<string>(file.has_art ? "keep" : "release");

  const search = useMutation({
    mutationFn: () => api.releaseCandidates({ artist, album }),
  });

  // Thumbnail of the art already on this file (the "Current" / first option).
  const embThumb = useQuery({
    queryKey: ["embedded-art", file.path],
    queryFn: () => api.embeddedArt(file.path),
    enabled: file.has_art,
    staleTime: Infinity,
  });

  // Thumbnail of the chosen edition's art (only once a candidate is selected).
  const relArt = useQuery({
    queryKey: ["release-art", selected?.id],
    queryFn: () => api.getReleaseArt(selected!.id),
    enabled: !!selected?.id,
    staleTime: Infinity,
  });

  const choose = useMutation({
    mutationFn: async (cand: ReleaseCandidate) => {
      const details = await api.getRelease(cand.id);
      if (details.error) throw new Error(details.error);
      // Align this file to a track in the chosen edition by title
      let match = null;
      for (const disc of details.discs) {
        for (const t of disc.tracks) {
          const a = t.title.toLowerCase().trim(), b = (title || "").toLowerCase().trim();
          if (a === b || a.includes(b) || b.includes(a)) {
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
        // keep = leave embedded art untouched; release = pull the chosen
        // album's art; none = explicitly skip.
        art_release_id: artChoice === "keep" ? "__keep__"
          : artChoice === "none" ? "__none__"
          : (selected?.id ?? "__keep__"),
      });
    },
    onSuccess: async (res) => {
      if (res.success) {
        const updated = await api.rescanLibraryPaths([file.path, res.new_path].filter(Boolean));
        qc.setQueryData(["library"], updated);
        onDone();
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
        <Field label="Album" className="flex-1">
          <Input value={album} onChange={(e) => setAlbum(e.target.value)} />
        </Field>
        <Field label="Track Title (to match)" className="flex-1">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Button variant="solid" disabled={search.isPending || !artist || !album}
                onClick={() => search.mutate()}>
          {search.isPending ? "Searching…" : "Search"}
        </Button>
      </div>

      {search.data && search.data.length === 0 && (
        <p className="font-mono text-xs text-muted">No matching editions found. Adjust the search terms.</p>
      )}

      {search.data && search.data.length > 0 && !preview && (
        <div className="max-h-56 space-y-1 overflow-y-auto">
          <p className="font-mono text-[0.68rem] text-muted">
            Pick the edition that contains this track (track count shown when known).
          </p>
          {search.data.map((c) => (
            <button
              key={`${c.provider}:${c.id}`}
              disabled={choose.isPending}
              onClick={() => choose.mutate(c)}
              className={cx(
                "flex w-full cursor-pointer items-center gap-2 border px-3 py-1.5 text-left font-mono text-[0.72rem]",
                "transition-colors hover:border-accent/60",
                c.recommended ? "border-ok/50 bg-ok/5" : "border-white/10",
              )}
            >
              <Tag tone={c.provider === "musicbrainz" ? "ok" : "warn"}>{c.provider}</Tag>
              <span className="tabular-nums text-muted">
                {c.track_count > 0 ? `${c.track_count} trk` : "? trk"}
              </span>
              <span className="text-muted">{c.date || "—"}</span>
              {c.country && <span className="text-muted">{c.country}</span>}
              {c.format && <span className="truncate text-accent-2">{c.format}</span>}
              {c.recommended && <Tag tone="ok">Recommended</Tag>}
            </button>
          ))}
          {choose.isPending && <Spinner label="loading edition + building preview…" />}
        </div>
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
                    <input type="checkbox" className="size-3.5 accent-[#22d3ee]"
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
                ...(file.has_art ? [{
                  id: "keep",
                  label: "Current",
                  sublabel: embThumb.data?.success
                    ? `${embThumb.data.width}×${embThumb.data.height}`
                    : "keep embedded art",
                  thumbSrc: embThumb.data?.success && embThumb.data.data
                    ? `data:image/jpeg;base64,${embThumb.data.data}`
                    : undefined,
                }] : []),
                {
                  id: "release",
                  label: selected?.title || "From album",
                  sublabel: relArt.data?.success
                    ? `${relArt.data.width}×${relArt.data.height}`
                    : "this album's art",
                  thumbSrc: relArt.data?.success && relArt.data.data
                    ? `data:image/jpeg;base64,${relArt.data.data}`
                    : undefined,
                },
                { id: "none", label: "No Art", sublabel: "skip" },
              ]}
              selectedId={artChoice}
              onSelect={setArtChoice}
            />
          </div>
          <div className="flex gap-2">
            <Button variant="solid" disabled={apply.isPending} onClick={() => apply.mutate()}>
              {apply.isPending ? "Applying…" : "Apply Reassign"}
            </Button>
            <Button variant="ghost" onClick={() => { setSelected(null); setMetadata(null); choose.reset(); }}>
              ← Candidates
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
