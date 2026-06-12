"use client";

/** Convert wizard: Source → Identify → Review → Convert.
 * Each fact renders exactly once; the Review step owns all metadata display.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { api, IdentifyResult } from "@/lib/api";
import { useConvertStore } from "@/stores/convert";
import { Panel, Button, Input, Field, Terminal, TermLine, Spinner, Tag, Checkbox, cx } from "@/components/ui";
import { MetadataCompare, CompareRow, defaultChoices, asText } from "@/components/MetadataCompare";
import { ArtPicker, ArtOption } from "@/components/ArtPicker";
import { JobProgress } from "@/components/JobProgress";
import { buildReleaseDetails } from "@/lib/buildRelease";

const STEPS = [
  { id: "source", label: "1 · Source" },
  { id: "identify", label: "2 · Identify" },
  { id: "review", label: "3 · Review" },
  { id: "convert", label: "4 · Convert" },
] as const;

export default function ConvertPage() {
  const step = useConvertStore((s) => s.step);
  return (
    <div className="space-y-3">
      <header className="flex items-center gap-2">
        <h1 className="font-display mr-4 text-2xl text-accent glow-accent">Convert</h1>
        {STEPS.map((s) => (
          <span
            key={s.id}
            className={cx(
              "rounded px-3 py-1 font-display text-[0.72rem]",
              step === s.id ? "bg-accent-2 text-bg" : "text-muted",
            )}
          >
            {s.label}
          </span>
        ))}
      </header>

      {step === "source" && <SourceStep />}
      {step === "identify" && <IdentifyStep />}
      {step === "review" && <ReviewStep />}
      {step === "convert" && <ConvertStep />}
    </div>
  );
}

// Files for the rest of the wizard: all files, or just the selected album
// group when the folder contains multiple albums.
function useWizardFiles() {
  const { scan, albumGroup } = useConvertStore();
  const files = scan?.files ?? [];
  if (!scan?.multi_album || !albumGroup) return files;
  return files.filter((f) => f.parsed_album === albumGroup);
}

// ── Step 1: Source ───────────────────────────────────────────────────────────

function SourceStep() {
  const { folder, setFolder, scan, setScan, setStep, albumGroup, setAlbumGroup } = useConvertStore();
  const wizardFiles = useWizardFiles();

  const settings = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const effectiveFolder = folder || String(settings.data?.input_folder ?? "");

  const doScan = useMutation({
    mutationFn: () => api.scanInput(effectiveFolder || undefined),
    onSuccess: (result) => setScan(result),
  });

  const lines: TermLine[] = [];
  if (scan) {
    if (scan.error) lines.push({ tone: "err", text: `[FAIL] ${scan.error}` });
    else {
      lines.push({ tone: "ok", text: `[ OK ] ${scan.files.length} WAV file(s) found` });
      lines.push(scan.cue_found
        ? { tone: "ok", text: `[ OK ] CUE sheet parsed${scan.cue_metadata ? ` — ${scan.cue_metadata.album.artist ?? "?"} / ${scan.cue_metadata.album.album ?? "?"}` : ""}` }
        : { tone: "warn", text: "[WARN] no CUE sheet — falling back to filenames + fingerprints" });
      if (scan.multi_album) lines.push({ tone: "warn", text: "[WARN] multiple albums detected in folder" });
    }
  }

  return (
    <div className="space-y-3">
      <Panel title="Input Folder">
        <div className="flex items-end gap-2">
          <Field label="Folder with WAV + CUE from EAC" className="flex-1">
            <Input
              value={effectiveFolder}
              onChange={(e) => setFolder(e.target.value)}
              placeholder="C:\Users\...\EAC_Rips"
            />
          </Field>
          <Button variant="ghost" onClick={async () => {
            const r = await api.browseDialog("folder");
            if (r.path) setFolder(r.path);
          }}>Browse</Button>
          <Button variant="solid" disabled={doScan.isPending} onClick={() => doScan.mutate()}>
            {doScan.isPending ? "Scanning…" : "Scan"}
          </Button>
        </div>
        {lines.length > 0 && <Terminal lines={lines} className="mt-3" />}
      </Panel>

      {scan?.multi_album && scan.album_groups && (
        <Panel title="Multiple Albums Detected — pick one">
          <div className="flex flex-wrap gap-2">
            {scan.album_groups.map((g) => (
              <button
                key={g.album}
                onClick={() => setAlbumGroup(g.album)}
                className={cx(
                  "chamfer cursor-pointer border px-3 py-1.5 font-mono text-[0.74rem]",
                  "transition-[box-shadow] duration-[240ms]",
                  albumGroup === g.album
                    ? "border-accent bg-accent text-bg"
                    : "border-accent/30 text-accent hover:box-glow",
                )}
              >
                {g.artist ? `${g.artist} — ` : ""}{g.album || "Unknown"}{" "}
                <span className="opacity-70">({g.file_count})</span>
              </button>
            ))}
          </div>
        </Panel>
      )}

      {scan && !scan.error && wizardFiles.length > 0 && (
        <Panel
          title={`Files (${wizardFiles.length}${scan.multi_album && albumGroup ? ` of ${scan.files.length}` : ""})`}
          actions={
            <Button
              variant="solid"
              disabled={!!scan.multi_album && !albumGroup}
              title={scan.multi_album && !albumGroup ? "Select an album group first" : undefined}
              onClick={() => setStep("identify")}
            >
              Continue →
            </Button>
          }
        >
          <table className="w-full font-mono text-[0.78rem]">
            <thead>
              <tr className="border-b border-white/15 text-left text-[0.66rem] uppercase text-muted">
                <th className="w-10 p-1.5">#</th>
                <th className="p-1.5">Title</th>
                <th className="p-1.5">File</th>
              </tr>
            </thead>
            <tbody>
              {wizardFiles.map((f, i) => (
                <tr key={f.path} className="border-b border-white/5">
                  <td className="p-1.5 text-muted">{f.parsed_track_number ?? i + 1}</td>
                  <td className="p-1.5">{f.parsed_title ?? <span className="text-muted">—</span>}</td>
                  <td className="max-w-[300px] truncate p-1.5 text-muted">{String(f.path).split(/[\\/]/).pop()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}

// ── Step 2: Identify ─────────────────────────────────────────────────────────

function IdentifyStep() {
  const { scan, folder, albumGroup, identifyResult, setIdentify, setChoices, setStep } = useConvertStore();
  const wizardFiles = useWizardFiles();
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const effectiveFolder = scan?.folder || folder || String(settingsQ.data?.input_folder ?? "");

  const doIdentify = useMutation({
    mutationFn: () => {
      // Multi-album folders: the folder's CUE belongs to one specific album,
      // so identify the SELECTED group by its own name + fingerprints instead
      if (scan?.multi_album && albumGroup) {
        const group = scan.album_groups?.find((g) => g.album === albumGroup);
        return api.identify({
          artist: group?.artist ?? "",
          album: albumGroup,
          file_paths: wizardFiles.map((f) => f.path),
        });
      }
      return api.identify({ folder_path: effectiveFolder });
    },
    onSuccess: (result) => {
      setIdentify(result);
      setChoices(defaultChoices(buildRows(result, cueValues(scan?.cue_metadata ?? null))));
    },
  });

  const r = identifyResult;
  const lines: TermLine[] = [];
  if (r) {
    const methodLabel = { discid: "disc ID (exact)", fingerprint: "audio fingerprint",
                          text_search: "text search", none: "no match" }[r.identity.method] ?? r.identity.method;
    lines.push({
      tone: r.identity.method === "none" ? "err" : "ok",
      text: `[${r.identity.method === "none" ? "FAIL" : " OK "}] identity via ${methodLabel}${r.identity.confidence_note ? ` (${r.identity.confidence_note})` : ""}`,
    });
    for (const [name, status] of Object.entries(r.providers)) {
      lines.push({
        tone: status === "ok" ? "ok" : status.startsWith("failed") ? "err" : "warn",
        text: `[${status === "ok" ? " OK " : status.startsWith("failed") ? "FAIL" : "SKIP"}] ${name}: ${status}`,
      });
    }
  }

  return (
    <div className="space-y-3">
      <Panel
        title="Identification"
        actions={
          <>
            <Button variant="ghost" onClick={() => setStep("source")}>← Back</Button>
            <Button variant="solid" disabled={doIdentify.isPending} onClick={() => doIdentify.mutate()}>
              {doIdentify.isPending ? "Querying providers…" : r ? "Re-identify" : "Identify"}
            </Button>
            {r && r.identity.method !== "none" && (
              <Button variant="amber" onClick={() => setStep("review")}>Review →</Button>
            )}
          </>
        }
      >
        <p className="mb-3 text-sm text-muted">
          Disc ID → audio fingerprint → text search, then enrichment from every
          enabled provider. One pass, merged with provenance.
        </p>
        {doIdentify.isPending && <Spinner label="querying MusicBrainz · Discogs · Last.fm · iTunes · Deezer · fanart.tv…" />}
        {lines.length > 0 && <Terminal lines={lines} />}
        {r && r.identity.method !== "none" && (
          <p className="mt-3 font-mono text-sm">
            <span className="text-accent">{asText(r.fields.artist?.value ?? "?")}</span>
            <span className="text-muted"> — </span>
            <span className="text-accent">{asText(r.fields.title?.value ?? "?")}</span>
            <span className="text-muted"> · {r.tracks.length} tracks · </span>
            <Tag tone="ok">{asText(r.fields.original_date?.value ?? "?")}</Tag>
          </p>
        )}
      </Panel>
    </div>
  );
}

// ── Step 3: Review ───────────────────────────────────────────────────────────

function cueValues(cue: { album: Record<string, string> } | null): Record<string, string> {
  if (!cue) return {};
  return {
    title: cue.album.album ?? "",
    artist: cue.album.artist ?? "",
    original_date: cue.album.date ?? "",
    release_date: cue.album.date ?? "",
    genre: cue.album.genre ?? "",
    barcode: cue.album.barcode ?? "",
  };
}

const FIELD_LABELS: Record<string, string> = {
  title: "Album", artist: "Album Artist", original_date: "Original Date",
  release_date: "Release Date", genre: "Genre", styles: "Styles",
  label: "Label", catalog_number: "Catalog #", barcode: "Barcode", country: "Country",
};

function buildRows(r: IdentifyResult, current: Record<string, string>): CompareRow[] {
  return Object.keys(FIELD_LABELS)
    .filter((key) => r.fields[key] || current[key])
    .map((key) => ({
      key,
      label: FIELD_LABELS[key],
      current: current[key] ?? "",
      merged: r.fields[key],
    }));
}

function ReviewStep() {
  const {
    scan, identifyResult: r, choices, setChoices, setStep,
    useProviderTitles, setUseProviderTitles, artChoiceId, setArtChoice,
  } = useConvertStore();
  const wizardFiles = useWizardFiles();

  if (!r) return null;
  const rows = buildRows(r, cueValues(scan?.cue_metadata ?? null));

  const artOptions: ArtOption[] = [
    { id: "auto", label: "Auto", sublabel: "highest resolution wins", badge: "Default" },
    ...r.art_candidates.map((a, i) => ({
      id: `url:${a.url}`,
      label: a.source,
      sublabel: a.width ? `${a.width}×${a.height}` : (a.likes ? `${a.likes} likes` : ""),
      thumbSrc: a.thumb_url || a.url,
      ...(i === 0 ? {} : {}),
    })),
    { id: "none", label: "No Art", sublabel: "skip embedding" },
  ];

  const matched = r.tracks.length;
  const scanned = wizardFiles.length;
  const discCount = Math.max(1, ...r.tracks.map((t) => t.disc_number || 1));

  return (
    <div className="space-y-3">
      <Panel
        title="Metadata Review"
        actions={
          <>
            <Button variant="ghost" onClick={() => setStep("identify")}>← Back</Button>
            <Button variant="solid" onClick={() => setStep("convert")}>Convert →</Button>
          </>
        }
      >
        <MetadataCompare rows={rows} choices={choices} onChange={setChoices} />
        {matched !== scanned && (
          <p className="mt-2 font-mono text-xs text-accent-2">
            ⚠ release has {matched} tracks; folder has {scanned} files
          </p>
        )}
        {discCount > 1 && (
          <p className="mt-2 font-mono text-xs text-muted">
            Multi-disc release ({discCount} discs) — files map to discs in sequence
            {matched === scanned ? "" : "; counts must match for disc mapping"}.
          </p>
        )}
      </Panel>

      <Panel title="Album Art">
        <ArtPicker options={artOptions} selectedId={artChoiceId} onSelect={setArtChoice} />
      </Panel>

      <Panel title={`Tracks (${r.tracks.length} from ${r.track_source || "n/a"})`}>
        <div className="mb-2">
          <Checkbox
            label="Use provider track titles (uncheck to keep CUE titles)"
            checked={useProviderTitles}
            onChange={(e) => setUseProviderTitles(e.target.checked)}
          />
        </div>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full font-mono text-[0.78rem]">
            <tbody>
              {r.tracks.map((t) => (
                <tr key={`${t.disc_number}-${t.position}`} className="border-b border-white/5">
                  <td className="w-10 p-1.5 text-muted">{t.position}</td>
                  <td className="p-1.5">{t.title}</td>
                  <td className="p-1.5 text-right text-muted">
                    {t.length_ms ? `${Math.floor(t.length_ms / 60000)}:${String(Math.floor((t.length_ms % 60000) / 1000)).padStart(2, "0")}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

// ── Step 4: Convert ──────────────────────────────────────────────────────────

function ConvertStep() {
  const {
    scan, identifyResult: r, choices, useProviderTitles, artChoiceId,
    jobId, setJobId, setStep, reset,
  } = useConvertStore();
  const wizardFiles = useWizardFiles();

  const start = useMutation({
    mutationFn: () => {
      const release = r ? buildReleaseDetails(r, choices, scan?.cue_metadata ?? null, useProviderTitles) : null;
      const options: Record<string, unknown> = {};
      if (artChoiceId === "none") options.embed_album_art = false;
      else if (artChoiceId?.startsWith("url:")) options.art_url = artChoiceId.slice(4);
      if (scan?.folder) options.input_folder = scan.folder;

      // Order files: by parsed track number when usable, otherwise the
      // filename order scan_wav_files already produced. (Note: || not ?? —
      // a parsed number of 0 means "unparsed" and must fall back.)
      const ordered = wizardFiles
        .map((f, i) => ({ f, key: (f.parsed_track_number as number) || (i + 1) }))
        .sort((a, b) => a.key - b.key)
        .map((x) => x.f);

      // The release track list is authoritative for ordering: when its track
      // count matches the file count, file[i] → track[i]. This is robust to
      // unparseable filenames (the original "Track 00" overwrite bug).
      const flat = (r?.tracks ?? []).slice()
        .sort((a, b) => (a.disc_number - b.disc_number) || (a.position - b.position));
      const alignByIndex = flat.length > 0 && flat.length === ordered.length;

      return api.startConvert({
        files: ordered.map((f, i) => ({
          path: f.path,
          track_number: alignByIndex ? flat[i].position : ((f.parsed_track_number as number) || i + 1),
          disc_number: alignByIndex ? (flat[i].disc_number || 1) : 1,
          parsed_title: f.parsed_title,
          parsed_artist: f.parsed_artist,
          parsed_album: f.parsed_album,
        })),
        release_details: release,
        options,
      });
    },
    onSuccess: (resp) => setJobId(resp.job_id),
  });

  return (
    <div className="space-y-3">
      <Panel
        title="Conversion"
        actions={!jobId && (
          <>
            <Button variant="ghost" onClick={() => setStep("review")}>← Back</Button>
            <Button variant="solid" disabled={start.isPending} onClick={() => start.mutate()}>
              {start.isPending ? "Starting…" : `Start (${wizardFiles.length} files)`}
            </Button>
          </>
        )}
      >
        {start.error && (
          <p className="mb-2 font-mono text-sm text-alert">{String(start.error)}</p>
        )}
        {jobId
          ? <JobProgress jobId={jobId} />
          : <p className="text-sm text-muted">Encode → tag → verify → move to the Plex library.</p>}
        {jobId && (
          <div className="mt-3">
            <Button variant="ghost" onClick={reset}>New conversion</Button>
          </div>
        )}
      </Panel>
    </div>
  );
}
