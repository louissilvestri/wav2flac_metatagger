"use client";

/** Multi-provider release-candidate list. ONE implementation shared by the
 * Convert wizard, Library Quick Clean Up, and single-track reassign so all
 * three behave and look identical (they had drifted into three copies).
 *
 * Renders the rows for a non-empty candidate array; callers own the
 * loading/empty/manual-search states around it. A built-in filter bar (country,
 * media type, track count) is offered whenever the candidates span more than one
 * value, so all three call sites get the same filtering for free. */

import { useEffect, useMemo, useState } from "react";
import { ReleaseCandidate } from "@/lib/api";
import { Tag, Spinner, Select, cx } from "@/components/ui";

export function EditionPicker({
  candidates, activeId = null, expectedTracks, pending = false, note, onPick,
}: {
  candidates: ReleaseCandidate[];
  activeId?: string | null;
  expectedTracks?: number;   // highlight a track-count match against this
  pending?: boolean;
  note?: string;
  onPick: (c: ReleaseCandidate) => void;
}) {
  const [country, setCountry] = useState("");
  const [format, setFormat] = useState("");
  const [tracks, setTracks] = useState("");

  // Distinct filter options present in the current candidate set.
  const countries = useMemo(
    () => [...new Set(candidates.map((c) => c.country).filter(Boolean))].sort(),
    [candidates]);
  const formats = useMemo(
    () => [...new Set(candidates.map((c) => c.format).filter(Boolean))].sort(),
    [candidates]);
  const counts = useMemo(
    () => [...new Set(candidates.map((c) => c.track_count).filter((n) => n > 0))]
      .sort((a, b) => a - b),
    [candidates]);

  // Reset filters whenever the candidate set itself changes (e.g. a new search,
  // or reassigning a different track) so stale selections never hide everything.
  const sig = candidates.map((c) => `${c.provider}:${c.id}`).join("|");
  useEffect(() => { setCountry(""); setFormat(""); setTracks(""); }, [sig]);

  const shown = candidates.filter((c) =>
    (!country || c.country === country) &&
    (!format || c.format === format) &&
    (!tracks || String(c.track_count) === tracks));

  const hasFilters = countries.length > 1 || formats.length > 1 || counts.length > 1;
  const active = !!(country || format || tracks);

  return (
    <div className="space-y-1.5">
      {hasFilters && (
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-[0.68rem]">
          {countries.length > 1 && (
            <Select aria-label="Filter by country" value={country}
              onChange={(e) => setCountry(e.target.value)}
              className="w-auto px-2 py-1 text-[0.7rem]">
              <option value="">All countries</option>
              {countries.map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          )}
          {formats.length > 1 && (
            <Select aria-label="Filter by media type" value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="w-auto px-2 py-1 text-[0.7rem]">
              <option value="">All media</option>
              {formats.map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          )}
          {counts.length > 1 && (
            <Select aria-label="Filter by track count" value={tracks}
              onChange={(e) => setTracks(e.target.value)}
              className="w-auto px-2 py-1 text-[0.7rem]">
              <option value="">Any tracks</option>
              {counts.map((n) => (
                <option key={n} value={n}>
                  {n} trk{expectedTracks === n ? " ✓" : ""}
                </option>
              ))}
            </Select>
          )}
          {active && (
            <button onClick={() => { setCountry(""); setFormat(""); setTracks(""); }}
              className="text-muted underline-offset-2 hover:text-text hover:underline">
              clear
            </button>
          )}
          <span className="ml-auto text-muted">
            {shown.length} of {candidates.length}
          </span>
        </div>
      )}

      <div className="max-h-56 space-y-1 overflow-y-auto">
        {note && <p className="font-mono text-[0.68rem] text-muted">{note}</p>}
        {shown.map((c) => {
          const key = `${c.provider}:${c.id}`;
          const isActive = key === activeId;
          const countMatches = !!expectedTracks && c.track_count > 0 && c.track_count === expectedTracks;
          return (
            <button
              key={key}
              disabled={pending}
              onClick={() => onPick(c)}
              className={cx(
                "flex w-full cursor-pointer flex-col gap-0.5 border px-3 py-1.5 text-left font-mono text-[0.72rem]",
                "transition-colors hover:border-accent/60",
                isActive ? "border-accent box-glow" : "border-white/10",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="truncate font-bold text-text">
                  {c.artist ? `${c.artist} — ` : ""}{c.title || "(untitled)"}
                </span>
                <span className="ml-auto flex shrink-0 items-center gap-1.5">
                  {c.recommended && <Tag tone="ok">Recommended</Tag>}
                  {isActive && <span className="text-accent">●</span>}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Tag tone={c.provider === "musicbrainz" ? "ok" : "warn"}>{c.provider}</Tag>
                <span className={cx("tabular-nums", countMatches ? "text-ok" : "text-muted")}>
                  {c.track_count > 0 ? `${c.track_count} trk` : "? trk"}
                </span>
                <span className="text-muted">{c.date || "—"}</span>
                {c.country && <span className="text-muted">{c.country}</span>}
                {c.format && <span className="truncate text-accent-2">{c.format}</span>}
              </div>
            </button>
          );
        })}
        {!pending && shown.length === 0 && candidates.length > 0 && (
          <p className="font-mono text-[0.68rem] text-muted">
            No editions match these filters.
          </p>
        )}
        {pending && <Spinner label="loading edition…" />}
      </div>
    </div>
  );
}
