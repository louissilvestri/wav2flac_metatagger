"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Settings } from "@/lib/api";
import { Panel, Button, Input, Field, Select, Checkbox, Spinner, Tag } from "@/components/ui";

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

      <Panel title="Metadata Providers">
        <p className="mb-3 text-sm text-muted">
          Identification and enrichment query all providers and merge per-field
          (precedence configurable in <code className="font-mono text-accent">.env</code>/settings).
          Keys live in <code className="font-mono text-accent">.env</code>.
        </p>
        <div className="flex flex-wrap gap-2 font-mono text-xs">
          {["musicbrainz", "discogs", "lastfm", "itunes", "deezer", "fanarttv"].map((p) => (
            <Tag key={p} tone="ok">{p}</Tag>
          ))}
          <Tag tone={fp.data?.available ? "ok" : "alert"}>
            acoustid {fp.data?.available ? "(fpcalc ready)" : "(fpcalc missing)"}
          </Tag>
        </div>
      </Panel>

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
