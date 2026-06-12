"use client";

/** Album-art candidate strip: thumbnails from every source (providers,
 * current embedded art, local EAC file) plus an explicit "No change" option.
 * Shared by Convert and Library flows.
 */

import { cx } from "@/components/ui";

export interface ArtOption {
  id: string;                 // "provider:<url>", "keep", "none"
  label: string;              // "fanart.tv", "Current", ...
  sublabel?: string;          // "1200×1200", likes, etc.
  thumbSrc?: string;          // URL or data: URI; absent => placeholder tile
  badge?: string;             // "New", "Recommended"
}

export function ArtPicker({ options, selectedId, onSelect }: {
  options: ArtOption[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (options.length === 0) {
    return <p className="font-mono text-xs text-muted">No artwork candidates.</p>;
  }
  return (
    <div className="flex gap-2.5 overflow-x-auto pb-2">
      {options.map((opt) => {
        const selected = opt.id === selectedId;
        return (
          <button
            key={opt.id}
            onClick={() => onSelect(opt.id)}
            title={`${opt.label}${opt.sublabel ? ` — ${opt.sublabel}` : ""}`}
            className={cx(
              "relative w-[110px] shrink-0 cursor-pointer border bg-surface-2 text-left",
              "transition-[box-shadow,border-color] duration-[240ms] ease-command",
              selected ? "border-accent box-glow" : "border-white/15 hover:border-accent/50",
            )}
          >
            <div className="flex h-[110px] items-center justify-center overflow-hidden bg-[#05080b]">
              {opt.thumbSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={opt.thumbSrc}
                  alt={opt.label}
                  loading="lazy"
                  className="h-full w-full object-cover"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              ) : (
                <span className="font-display text-xl text-muted">
                  {opt.id === "none" ? "✕" : "·"}
                </span>
              )}
            </div>
            <div className="px-1.5 py-1">
              <div className="truncate font-mono text-[0.66rem] font-bold text-accent">
                {opt.label}
              </div>
              {opt.sublabel && (
                <div className="truncate font-mono text-[0.62rem] text-muted">{opt.sublabel}</div>
              )}
            </div>
            {opt.badge && (
              <div className="bg-ok/20 py-0.5 text-center font-mono text-[0.58rem] font-bold uppercase tracking-wider text-ok">
                {opt.badge}
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}
