"use client";

import { useQuery } from "@tanstack/react-query";
import { api, fmtBytes, fmtDuration } from "@/lib/api";
import { Panel, StatCard, Spinner, Tag } from "@/components/ui";

export default function HistoryPage() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const history = useQuery({ queryKey: ["history"], queryFn: () => api.history(200) });

  const s = stats.data;
  const saved = s ? s.total_wav_bytes - s.total_flac_bytes : 0;

  return (
    <div className="space-y-3">
      <h1 className="font-display text-2xl text-text">History</h1>

      {s && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <StatCard label="Conversions" value={s.total} />
          <StatCard label="Failed" value={s.failed} />
          <StatCard label="Space Saved" value={fmtBytes(saved)} />
          <StatCard label="Avg Encode" value={fmtDuration(s.avg_duration_ms)} />
        </div>
      )}

      <Panel title="Conversion Log">
        {history.isLoading && <Spinner label="loading history…" />}
        {history.isError && (
          <p className="font-mono text-sm text-alert">
            Failed to load history: {String((history.error as Error)?.message ?? history.error)}
          </p>
        )}
        {history.data && history.data.length === 0 && (
          <p className="font-mono text-sm text-muted">No conversions yet.</p>
        )}
        {history.data && history.data.length > 0 && (
          <div className="max-h-[70vh] overflow-y-auto">
            <table className="w-full font-mono text-[0.74rem]">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-white/15 text-left text-[0.62rem] uppercase text-muted">
                  <th className="p-1.5">When</th>
                  <th className="p-1.5">Track</th>
                  <th className="p-1.5">Status</th>
                  <th className="p-1.5 text-right">Size</th>
                  <th className="p-1.5 text-right">Time</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((h) => (
                  <tr key={h.id} className="border-b border-white/5">
                    <td className="whitespace-nowrap p-1.5 text-muted">
                      {new Date(h.timestamp).toLocaleString(undefined,
                        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="max-w-[320px] truncate p-1.5"
                        title={`${h.artist ?? ""} — ${h.title ?? ""}`}>
                      {h.artist ? `${h.artist} — ` : ""}{h.title || h.source_path.split(/[\\/]/).pop()}
                    </td>
                    <td className="p-1.5">
                      <Tag tone={h.status === "completed" ? "ok" : h.status === "failed" ? "alert" : "warn"}>
                        {h.status}
                      </Tag>
                      {h.error_message && (
                        <span className="ml-2 text-[0.66rem] text-alert">{h.error_message}</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap p-1.5 text-right text-muted">
                      {h.file_size_after ? fmtBytes(h.file_size_after) : "–"}
                    </td>
                    <td className="p-1.5 text-right text-muted">{fmtDuration(h.duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
