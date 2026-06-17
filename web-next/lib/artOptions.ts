/** Shared builders for the ArtPicker option list. ONE source of truth for how
 * every flow (Convert, Quick Clean Up, single-track reassign) turns its art
 * sources into picker tiles — so resolution display and thumbnail fallbacks
 * behave identically everywhere.
 */

import { ArtOption } from "@/components/ArtPicker";
import { ArtCandidate } from "@/lib/api";

/** Shape returned by the embedded/local/release art endpoints. */
export interface EmbeddedArt {
  success?: boolean;
  data?: string;        // base64 JPEG (no data: prefix)
  width?: number;       // ORIGINAL image dimensions (not the thumbnail's)
  height?: number;
}

const dataUri = (data?: string): string | undefined =>
  data ? `data:image/jpeg;base64,${data}` : undefined;

/** A tile for art we already hold as base64 (embedded FLAC art, local EAC file,
 * a fetched release's art). Requires BOTH success AND data before setting a
 * thumb, so a failed/empty fetch shows the placeholder tile rather than a
 * broken image. Carries the original width/height so the real resolution shows. */
export function embeddedArtOption(
  id: string, label: string, art: EmbeddedArt | undefined,
  fallbackSub: string, badge?: string,
): ArtOption {
  const ok = !!art?.success && !!art.data;
  return {
    id, label,
    sublabel: ok ? undefined : fallbackSub,
    width: art?.width, height: art?.height,
    thumbSrc: ok ? dataUri(art!.data) : undefined,
    ...(badge ? { badge } : {}),
  };
}

/** Tiles for provider art candidates. Entries with no image URL at all are
 * dropped (they would render as a broken tile). Declared width/height (when the
 * provider supplies them) are carried through for the resolution line. */
export function candidateArtOptions(candidates: ArtCandidate[] | undefined): ArtOption[] {
  return (candidates ?? [])
    .filter((a) => a.thumb_url || a.url)
    .map((a) => ({
      id: `url:${a.url}`,
      label: a.source,
      sublabel: a.likes != null ? `${a.likes} likes` : undefined,
      width: a.width, height: a.height,
      thumbSrc: a.thumb_url || a.url,
    }));
}

export const autoArtOption = (sublabel: string, badge?: string): ArtOption =>
  ({ id: "auto", label: "Auto", sublabel, ...(badge ? { badge } : {}) });

export const noneArtOption = (sublabel = "skip"): ArtOption =>
  ({ id: "none", label: "No Art", sublabel });
