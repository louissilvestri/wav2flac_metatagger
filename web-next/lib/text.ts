/** Typographic-punctuation folding, mirroring the backend text_utils.py.
 * Keeps client-side filtering and search-box values consistent with how the
 * providers are queried (smart quotes / dashes → ASCII).
 */

const PUNCT: Record<string, string> = {
  "‘": "'", "’": "'", "‚": "'", "‛": "'",
  "ʼ": "'", "´": "'", "`": "'",
  "“": '"', "”": '"', "„": '"', "‟": '"',
  "‐": "-", "‑": "-", "‒": "-", "–": "-",
  "—": "-", "―": "-", "−": "-",
  "…": "...",
  " ": " ", " ": " ", " ": " ",
};

export function normalizePunctuation(s: string): string {
  if (!s) return s;
  return s.replace(/[‘’‚‛ʼ´`“”„‟‐‑‒–—―−…   ]/g,
    (ch) => PUNCT[ch] ?? ch);
}

/** Fold accented letters to their base form (Motörhead → Motorhead). For
 * COMPARISON only — never for queries (providers index the accents). */
export function stripAccents(s: string): string {
  return (s || "").normalize("NFKD").replace(/\p{Diacritic}/gu, "");
}

/** Fold for equality/contains checks: punctuation-insensitive. Mirrors the
 * backend text_utils.fold_for_compare exactly. Use on BOTH sides.
 *
 * Base (typography, accents, case) + "&" → "and"; apostrophes dropped
 * ("She's" == "Shes"); every other punctuation/symbol → space. Tolerant of the
 * ways providers disagree on titles — & vs and, parentheses, slashes, commas,
 * hyphens — without joining separate words. */
export function foldForCompare(s: string): string {
  return stripAccents(normalizePunctuation(s || ""))
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/'/g, "")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/).join(" ").trim();
}

/** Prepare an artist name for a provider search:
 * "Various Artists" → "" (compilations match by album), and
 * sort-order "Name, The" → "The Name". Punctuation folded. */
export function normalizeArtistForSearch(artist: string): string {
  const a = normalizePunctuation(artist || "").trim();
  if (!a) return "";
  if (["various artists", "various"].includes(a.toLowerCase())) return "";
  const m = a.match(/^(.+),\s*(The|A|An|Les|La|Le|El|Los|Las|Die|Das|Der)$/i);
  return m ? `${m[2]} ${m[1]}` : a;
}
