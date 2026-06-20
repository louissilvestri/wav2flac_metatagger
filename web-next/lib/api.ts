/** Typed client for the Music Manager FastAPI backend.
 *
 * Same-origin in production (static export served by FastAPI); proxied via
 * next.config rewrites in dev. All calls are plain fetch — React Query
 * handles retry/refetch, which is what makes sleep/wake recovery free.
 */

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch { /* keep default */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const get = <T,>(path: string) => http<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  http<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) =>
  http<T>(path, { method: "PUT", body: JSON.stringify(body) });

// ── Types (the shapes the backend actually returns) ──────────────────────────

export interface Health { name: string; version: string; status: string }

export type Settings = Record<string, unknown> & {
  input_folder?: string;
  output_folder?: string;
  flac_exe_path?: string;
  compression_level?: number;
  verify_encoding?: boolean;
  embed_album_art?: boolean;
  add_replay_gain?: boolean;
  art_max_size?: number;
  multi_disc_style?: string;
  delete_wav_after_convert?: boolean;
  metadata_provider?: string;
};

export interface ScanResult {
  error?: string;
  files: ScannedFile[];
  album_info?: { artist?: string; album?: string; year?: string };
  folder?: string;
  cue_found?: boolean;
  cue_metadata?: CueMetadata | null;
  multi_album?: boolean;
  album_groups?: { album: string; artist: string; file_count: number }[] | null;
}

export interface ScannedFile {
  path: string;
  filename?: string;
  parsed_title?: string;
  parsed_artist?: string;
  parsed_album?: string;
  parsed_track_number?: number;
  isrc?: string;
  [k: string]: unknown;
}

export interface CueMetadata {
  album: Record<string, string>;
  track_count: number;
  tracks: { title?: string; artist?: string; tracknumber?: string; isrc?: string }[];
}

export interface FieldValue {
  value: string | string[];
  source: string;
  candidates: { value: string | string[]; source: string }[];
}

export interface IdentifyResult {
  identity: { method: string; confidence_note?: string };
  fields: Record<string, FieldValue>;
  tracks: IdentifiedTrack[];
  track_source: string;
  art_candidates: ArtCandidate[];
  ids: Record<string, string>;
  providers: Record<string, string>;
  compilation?: boolean;
}

export interface IdentifiedTrack {
  position: number;
  disc_number: number;
  title: string;
  artist: string;
  length_ms?: number | null;
  isrc?: string;
  recording_id?: string;
}

export interface ArtCandidate {
  source: string;
  url: string;
  thumb_url?: string;
  width?: number;
  height?: number;
  likes?: number;
  primary?: boolean;
}

export interface Job {
  id: string;
  type: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
  progress?: { status?: string; current?: number; total?: number; file?: string } | null;
  result?: { completed: number; failed: number; cancelled: boolean; total: number } | null;
  error?: string | null;
}

export interface LibraryFile {
  path: string;
  filename: string;
  artist: string;
  albumartist: string;
  album: string;
  title: string;
  tracknumber: string;
  discnumber: string;
  date: string;
  genre: string;
  has_art: boolean;
  completeness: number;
  missing_fields: string[];
  is_compilation: boolean;
  musicbrainz_albumid: string;
  all_tags: Record<string, string>;
}

export interface LibraryAlbum {
  album: string;
  albumartist: string;
  date: string;
  genre: string;
  label: string;
  catalog_number: string;
  barcode: string;
  country: string;
  musicbrainz_albumid: string;
  has_art: boolean;
  disc_count: number;
  track_count: number;
  avg_completeness: number;
  is_compilation: boolean;
  has_replay_gain: boolean;
  files: LibraryFile[];
}

export interface LibraryScan {
  error?: string;
  albums: LibraryAlbum[];
  total_files: number;
  compilation_tracks: number;
  incomplete_tracks: number;
  duplicate_count: number;
  duplicates: { artist: string; title: string; copies: LibraryFile[] }[];
  output_folder: string;
}

export interface AlbumCandidate {
  release_group_id: string;
  release_id: string;
  album: string;
  artist: string;
  date: string;
  first_release_date: string;
  type: string;
  secondary_types: string[];
  country: string;
  is_original: boolean;
}

export interface ReleaseDetails {
  id: string;
  title: string;
  artist: string;
  artist_id?: string;
  date: string;
  first_release_date?: string;
  genre?: string;
  label?: string;
  catalog_number?: string;
  barcode?: string;
  country?: string;
  compilation?: boolean;
  release_group_id?: string;
  error?: string;
  discs: { position: number; format?: string; tracks: {
    position: number; title: string; artist: string;
    isrc?: string; length_ms?: number | null;
    recording_id?: string; disc_number?: number;
  }[] }[];
}

export interface ReleaseCandidate {
  provider: string;
  id: string;
  title: string;
  artist: string;
  date: string;
  country: string;
  format: string;
  label: string;
  track_count: number;
  disc_count: number;
  recommended: boolean;
}

export interface ReassignPreview {
  changes: { field: string; key: string; old: string; new: string }[];
  current_path: string;
  new_path: string;
  path_changed: boolean;
  current_has_art: boolean;
}

export interface HistoryEntry {
  id: number;
  timestamp: string;
  source_path: string;
  dest_path?: string;
  status: string;
  artist?: string;
  album?: string;
  title?: string;
  duration_ms?: number;
  file_size_before?: number;
  file_size_after?: number;
  error_message?: string;
}

export interface Stats {
  total: number;
  completed: number;
  failed: number;
  total_wav_bytes: number;
  total_flac_bytes: number;
  avg_duration_ms: number | null;
}

// ── Endpoints ─────────────────────────────────────────────────────────────────

export const api = {
  health: () => get<Health>("/api/health"),

  getSettings: () => get<Settings>("/api/settings"),
  updateSettings: (s: Partial<Settings>) => put<{ success: boolean }>("/api/settings", s),
  autodetectFlac: () => post<{ path: string }>("/api/settings/autodetect-flac"),
  browseDialog: (kind: "folder" | "exe" = "folder") =>
    post<{ path: string }>("/api/settings/browse-dialog", { kind }),

  getSecrets: () => get<Record<string, {
    has_keys: boolean; keys: { name: string; value: string }[];
  }>>("/api/secrets"),
  putSecrets: (values: Record<string, string>) =>
    put<{ success: boolean }>("/api/secrets", { values }),
  testSecret: (provider: string) =>
    post<{ ok: boolean; message: string }>(`/api/secrets/test/${provider}`),

  scanInput: (folder_path?: string) => post<ScanResult>("/api/input/scan", { folder_path }),

  identify: (req: {
    artist?: string; album?: string; disc_id?: string; track_count?: number;
    file_paths?: string[]; folder_path?: string;
  }) => post<IdentifyResult>("/api/metadata/identify", req),

  releaseCandidates: (req: {
    artist?: string; album?: string; title?: string; track_count?: number;
    disc_id?: string; folder_path?: string;
  }) => post<ReleaseCandidate[]>("/api/metadata/release-candidates", req),

  startConvert: (req: { files: unknown[]; release_details?: unknown; options?: unknown }) =>
    post<{ job_id: string }>("/api/convert", req),
  getJob: (id: string) => get<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => post<{ cancelled: boolean }>(`/api/jobs/${id}/cancel`),

  history: (limit = 100) => get<HistoryEntry[]>(`/api/history?limit=${limit}`),
  stats: () => get<Stats>("/api/stats"),

  libraryScan: () => get<LibraryScan>("/api/library/scan"),
  rescanLibraryPaths: (paths: string[]) =>
    post<LibraryScan>("/api/library/rescan-paths", { paths }),
  findOriginalAlbum: (artist: string, title: string) =>
    get<AlbumCandidate[]>(`/api/library/original-album?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`),
  getRelease: (id: string) => get<ReleaseDetails>(`/api/releases/${id}`),
  getReleaseArt: (id: string, folder?: string) =>
    get<{ success: boolean; data?: string; source?: string; width?: number; height?: number }>(
      `/api/releases/${id}/art${folder ? `?folder=${encodeURIComponent(folder)}` : ""}`),
  reassignTrack: (req: { path: string; metadata: Record<string, string>;
                         move_file?: boolean; art_release_id?: string | null;
                         art_url?: string | null }) =>
    post<{ success: boolean; new_path: string; error?: string }>("/api/library/reassign", req),
  localArt: (folder?: string) =>
    get<{ success: boolean; data?: string; width?: number; height?: number; source_file?: string }>(
      `/api/input/local-art${folder ? `?folder=${encodeURIComponent(folder)}` : ""}`),
  reassignPreview: (path: string, metadata: Record<string, string>) =>
    post<ReassignPreview>("/api/library/reassign/preview", { path, metadata }),
  deleteLibraryFile: (path: string) =>
    post<{ success: boolean; error?: string }>("/api/library/delete-file", { path }),
  embeddedArt: (path: string) =>
    get<{ success: boolean; data?: string; width?: number; height?: number }>(
      `/api/library/embedded-art?path=${encodeURIComponent(path)}`),
  updateTrackTags: (path: string, changes: Record<string, string | null>) =>
    put<{ success: boolean; error?: string; tags: Record<string, string | string[]> }>(
      "/api/library/tags", { path, changes }),
  replayGain: (paths: string[]) =>
    post<{ success: boolean; processed: number; errors: string[] }>(
      "/api/library/replay-gain", { paths }),
  replayGainLibrary: () =>
    post<{ success: boolean; albums: number; processed: number; skipped: number; errors: string[] }>(
      "/api/library/replay-gain-all"),
  batchReassign: (req: { tracks: unknown[]; album_metadata: Record<string, string>;
                         art_release_id?: string | null; art_url?: string | null }) =>
    post<{ success: boolean; failed: number; total: number;
           results: { path: string; new_path: string; success: boolean; error?: string }[] }>(
      "/api/library/batch-reassign", req),
};

export function fmtBytes(n?: number | null): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(n) / Math.log(1024));
  return `${(n / 1024 ** i).toFixed(1)} ${units[i]}`;
}

export function fmtDuration(ms?: number | null): string {
  if (!ms) return "–";
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
