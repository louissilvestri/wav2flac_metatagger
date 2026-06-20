"use client";

/** Album-art candidate strip: thumbnails from every source (providers,
 * current embedded art, local EAC file) plus an explicit "No change" option.
 * Shared by Convert and Library flows.
 *
 * Resolution is shown under every tile: the declared full-image dimensions when
 * a source reports them, otherwise the loaded image's natural size (captured
 * onLoad) so the line is never blank. A thumbnail that fails to load falls back
 * to the placeholder tile instead of an empty box.
 */

import { useState } from "react";
import { cx } from "@/components/ui";

export interface ArtOption {
  id: string;                 // "provider:<url>", "keep", "none"
  label: string;              // "fanart.tv", "Current", ...
  sublabel?: string;          // extra note: likes, "skip", "from rip folder"
  width?: number;             // declared full-image dimensions (preferred)
  height?: number;
  thumbSrc?: string;          // URL or data: URI; absent => placeholder tile
  badge?: string;             // "New", "Recommended"
}

export function ArtPicker({ options, selectedId, onSelect }: {
  options: ArtOption[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  // Natural dimensions of loaded thumbnails, and tiles whose image failed.
  const [dims, setDims] = useState<Record<string, { w: number; h: number }>>({});
  const [errored, setErrored] = useState<Record<string, boolean>>({});

  if (options.length === 0) {
    return <p className="font-mono text-xs text-muted">No artwork candidates.</p>;
  }

  return (
    <div className="flex gap-2.5 overflow-x-auto pb-2">
      {options.map((opt) => {
        const selected = opt.id === selectedId;
        const showImg = !!opt.thumbSrc && !errored[opt.id];
        // Declared dimensions describe the full image and win; otherwise show
        // the loaded preview's natural size so a resolution always appears.
        const declared = opt.width && opt.height ? `${opt.width}×${opt.height}` : "";
        const loaded = dims[opt.id] ? `${dims[opt.id].w}×${dims[opt.id].h}` : "";
        const resolution = declared || loaded;
        return (
          <button
            key={opt.id}
            onClick={() => onSelect(opt.id)}
            title={`${opt.label}${resolution ? ` — ${resolution}` : ""}${opt.sublabel ? ` — ${opt.sublabel}` : ""}`}
            className={cx(
              "relative w-[110px] shrink-0 cursor-pointer overflow-hidden rounded-[var(--radius)] border bg-surface-2 text-left",
              "transition-[box-shadow,border-color] duration-[250ms] ease-command",
              selected ? "border-accent shadow-[var(--shadow)]" : "border-border hover:border-accent/60",
            )}
          >
            <div className="flex h-[110px] items-center justify-center overflow-hidden bg-surface-2">
              {showImg ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={opt.thumbSrc}
                  alt={opt.label}
                  loading="lazy"
                  className="h-full w-full object-cover"
                  onLoad={(e) => {
                    const img = e.target as HTMLImageElement;
                    if (img.naturalWidth && !dims[opt.id]) {
                      setDims((d) => ({ ...d, [opt.id]: { w: img.naturalWidth, h: img.naturalHeight } }));
                    }
                  }}
                  onError={() => setErrored((m) => ({ ...m, [opt.id]: true }))}
                />
              ) : (
                <span className="font-display text-xl text-muted">
                  {opt.id === "none" ? "✕" : "·"}
                </span>
              )}
            </div>
            <div className="px-1.5 py-1">
              <div className="truncate font-mono text-[0.66rem] font-bold text-text">
                {opt.label}
              </div>
              {/* Resolution line — always rendered so tiles align; em-dash when unknown */}
              <div className="truncate font-mono text-[0.62rem] tabular-nums text-muted">
                {resolution || (opt.id === "none" ? "" : "—")}
              </div>
              {opt.sublabel && (
                <div className="truncate font-mono text-[0.6rem] text-muted">{opt.sublabel}</div>
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
