"use client";

/** Library: scan, stats, filters, albums, duplicates, Quick Clean Up.
 * Quick Clean Up uses the same MetadataCompare/ArtPicker as the Convert
 * wizard, fed by the aggregator (fingerprints work even on blank tags).
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, LibraryAlbum, LibraryFile, LibraryScan, IdentifyResult } from "@/lib/api";
import { Panel, Button, Input, StatCard, Spinner, Tag, Dialog, Terminal, TermLine, cx } from "@/components/ui";
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
  });

  const data = scan.data;
  const albums = useMemo(() => {
    if (!data?.albums) return [];
    const q = search.toLowerCase().trim();
    return data.albums.filter((a) => {
      if (filter === "compilations" && !a.is_compilation) return false;
      if (filter === "incomplete" && a.avg_completeness >= 100) return false;
      if (q) {
        const hay = `${a.albumartist} ${a.album} ${a.files.map((f) => f.title).join(" ")}`.toLowerCase();
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
    },
  });

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
      const meta: Record<string, string> = {
        musicbrainz_albumid: result.ids.musicbrainz_release ?? "",
        disctotal: String(Math.max(1, ...result.tracks.map((t) => t.disc_number || 1))),
      };
      const map: Record<string, string> = {
        artist: "albumartist", title: "album", original_date: "date",
        genre: "genre", label: "label",
      };
      for (const [key, tag] of Object.entries(map)) {
        if (choices[key]?.include) meta[tag] = choices[key].value;
      }

      const tracks = album.files.map((f) => {
        const match = matchTrack(result, f);
        return {
          path: f.path,
          title: match?.title ?? (f.title || f.filename.replace(/^\d+[\s\-._]+/, "").replace(/\.flac$/i, "")),
          artist: match?.artist ?? f.artist,
          tracknumber: String(match?.position ?? f.tracknumber ?? "1"),
          discnumber: String(match?.disc_number ?? f.discnumber ?? "1"),
          musicbrainz_trackid: match?.recording_id ?? "",
        };
      });

      return api.batchReassign({
        tracks,
        album_metadata: meta,
        art_release_id: artChoice === "keep" ? null
          : artChoice === "none" ? "__none__"
          : artChoice === "auto" ? (result.ids.musicbrainz_release ?? null)
          : null,
        art_url: artChoice.startsWith("url:") ? artChoice.slice(4) : null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["library"] });
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
    ...(album.has_art ? [{ id: "keep", label: "Current", sublabel: "keep embedded art" }] : []),
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
                {result.tracks.length} tracks vs {album.files.length} files
              </p>
              <MetadataCompare rows={rowsFor(result)} choices={choices} onChange={setChoices} />
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
function matchTrack(r: IdentifyResult, f: LibraryFile) {
  const title = (f.title || f.filename.replace(/^\d+[\s\-._]+/, "").replace(/\.flac$/i, "")).toLowerCase().trim();
  if (!title) return null;
  let best = null, bestScore = 0;
  for (const t of r.tracks) {
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

// ── Track detail dialog ───────────────────────────────────────────────────────

function TrackDetail({ file, onClose }: { file: LibraryFile | null; onClose: () => void }) {
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
    <Dialog open title={file.title || file.filename} onClose={onClose}>
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
                <td className="max-w-[260px] truncate py-0.5" title={value}>{value || "—"}</td>
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
    </Dialog>
  );
}
