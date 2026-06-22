"use client";

/** Live conversion progress: SSE stream with automatic polling fallback.
 * If the SSE connection drops (sleep/wake), polling keeps the UI honest and
 * the stream reconnects on the next mount/focus.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Job } from "@/lib/api";
import { Button, Progress, Terminal, TermLine } from "@/components/ui";

export function JobProgress({ jobId, onDone }: {
  jobId: string;
  onDone?: (job: Job) => void;
}) {
  const [lines, setLines] = useState<TermLine[]>([{ tone: "info", text: "» job queued" }]);
  const [sseProgress, setSseProgress] = useState<{ current: number; total: number; file?: string } | null>(null);
  const doneRef = useRef(false);

  // Polling fallback — also the source of truth for late joins
  const poll = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId),
    refetchInterval: (q) =>
      ["done", "failed", "cancelled", "interrupted"].includes(q.state.data?.status ?? "")
        ? false : 2000,
  });

  useEffect(() => {
    const es = new EventSource(`/api/jobs/${jobId}/events`);

    es.addEventListener("progress", (e) => {
      const p = JSON.parse((e as MessageEvent).data);
      // Any job that reports a total drives the bar (conversion "encoding",
      // ReplayGain "analyzing", etc.).
      if (p.total != null && p.status !== "done") {
        setSseProgress({ current: p.current, total: p.total, file: p.file });
      }
    });

    es.addEventListener("file_done", (e) => {
      const r = JSON.parse((e as MessageEvent).data);
      // Standalone notices (e.g. album-art rescaled / missing) carry a `note`
      // and tone instead of a per-file result.
      if (r.note) {
        setLines((prev) => [...prev, { tone: r.tone === "warn" ? "warn" : "info", text: r.note }]);
        return;
      }
      const name = String(r.file ?? "").split(/[\\/]/).pop();
      setLines((prev) => {
        const next: TermLine[] = [...prev, r.success
          ? { tone: "ok", text: `[ OK ] ${name}${r.dest ? "  →  " + String(r.dest).split(/[\\/]/).slice(-3).join("/") : ""}` }
          : { tone: "err", text: `[FAIL] ${name}: ${r.error}` }];
        if (r.success && r.warning) next.push({ tone: "warn", text: `       ⚠ ${r.warning}` });
        return next;
      });
    });

    es.addEventListener("done", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setLines((prev) => [...prev, {
        tone: d.status === "done" ? "ok" : "err",
        text: `» job ${d.status}${d.error ? ": " + d.error : ""}`,
      }]);
      es.close();
    });

    es.onerror = () => { /* polling covers us; EventSource auto-retries */ };
    return () => es.close();
  }, [jobId]);

  const job = poll.data;
  const finished = ["done", "failed", "cancelled", "interrupted"].includes(job?.status ?? "");

  useEffect(() => {
    if (finished && job && !doneRef.current) {
      doneRef.current = true;
      onDone?.(job);
    }
  }, [finished, job, onDone]);

  const progress = sseProgress
    ?? (job?.progress?.total
      ? { current: job.progress.current ?? 0, total: job.progress.total, file: job.progress.file }
      : null);

  return (
    <div className="space-y-3">
      {progress && (
        <>
          <div className="flex items-baseline justify-between font-mono text-xs text-muted">
            <span>{progress.file ?? ""}</span>
            <span>{progress.current} / {progress.total}</span>
          </div>
          <Progress value={progress.current} max={progress.total} />
        </>
      )}
      <Terminal lines={lines} busy={!finished} className="max-h-64 overflow-y-auto" />
      {!finished && (
        <Button variant="alert" onClick={() => api.cancelJob(jobId)}>Cancel</Button>
      )}
      {job?.status === "done" && job.result && (
        <p className="font-mono text-sm text-ok">
          {job.result.completed}/{job.result.total} completed
          {job.result.failed > 0 && <span className="text-alert"> · {job.result.failed} failed</span>}
        </p>
      )}
    </div>
  );
}
