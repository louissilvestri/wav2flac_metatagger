/** Build the release_details dict the conversion service expects, from an
 * aggregator IdentifyResult plus the user's per-field choices.
 *
 * Unchecked fields are simply omitted, so the CUE/filename value (or nothing)
 * is used instead — same per-field semantics as Quick Clean Up.
 */

import { IdentifyResult, CueMetadata } from "@/lib/api";
import { Choices } from "@/components/MetadataCompare";

export function buildReleaseDetails(
  result: IdentifyResult,
  choices: Choices,
  cue: CueMetadata | null,
  useProviderTitles: boolean,
) {
  const chosen = (key: string): string =>
    choices[key]?.include ? choices[key].value : "";

  // Group identified tracks by disc
  const byDisc = new Map<number, IdentifyResult["tracks"]>();
  for (const t of result.tracks) {
    const d = t.disc_number || 1;
    if (!byDisc.has(d)) byDisc.set(d, []);
    byDisc.get(d)!.push(t);
  }

  const discs = [...byDisc.entries()]
    .sort(([a], [b]) => a - b)
    .map(([position, tracks]) => ({
      position,
      format: "CD",
      tracks: tracks.map((t, i) => {
        const cueTrack = cue?.tracks?.[t.position - 1];
        const title = useProviderTitles
          ? t.title
          : (cueTrack?.title || t.title);
        return {
          position: t.position || i + 1,
          title,
          artist: t.artist || "",
          artist_id: "",
          length_ms: t.length_ms ?? null,
          isrc: t.isrc || cueTrack?.isrc || "",
          recording_id: t.recording_id || "",
        };
      }),
    }));

  const fallback = (key: string, cueKey?: string): string =>
    chosen(key) || (cue?.album?.[cueKey ?? key] ?? "");

  return {
    id: result.ids.musicbrainz_release || result.ids.discogs_release || "",
    release_group_id: result.ids.musicbrainz_release_group || "",
    title: fallback("title", "album"),
    artist: fallback("artist", "artist"),
    artist_id: "",
    // Conversion uses first_release_date when present — feed the chosen
    // original date through that slot
    date: chosen("release_date") || (cue?.album?.date ?? ""),
    first_release_date: chosen("original_date"),
    genre: fallback("genre", "genre"),
    label: chosen("label"),
    catalog_number: chosen("catalog_number"),
    barcode: chosen("barcode") || (cue?.album?.barcode ?? ""),
    country: chosen("country"),
    discs,
  };
}
