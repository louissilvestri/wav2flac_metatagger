"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Settings } from "@/lib/api";
import { Panel, Button, Input, Field, Select, Checkbox, Spinner, Tag } from "@/components/ui";
import { JobProgress } from "@/components/JobProgress";

export default function SettingsPage() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const [form, setForm] = useState<Settings | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const fp = useQuery({
    queryKey: ["fingerprint-status"],
    queryFn: () => fetch("/api/metadata/fingerprint-status").then((r) => r.json()),
  });

  useEffect(() => {
    if (query.data && !form) setForm(query.data);
  }, [query.data, form]);

  const save = useMutation({
    mutationFn: (s: Settings) => api.updateSettings(s),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  // Bulk ReplayGain over the whole library (albums missing it) — runs as a
  // background job; progress is shown via JobProgress.
  const [rgJob, setRgJob] = useState<string | null>(null);
  const rgAll = useMutation({
    mutationFn: () => api.replayGainLibrary(),
    onSuccess: (d) => setRgJob(d.job_id),
  });

  if (query.isError) return (
    <p className="font-mono text-sm text-alert">
      Failed to load settings: {String((query.error as Error)?.message ?? query.error)}
    </p>
  );
  if (!form) return <Spinner label="loading settings…" />;

  // Editing clears a stale "Saved ✓"/"Retry Save" label so it never claims a
  // dirty form is saved.
  const set = (key: string, value: unknown) => {
    if (save.isSuccess || save.isError) save.reset();
    setForm({ ...form, [key]: value });
  };
  const browse = async (key: string, kind: "folder" | "exe" = "folder") => {
    setActionError(null);
    try {
      const r = await api.browseDialog(kind);
      if (r.path) set(key, r.path);
    } catch (e) {
      setActionError(`Browse failed: ${String((e as Error)?.message ?? e)}`);
    }
  };

  return (
    <div className="max-w-3xl space-y-3">
      <header className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl text-text">Settings</h1>
        <div className="flex items-center gap-3">
          {actionError && <span className="font-mono text-xs text-alert">{actionError}</span>}
          {save.isError && (
            <span className="font-mono text-xs text-alert">
              Save failed: {String((save.error as Error)?.message ?? save.error)}
            </span>
          )}
          <Button variant="solid" disabled={save.isPending} onClick={() => save.mutate(form)}>
            {save.isPending ? "Saving…" : save.isError ? "Retry Save" : save.isSuccess ? "Saved ✓" : "Save Settings"}
          </Button>
        </div>
      </header>

      <Panel title="File Paths">
        <div className="space-y-3">
          {([
            ["input_folder", "Default input folder", "folder"],
            ["output_folder", "Output folder", "folder"],
            ["flac_exe_path", "flac.exe path", "exe"],
          ] as const).map(([key, label, kind]) => (
            <Field key={key} label={label}>
              <div className="flex gap-2">
                <Input value={String(form[key] ?? "")} onChange={(e) => set(key, e.target.value)} />
                <Button variant="ghost" onClick={() => browse(key, kind)}>Browse</Button>
                {key === "flac_exe_path" && (
                  <Button variant="ghost" onClick={async () => {
                    setActionError(null);
                    try {
                      const r = await api.autodetectFlac();
                      if (r.path) set(key, r.path);
                      else setActionError("flac.exe not found automatically — set the path manually.");
                    } catch (e) {
                      setActionError(`Detect failed: ${String((e as Error)?.message ?? e)}`);
                    }
                  }}>Detect</Button>
                )}
              </div>
            </Field>
          ))}
        </div>
      </Panel>

      <Panel title="Encoding">
        <div className="grid grid-cols-2 gap-4">
          <Field label={`Compression level: ${form.compression_level ?? 8}`}>
            <input
              type="range" min={0} max={8}
              className="w-full accent-accent"
              value={Number(form.compression_level ?? 8)}
              onChange={(e) => set("compression_level", Number(e.target.value))}
            />
          </Field>
          <div className="space-y-2 pt-4">
            <Checkbox label="Verify encoding (bit-perfect guarantee)"
              checked={!!form.verify_encoding}
              onChange={(e) => set("verify_encoding", e.target.checked)} />
            <Checkbox label="Delete WAVs after successful conversion"
              checked={!!form.delete_wav_after_convert}
              onChange={(e) => set("delete_wav_after_convert", e.target.checked)} />
            <Checkbox label="Calculate ReplayGain (loudness) tags"
              checked={!!form.add_replay_gain}
              onChange={(e) => set("add_replay_gain", e.target.checked)} />
            <Checkbox label="Fetch performer credits (composer, conductor… — slower)"
              checked={!!form.fetch_performer_credits}
              onChange={(e) => set("fetch_performer_credits", e.target.checked)} />
            <Checkbox label="Fill missing fields from Discogs when MusicBrainz lacks them"
              checked={!!form.cross_provider_backfill}
              onChange={(e) => set("cross_provider_backfill", e.target.checked)} />
          </div>
        </div>
        <div className="mt-3 border-t border-white/10 pt-3">
          <Button variant="outline" disabled={rgAll.isPending || !!rgJob}
                  onClick={() => rgAll.mutate()}>
            {rgAll.isPending ? "Starting…" : "Scan Library and Apply ReplayGain Now"}
          </Button>
          <p className="mt-1 font-mono text-[0.68rem] text-muted">
            Adds loudness tags to existing library albums that don’t have them yet.
            Runs in the background; audio is never modified.
          </p>
          {rgAll.isError && (
            <p className="mt-1 font-mono text-[0.68rem] text-alert">
              Failed: {String((rgAll.error as Error)?.message ?? rgAll.error)}
            </p>
          )}
          {rgJob && (
            <div className="mt-3">
              <JobProgress jobId={rgJob} onDone={() => {
                qc.invalidateQueries({ queryKey: ["library"] });
              }} />
            </div>
          )}
        </div>
      </Panel>

      <Panel title="Album Art">
        <div className="grid grid-cols-2 gap-4">
          <div className="pt-4">
            <Checkbox label="Embed album art in FLAC files"
              checked={!!form.embed_album_art}
              onChange={(e) => set("embed_album_art", e.target.checked)} />
          </div>
          <Field label="Max image size">
            <Select value={String(form.art_max_size ?? 1200)}
                    onChange={(e) => set("art_max_size", Number(e.target.value))}>
              <option value="500">500 px</option>
              <option value="800">800 px</option>
              <option value="1200">1200 px (recommended)</option>
              <option value="1500">1500 px</option>
              <option value="3000">3000 px</option>
            </Select>
          </Field>
        </div>
      </Panel>

      <ApiKeysPanel />

      <ProvidersPanel form={form} set={set} fpAvailable={!!fp.data?.available} />

      <Panel title="Output Structure">
        <Field label="Multi-disc albums">
          <Select value={String(form.multi_disc_style ?? "subfolder")}
                  onChange={(e) => set("multi_disc_style", e.target.value)}>
            <option value="subfolder">Disc subfolders (Disc 1/, Disc 2/)</option>
            <option value="prefix">Track number prefix (101, 201)</option>
          </Select>
        </Field>
      </Panel>
    </div>
  );
}

// ── Provider enable/precedence editor ─────────────────────────────────────────

const FIELD_LABELS: Record<string, string> = {
  title: "Album Title", artist: "Artist", original_date: "Original Date",
  release_date: "Release Date", genre: "Genre", styles: "Styles",
  label: "Label", catalog_number: "Catalog #", barcode: "Barcode", country: "Country",
};

function ProvidersPanel({ form, set, fpAvailable }: {
  form: Settings;
  set: (key: string, value: unknown) => void;
  fpAvailable: boolean;
}) {
  const meta = useQuery({
    queryKey: ["precedence"],
    queryFn: () => fetch("/api/metadata/precedence").then((r) => r.json()) as Promise<{
      precedence: Record<string, string[]>;
      defaults: Record<string, string[]>;
      enabled: string[];
      all_providers: string[];
    }>,
  });
  // Must be called unconditionally (before any early return) to keep hook order stable.
  const secrets = useQuery({ queryKey: ["secrets"], queryFn: api.getSecrets });

  if (!meta.data) return <Panel title="Metadata Providers"><Spinner /></Panel>;

  const enabled: string[] =
    (form.metadata_providers_enabled as string[] | undefined) ?? meta.data.enabled;
  const precedence: Record<string, string[]> =
    (form.merge_precedence as Record<string, string[]> | undefined) ?? {};
  const effective = (field: string) =>
    precedence[field] ?? meta.data!.precedence[field] ?? [];

  const toggleProvider = (p: string) => {
    const next = enabled.includes(p) ? enabled.filter((x) => x !== p) : [...enabled, p];
    set("metadata_providers_enabled", next);
  };

  const promote = (field: string, source: string) => {
    const order = effective(field);
    const idx = order.indexOf(source);
    if (idx <= 0) return;
    const next = [...order];
    [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
    set("merge_precedence", { ...precedence, [field]: next });
  };

  const needsKey = (p: string) =>
    !!secrets.data?.[p] && !secrets.data[p].has_keys;

  const providerLabel = (p: string) => {
    if (p === "acoustid" && !fpAvailable) return `${p} (fpcalc missing)`;
    if (needsKey(p)) return `${p} (needs key)`;
    return p;
  };

  return (
    <Panel title="Metadata Providers">
      <p className="mb-2 text-sm text-muted">
        Enabled providers are queried on every identify; fields merge by the
        precedence below. Click ◂ to promote a source. A provider that needs an
        API key but has none is skipped — add keys under{" "}
        <b className="text-accent">Provider API Keys</b> above.
      </p>

      <div className="mb-4 flex flex-wrap gap-3">
        {meta.data.all_providers.map((p) => (
          <Checkbox
            key={p}
            label={providerLabel(p)}
            checked={enabled.includes(p)}
            onChange={() => toggleProvider(p)}
          />
        ))}
      </div>

      <table className="w-full font-mono text-[0.72rem]">
        <tbody>
          {Object.entries(FIELD_LABELS).map(([field, label]) => (
            <tr key={field} className="border-b border-white/5">
              <td className="w-32 py-1 pr-2 text-muted">{label}</td>
              <td className="py-1">
                <div className="flex flex-wrap items-center gap-1">
                  {effective(field).map((source, i) => (
                    <span
                      key={source}
                      className={cxLocal(
                        "flex items-center gap-1 rounded-sm border px-1.5 py-0.5",
                        i === 0 ? "border-accent text-accent" : "border-white/15 text-muted",
                        !enabled.includes(source) && "opacity-40 line-through",
                      )}
                    >
                      {i > 0 && (
                        <button
                          className="cursor-pointer text-accent-2 hover:text-accent"
                          title={`Promote ${source}`}
                          onClick={() => promote(field, source)}
                        >
                          ◂
                        </button>
                      )}
                      {source}
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function cxLocal(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ── Provider API keys (enter, reveal, test) ───────────────────────────────────

const PROVIDER_LABELS: Record<string, string> = {
  discogs: "Discogs", lastfm: "Last.fm", acoustid: "AcoustID", fanarttv: "fanart.tv",
};

function ApiKeysPanel() {
  const qc = useQueryClient();
  const secrets = useQuery({ queryKey: ["secrets"], queryFn: api.getSecrets });
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [reveal, setReveal] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (values: Record<string, string>) => api.putSecrets(values),
    onSuccess: () => {
      // Re-read keys + anything gated by them (provider availability, precedence).
      qc.invalidateQueries({ queryKey: ["secrets"] });
      qc.invalidateQueries({ queryKey: ["precedence"] });
      qc.invalidateQueries({ queryKey: ["fingerprint-status"] });
    },
  });

  if (secrets.isError) return (
    <Panel title="Provider API Keys">
      <p className="font-mono text-sm text-alert">Failed to load keys.</p>
    </Panel>
  );
  if (!secrets.data) return <Panel title="Provider API Keys"><Spinner /></Panel>;

  const valueOf = (name: string, saved: string) => (name in edits ? edits[name] : saved);
  const dirty = Object.keys(edits).length > 0;

  const saveAll = async () => {
    setError(null);
    try { await save.mutateAsync(edits); setEdits({}); }
    catch (e) { setError(`Save failed: ${String((e as Error)?.message ?? e)}`); }
  };

  const test = async (provider: string, names: string[]) => {
    setError(null);
    setTesting(provider);
    try {
      // Persist any edits for this provider first so we test what's on screen.
      const pending: Record<string, string> = {};
      for (const n of names) if (n in edits) pending[n] = edits[n];
      if (Object.keys(pending).length) {
        await save.mutateAsync(pending);
        setEdits((e) => { const c = { ...e }; names.forEach((n) => delete c[n]); return c; });
      }
      const r = await api.testSecret(provider);
      setResults((m) => ({ ...m, [provider]: r }));
    } catch (e) {
      setResults((m) => ({ ...m, [provider]: { ok: false, message: String((e as Error)?.message ?? e) } }));
    } finally {
      setTesting(null);
    }
  };

  return (
    <Panel title="Provider API Keys">
      <p className="mb-3 text-sm text-muted">
        Keys are stored locally on this machine. A provider with no key (where one
        is required) is simply not used. Test a key to confirm it works.
      </p>
      <div className="space-y-4">
        {Object.entries(secrets.data).map(([provider, info]) => {
          const result = results[provider];
          return (
            <div key={provider} className="border-b border-white/5 pb-3 last:border-0">
              <div className="mb-1 flex items-center gap-2">
                <span className="font-display text-sm text-text">
                  {PROVIDER_LABELS[provider] ?? provider}
                </span>
                {info.has_keys
                  ? <Tag tone="ok">key set</Tag>
                  : <Tag tone="warn">no key — not used</Tag>}
              </div>
              {info.keys.map((k) => (
                <div key={k.name} className="mb-1.5 flex items-end gap-2">
                  <Field label={k.name} className="flex-1">
                    <Input
                      type={reveal[k.name] ? "text" : "password"}
                      autoComplete="off"
                      value={valueOf(k.name, k.value)}
                      placeholder="(not set)"
                      onChange={(e) => setEdits((s) => ({ ...s, [k.name]: e.target.value }))}
                    />
                  </Field>
                  <Button variant="ghost" onClick={() => setReveal((r) => ({ ...r, [k.name]: !r[k.name] }))}>
                    {reveal[k.name] ? "Hide" : "Show"}
                  </Button>
                </div>
              ))}
              <div className="flex items-center gap-3">
                <Button variant="outline" disabled={testing === provider}
                        onClick={() => test(provider, info.keys.map((k) => k.name))}>
                  {testing === provider ? "Testing…" : "Test"}
                </Button>
                {result && (
                  <span className={cxLocal("font-mono text-xs", result.ok ? "text-ok" : "text-alert")}>
                    {result.ok ? "✓ " : "✗ "}{result.message}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button variant="solid" disabled={!dirty || save.isPending} onClick={saveAll}>
          {save.isPending ? "Saving…" : "Save Keys"}
        </Button>
        {error && <span className="font-mono text-xs text-alert">{error}</span>}
      </div>
    </Panel>
  );
}
