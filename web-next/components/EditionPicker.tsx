"use client";

/** Multi-provider release-candidate list. ONE implementation shared by the
 * Convert wizard, Library Quick Clean Up, and single-track reassign so all
 * three behave and look identical (they had drifted into three copies).
 *
 * Renders the rows for a non-empty candidate array; callers own the
 * loading/empty/manual-search states around it. */

import { ReleaseCandidate } from "@/lib/api";
import { Tag, Spinner, cx } from "@/components/ui";

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
  return (
    <div className="max-h-56 space-y-1 overflow-y-auto">
      {note && <p className="font-mono text-[0.68rem] text-muted">{note}</p>}
      {candidates.map((c) => {
        const key = `${c.provider}:${c.id}`;
        const active = key === activeId;
        const countMatches = !!expectedTracks && c.track_count > 0 && c.track_count === expectedTracks;
        return (
          <button
            key={key}
            disabled={pending}
            onClick={() => onPick(c)}
            className={cx(
              "flex w-full cursor-pointer flex-col gap-0.5 border px-3 py-1.5 text-left font-mono text-[0.72rem]",
              "transition-colors hover:border-accent/60",
              active ? "border-accent box-glow" : "border-white/10",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="truncate font-bold text-text">
                {c.artist ? `${c.artist} — ` : ""}{c.title || "(untitled)"}
              </span>
              <span className="ml-auto flex shrink-0 items-center gap-1.5">
                {c.recommended && <Tag tone="ok">Recommended</Tag>}
                {active && <span className="text-accent">●</span>}
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
      {pending && <Spinner label="loading edition…" />}
    </div>
  );
}
