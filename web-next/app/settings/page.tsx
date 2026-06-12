"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Settings } from "@/lib/api";
import { Panel, Button, Input, Field, Select, Checkbox, Spinner } from "@/components/ui";

export default function SettingsPage() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const [form, setForm] = useState<Settings | null>(null);
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

  if (!form) return <Spinner label="loading settings…" />;

  const set = (key: string, value: unknown) => setForm({ ...form, [key]: value });
  const browse = async (key: string, kind: "folder" | "exe" = "folder") => {
    const r = await api.browseDialog(kind);
    if (r.path) set(key, r.path);
  };

  return (
    <div className="max-w-3xl space-y-3">
      <header className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-accent glow-accent">Settings</h1>
        <Button variant="solid" disabled={save.isPending} onClick={() => save.mutate(form)}>
          {save.isPending ? "Saving…" : save.isSuccess ? "Saved ✓" : "Save Settings"}
        </Button>
      </header>

      <Panel title="File Paths">
        <div className="space-y-3">
          {([
            ["input_folder", "Default input folder (EAC rips)", "folder"],
            ["output_folder", "Output folder (Plex library)", "folder"],
            ["flac_exe_path", "flac.exe path", "exe"],
          ] as const).map(([key, label, kind]) => (
            <Field key={key} label={label}>
              <div className="flex gap-2">
                <Input value={String(form[key] ?? "")} onChange={(e) => set(key, e.target.value)} />
                <Button variant="ghost" onClick={() => browse(key, kind)}>Browse</Button>
                {key === "flac_exe_path" && (
                  <Button variant="ghost" onClick={async () => {
                    const r = await api.autodetectFlac();
                    if (r.path) set(key, r.path);
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
              className="w-full accent-[#22d3ee]"
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
          </div>
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

  return (
    <Panel title="Metadata Providers">
      <p className="mb-2 text-sm text-muted">
        Enabled providers are queried on every identify; fields merge by the
        precedence below. Click ◂ to promote a source. API keys live in{" "}
        <code className="font-mono text-accent">.env</code>.
      </p>

      <div className="mb-4 flex flex-wrap gap-3">
        {meta.data.all_providers.map((p) => (
          <Checkbox
            key={p}
            label={p === "acoustid" && !fpAvailable ? `${p} (fpcalc missing)` : p}
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
