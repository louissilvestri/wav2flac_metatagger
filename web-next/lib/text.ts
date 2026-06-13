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

/** Fold for equality/contains checks: punctuation normalized, lowercased,
 * whitespace collapsed. Use on BOTH haystack and needle. */
export function foldForCompare(s: string): string {
  return normalizePunctuation(s || "").toLowerCase().split(/\s+/).join(" ").trim();
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
