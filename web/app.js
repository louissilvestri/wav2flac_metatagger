// Music Manager - Frontend Application Logic

let currentFiles = [];
let currentReleaseDetails = null;
let selectedReleaseId = null;
let albumArtData = null;
let albumArtSource = null;
let currentCueMetadata = null;
let currentFolder = '';
let manualDiscOverride = null;  // User's explicit disc selection (null = auto-detect)

// ─── WebSocket Reconnection (sleep/wake recovery) ─────────────────────────────
// The Python server runs on a fixed port and stays alive indefinitely.
// If the WebSocket drops (sleep/wake), we just reload the page to reconnect.

(function initReconnectionMonitor() {
    let lastHeartbeat = Date.now();
    let reconnecting = false;

    // Detect sleep/wake: if a 1s interval fires after a long gap, system was asleep
    setInterval(() => {
        const now = Date.now();
        const elapsed = now - lastHeartbeat;
        lastHeartbeat = now;

        if (elapsed > 5000 && !reconnecting) {
            checkConnection();
        }
    }, 1000);

    // Also check when tab becomes visible again or network comes back
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) setTimeout(checkConnection, 500);
    });
    window.addEventListener('online', () => setTimeout(checkConnection, 1000));

    async function checkConnection() {
        if (reconnecting) return;
        try {
            await eel.get_settings()();
        } catch (e) {
            reconnecting = true;
            showBanner('Connection lost — reconnecting...');
            attemptReload();
        }
    }

    function showBanner(text) {
        let banner = document.getElementById('reconnect-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'reconnect-banner';
            banner.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
                background: var(--warning, #f59e0b); color: #000; text-align: center;
                padding: 8px; font-size: 13px; font-weight: 500;
            `;
            document.body.prepend(banner);
        }
        banner.textContent = text;
        banner.style.display = 'block';
    }

    async function attemptReload(attempts = 0) {
        // Check if the server is reachable via a plain fetch (no WebSocket needed)
        try {
            const resp = await fetch(`/index.html`, {cache: 'no-store'});
            if (resp.ok) {
                // Server is alive — reload to get a fresh WebSocket
                window.location.reload();
                return;
            }
        } catch (e) {
            // Server not ready yet
        }

        if (attempts < 30) {
            setTimeout(() => attemptReload(attempts + 1), 2000);
        } else {
            showBanner('Could not reconnect. Please restart the app.');
        }
    }
})();

// ─── Navigation ────────────────────────────────────────────────────────────────

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = link.dataset.page;
        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById(`page-${page}`).classList.add('active');

        if (page === 'history') loadHistory();
        if (page === 'library') initLibraryPage();
        if (page === 'settings') loadSettingsUI();
    });
});

// ─── Initialize ────────────────────────────────────────────────────────────────

async function init() {
    try {
        const info = await eel.get_app_info()();
        document.getElementById('app-version').textContent = `v${info.version}`;
        const settings = await eel.get_settings()();
        if (settings.input_folder) {
            document.getElementById('input-folder').value = settings.input_folder;
        }
    } catch (e) {
        console.error('Init error:', e);
    }
}

init();

// ─── Step 1: Source Files ──────────────────────────────────────────────────────

async function browseInputFolder() {
    const path = await eel.browse_folder('folder')();
    if (path) {
        document.getElementById('input-folder').value = path;
        await eel.update_settings({ input_folder: path })();
    }
}

async function scanFolder() {
    const folder = document.getElementById('input-folder').value;
    if (!folder) {
        showToast('Please select an input folder first', 'error');
        return;
    }

    // Reset state
    currentReleaseDetails = null;
    selectedReleaseId = null;
    albumArtData = null;
    albumArtSource = null;
    currentCueMetadata = null;
    manualDiscOverride = null;
    document.getElementById('search-results').classList.add('hidden');
    document.getElementById('release-details').classList.add('hidden');
    document.getElementById('disc-selector').classList.add('hidden');
    document.getElementById('cascade-log').classList.add('hidden');
    document.getElementById('cue-status').classList.add('hidden');
    document.getElementById('art-comparison').classList.add('hidden');
    document.getElementById('metadata-completeness').classList.add('hidden');

    const result = await eel.scan_input_folder(folder)();
    if (result.error) {
        showToast(result.error, 'error');
        return;
    }

    currentFiles = result.files;
    currentFolder = result.folder;
    renderFileList(result.files, result.album_groups);

    // Pre-fill manual search fields from whatever source is available
    const albumInfo = result.album_info;
    if (albumInfo.artist) document.getElementById('search-artist').value = normalizeArtistForSearch(albumInfo.artist);
    if (albumInfo.album) document.getElementById('search-album').value = albumInfo.album;

    // Multi-album warning
    if (result.multi_album && result.album_groups) {
        const names = result.album_groups.map(g => `"${g.album}" (${g.file_count} tracks)`).join(', ');
        showToast(`Detected ${result.album_groups.length} albums: ${names}`, 'success');
    }

    // If CUE sheet found, show it and run automated lookup
    if (result.cue_found) {
        currentCueMetadata = result.cue_metadata;
        showCueStatus(result.cue_metadata, result.cue_path);
        runAutomatedLookup(result.folder);
    } else {
        showNoCueStatus();
    }

    updateConvertButton();
}

function renderFileList(files, albumGroups) {
    const container = document.getElementById('file-list-container');
    const list = document.getElementById('file-list');
    const count = document.getElementById('file-count');

    container.classList.remove('hidden');

    if (albumGroups && albumGroups.length > 1) {
        count.textContent = `${files.length} WAV files in ${albumGroups.length} albums`;
    } else {
        count.textContent = `${files.length} WAV file${files.length !== 1 ? 's' : ''} found`;
    }

    let html = '';
    let currentAlbum = null;

    files.forEach((f, i) => {
        // Show album separator when parsed_album changes (for multi-album folders)
        if (albumGroups && albumGroups.length > 1 && f.parsed_album !== currentAlbum) {
            currentAlbum = f.parsed_album;
            html += `<div class="file-item" style="background:var(--bg-hover); font-weight:600; font-size:12px; color:var(--accent);">
                ${escapeHtml(f.parsed_artist || '')} — ${escapeHtml(f.parsed_album || 'Unknown Album')}
            </div>`;
        }
        const isrc = f.isrc ? `<span class="isrc-tag" title="ISRC: ${f.isrc}">ISRC</span>` : '';
        html += `
            <div class="file-item">
                <span class="track-num">${f.parsed_track_number || (i + 1)}</span>
                <span class="track-title">${escapeHtml(f.parsed_title || f.filename)} ${isrc}</span>
                <span class="file-size">${formatBytes(f.size)}</span>
            </div>
        `;
    });

    list.innerHTML = html;
}

// ─── CUE Sheet Status ──────────────────────────────────────────────────────────

function showCueStatus(cueMeta, cuePath) {
    const statusDiv = document.getElementById('cue-status');
    const badge = document.getElementById('cue-badge');
    const badgeText = document.getElementById('cue-badge-text');
    const info = document.getElementById('cue-info');

    statusDiv.classList.remove('hidden');
    badge.className = 'cue-badge success';
    badgeText.textContent = 'CUE sheet detected';

    const album = cueMeta.album;
    let infoHtml = '';
    if (album.artist) infoHtml += `<strong>Artist:</strong> ${escapeHtml(album.artist)}<br>`;
    if (album.album) infoHtml += `<strong>Album:</strong> ${escapeHtml(album.album)}<br>`;
    if (album.date) infoHtml += `<strong>Date:</strong> ${escapeHtml(album.date)}<br>`;
    if (album.genre) infoHtml += `<strong>Genre:</strong> ${escapeHtml(album.genre)}<br>`;
    if (album.barcode) infoHtml += `<strong>Barcode:</strong> ${album.barcode}<br>`;
    infoHtml += `<strong>Tracks:</strong> ${cueMeta.track_count}`;

    const isrcCount = cueMeta.tracks.filter(t => t.isrc).length;
    if (isrcCount > 0) infoHtml += ` (${isrcCount} with ISRC codes)`;

    info.innerHTML = infoHtml;

    // Hide manual search by default when CUE is found
    document.getElementById('manual-search-section').classList.add('hidden');
}

function showNoCueStatus() {
    const statusDiv = document.getElementById('cue-status');
    const badge = document.getElementById('cue-badge');
    const badgeText = document.getElementById('cue-badge-text');
    const info = document.getElementById('cue-info');

    statusDiv.classList.remove('hidden');
    badge.className = 'cue-badge warning';
    badgeText.textContent = 'No CUE sheet found';
    info.innerHTML = 'Use <strong>Action → Create CUE Sheet</strong> in EAC for automated lookup, or search manually below.';

    // Show manual search
    document.getElementById('manual-search-section').classList.remove('hidden');
}

// ─── Automated Lookup Cascade ──────────────────────────────────────────────────

async function runAutomatedLookup(folderPath) {
    const cascadeDiv = document.getElementById('cascade-log');
    cascadeDiv.classList.remove('hidden');
    cascadeDiv.innerHTML = '<div class="cascade-step"><span class="step-icon searching">⟳</span><span class="step-detail">Running automated lookup...</span></div>';

    const result = await eel.run_automated_lookup(folderPath)();

    if (result.error) {
        cascadeDiv.innerHTML = `<div class="cascade-step"><span class="step-icon no_match">✕</span><span class="step-detail" style="color:var(--danger)">${escapeHtml(result.error)}</span></div>`;
        document.getElementById('manual-search-section').classList.remove('hidden');
        return;
    }

    // Render cascade log
    renderCascadeLog(result.cascade_log, result.disc_id);

    if (result.best_match) {
        const method = result.match_method;
        const isConfidentMatch = (method === 'disc_id' || method === 'barcode');

        if (isConfidentMatch) {
            // Auto-select only for high-confidence matches
            showToast(`Matched via ${formatMatchMethod(method)}`, 'success');
            if (result.releases.length > 1) {
                renderSearchResults(result.releases);
            }
            await selectRelease(result.best_match.id, null);
        } else {
            // Text search results are not reliable enough to auto-select.
            // Show them as suggestions for the user to pick from.
            showToast('Possible matches found — please verify', 'info');
            renderSearchResults(result.releases);
            document.getElementById('manual-search-section').classList.remove('hidden');
            cascadeDiv.innerHTML += '<div class="cascade-step" style="margin-top:8px; color:var(--text-secondary); font-size:12px">Text search results shown below. Select the correct release, or convert using EAC metadata only.</div>';
        }
    } else if (result.gnudb_result) {
        // GnuDB found metadata — enrich the CUE/file data with it
        applyGnudbResult(result.gnudb_result);
        showToast('Matched via GnuDB (freedb)', 'success');
        updateConvertButton();
    } else {
        cascadeDiv.innerHTML += '<div class="cascade-step" style="margin-top:8px; color:var(--text-secondary); font-size:12px">No matches found. You can search manually or convert using EAC metadata.</div>';
        document.getElementById('manual-search-section').classList.remove('hidden');
    }
}

function renderCascadeLog(log, discId) {
    const cascadeDiv = document.getElementById('cascade-log');
    const METHOD_LABELS = {
        disc_id: 'Disc ID',
        barcode: 'Barcode',
        gnudb: 'GnuDB',
        toc: 'TOC',
        text: 'Text Search',
    };
    const STATUS_ICONS = {
        found: '✓',
        no_match: '—',
        searching: '⟳',
        skipped: '○',
    };

    let html = '';
    if (discId) {
        html += `<div class="cascade-step"><span class="step-icon" style="color:var(--text-muted)">●</span><span class="step-method">Disc ID</span><span class="step-detail" style="font-family:monospace; font-size:11px">${escapeHtml(discId)}</span></div>`;
    }

    for (const step of log) {
        const icon = STATUS_ICONS[step.status] || '?';
        const method = METHOD_LABELS[step.method] || step.method;
        let detail = step.query || '';
        let resultText = '';

        if (step.status === 'found') {
            resultText = `<span class="step-result found">${step.count} match${step.count !== 1 ? 'es' : ''}</span>`;
        } else if (step.status === 'no_match') {
            resultText = `<span class="step-result no_match">no match</span>`;
        }

        html += `
            <div class="cascade-step">
                <span class="step-icon ${step.status}">${icon}</span>
                <span class="step-method">${method}</span>
                <span class="step-detail">${escapeHtml(detail)}</span>
                ${resultText}
            </div>
        `;
    }

    // Add toggle for manual search
    html += `
        <div class="manual-search-toggle">
            <button onclick="toggleManualSearch()">Manual search...</button>
        </div>
    `;

    cascadeDiv.innerHTML = html;
}

function toggleManualSearch() {
    const section = document.getElementById('manual-search-section');
    section.classList.toggle('hidden');
}

function formatMatchMethod(method) {
    const labels = {
        disc_id: 'Disc ID (exact match)',
        barcode: 'barcode',
        gnudb: 'GnuDB/freedb',
        toc: 'TOC (fuzzy match)',
        text: 'text search',
    };
    return labels[method] || method;
}

function applyGnudbResult(gnudb) {
    /**
     * Apply GnuDB metadata to the current files when MusicBrainz had no match.
     * Enriches parsed_title, parsed_artist, parsed_album on each file and updates CUE metadata.
     */
    if (!gnudb || !gnudb.tracks) return;

    // Update CUE metadata with GnuDB data
    if (currentCueMetadata) {
        if (gnudb.artist) currentCueMetadata.album.artist = gnudb.artist;
        if (gnudb.album) currentCueMetadata.album.album = gnudb.album;
        if (gnudb.year) currentCueMetadata.album.date = gnudb.year;
        if (gnudb.genre) currentCueMetadata.album.genre = gnudb.genre;

        // Update track titles from GnuDB
        for (let i = 0; i < gnudb.tracks.length && i < currentCueMetadata.tracks.length; i++) {
            if (gnudb.tracks[i].title) {
                currentCueMetadata.tracks[i].title = gnudb.tracks[i].title;
            }
            if (gnudb.tracks[i].artist && gnudb.tracks[i].artist !== gnudb.artist) {
                currentCueMetadata.tracks[i].artist = gnudb.tracks[i].artist;
            }
        }
    }

    // Update file entries
    for (let i = 0; i < currentFiles.length; i++) {
        if (i < gnudb.tracks.length) {
            currentFiles[i].parsed_title = gnudb.tracks[i].title || currentFiles[i].parsed_title;
            currentFiles[i].parsed_artist = gnudb.tracks[i].artist || gnudb.artist || currentFiles[i].parsed_artist;
        }
        currentFiles[i].parsed_album = gnudb.album || currentFiles[i].parsed_album;
    }

    // Re-render the file list with updated info
    renderFileList(currentFiles, null);

    // Show GnuDB match info in the release details area
    const detailsDiv = document.getElementById('release-details');
    let tracksHtml = '';
    for (let i = 0; i < gnudb.tracks.length; i++) {
        const t = gnudb.tracks[i];
        const artistCol = t.artist !== gnudb.artist
            ? `<td style="width:100px; color:var(--text-muted); font-size:12px">${escapeHtml(t.artist)}</td>`
            : '<td></td>';
        tracksHtml += `<tr><td style="width:40px; color:var(--text-muted)">${i + 1}</td><td>${escapeHtml(t.title)}</td>${artistCol}</tr>`;
    }

    detailsDiv.innerHTML = `
        <div class="release-header">
            <div class="release-art">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="var(--text-muted)"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
            </div>
            <div class="release-info">
                <h3>${escapeHtml(gnudb.album)}</h3>
                <p>${escapeHtml(gnudb.artist)}</p>
                <p>${gnudb.year || 'Unknown date'}${gnudb.genre ? ' • ' + escapeHtml(gnudb.genre) : ''}</p>
                <p style="color:var(--success); font-size:12px">Matched via GnuDB/freedb (same database as EAC)</p>
            </div>
        </div>
        <div class="track-list">
            <table>
                <thead><tr><th>#</th><th>Title</th><th>Artist</th></tr></thead>
                <tbody>${tracksHtml}</tbody>
            </table>
        </div>
    `;
    detailsDiv.classList.remove('hidden');
}

// ─── Step 2: Metadata (manual + results) ───────────────────────────────────────

async function searchMetadata() {
    const artist = normalizeArtistForSearch(document.getElementById('search-artist').value.trim());
    const album = document.getElementById('search-album').value.trim();

    if (!artist && !album) {
        showToast('Enter at least an artist or album name', 'error');
        return;
    }

    const resultsDiv = document.getElementById('search-results');
    resultsDiv.classList.remove('hidden');
    resultsDiv.innerHTML = '<p style="color: var(--text-muted)">Searching...</p>';

    const trackCount = currentFiles.length || null;
    const results = await eel.lookup_metadata(artist, album, trackCount)();

    if (results.length === 0 || results[0]?.error) {
        resultsDiv.innerHTML = '<p style="color: var(--text-muted)">No results found. Try different search terms.</p>';
        return;
    }

    renderSearchResults(results);
}

function renderSearchResults(results) {
    const resultsDiv = document.getElementById('search-results');
    resultsDiv.classList.remove('hidden');

    resultsDiv.innerHTML = results.slice(0, 8).map(r => {
        const matchBadge = r.match_method
            ? `<span class="result-badge" style="background:var(--accent-dim); color:var(--accent)">${formatMatchMethod(r.match_method)}</span>`
            : `<span class="result-badge">${r.format || 'Unknown'}</span>`;
        return `
            <div class="result-item" onclick="selectRelease('${r.id}', this)">
                <div class="result-info">
                    <div class="result-title">${escapeHtml(r.title)}</div>
                    <div class="result-meta">
                        ${escapeHtml(r.artist)} &bull;
                        ${r.date || 'Unknown date'} &bull;
                        ${r.total_tracks || '?'} tracks &bull;
                        ${r.country || '??'}
                    </div>
                </div>
                ${matchBadge}
            </div>
        `;
    }).join('');
}

async function selectRelease(releaseId, element) {
    // Highlight selected
    document.querySelectorAll('.result-item').forEach(el => el.classList.remove('selected'));
    if (element) element.classList.add('selected');

    selectedReleaseId = releaseId;
    const detailsDiv = document.getElementById('release-details');
    detailsDiv.classList.remove('hidden');
    detailsDiv.innerHTML = '<p style="color: var(--text-muted)">Loading release details...</p>';

    // Fetch details and art in parallel
    const [details, artResult] = await Promise.all([
        eel.fetch_release_details(releaseId)(),
        eel.fetch_album_art(releaseId, currentFolder)(),
    ]);

    if (details.error) {
        detailsDiv.innerHTML = `<p style="color: var(--danger)">Error: ${escapeHtml(details.error)}</p>`;
        return;
    }

    currentReleaseDetails = details;
    albumArtData = artResult.success ? artResult.data : null;
    albumArtSource = artResult.success ? artResult.source : null;

    // Merge ISRC codes from CUE sheet into release details if MusicBrainz didn't have them
    if (currentCueMetadata) {
        for (const disc of details.discs || []) {
            for (const track of disc.tracks || []) {
                if (!track.isrc) {
                    const cueTrackIdx = track.position - 1;
                    if (cueTrackIdx < currentCueMetadata.tracks.length) {
                        const cueIsrc = currentCueMetadata.tracks[cueTrackIdx].isrc;
                        if (cueIsrc) track.isrc = cueIsrc;
                    }
                }
            }
        }
    }

    renderReleaseDetails(details, albumArtData);
    showDiscSelector(details);
    renderArtComparison(artResult);
    loadMetadataCompleteness();
    updateConvertButton();
}

function renderReleaseDetails(details, artBase64) {
    const detailsDiv = document.getElementById('release-details');
    const artHtml = artBase64
        ? `<img src="data:image/jpeg;base64,${artBase64}" alt="Album Art">`
        : '<svg viewBox="0 0 24 24" width="48" height="48" fill="var(--text-muted)"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>';

    let tracksHtml = '';
    for (const disc of details.discs) {
        if (details.discs.length > 1) {
            tracksHtml += `<tr><td colspan="4" style="font-weight:600; padding-top:12px;">Disc ${disc.position}</td></tr>`;
        }
        for (const track of disc.tracks) {
            const isrcHtml = track.isrc ? `<span class="isrc-tag" title="${track.isrc}">ISRC</span>` : '';
            tracksHtml += `
                <tr>
                    <td style="width:40px; color:var(--text-muted)">${track.position}</td>
                    <td>${escapeHtml(track.title)} ${isrcHtml}</td>
                    <td style="width:100px; color:var(--text-muted); font-size:12px">${escapeHtml(track.artist !== details.artist ? track.artist : '')}</td>
                    <td style="width:60px; color:var(--text-muted)">${formatDuration(track.length_ms)}</td>
                </tr>
            `;
        }
    }

    const matchInfo = currentReleaseDetails?._matchMethod
        ? `<p style="color:var(--success); font-size:12px">Matched via ${formatMatchMethod(currentReleaseDetails._matchMethod)}</p>`
        : '';

    detailsDiv.innerHTML = `
        <div class="release-header">
            <div class="release-art">${artHtml}</div>
            <div class="release-info">
                <h3>${escapeHtml(details.title)}</h3>
                <p>${escapeHtml(details.artist)}</p>
                <p>${details.date || 'Unknown date'} &bull; ${details.label || 'Unknown label'}</p>
                <p>${details.discs.length} disc${details.discs.length > 1 ? 's' : ''} &bull; ${details.barcode || 'No barcode'}${details.catalog_number ? ' &bull; ' + escapeHtml(details.catalog_number) : ''}</p>
                ${matchInfo}
            </div>
        </div>
        <div class="track-list">
            <table>
                <thead><tr><th>#</th><th>Title</th><th>Artist</th><th>Length</th></tr></thead>
                <tbody>${tracksHtml}</tbody>
            </table>
        </div>
    `;
}

// ─── Art Comparison ────────────────────────────────────────────────────────────

let _convertArtCandidates = [];  // Store candidates for selection

function renderArtComparison(artResult) {
    const div = document.getElementById('art-comparison');

    if (!artResult || !artResult.success) {
        div.classList.remove('hidden');
        div.innerHTML = `
            <h4>Album Art</h4>
            <p style="color:var(--text-muted); font-size:12px;">No artwork found.</p>
        `;
        _convertArtCandidates = [];
        return;
    }

    div.classList.remove('hidden');
    _convertArtCandidates = artResult.candidates || [];

    const SOURCE_LABELS = {
        coverartarchive: 'Cover Art Archive',
        discogs: 'Discogs',
        local: 'Local (EAC)',
    };

    // Show all candidates as selectable thumbnails
    let optionsHtml = '';
    const candidates = artResult.candidates && artResult.candidates.length > 0
        ? artResult.candidates
        : [{source: artResult.source, width: artResult.width, height: artResult.height, selected: true, thumb: artResult.data}];

    candidates.forEach((c, idx) => {
        const label = SOURCE_LABELS[c.source] || c.source || 'Unknown';
        const thumbSrc = c.thumb
            ? `<img src="data:image/jpeg;base64,${c.thumb}" alt="${escapeHtml(label)}">`
            : `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:11px;">${c.width}×${c.height}</div>`;
        optionsHtml += `
            <div class="art-option ${c.selected ? 'selected recommended' : ''}" onclick="selectConvertArt(${idx})"
                 title="${escapeHtml(label)} (${c.width}×${c.height})">
                <div class="art-option-img">${thumbSrc}</div>
                <div class="art-option-label">
                    <span class="art-option-country">${escapeHtml(label)}</span>
                    <span class="art-option-format">${c.width}×${c.height}</span>
                </div>
                ${c.selected ? '<div class="art-option-badge">Selected</div>' : ''}
            </div>
        `;
    });

    // "No art" option
    optionsHtml += `
        <div class="art-option" onclick="selectConvertArt(-1)"
             title="Don't embed artwork">
            <div class="art-option-img" style="display:flex; align-items:center; justify-content:center;">
                <span style="font-size:20px; color:var(--text-muted);">✕</span>
            </div>
            <div class="art-option-label">
                <span class="art-option-country">No Art</span>
                <span class="art-option-format">Skip</span>
            </div>
        </div>
    `;

    div.innerHTML = `
        <h4>Album Art</h4>
        <div class="art-options-row">${optionsHtml}</div>
    `;
}

async function selectConvertArt(candidateIdx) {
    const div = document.getElementById('art-comparison');
    div.querySelectorAll('.art-option').forEach(el => {
        el.classList.remove('selected');
        // Remove badge from all
        const badge = el.querySelector('.art-option-badge');
        if (badge) badge.remove();
    });

    const options = div.querySelectorAll('.art-option');

    if (candidateIdx === -1) {
        // No art
        albumArtData = null;
        albumArtSource = null;
        options[options.length - 1]?.classList.add('selected');
    } else {
        const c = _convertArtCandidates[candidateIdx];
        if (c) {
            // If this candidate was auto-selected (has full data), use it directly
            // Otherwise re-fetch art preferring this source
            if (c.selected) {
                // Already the winner — data is in albumArtData
            } else {
                // Fetch full-res art for this candidate
                // For now, re-fetch using the release ID — the backend picks highest res
                // The user selected a non-default, so we need to re-fetch
                try {
                    const artResult = await eel.fetch_album_art(selectedReleaseId, currentFolder)();
                    if (artResult.success) {
                        albumArtData = artResult.data;
                        albumArtSource = c.source;
                    }
                } catch (e) { /* use whatever we had */ }
            }
            albumArtSource = c.source;
            options[candidateIdx]?.classList.add('selected');

            // Add badge
            const selected = options[candidateIdx];
            if (selected && !selected.querySelector('.art-option-badge')) {
                selected.insertAdjacentHTML('beforeend', '<div class="art-option-badge">Selected</div>');
            }
        }
    }

    // Update the album art preview in the release header
    const artImg = document.querySelector('.release-art img');
    if (artImg && albumArtData) {
        artImg.src = `data:image/jpeg;base64,${albumArtData}`;
    }

    loadMetadataCompleteness();
}

// ─── Metadata Completeness ─────────────────────────────────────────────────────

async function loadMetadataCompleteness() {
    const div = document.getElementById('metadata-completeness');
    const hasArt = !!albumArtData;

    const result = await eel.get_metadata_completeness(
        currentReleaseDetails, currentCueMetadata, hasArt
    )();

    if (!result.tracks || result.tracks.length === 0) {
        div.classList.add('hidden');
        return;
    }

    div.classList.remove('hidden');
    const pctClass = result.album_average >= 80 ? 'high' : result.album_average >= 50 ? 'medium' : 'low';

    let tracksHtml = '';
    result.tracks.forEach((t, idx) => {
        const tPctClass = t.percentage >= 80 ? 'high' : t.percentage >= 50 ? 'medium' : 'low';

        // Field detail chips
        const fieldChips = Object.entries(t.fields).map(([name, info]) => {
            const icon = info.status === 'filled' ? '✓' : '✕';
            const displayName = name.replace('MUSICBRAINZ_', 'MB_');
            return `<span class="field-chip ${info.status}"><span class="chip-icon">${icon}</span>${displayName}</span>`;
        }).join('');

        tracksHtml += `
            <div class="completeness-track">
                <span class="ct-num">${t.track_number}</span>
                <span class="ct-title">${escapeHtml(t.title || 'Unknown')}</span>
                <span class="ct-bar-container">
                    <div class="ct-bar"><div class="ct-bar-fill ${tPctClass}" style="width:${t.percentage}%"></div></div>
                </span>
                <span class="ct-pct ${tPctClass}">${t.percentage}%</span>
                <button class="ct-detail-btn" onclick="toggleFieldDetail(${idx})" title="Show fields">▸</button>
            </div>
            <div class="ct-fields-detail" id="fields-detail-${idx}">${fieldChips}</div>
        `;
    });

    div.innerHTML = `
        <div class="completeness-header">
            <h4>Plex Metadata Completeness</h4>
            <div class="album-completeness">
                <span class="completeness-pct ${pctClass}">${result.album_average}%</span>
                <span class="completeness-label">album avg<br>${result.plex_field_count} fields tracked</span>
            </div>
        </div>
        <div class="completeness-track-list">${tracksHtml}</div>
    `;
}

function toggleFieldDetail(idx) {
    const detail = document.getElementById(`fields-detail-${idx}`);
    if (detail) {
        detail.classList.toggle('visible');
    }
}

// ─── Step 3: Conversion ────────────────────────────────────────────────────────

function updateConvertButton() {
    const btn = document.getElementById('btn-convert');
    const summary = document.getElementById('convert-summary');

    if (currentFiles.length === 0) {
        btn.disabled = true;
        summary.innerHTML = '<p>Scan a folder to find WAV files to convert.</p>';
        return;
    }

    btn.disabled = false;

    let metaSource;
    if (currentReleaseDetails) {
        metaSource = `MusicBrainz: <strong>${escapeHtml(currentReleaseDetails.title)}</strong> by ${escapeHtml(currentReleaseDetails.artist)}`;
    } else if (currentCueMetadata) {
        metaSource = `CUE sheet: <strong>${escapeHtml(currentCueMetadata.album.album)}</strong> by ${escapeHtml(currentCueMetadata.album.artist)}`;
    } else {
        metaSource = 'filename parsing (no CUE or MusicBrainz match)';
    }

    summary.innerHTML = `
        <p><strong>${currentFiles.length}</strong> files ready for conversion</p>
        <p>Metadata: ${metaSource}</p>
        ${albumArtData
            ? `<p>Album art: ${albumArtSource === 'local' ? 'local file (EAC)' : albumArtSource === 'discogs' ? 'Discogs' : 'Cover Art Archive'}</p>`
            : '<p style="color:var(--text-muted)">Album art: none found</p>'}
    `;
}

function showDiscSelector(releaseDetails) {
    /**
     * Show a disc selector dropdown when the release has multiple discs.
     * Auto-detects which disc the current files belong to and pre-selects it.
     * User can override if auto-detection is wrong.
     */
    const container = document.getElementById('disc-selector');
    const select = document.getElementById('disc-select');
    const hint = document.getElementById('disc-selector-hint');

    if (!releaseDetails || !releaseDetails.discs || releaseDetails.discs.length <= 1) {
        container.classList.add('hidden');
        manualDiscOverride = null;
        return;
    }

    const discs = releaseDetails.discs.sort((a, b) => a.position - b.position);
    const totalReleaseTracks = discs.reduce((sum, d) => sum + d.tracks.length, 0);

    // Don't show selector if file count matches total (user ripped all discs)
    if (currentFiles.length >= totalReleaseTracks) {
        container.classList.add('hidden');
        manualDiscOverride = null;
        return;
    }

    // Auto-detect which disc (same logic as assignTracksToDiscs)
    let autoDetected = null;
    let detectionMethod = '';

    // Check CUE
    if (currentCueMetadata?.album?.discnumber) {
        const cueDiscNum = parseInt(currentCueMetadata.album.discnumber, 10);
        if (cueDiscNum > 0) {
            autoDetected = cueDiscNum;
            detectionMethod = 'CUE sheet';
        }
    }

    // Check track count
    if (!autoDetected) {
        const matchingDiscs = discs.filter(d => d.tracks.length === currentFiles.length);
        if (matchingDiscs.length === 1) {
            autoDetected = matchingDiscs[0].position;
            detectionMethod = 'track count';
        }
    }

    // Build options
    select.innerHTML = '';
    const autoOption = document.createElement('option');
    autoOption.value = 'auto';
    autoOption.textContent = 'Auto-detect';
    select.appendChild(autoOption);

    for (const disc of discs) {
        const opt = document.createElement('option');
        opt.value = disc.position;
        opt.textContent = `Disc ${disc.position} (${disc.tracks.length} tracks)`;
        select.appendChild(opt);
    }

    // Pre-select auto-detected disc
    if (autoDetected) {
        select.value = String(autoDetected);
        hint.textContent = `Auto-detected via ${detectionMethod}`;
        hint.className = 'disc-selector-hint auto-detected';
    } else {
        select.value = 'auto';
        hint.textContent = `${currentFiles.length} files — select which disc you ripped`;
        hint.className = 'disc-selector-hint';
    }

    // Event handler
    select.onchange = () => {
        if (select.value === 'auto') {
            manualDiscOverride = null;
            hint.textContent = autoDetected
                ? `Auto-detected via ${detectionMethod}`
                : 'Will attempt auto-detection';
            hint.className = 'disc-selector-hint' + (autoDetected ? ' auto-detected' : '');
        } else {
            manualDiscOverride = parseInt(select.value, 10);
            hint.textContent = `Manually set to disc ${manualDiscOverride}`;
            hint.className = 'disc-selector-hint';
        }
    };

    container.classList.remove('hidden');
}

function assignTracksToDiscs(files, releaseDetails, cueMetadata) {
    /**
     * Map WAV files to disc/track numbers using MusicBrainz release details.
     *
     * Handles partial rips (e.g. only disc 2 of a 2-disc set) by:
     * 1. Checking the CUE sheet's REM DISCNUMBER field
     * 2. Matching file count to a specific disc's track count
     * 3. Matching track titles against MusicBrainz data per disc
     * 4. Falling back to sequential fill only if files span all discs
     */
    if (!releaseDetails || !releaseDetails.discs || releaseDetails.discs.length === 0) {
        // No release data — use manual override, CUE, or default to disc 1
        const discNum = manualDiscOverride
            || (cueMetadata?.album?.discnumber ? parseInt(cueMetadata.album.discnumber, 10) || 1 : 1);
        return files.map((f, i) => ({
            path: f.path,
            track_number: f.parsed_track_number || (i + 1),
            disc_number: discNum,
            parsed_title: f.parsed_title,
            parsed_artist: f.parsed_artist,
            parsed_album: f.parsed_album,
        }));
    }

    const discs = releaseDetails.discs.sort((a, b) => a.position - b.position);
    const totalReleaseTracks = discs.reduce((sum, d) => sum + d.tracks.length, 0);

    // --- Detect if this is a partial rip (subset of discs) ---

    // Signal 0: User manually selected a disc in the UI
    let detectedDiscNum = manualDiscOverride;

    // Signal 1: CUE sheet has explicit disc number
    if (!detectedDiscNum && cueMetadata?.album?.discnumber) {
        const cueDiscNum = parseInt(cueMetadata.album.discnumber, 10);
        if (cueDiscNum > 0) {
            detectedDiscNum = cueDiscNum;
        }
    }

    // Signal 2: File count matches exactly one disc's track count (but not total)
    if (!detectedDiscNum && files.length < totalReleaseTracks) {
        const matchingDiscs = discs.filter(d => d.tracks.length === files.length);
        if (matchingDiscs.length === 1) {
            detectedDiscNum = matchingDiscs[0].position;
        } else if (matchingDiscs.length > 1) {
            // Multiple discs have the same track count — try title matching
            detectedDiscNum = _matchDiscByTitles(files, matchingDiscs);
        }
    }

    // Signal 3: File count doesn't match any single disc exactly but is less than total
    // Try title matching across all discs
    if (!detectedDiscNum && files.length < totalReleaseTracks) {
        detectedDiscNum = _matchDiscByTitles(files, discs);
    }

    // --- If we detected a specific disc, assign all files to it ---
    if (detectedDiscNum) {
        const targetDisc = discs.find(d => d.position === detectedDiscNum);
        if (targetDisc) {
            return files.map((f, i) => ({
                path: f.path,
                track_number: i < targetDisc.tracks.length
                    ? targetDisc.tracks[i].position
                    : (i + 1),
                disc_number: detectedDiscNum,
                parsed_title: f.parsed_title,
                parsed_artist: f.parsed_artist,
                parsed_album: f.parsed_album,
            }));
        }
    }

    // --- Full set: distribute files sequentially across all discs ---
    const result = [];
    let fileIdx = 0;

    for (const disc of discs) {
        const tracksOnDisc = disc.tracks.length;
        for (let t = 0; t < tracksOnDisc && fileIdx < files.length; t++) {
            const f = files[fileIdx];
            result.push({
                path: f.path,
                track_number: disc.tracks[t].position,
                disc_number: disc.position,
                parsed_title: f.parsed_title,
                parsed_artist: f.parsed_artist,
                parsed_album: f.parsed_album,
            });
            fileIdx++;
        }
    }

    // Any remaining files (more WAVs than release tracks) — append to last disc
    while (fileIdx < files.length) {
        const f = files[fileIdx];
        const lastDisc = discs[discs.length - 1];
        result.push({
            path: f.path,
            track_number: fileIdx + 1,
            disc_number: lastDisc.position,
            parsed_title: f.parsed_title,
            parsed_artist: f.parsed_artist,
            parsed_album: f.parsed_album,
        });
        fileIdx++;
    }

    return result;
}

function _matchDiscByTitles(files, candidateDiscs) {
    /**
     * Try to determine which disc the files belong to by comparing
     * parsed track titles against MusicBrainz track titles.
     * Returns the disc position number or null if no clear match.
     */
    let bestDisc = null;
    let bestScore = 0;

    for (const disc of candidateDiscs) {
        let matches = 0;
        for (let i = 0; i < Math.min(files.length, disc.tracks.length); i++) {
            const fileTitle = (files[i].parsed_title || '').toLowerCase().trim();
            const mbTitle = (disc.tracks[i].title || '').toLowerCase().trim();
            if (fileTitle && mbTitle && (
                fileTitle === mbTitle ||
                fileTitle.includes(mbTitle) ||
                mbTitle.includes(fileTitle)
            )) {
                matches++;
            }
        }
        if (matches > bestScore) {
            bestScore = matches;
            bestDisc = disc.position;
        }
    }

    // Only return if we matched at least 2 titles (avoid false positives)
    return bestScore >= 2 ? bestDisc : null;
}

async function startConversion() {
    if (currentFiles.length === 0) return;

    const settings = await eel.get_settings()();
    if (!settings.output_folder) {
        showToast('Please configure the output folder in Settings first', 'error');
        return;
    }

    // Build file list with track assignments, handling multi-disc correctly
    const files = assignTracksToDiscs(currentFiles, currentReleaseDetails, currentCueMetadata);

    document.getElementById('btn-convert').classList.add('hidden');
    document.getElementById('btn-cancel').classList.remove('hidden');
    document.getElementById('progress-container').classList.remove('hidden');
    document.getElementById('conversion-log').innerHTML = '';
    document.getElementById('progress-fill').style.width = '0%';

    await eel.start_conversion(files, currentReleaseDetails, null)();
}

async function cancelConversion() {
    await eel.cancel_conversion()();
    showToast('Cancellation requested...', 'error');
}

// Eel callbacks from Python
eel.expose(on_conversion_progress);
function on_conversion_progress(data) {
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;

    progressFill.style.width = `${pct}%`;

    if (data.status === 'encoding') {
        progressText.textContent = `Encoding ${data.current}/${data.total}: ${data.file}`;
    } else if (data.status === 'done') {
        progressText.textContent = `Complete! ${data.total} files processed.`;
        document.getElementById('btn-convert').classList.remove('hidden');
        document.getElementById('btn-cancel').classList.add('hidden');
        showToast(`Conversion complete: ${data.total} files`, 'success');
    } else if (data.status === 'cancelled') {
        progressText.textContent = `Cancelled after ${data.current} files.`;
        document.getElementById('btn-convert').classList.remove('hidden');
        document.getElementById('btn-cancel').classList.add('hidden');
    }
}

eel.expose(on_conversion_file_done);
function on_conversion_file_done(data) {
    const log = document.getElementById('conversion-log');
    const time = new Date().toLocaleTimeString();

    if (data.file === 'cleanup') {
        // Source file cleanup result
        if (data.success) {
            log.innerHTML += `
                <div class="log-entry success">
                    <span class="log-time">${time}</span>
                    <span>${data.message || 'Source files cleaned up'}</span>
                </div>
            `;
        } else {
            log.innerHTML += `
                <div class="log-entry error">
                    <span class="log-time">${time}</span>
                    <span>${data.error}</span>
                </div>
            `;
        }
    } else if (data.success) {
        log.innerHTML += `
            <div class="log-entry success">
                <span class="log-time">${time}</span>
                <span>OK ${Path_basename(data.file)} → ${data.compression_ratio ? (data.compression_ratio * 100).toFixed(1) + '%' : ''} (${data.tags_written} tags)</span>
            </div>
        `;
    } else {
        log.innerHTML += `
            <div class="log-entry error">
                <span class="log-time">${time}</span>
                <span>FAIL ${Path_basename(data.file)}: ${data.error}</span>
            </div>
        `;
    }
    log.scrollTop = log.scrollHeight;
}

eel.expose(on_conversion_error);
function on_conversion_error(message) {
    showToast(message, 'error');
    document.getElementById('btn-convert').classList.remove('hidden');
    document.getElementById('btn-cancel').classList.add('hidden');
}

// ─── History Page ──────────────────────────────────────────────────────────────

async function loadHistory() {
    const [logs, stats] = await Promise.all([
        eel.get_log_history(100)(),
        eel.get_dashboard_stats()(),
    ]);

    // Stats
    document.getElementById('stat-total').textContent = stats.total || 0;
    document.getElementById('stat-completed').textContent = stats.completed || 0;
    document.getElementById('stat-failed').textContent = stats.failed || 0;

    const wavBytes = stats.total_wav_bytes || 0;
    const flacBytes = stats.total_flac_bytes || 0;
    const saved = wavBytes - flacBytes;
    document.getElementById('stat-saved').textContent = saved > 0 ? formatBytes(saved) : '0 B';

    // Table
    const tbody = document.getElementById('log-tbody');
    tbody.innerHTML = logs.map(row => `
        <tr>
            <td>${formatTimestamp(row.timestamp)}</td>
            <td>${escapeHtml(row.artist || '')}</td>
            <td>${escapeHtml(row.album || '')}</td>
            <td>${escapeHtml(row.title || '')}</td>
            <td><span class="status-badge ${row.status}">${row.status}</span></td>
            <td>${row.compression_ratio ? (row.compression_ratio * 100).toFixed(1) + '%' : '-'}</td>
        </tr>
    `).join('');
}

// ─── Settings Page ─────────────────────────────────────────────────────────────

async function loadSettingsUI() {
    const s = await eel.get_settings()();
    document.getElementById('setting-input-folder').value = s.input_folder || '';
    document.getElementById('setting-output-folder').value = s.output_folder || '';
    document.getElementById('setting-flac-exe').value = s.flac_exe_path || '';
    document.getElementById('setting-compression').value = s.compression_level || 8;
    updateCompressionLabel(s.compression_level || 8);
    document.getElementById('setting-verify').checked = s.verify_encoding !== false;
    document.getElementById('setting-embed-art').checked = s.embed_album_art !== false;
    document.getElementById('setting-art-size').value = String(s.art_max_size || 1200);
    document.getElementById('setting-multi-disc').value = s.multi_disc_style || 'subfolder';
    document.getElementById('setting-delete-wav').checked = !!s.delete_wav_after_convert;
    document.getElementById('setting-metadata-provider').value = s.metadata_provider || 'musicbrainz';
    document.getElementById('setting-discogs-token').value = s.discogs_token || '';
}

function updateCompressionLabel(val) {
    const labels = ['0 (Fastest)', '1', '2', '3', '4', '5 (Default)', '6', '7', '8 (Maximum)'];
    document.getElementById('compression-label').textContent = labels[val] || val;
}

async function browseSetting(settingKey, inputId, dialogType = 'folder') {
    const path = await eel.browse_folder(dialogType)();
    if (path) {
        document.getElementById(inputId).value = path;
    }
}

async function autoDetectFlac() {
    const path = await eel.auto_detect_flac()();
    if (path) {
        document.getElementById('setting-flac-exe').value = path;
        showToast(`Found: ${path}`, 'success');
    } else {
        showToast('Could not find flac.exe. Please browse manually.', 'error');
    }
}

async function saveAllSettings() {
    const settings = {
        input_folder: document.getElementById('setting-input-folder').value,
        output_folder: document.getElementById('setting-output-folder').value,
        flac_exe_path: document.getElementById('setting-flac-exe').value,
        compression_level: parseInt(document.getElementById('setting-compression').value),
        verify_encoding: document.getElementById('setting-verify').checked,
        embed_album_art: document.getElementById('setting-embed-art').checked,
        art_max_size: parseInt(document.getElementById('setting-art-size').value),
        multi_disc_style: document.getElementById('setting-multi-disc').value,
        delete_wav_after_convert: document.getElementById('setting-delete-wav').checked,
        metadata_provider: document.getElementById('setting-metadata-provider').value,
        discogs_token: document.getElementById('setting-discogs-token').value,
    };

    await eel.update_settings(settings)();
    showToast('Settings saved', 'success');
}

// ─── Utilities ─────────────────────────────────────────────────────────────────

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatDuration(ms) {
    if (!ms) return '-';
    const s = Math.floor(ms / 1000);
    const min = Math.floor(s / 60);
    const sec = s % 60;
    return `${min}:${sec.toString().padStart(2, '0')}`;
}

function formatTimestamp(ts) {
    if (!ts) return '-';
    const d = new Date(ts);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function Path_basename(path) {
    return path.split(/[\\/]/).pop();
}

function normalizeArtistForSearch(artist) {
    // Normalize artist names for metadata provider searches:
    // 1. "Various Artists" / "Various" → "" (search by album only for compilations)
    // 2. Sort-order "Artist, The" → "The Artist"
    if (!artist) return '';
    if (artist.toLowerCase().trim() === 'various artists' || artist.toLowerCase().trim() === 'various') {
        return '';
    }
    const match = artist.match(/^(.+),\s*(The|A|An|Les|La|Le|El|Los|Las|Die|Das|Der)$/i);
    if (match) {
        return `${match[2]} ${match[1]}`;
    }
    return artist;
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// ─── Library Manager ──────────────────────────────────────────────────────────

let libraryData = null;       // Full scan result from backend
let libraryFiltered = null;   // Filtered album list currently displayed
let selectedTrack = null;     // Currently selected track for detail view
let reassignMetadata = null;  // Metadata staged for reassignment
let selectedCandidate = null; // Selected original album candidate
let selectedArtReleaseId = null; // User-selected release for artwork (null = auto)

function initLibraryPage() {
    // Show filter/album sections if we already have data
    if (libraryData) {
        document.getElementById('library-filter-section').style.display = '';
        document.getElementById('library-albums-section').style.display = '';
    }
}

function applyStatFilter(stat) {
    if (!libraryData) return;

    // Highlight the active stat card
    document.querySelectorAll('.stat-card.stat-clickable').forEach(el => el.classList.remove('active'));
    const cardMap = {
        all: 'lib-total-files',
        albums: 'lib-total-albums',
        compilations: 'lib-compilations',
        incomplete: 'lib-incomplete',
        duplicates: 'lib-duplicates',
    };
    const activeCard = document.getElementById(cardMap[stat])?.closest('.stat-card');
    if (activeCard) activeCard.classList.add('active');

    // Reset filter bar checkboxes to match
    document.getElementById('library-search').value = '';
    document.getElementById('filter-compilations').checked = (stat === 'compilations');
    document.getElementById('filter-incomplete').checked = (stat === 'incomplete');
    document.getElementById('filter-duplicates').checked = (stat === 'duplicates');

    // Handle duplicates view toggle
    if (stat === 'duplicates') {
        toggleDuplicatesView();
        return;
    }

    // Make sure duplicates view is off and album view is on
    document.getElementById('library-duplicates-section').classList.add('hidden');
    document.getElementById('library-albums-section').style.display = '';

    // Apply the filter
    filterLibrary();

    // Scroll to the album list
    document.getElementById('library-filter-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function scanLibrary() {
    const btn = document.getElementById('btn-scan-library');
    btn.disabled = true;
    btn.textContent = 'Scanning...';

    try {
        const result = await eel.scan_library()();

        if (result.error) {
            showToast(result.error, 'error');
            btn.disabled = false;
            btn.textContent = 'Scan Library';
            return;
        }

        libraryData = result;
        libraryFiltered = result.albums;

        // Update stats
        document.getElementById('lib-total-files').textContent = result.total_files;
        document.getElementById('lib-total-albums').textContent = result.albums.length;
        document.getElementById('lib-compilations').textContent = result.compilation_tracks;
        document.getElementById('lib-incomplete').textContent = result.incomplete_tracks;
        document.getElementById('lib-duplicates').textContent = result.duplicate_count || 0;

        // Show filter and album sections
        document.getElementById('library-filter-section').style.display = '';
        document.getElementById('library-albums-section').style.display = '';

        // Reset filters
        document.getElementById('library-search').value = '';
        document.getElementById('filter-compilations').checked = false;
        document.getElementById('filter-incomplete').checked = false;
        document.getElementById('filter-duplicates').checked = false;
        document.getElementById('library-duplicates-section').classList.add('hidden');

        renderLibraryAlbums(libraryFiltered);
        closeTrackDetail();
    } catch (e) {
        showToast('Scan failed: ' + e, 'error');
    }

    btn.disabled = false;
    btn.textContent = 'Scan Library';
}

function filterLibrary() {
    if (!libraryData) return;

    // Clear stat card highlights when user manually adjusts filters
    document.querySelectorAll('.stat-card.stat-clickable').forEach(el => el.classList.remove('active'));

    const search = document.getElementById('library-search').value.toLowerCase().trim();
    const compOnly = document.getElementById('filter-compilations').checked;
    const incompleteOnly = document.getElementById('filter-incomplete').checked;

    libraryFiltered = libraryData.albums.filter(album => {
        if (compOnly && !album.is_compilation) return false;
        if (incompleteOnly && album.avg_completeness >= 100) return false;
        if (search) {
            const haystack = `${album.albumartist} ${album.album} ${album.files.map(f => f.title).join(' ')}`.toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });

    renderLibraryAlbums(libraryFiltered);
}

function _renderAlbumInfoBar(album) {
    const items = [];

    // Release date
    if (album.date) items.push(`<span><strong>Released:</strong> ${escapeHtml(album.date)}</span>`);

    // Genre
    if (album.genre) items.push(`<span><strong>Genre:</strong> ${escapeHtml(album.genre)}</span>`);

    // Label / catalog
    if (album.label) {
        let labelStr = escapeHtml(album.label);
        if (album.catalog_number) labelStr += ` (${escapeHtml(album.catalog_number)})`;
        items.push(`<span><strong>Label:</strong> ${labelStr}</span>`);
    }

    // Disc/track count
    const discInfo = album.disc_count > 1 ? `${album.disc_count} discs · ` : '';
    items.push(`<span>${discInfo}${album.track_count} track${album.track_count !== 1 ? 's' : ''}</span>`);

    // Cover art
    items.push(`<span><strong>Art:</strong> ${album.has_art ? '✓' : '<span style="color:var(--danger)">✕ Missing</span>'}</span>`);

    // MusicBrainz link
    if (album.musicbrainz_albumid) {
        items.push(`<span class="album-info-mb" title="View on MusicBrainz">
            <a href="https://musicbrainz.org/release/${album.musicbrainz_albumid}" target="_blank"
               onclick="event.stopPropagation()" style="color:var(--accent); text-decoration:none; font-size:11px;">
                MusicBrainz ↗
            </a>
        </span>`);
    }

    if (items.length === 0) return '';
    return `<div class="album-info-bar">${items.join('')}</div>`;
}

function renderLibraryAlbums(albums) {
    const container = document.getElementById('library-albums');

    if (albums.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No albums match the current filters.</p>';
        return;
    }

    container.innerHTML = albums.map((album, albumIdx) => {
        const pctClass = album.avg_completeness >= 90 ? 'high' : album.avg_completeness >= 50 ? 'medium' : 'low';
        const compBadge = album.is_compilation ? '<span class="compilation-badge">Compilation</span>' : '';

        const tracksHtml = album.files.map((file, fileIdx) => {
            const filePctClass = file.completeness >= 90 ? 'high' : file.completeness >= 50 ? 'medium' : 'low';
            const missingCount = file.missing_fields ? file.missing_fields.length : 0;
            const missingLabel = missingCount > 0 ? `<span class="missing-count">${missingCount} missing</span>` : '';

            return `
                <div class="lib-track" onclick="selectTrack(${albumIdx}, ${fileIdx})" data-path="${escapeHtml(file.path)}">
                    <span class="track-num">${file.tracknumber || fileIdx + 1}</span>
                    <span class="track-title">${escapeHtml(file.title || file.filename)}</span>
                    <span class="track-artist" style="color:var(--text-muted); font-size:12px;">${escapeHtml(file.artist !== album.albumartist ? file.artist : '')}</span>
                    ${missingLabel}
                    <span class="completeness-mini">
                        <span class="completeness-mini-bar"><span class="completeness-mini-fill ${filePctClass}" style="width:${file.completeness}%"></span></span>
                        <span class="completeness-mini-pct ${filePctClass}">${file.completeness}%</span>
                    </span>
                </div>
            `;
        }).join('');

        return `
            <div class="lib-album" id="lib-album-${albumIdx}">
                <div class="lib-album-header" onclick="toggleAlbumTracks(${albumIdx})">
                    <div class="lib-album-info">
                        <span class="lib-album-title">${escapeHtml(album.album || 'Unknown Album')}</span>
                        <span class="lib-album-artist">${escapeHtml(album.albumartist || 'Unknown Artist')}</span>
                        ${album.date ? `<span class="lib-album-date">${escapeHtml(album.date)}</span>` : ''}
                        ${compBadge}
                    </div>
                    <div class="lib-album-meta">
                        <span>${album.track_count} track${album.track_count !== 1 ? 's' : ''}</span>
                        <span class="completeness-mini">
                            <span class="completeness-mini-bar"><span class="completeness-mini-fill ${pctClass}" style="width:${album.avg_completeness}%"></span></span>
                            <span class="completeness-mini-pct ${pctClass}">${Math.round(album.avg_completeness)}%</span>
                        </span>
                        <span class="expand-icon">▸</span>
                    </div>
                </div>
                <div class="lib-album-tracks" id="lib-album-tracks-${albumIdx}" style="display:none;">
                    ${_renderAlbumInfoBar(album)}
                    ${tracksHtml}
                    <div class="quick-cleanup-bar">
                        <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); quickCleanup(${albumIdx})">Quick Clean Up</button>
                    </div>
                    <div class="quick-cleanup-panel hidden" id="quick-cleanup-${albumIdx}"></div>
                </div>
            </div>
        `;
    }).join('');
}

function toggleAlbumTracks(albumIdx) {
    const tracks = document.getElementById(`lib-album-tracks-${albumIdx}`);
    const album = tracks?.closest('.lib-album');
    if (!tracks || !album) return;
    const icon = album.querySelector('.expand-icon');

    if (tracks.style.display === 'none') {
        tracks.style.display = '';
        icon.textContent = '▾';
        album.classList.add('expanded');
    } else {
        tracks.style.display = 'none';
        icon.textContent = '▸';
        album.classList.remove('expanded');
    }
}

function selectTrack(albumIdx, fileIdx) {
    const album = libraryFiltered[albumIdx];
    const file = album.files[fileIdx];
    if (!file) return;

    selectedTrack = file;
    selectedCandidate = null;
    reassignMetadata = null;
    selectedArtReleaseId = null;

    // Highlight selected track
    document.querySelectorAll('.lib-track').forEach(el => el.classList.remove('selected'));
    const trackEl = document.querySelector(`.lib-track[data-path="${CSS.escape(file.path)}"]`);
    if (trackEl) trackEl.classList.add('selected');

    // Populate detail panel
    const panel = document.getElementById('track-detail-panel');
    panel.classList.remove('hidden');

    document.getElementById('track-detail-title').textContent =
        `${file.title || file.filename} — ${file.artist || 'Unknown Artist'}`;

    // Current metadata table
    const metaDiv = document.getElementById('track-current-meta');
    const tags = file.all_tags || {};
    const metaFields = [
        ['Title', tags.TITLE || ''],
        ['Artist', tags.ARTIST || ''],
        ['Album Artist', tags.ALBUMARTIST || ''],
        ['Album', tags.ALBUM || ''],
        ['Track', tags.TRACKNUMBER || ''],
        ['Disc', tags.DISCNUMBER || ''],
        ['Year', tags.DATE || ''],
        ['Genre', tags.GENRE || ''],
        ['Cover Art', file.has_art ? 'Yes' : 'No'],
        ['MB Album ID', tags.MUSICBRAINZ_ALBUMID || ''],
        ['MB Track ID', tags.MUSICBRAINZ_TRACKID || ''],
        ['MB Artist ID', tags.MUSICBRAINZ_ARTISTID || ''],
    ];

    metaDiv.innerHTML = `
        <table class="meta-table">
            ${metaFields.map(([label, val]) => {
                const cls = val ? '' : 'class="missing"';
                const display = val || '—';
                return `<tr><td class="meta-label">${label}</td><td ${cls}>${escapeHtml(String(display))}</td></tr>`;
            }).join('')}
        </table>
    `;

    // Show original album search for compilation tracks or any track
    const origSection = document.getElementById('original-album-section');
    origSection.classList.remove('hidden');
    document.getElementById('original-album-results').innerHTML = `
        <button class="btn btn-primary" onclick="findOriginalAlbum()">Search for Original Album</button>
        <p style="margin-top:6px; color:var(--text-muted); font-size:12px;">
            Search MusicBrainz for the original studio album this track appeared on.
        </p>
    `;

    // Hide reassign preview and art selector
    document.getElementById('reassign-preview').classList.add('hidden');
    document.getElementById('art-selector').classList.add('hidden');

    // Scroll panel into view
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeTrackDetail() {
    selectedTrack = null;
    selectedCandidate = null;
    reassignMetadata = null;
    selectedArtReleaseId = null;
    document.getElementById('track-detail-panel').classList.add('hidden');
    document.getElementById('art-selector').classList.add('hidden');
    document.querySelectorAll('.lib-track').forEach(el => el.classList.remove('selected'));
}

async function findOriginalAlbum() {
    if (!selectedTrack) return;

    const resultsDiv = document.getElementById('original-album-results');
    resultsDiv.innerHTML = '<p style="color:var(--text-muted)">Searching...</p>';

    const artist = normalizeArtistForSearch(selectedTrack.artist || '');
    const title = selectedTrack.title || '';

    if (!artist || !title) {
        resultsDiv.innerHTML = '<p style="color:var(--danger)">Track needs artist and title to search.</p>';
        return;
    }

    try {
        const candidates = await eel.find_original_album(artist, title)();

        if (!candidates || candidates.length === 0) {
            resultsDiv.innerHTML = _renderNoResultsWithManualSearch(artist);
            return;
        }

        resultsDiv.innerHTML = `
            <p style="margin-bottom:8px; font-size:12px; color:var(--text-muted);">
                Found ${candidates.length} candidate${candidates.length !== 1 ? 's' : ''} (sorted by original release date). Select the correct album:
            </p>
            ${_renderCandidateList(candidates)}
        `;
        resultsDiv.innerHTML += _renderManualSearchToggle(artist);

        // Store candidates for selection
        resultsDiv._candidates = candidates;
    } catch (e) {
        resultsDiv.innerHTML = `<p style="color:var(--danger)">Search failed: ${escapeHtml(String(e))}</p>`;
    }
}

function _renderCandidateList(candidates) {
    return candidates.map((c, i) => {
        const displayDate = c.first_release_date || c.date || 'Unknown date';
        const dateNote = c.first_release_date && c.date && c.first_release_date !== c.date
            ? ` <span style="color:var(--text-muted); font-size:11px">(this release: ${escapeHtml(c.date)})</span>`
            : '';
        const secTypes = c.secondary_types && c.secondary_types.length > 0
            ? ` &bull; <span style="color:var(--warning)">${escapeHtml(c.secondary_types.join(', '))}</span>`
            : '';
        return `
            <div class="album-candidate ${c.is_original ? 'recommended' : ''}" onclick="selectCandidate(${i})">
                <div class="candidate-info">
                    <div class="candidate-title">${escapeHtml(c.album)}</div>
                    <div class="candidate-meta">
                        ${escapeHtml(c.artist)} &bull;
                        ${escapeHtml(displayDate)}${dateNote} &bull;
                        ${escapeHtml(c.type || 'Unknown')}${secTypes}
                        ${c.country ? ' &bull; ' + escapeHtml(c.country) : ''}
                    </div>
                </div>
                ${c.is_original ? '<span class="candidate-badge">Likely Original</span>' : ''}
            </div>
        `;
    }).join('');
}

function _renderNoResultsWithManualSearch(artistHint) {
    return `
        <p style="color:var(--text-muted); margin-bottom:12px;">No original album found on MusicBrainz.</p>
        ${_renderManualSearchForm(artistHint, '', true)}
    `;
}

function _renderManualSearchToggle(artistHint) {
    return `
        <div style="margin-top:10px;">
            <button class="btn btn-sm btn-secondary" onclick="showLibraryManualSearch('${escapeHtml(artistHint)}')">
                Search manually...
            </button>
        </div>
    `;
}

function _renderManualSearchForm(artistHint, albumHint, expanded) {
    const enterHandler = 'onkeydown="if(event.key===\'Enter\')runLibraryManualSearch()"';
    return `
        <div class="lib-manual-search ${expanded ? '' : 'hidden'}" id="lib-manual-search-form">
            <div class="lib-manual-search-row">
                <div class="input-group" style="flex:1; margin:0;">
                    <label>Artist</label>
                    <input type="text" id="lib-search-artist" value="${escapeHtml(artistHint || '')}" placeholder="Artist name..." ${enterHandler}>
                </div>
                <div class="input-group" style="flex:1; margin:0;">
                    <label>Album</label>
                    <input type="text" id="lib-search-album" value="${escapeHtml(albumHint || '')}" placeholder="Album name..." ${enterHandler}>
                </div>
                <button class="btn btn-primary" onclick="runLibraryManualSearch()" style="align-self:flex-end;">Search</button>
            </div>
            <div id="lib-manual-search-results"></div>
        </div>
    `;
}

function showLibraryManualSearch(artistHint) {
    // Check if form already exists
    let form = document.getElementById('lib-manual-search-form');
    if (form) {
        form.classList.toggle('hidden');
        return;
    }

    // Append the form to the results area
    const resultsDiv = document.getElementById('original-album-results');
    resultsDiv.insertAdjacentHTML('beforeend', _renderManualSearchForm(artistHint, '', true));
}

async function runLibraryManualSearch() {
    const artist = normalizeArtistForSearch(document.getElementById('lib-search-artist').value.trim());
    const album = document.getElementById('lib-search-album').value.trim();
    const resultsContainer = document.getElementById('lib-manual-search-results');

    if (!artist && !album) {
        showToast('Enter at least an artist or album name', 'error');
        return;
    }

    resultsContainer.innerHTML = '<p style="color:var(--text-muted)">Searching...</p>';

    try {
        const results = await eel.lookup_metadata(artist, album, null)();

        if (!results || results.length === 0 || results[0]?.error) {
            resultsContainer.innerHTML = '<p style="color:var(--text-muted)">No results found. Try different search terms.</p>';
            return;
        }

        resultsContainer.innerHTML = `
            <p style="margin:8px 0; font-size:12px; color:var(--text-muted);">
                ${results.length} release${results.length !== 1 ? 's' : ''} found. Select one:
            </p>
            ${results.slice(0, 8).map((r, i) => `
                <div class="album-candidate" onclick="selectManualRelease('${r.id}', ${i})">
                    <div class="candidate-info">
                        <div class="candidate-title">${escapeHtml(r.title)}</div>
                        <div class="candidate-meta">
                            ${escapeHtml(r.artist)} &bull;
                            ${r.date || 'Unknown date'} &bull;
                            ${r.total_tracks || '?'} tracks &bull;
                            ${r.country || '??'}
                            ${r.format ? ' &bull; ' + escapeHtml(r.format) : ''}
                        </div>
                    </div>
                </div>
            `).join('')}
        `;
    } catch (e) {
        resultsContainer.innerHTML = `<p style="color:var(--danger)">Search failed: ${escapeHtml(String(e))}</p>`;
    }
}

async function selectManualRelease(releaseId, idx) {
    if (!selectedTrack) return;

    // Highlight
    const container = document.getElementById('lib-manual-search-results');
    container.querySelectorAll('.album-candidate').forEach(el => el.classList.remove('selected'));
    container.querySelectorAll('.album-candidate')[idx]?.classList.add('selected');

    selectedArtReleaseId = null;

    const previewDiv = document.getElementById('reassign-preview');
    previewDiv.classList.remove('hidden');
    document.getElementById('reassign-diff').innerHTML = '<p style="color:var(--text-muted)">Loading release details...</p>';
    document.getElementById('art-selector').innerHTML = '<p style="color:var(--text-muted); font-size:12px;">Loading artwork options...</p>';
    document.getElementById('art-selector').classList.remove('hidden');

    try {
        const details = await eel.get_release_for_reassign(releaseId)();

        if (details.error) {
            document.getElementById('reassign-diff').innerHTML = `<p style="color:var(--danger)">Error: ${escapeHtml(details.error)}</p>`;
            return;
        }

        // Find the matching track in the release
        const matchedTrack = _findMatchingTrack(details, selectedTrack.title, selectedTrack.artist);

        // Build new metadata — same structure as selectCandidate
        reassignMetadata = {
            title: matchedTrack ? matchedTrack.title : selectedTrack.title,
            artist: matchedTrack ? matchedTrack.artist : (details.artist || selectedTrack.artist),
            albumartist: details.artist || '',
            album: details.title || '',
            tracknumber: matchedTrack ? String(matchedTrack.position) : (selectedTrack.tracknumber || '1'),
            discnumber: matchedTrack ? String(matchedTrack.disc_number || 1) : '1',
            date: details.first_release_date || details.date || '',
            genre: details.genre || '',
            musicbrainz_albumid: releaseId,
            musicbrainz_trackid: matchedTrack ? (matchedTrack.recording_id || '') : '',
            musicbrainz_artistid: details.artist_id || '',
            musicbrainz_albumartistid: details.artist_id || '',
            tracktotal: matchedTrack ? String(matchedTrack.track_total || '') : '',
            disctotal: String(details.discs ? details.discs.length : 1),
        };

        // Store a synthetic candidate so applyReassign works
        selectedCandidate = {
            release_id: releaseId,
            release_group_id: details.release_group_id || '',
            album: details.title,
            artist: details.artist,
        };

        // Preview + art options in parallel
        const [preview] = await Promise.all([
            eel.preview_reassign(selectedTrack.path, reassignMetadata)(),
            details.release_group_id ? loadArtOptions(details.release_group_id) : Promise.resolve(),
        ]);
        renderReassignPreview(preview);
    } catch (e) {
        document.getElementById('reassign-diff').innerHTML = `<p style="color:var(--danger)">Failed to load: ${escapeHtml(String(e))}</p>`;
    }
}

async function selectCandidate(idx) {
    const resultsDiv = document.getElementById('original-album-results');
    const candidates = resultsDiv._candidates;
    if (!candidates || !candidates[idx]) return;

    selectedCandidate = candidates[idx];
    selectedArtReleaseId = null; // Reset art selection

    // Highlight selected candidate
    document.querySelectorAll('.album-candidate').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.album-candidate')[idx]?.classList.add('selected');

    // Load full release details to get track-level metadata
    const previewDiv = document.getElementById('reassign-preview');
    previewDiv.classList.remove('hidden');
    document.getElementById('reassign-diff').innerHTML = '<p style="color:var(--text-muted)">Loading release details...</p>';
    document.getElementById('art-selector').innerHTML = '<p style="color:var(--text-muted); font-size:12px;">Loading artwork options...</p>';
    document.getElementById('art-selector').classList.remove('hidden');

    try {
        const details = await eel.get_release_for_reassign(selectedCandidate.release_id)();

        if (details.error) {
            document.getElementById('reassign-diff').innerHTML = `<p style="color:var(--danger)">Error: ${escapeHtml(details.error)}</p>`;
            return;
        }

        // Find the matching track in the release
        const matchedTrack = _findMatchingTrack(details, selectedTrack.title, selectedTrack.artist);

        // Build new metadata
        reassignMetadata = {
            title: matchedTrack ? matchedTrack.title : selectedTrack.title,
            artist: matchedTrack ? matchedTrack.artist : (details.artist || selectedTrack.artist),
            albumartist: details.artist || '',
            album: details.title || '',
            tracknumber: matchedTrack ? String(matchedTrack.position) : (selectedTrack.tracknumber || '1'),
            discnumber: matchedTrack ? String(matchedTrack.disc_number || 1) : '1',
            date: details.first_release_date || details.date || '',
            genre: details.genre || '',
            musicbrainz_albumid: selectedCandidate.release_id || '',
            musicbrainz_trackid: matchedTrack ? (matchedTrack.recording_id || '') : '',
            musicbrainz_artistid: details.artist_id || '',
            musicbrainz_albumartistid: details.artist_id || '',
            tracktotal: matchedTrack ? String(matchedTrack.track_total || '') : '',
            disctotal: String(details.discs ? details.discs.length : 1),
        };

        // Preview the changes + load art options in parallel
        const [preview] = await Promise.all([
            eel.preview_reassign(selectedTrack.path, reassignMetadata)(),
            loadArtOptions(selectedCandidate.release_group_id),
        ]);
        renderReassignPreview(preview);
    } catch (e) {
        document.getElementById('reassign-diff').innerHTML = `<p style="color:var(--danger)">Failed to load: ${escapeHtml(String(e))}</p>`;
    }
}

async function loadArtOptions(releaseGroupId) {
    const container = document.getElementById('art-selector');
    if (!releaseGroupId) {
        container.classList.add('hidden');
        return;
    }

    try {
        const options = await eel.get_art_options(releaseGroupId)();

        if (!options || options.length === 0) {
            container.innerHTML = '<p style="color:var(--text-muted); font-size:12px;">No cover art found for any release in this group.</p>';
            return;
        }

        // Auto-select the recommended one
        const recommended = options.find(o => o.recommended);
        if (recommended) {
            selectedArtReleaseId = recommended.release_id;
        }

        container.innerHTML = `
            <h4 style="font-size:13px; font-weight:600; margin-bottom:8px;">Select Album Art</h4>
            <p style="font-size:11px; color:var(--text-muted); margin-bottom:10px;">
                ${options.length} release${options.length !== 1 ? 's' : ''} with cover art. Click to select which artwork to embed.
            </p>
            <div class="art-options-row">
                ${options.map((opt, i) => `
                    <div class="art-option ${opt.recommended ? 'recommended' : ''} ${opt.release_id === selectedArtReleaseId ? 'selected' : ''}"
                         onclick="selectArtOption('${opt.release_id}', ${i})"
                         title="${escapeHtml(opt.format)} — ${escapeHtml(opt.country)} ${escapeHtml(opt.date)}">
                        <div class="art-option-img">
                            <img src="${escapeHtml(opt.thumb_url)}" alt="${escapeHtml(opt.country)} ${escapeHtml(opt.format)}"
                                 onerror="this.parentElement.innerHTML='<span>No image</span>'" loading="lazy">
                        </div>
                        <div class="art-option-label">
                            <span class="art-option-country">${escapeHtml(opt.country || '??')}</span>
                            <span class="art-option-format">${escapeHtml(opt.format)}</span>
                            ${opt.date ? `<span class="art-option-date">${escapeHtml(opt.date)}</span>` : ''}
                        </div>
                        ${opt.recommended ? '<div class="art-option-badge">Recommended</div>' : ''}
                    </div>
                `).join('')}
            </div>
        `;
    } catch (e) {
        container.innerHTML = `<p style="color:var(--text-muted); font-size:12px;">Could not load artwork options.</p>`;
    }
}

function selectArtOption(releaseId, idx) {
    selectedArtReleaseId = releaseId;

    // Update selection styling
    document.querySelectorAll('.art-option').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.art-option')[idx]?.classList.add('selected');
}

function _findMatchingTrack(releaseDetails, title, artist) {
    /**
     * Find the best matching track in a release by title.
     * Returns the track object with disc_number and track_total added, or null.
     */
    if (!releaseDetails.discs) return null;

    const targetTitle = (title || '').toLowerCase().trim();
    if (!targetTitle) return null;

    let bestMatch = null;
    let bestScore = 0;

    for (const disc of releaseDetails.discs) {
        for (const track of disc.tracks) {
            const mbTitle = (track.title || '').toLowerCase().trim();
            let score = 0;

            if (mbTitle === targetTitle) {
                score = 3;
            } else if (mbTitle.includes(targetTitle) || targetTitle.includes(mbTitle)) {
                score = 2;
            } else {
                // Try without parenthetical suffixes
                const mbClean = mbTitle.replace(/\s*\(.*?\)\s*/g, '').trim();
                const targetClean = targetTitle.replace(/\s*\(.*?\)\s*/g, '').trim();
                if (mbClean === targetClean) score = 1;
            }

            if (score > bestScore) {
                bestScore = score;
                bestMatch = {
                    ...track,
                    disc_number: disc.position,
                    track_total: disc.tracks.length,
                };
            }
        }
    }

    return bestMatch;
}

function renderReassignPreview(preview) {
    const diffDiv = document.getElementById('reassign-diff');

    if (!preview.changes || preview.changes.length === 0) {
        diffDiv.innerHTML = '<p style="color:var(--text-muted)">No metadata changes needed.</p>';
        document.getElementById('btn-apply-reassign').disabled = true;
        return;
    }

    document.getElementById('btn-apply-reassign').disabled = false;

    let html = '<table class="diff-table"><thead><tr><th>Field</th><th>Current</th><th>New</th></tr></thead><tbody>';

    for (const change of preview.changes) {
        html += `
            <tr>
                <td class="diff-field">${escapeHtml(change.field)}</td>
                <td class="diff-old">${escapeHtml(change.old) || '<em>empty</em>'}</td>
                <td class="diff-new">${escapeHtml(change.new)}</td>
            </tr>
        `;
    }

    html += '</tbody></table>';

    if (preview.path_changed) {
        html += `
            <div style="margin-top:8px; padding:8px; background:var(--bg-hover); border-radius:6px; font-size:12px;">
                <strong>File will move:</strong><br>
                <span style="color:var(--text-muted)">${escapeHtml(Path_basename(preview.current_path))}</span><br>
                → <span style="color:var(--accent)">${escapeHtml(preview.new_path.replace(/\\/g, ' \\ ').trim())}</span>
            </div>
        `;
    }

    // Album art status — only show if user hasn't loaded the art selector
    if (selectedArtReleaseId) {
        html += `
            <div style="margin-top:8px; padding:8px; background:rgba(16,185,129,0.1); border-radius:6px; font-size:12px; color:var(--success);">
                ✓ Album art selected from artwork picker above
            </div>
        `;
    } else if (preview.art_available) {
        html += `
            <div style="margin-top:8px; padding:8px; background:rgba(16,185,129,0.1); border-radius:6px; font-size:12px; color:var(--success);">
                ✓ Album art will be ${preview.current_has_art ? 'replaced with' : 'embedded from'} Cover Art Archive
            </div>
        `;
    } else if (preview.current_has_art) {
        html += `
            <div style="margin-top:8px; padding:8px; background:var(--bg-hover); border-radius:6px; font-size:12px; color:var(--text-muted);">
                No art found for new album — existing cover art will be kept
            </div>
        `;
    } else {
        html += `
            <div style="margin-top:8px; padding:8px; background:rgba(245,158,11,0.1); border-radius:6px; font-size:12px; color:var(--warning);">
                ⚠ No album art available (track has none, and none found on Cover Art Archive)
            </div>
        `;
    }

    diffDiv.innerHTML = html;
}

async function applyReassign() {
    if (!selectedTrack || !reassignMetadata) return;

    const btn = document.getElementById('btn-apply-reassign');
    btn.disabled = true;
    btn.textContent = 'Applying...';

    try {
        const result = await eel.reassign_track(selectedTrack.path, reassignMetadata, true, selectedArtReleaseId || null)();

        if (result.success) {
            showToast('Track reassigned successfully', 'success');
            // Optimistic local update — patch in-memory state instead of full rescan
            _patchLibraryAfterReassign(selectedTrack.path, result.new_path, reassignMetadata, !!selectedArtReleaseId);
            closeTrackDetail();
        } else {
            showToast('Reassignment failed: ' + (result.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Reassignment failed: ' + e, 'error');
    }

    btn.disabled = false;
    btn.textContent = 'Apply Changes';
}

function cancelReassign() {
    reassignMetadata = null;
    selectedCandidate = null;
    selectedArtReleaseId = null;
    document.getElementById('reassign-preview').classList.add('hidden');
    document.getElementById('art-selector').classList.add('hidden');
    document.querySelectorAll('.album-candidate').forEach(el => el.classList.remove('selected'));
}

// ─── Optimistic Local State Updates ──────────────────────────────────────────

function _patchLibraryAfterReassign(oldPath, newPath, metadata, hasNewArt) {
    /**
     * After a successful reassign, update the in-memory libraryData
     * instead of doing a full network rescan.
     *
     * 1. Find the file entry by oldPath
     * 2. Update its metadata fields + path
     * 3. Rebuild album groups, stats, and duplicates
     * 4. Re-render the current view
     */
    if (!libraryData) return;

    // Find the file in all albums
    let fileEntry = null;
    let sourceAlbum = null;
    let sourceFileIdx = -1;

    for (const album of libraryData.albums) {
        const idx = album.files.findIndex(f => f.path === oldPath);
        if (idx !== -1) {
            fileEntry = album.files[idx];
            sourceAlbum = album;
            sourceFileIdx = idx;
            break;
        }
    }

    if (!fileEntry) return; // Not found — fall back silently

    // Remove from source album
    sourceAlbum.files.splice(sourceFileIdx, 1);

    // Update the file entry with new metadata
    fileEntry.path = newPath || oldPath;
    fileEntry.relative_path = fileEntry.path; // approximate
    fileEntry.filename = Path_basename(fileEntry.path);
    fileEntry.artist = metadata.artist || fileEntry.artist;
    fileEntry.albumartist = metadata.albumartist || fileEntry.albumartist;
    fileEntry.album = metadata.album || fileEntry.album;
    fileEntry.title = metadata.title || fileEntry.title;
    fileEntry.tracknumber = metadata.tracknumber || fileEntry.tracknumber;
    fileEntry.discnumber = metadata.discnumber || fileEntry.discnumber;
    fileEntry.date = metadata.date || fileEntry.date;
    fileEntry.genre = metadata.genre || fileEntry.genre;
    fileEntry.musicbrainz_albumid = metadata.musicbrainz_albumid || '';
    fileEntry.musicbrainz_trackid = metadata.musicbrainz_trackid || '';
    fileEntry.musicbrainz_artistid = metadata.musicbrainz_artistid || '';
    if (hasNewArt) fileEntry.has_art = true;

    // Update all_tags to match
    if (fileEntry.all_tags) {
        for (const [key, val] of Object.entries(metadata)) {
            fileEntry.all_tags[key.toUpperCase()] = val;
        }
    }

    // Recalculate completeness for this file
    fileEntry.is_compilation = false; // It was just reassigned to a studio album
    const missingFields = [];
    const plexFields = ['TITLE','ARTIST','ALBUMARTIST','ALBUM','TRACKNUMBER','DISCNUMBER','DATE','GENRE',
                        'MUSICBRAINZ_ALBUMID','MUSICBRAINZ_ARTISTID','MUSICBRAINZ_TRACKID','MUSICBRAINZ_ALBUMARTISTID',
                        'TRACKTOTAL','DISCTOTAL'];
    const totalFields = plexFields.length + 1; // +1 for cover art
    let filled = 0;
    for (const field of plexFields) {
        const val = metadata[field.toLowerCase()] || (fileEntry.all_tags && fileEntry.all_tags[field]) || '';
        if (val && String(val).trim()) {
            filled++;
        } else {
            missingFields.push(field);
        }
    }
    if (fileEntry.has_art) filled++;
    else missingFields.push('COVER_ART');

    fileEntry.completeness = Math.round(filled / totalFields * 100);
    fileEntry.missing_fields = missingFields;

    // Find or create the target album group
    const targetKey = `${fileEntry.albumartist}|||${fileEntry.album}`;
    let targetAlbum = libraryData.albums.find(
        a => `${a.albumartist}|||${a.album}` === targetKey
    );

    if (!targetAlbum) {
        targetAlbum = {
            album: fileEntry.album,
            albumartist: fileEntry.albumartist,
            date: fileEntry.date,
            track_count: 0,
            avg_completeness: 0,
            is_compilation: false,
            files: [],
        };
        libraryData.albums.push(targetAlbum);
    }

    targetAlbum.files.push(fileEntry);

    // Clean up empty source album
    if (sourceAlbum.files.length === 0) {
        libraryData.albums = libraryData.albums.filter(a => a !== sourceAlbum);
    } else {
        _recalcAlbumStats(sourceAlbum);
    }

    _recalcAlbumStats(targetAlbum);

    // Sort files within target album by disc/track
    targetAlbum.files.sort((a, b) => {
        const da = parseInt(a.discnumber || '1');
        const db = parseInt(b.discnumber || '1');
        if (da !== db) return da - db;
        return parseInt(a.tracknumber || '0') - parseInt(b.tracknumber || '0');
    });

    // Rebuild derived data
    _rebuildLibraryStats();
    _rebuildDuplicates();

    // Re-render
    filterLibrary();
}

function _removeFileFromLibrary(filePath) {
    /**
     * After a successful file deletion, remove it from in-memory state
     * and rebuild album groups, stats, and duplicates.
     */
    if (!libraryData) return;

    for (const album of libraryData.albums) {
        const idx = album.files.findIndex(f => f.path === filePath);
        if (idx !== -1) {
            album.files.splice(idx, 1);
            if (album.files.length === 0) {
                libraryData.albums = libraryData.albums.filter(a => a !== album);
            } else {
                _recalcAlbumStats(album);
            }
            break;
        }
    }

    _rebuildLibraryStats();
    _rebuildDuplicates();

    // Re-render album view (if visible)
    filterLibrary();
}

function _recalcAlbumStats(album) {
    album.track_count = album.files.length;
    album.avg_completeness = album.files.length > 0
        ? album.files.reduce((sum, f) => sum + f.completeness, 0) / album.files.length
        : 0;
    album.is_compilation = album.files.some(f => f.is_compilation);
}

function _rebuildLibraryStats() {
    if (!libraryData) return;

    // Collect all files across all albums
    const allFiles = libraryData.albums.flatMap(a => a.files);

    libraryData.total_files = allFiles.length;
    libraryData.compilation_tracks = allFiles.filter(f => f.is_compilation).length;
    libraryData.incomplete_tracks = allFiles.filter(f => f.completeness < 100).length;

    // Update stat cards
    document.getElementById('lib-total-files').textContent = libraryData.total_files;
    document.getElementById('lib-total-albums').textContent = libraryData.albums.length;
    document.getElementById('lib-compilations').textContent = libraryData.compilation_tracks;
    document.getElementById('lib-incomplete').textContent = libraryData.incomplete_tracks;
    document.getElementById('lib-duplicates').textContent = libraryData.duplicate_count || 0;
}

function _rebuildDuplicates() {
    if (!libraryData) return;

    // Collect all files across all albums
    const allFiles = libraryData.albums.flatMap(a => a.files);

    // Group by normalized artist+title (same logic as Python find_duplicates)
    const byTrack = {};
    for (const f of allFiles) {
        const artist = (f.artist || '').toLowerCase().trim();
        const title = (f.title || '').toLowerCase().trim();
        if (!artist || !title) continue;
        const key = `${artist}|||${title}`;
        if (!byTrack[key]) byTrack[key] = [];
        byTrack[key].push(f);
    }

    const duplicates = [];
    for (const copies of Object.values(byTrack)) {
        // Any track with 2+ files is a duplicate (same album or different)
        // Deduplicate by path to avoid false positives
        const seenPaths = new Set();
        const deduped = [];
        for (const c of copies) {
            if (!seenPaths.has(c.path)) {
                seenPaths.add(c.path);
                deduped.push(c);
            }
        }
        if (deduped.length >= 2) {
            duplicates.push({
                artist: deduped[0].artist,
                title: deduped[0].title,
                copies: deduped,
            });
        }
    }

    duplicates.sort((a, b) => {
        const cmp1 = a.artist.toLowerCase().localeCompare(b.artist.toLowerCase());
        if (cmp1 !== 0) return cmp1;
        return a.title.toLowerCase().localeCompare(b.title.toLowerCase());
    });

    libraryData.duplicates = duplicates;
    libraryData.duplicate_count = duplicates.length;
    document.getElementById('lib-duplicates').textContent = duplicates.length;
}

// ─── Quick Clean Up (album-level batch reclassification) ─────────────────────

let _quickCleanupState = null;  // {albumIdx, allFiles, releaseDetails, artReleaseId}

async function quickCleanup(albumIdx) {
    const album = libraryFiltered[albumIdx];
    if (!album) return;

    const panel = document.getElementById(`quick-cleanup-${albumIdx}`);
    if (!panel) return;

    // If panel is already visible, toggle it off
    if (!panel.classList.contains('hidden')) {
        panel.classList.add('hidden');
        _quickCleanupState = null;
        return;
    }

    // Find ALL albums in the library with the same normalized artist + album name
    // (catches split folders from different release dates)
    const targetArtist = album.albumartist.toLowerCase().trim();
    const targetAlbum = album.album.toLowerCase().trim();
    const relatedAlbums = libraryData.albums.filter(a =>
        a.albumartist.toLowerCase().trim() === targetArtist &&
        a.album.toLowerCase().trim() === targetAlbum
    );

    // Collect all files from all related album folders
    const allFiles = relatedAlbums.flatMap(a => a.files);
    const uniqueDates = [...new Set(relatedAlbums.map(a => a.date).filter(Boolean))];
    const isSplit = relatedAlbums.length > 1;

    _quickCleanupState = { albumIdx, allFiles, releaseDetails: null, artReleaseId: null };

    // Show the panel with split-album info and search
    let splitInfo = '';
    if (isSplit) {
        splitInfo = `
            <div class="qc-split-warning">
                ⚠ This album is split across ${relatedAlbums.length} folders
                (dates: ${uniqueDates.join(', ')}). All ${allFiles.length} tracks will be merged.
            </div>
        `;
    }

    panel.classList.remove('hidden');
    panel.innerHTML = `
        ${splitInfo}
        <div class="qc-search-section">
            <p style="font-size:12px; color:var(--text-secondary); margin-bottom:8px;">
                Look up <strong>${escapeHtml(album.album)}</strong> by <strong>${escapeHtml(album.albumartist)}</strong>
                on MusicBrainz to get the correct original release date and metadata.
            </p>
            <div class="qc-search-row">
                <div class="input-group" style="flex:1; margin:0;">
                    <label>Artist</label>
                    <input type="text" id="qc-artist-${albumIdx}" value="${escapeHtml(normalizeArtistForSearch(album.albumartist))}"
                           onkeydown="if(event.key==='Enter')quickCleanupSearch(${albumIdx})">
                </div>
                <div class="input-group" style="flex:1; margin:0;">
                    <label>Album</label>
                    <input type="text" id="qc-album-${albumIdx}" value="${escapeHtml(album.album)}"
                           onkeydown="if(event.key==='Enter')quickCleanupSearch(${albumIdx})">
                </div>
                <button class="btn btn-primary" onclick="quickCleanupSearch(${albumIdx})" style="align-self:flex-end;">Search</button>
            </div>
            <div id="qc-results-${albumIdx}" style="margin-top:10px;"></div>
        </div>
        <div id="qc-preview-${albumIdx}" class="hidden"></div>
        <div id="qc-art-${albumIdx}" class="hidden"></div>
    `;

    // Auto-search immediately
    quickCleanupSearch(albumIdx);
}

async function quickCleanupSearch(albumIdx) {
    const artist = normalizeArtistForSearch(document.getElementById(`qc-artist-${albumIdx}`)?.value.trim());
    const album = document.getElementById(`qc-album-${albumIdx}`)?.value.trim();
    const resultsDiv = document.getElementById(`qc-results-${albumIdx}`);

    if (!artist && !album) {
        showToast('Enter at least an artist or album name', 'error');
        return;
    }

    resultsDiv.innerHTML = '<p style="color:var(--text-muted)">Searching...</p>';

    try {
        const candidates = await eel.find_original_album_by_name(artist, album)();

        if (!candidates || !Array.isArray(candidates) || candidates.length === 0) {
            // Check if it's an error response
            const errMsg = candidates?.error || (candidates?.[0]?.error) || '';
            if (errMsg) {
                resultsDiv.innerHTML = `<p style="color:var(--danger)">Search error: ${escapeHtml(errMsg)}</p>`;
            } else {
                resultsDiv.innerHTML = '<p style="color:var(--text-muted)">No results found. Try different search terms.</p>';
            }
            return;
        }

        // Store candidates for selection (same pattern as individual track flow)
        resultsDiv._qcCandidates = candidates;

        resultsDiv.innerHTML = `
            <p style="margin-bottom:8px; font-size:12px; color:var(--text-muted);">
                Found ${candidates.length} candidate${candidates.length !== 1 ? 's' : ''} (sorted by original release date). Select the correct album:
            </p>
            ${_renderQcCandidateList(candidates, albumIdx)}
        `;
    } catch (e) {
        const msg = e?.message || (typeof e === 'string' ? e : JSON.stringify(e));
        resultsDiv.innerHTML = `<p style="color:var(--danger)">Search failed: ${escapeHtml(msg)}</p>`;
    }
}

function _renderQcCandidateList(candidates, albumIdx) {
    return candidates.map((c, i) => {
        const displayDate = c.first_release_date || c.date || 'Unknown date';
        const dateNote = c.first_release_date && c.date && c.first_release_date !== c.date
            ? ` <span style="color:var(--text-muted); font-size:11px">(this release: ${escapeHtml(c.date)})</span>`
            : '';
        const secTypes = c.secondary_types && c.secondary_types.length > 0
            ? ` &bull; <span style="color:var(--warning)">${escapeHtml(c.secondary_types.join(', '))}</span>`
            : '';
        const trackInfo = c.total_tracks ? ` &bull; ${c.total_tracks} tracks` : '';
        const formatInfo = c.format ? ` &bull; ${escapeHtml(c.format)}` : '';
        const labelInfo = c.label ? ` &bull; <span style="color:var(--text-muted)">${escapeHtml(c.label)}</span>` : '';
        return `
            <div class="album-candidate ${c.is_original ? 'recommended' : ''}" onclick="quickCleanupSelect(${albumIdx}, ${i})">
                <div class="candidate-info">
                    <div class="candidate-title">${escapeHtml(c.album)}</div>
                    <div class="candidate-meta">
                        ${escapeHtml(c.artist)} &bull;
                        ${escapeHtml(displayDate)}${dateNote} &bull;
                        ${escapeHtml(c.type || 'Unknown')}${secTypes}${trackInfo}${formatInfo}${labelInfo}
                        ${c.country ? ' &bull; ' + escapeHtml(c.country) : ''}
                    </div>
                </div>
                ${c.is_original ? '<span class="candidate-badge">Likely Original</span>' : ''}
            </div>
        `;
    }).join('');
}

async function quickCleanupSelect(albumIdx, candidateIdx) {
    if (!_quickCleanupState) return;

    const resultsDiv = document.getElementById(`qc-results-${albumIdx}`);
    const candidates = resultsDiv._qcCandidates;
    if (!candidates || !candidates[candidateIdx]) return;

    const candidate = candidates[candidateIdx];

    // Highlight selected
    resultsDiv.querySelectorAll('.album-candidate').forEach(el => el.classList.remove('selected'));
    resultsDiv.querySelectorAll('.album-candidate')[candidateIdx]?.classList.add('selected');

    const previewDiv = document.getElementById(`qc-preview-${albumIdx}`);
    const artDiv = document.getElementById(`qc-art-${albumIdx}`);
    previewDiv.classList.remove('hidden');
    previewDiv.innerHTML = '<p style="color:var(--text-muted)">Loading release details...</p>';
    artDiv.innerHTML = '<p style="color:var(--text-muted); font-size:12px;">Loading artwork...</p>';
    artDiv.classList.remove('hidden');

    try {
        const details = await eel.get_release_for_reassign(candidate.release_id)();
        if (details.error) {
            previewDiv.innerHTML = `<p style="color:var(--danger)">Error: ${escapeHtml(details.error)}</p>`;
            return;
        }

        _quickCleanupState.releaseDetails = details;
        _quickCleanupState.releaseId = candidate.release_id;
        _quickCleanupState.releaseGroupId = candidate.release_group_id;
        _quickCleanupState.artReleaseId = null;

        const originalDate = candidate.first_release_date || details.first_release_date || details.date || '';

        // Match each file to a track in the release
        const allFiles = _quickCleanupState.allFiles;
        const matchedTracks = allFiles.map(file => {
            const fileTitle = file.title || file.filename.replace(/^\d+[\s\-._]+/, '').replace(/\.flac$/i, '');
            const fileArtist = file.artist || file.albumartist || '';
            const matched = _findMatchingTrack(details, fileTitle, fileArtist);
            return {
                file,
                matched,
                newTrackNum: matched ? matched.position : (file.tracknumber || '?'),
                newDiscNum: matched ? (matched.disc_number || 1) : (file.discnumber || 1),
                newTitle: matched ? matched.title : fileTitle,
                newArtist: matched ? matched.artist : fileArtist,
                recordingId: matched ? (matched.recording_id || '') : '',
                trackTotal: matched ? (matched.track_total || '') : '',
            };
        });

        _quickCleanupState.matchedTracks = matchedTracks;
        _quickCleanupState.originalDate = originalDate;

        // Build side-by-side field comparison
        const album = libraryFiltered[albumIdx];
        const currentMeta = {
            albumartist: album.albumartist || '',
            album: album.album || '',
            date: album.date || '',
            genre: album.genre || '',
        };
        const newMeta = {
            albumartist: details.artist || '',
            album: details.title || '',
            date: originalDate,
            genre: details.genre || (details.styles ? details.styles.join(', ') : ''),
        };

        // Determine which fields should be checked by default
        // Rule: check if new value is non-empty AND (current is empty OR new is more specific)
        const fields = [
            {key: 'albumartist', label: 'Album Artist'},
            {key: 'album', label: 'Album'},
            {key: 'date', label: 'Release Date'},
            {key: 'genre', label: 'Genre'},
        ];

        _quickCleanupState.fieldSelections = {};
        const comparisonRows = fields.map(f => {
            const cur = currentMeta[f.key] || '';
            const neu = newMeta[f.key] || '';
            const changed = cur !== neu && neu !== '';
            // Auto-check: new is non-empty AND (current is empty, OR new is longer/more specific)
            const isMoreSpecific = neu.length > cur.length;
            const autoCheck = changed && (cur === '' || isMoreSpecific);
            _quickCleanupState.fieldSelections[f.key] = autoCheck;

            const highlightClass = !changed ? 'qc-field-same' : autoCheck ? 'qc-field-update' : 'qc-field-skip';
            return `
                <tr class="${highlightClass}">
                    <td style="width:30px; text-align:center;">
                        <input type="checkbox" class="qc-field-check" data-field="${f.key}"
                               ${autoCheck ? 'checked' : ''} ${!changed ? 'disabled' : ''}
                               onchange="_quickCleanupState.fieldSelections['${f.key}']=this.checked">
                    </td>
                    <td class="qc-field-label">${f.label}</td>
                    <td class="qc-field-current">${escapeHtml(cur) || '<span style="color:var(--text-muted)">—</span>'}</td>
                    <td class="qc-field-new">${changed ? escapeHtml(neu) : '<span style="color:var(--text-muted)">same</span>'}</td>
                </tr>
            `;
        }).join('');

        // Track matching table
        let trackRows = '';
        for (const mt of matchedTracks) {
            const matchStatus = mt.matched
                ? '<span style="color:var(--success)">✓</span>'
                : '<span style="color:var(--warning)" title="No exact match — keeps existing title">~</span>';
            trackRows += `
                <tr>
                    <td style="width:35px; color:var(--text-muted)">${mt.newTrackNum}</td>
                    <td>${escapeHtml(mt.newTitle)}</td>
                    <td style="width:35px; text-align:center">${matchStatus}</td>
                </tr>
            `;
        }

        previewDiv.innerHTML = `
            <div class="qc-preview-header">
                <h4>${escapeHtml(details.title)} — ${escapeHtml(details.artist)}</h4>
            </div>
            <div class="qc-comparison">
                <table class="qc-comparison-table">
                    <thead><tr><th></th><th>Field</th><th>Current</th><th>New</th></tr></thead>
                    <tbody>${comparisonRows}</tbody>
                </table>
            </div>
            <details class="qc-tracks-details" open>
                <summary style="cursor:pointer; font-size:12px; font-weight:600; margin:10px 0 6px; color:var(--text-secondary);">
                    Track Matching (${matchedTracks.filter(m => m.matched).length}/${matchedTracks.length} matched)
                </summary>
                <div class="qc-track-preview">
                    <table class="diff-table">
                        <thead><tr><th>#</th><th>Title</th><th></th></tr></thead>
                        <tbody>${trackRows}</tbody>
                    </table>
                </div>
            </details>
            <div class="qc-actions">
                <button class="btn btn-primary" id="qc-apply-btn-${albumIdx}" onclick="quickCleanupApply(${albumIdx})">
                    Apply to ${allFiles.length} track${allFiles.length !== 1 ? 's' : ''}
                </button>
                <button class="btn btn-secondary" onclick="quickCleanupCancel(${albumIdx})">Cancel</button>
            </div>
        `;

        // Load art options (provider art + existing embedded art)
        _loadQuickCleanupArtWithEmbedded(albumIdx, candidate, details);

    } catch (e) {
        const msg = e?.message || (typeof e === 'string' ? e : JSON.stringify(e));
        previewDiv.innerHTML = `<p style="color:var(--danger)">Failed to load: ${escapeHtml(msg)}</p>`;
    }
}

async function _loadQuickCleanupArtWithEmbedded(albumIdx, candidate, details) {
    const artDiv = document.getElementById(`qc-art-${albumIdx}`);
    const allFiles = _quickCleanupState?.allFiles || [];

    // Fetch existing embedded art from the first file that has it
    let embeddedArt = null;
    const fileWithArt = allFiles.find(f => f.has_art);
    if (fileWithArt) {
        try {
            embeddedArt = await eel.get_embedded_art(fileWithArt.path)();
            console.log('Embedded art result:', embeddedArt?.success, embeddedArt?.width);
        } catch (e) {
            console.error('get_embedded_art failed:', e);
        }
    } else {
        console.log('No files with has_art in allFiles, count:', allFiles.length);
    }

    // Fetch provider art
    let providerArt = null;
    const rgId = candidate.release_group_id || details.release_group_id;

    if (details.provider === 'discogs') {
        try {
            providerArt = await eel.fetch_album_art(candidate.release_id, null)();
        } catch (e) { /* ignore */ }
    } else if (rgId) {
        // MusicBrainz: get art options from release group
        try {
            const options = await eel.get_art_options(rgId)();
            if (options && options.length > 0) {
                // Use the recommended option's thumbnail
                const rec = options.find(o => o.recommended) || options[0];
                if (_quickCleanupState) _quickCleanupState.artReleaseId = rec.release_id;
                providerArt = {success: true, thumb_url: rec.thumb_url, release_id: rec.release_id, source: `${rec.country} ${rec.format}`};
            }
        } catch (e) { /* ignore */ }
    }

    // Build art selector — always show: current (if exists), provider, and "keep current / no change"
    let artHtml = '<h4 style="font-size:13px; font-weight:600; margin-bottom:6px;">Album Art</h4><div class="art-options-row">';

    const hasEmbedded = (embeddedArt && embeddedArt.success) || fileWithArt;
    const hasProvider = (providerArt && providerArt.success && providerArt.data) || (providerArt && providerArt.thumb_url);

    // Default: if files have art, keep it; otherwise use provider art
    const defaultKeep = hasEmbedded;
    if (!defaultKeep && hasProvider && _quickCleanupState) {
        _quickCleanupState.artReleaseId = providerArt.release_id || candidate.release_id;
    }

    // Option 1: Keep current embedded art
    if (hasEmbedded) {
        const embeddedImg = (embeddedArt && embeddedArt.success)
            ? `<img src="data:image/jpeg;base64,${embeddedArt.data}" alt="Current">`
            : '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:11px;">Embedded</div>';
        const dims = (embeddedArt && embeddedArt.success) ? `${embeddedArt.width}×${embeddedArt.height}` : 'Embedded';
        artHtml += `
            <div class="art-option ${defaultKeep ? 'selected' : ''}" onclick="selectQuickCleanupArtSource('keep', ${albumIdx})"
                 title="Keep current embedded art">
                <div class="art-option-img">${embeddedImg}</div>
                <div class="art-option-label">
                    <span class="art-option-country">Current</span>
                    <span class="art-option-format">${dims}</span>
                </div>
            </div>
        `;
    }

    // Option 2: Provider art (Discogs or MusicBrainz)
    if (providerArt && providerArt.success && providerArt.data) {
        const providerLabel = details.provider === 'discogs' ? 'Discogs' : 'MusicBrainz';
        artHtml += `
            <div class="art-option recommended ${!defaultKeep ? 'selected' : ''}" onclick="selectQuickCleanupArtSource('provider', ${albumIdx})"
                 title="From ${escapeHtml(providerLabel)} (${providerArt.width}×${providerArt.height})">
                <div class="art-option-img">
                    <img src="data:image/jpeg;base64,${providerArt.data}" alt="${escapeHtml(providerLabel)}">
                </div>
                <div class="art-option-label">
                    <span class="art-option-country">${escapeHtml(providerLabel)}</span>
                    <span class="art-option-format">${providerArt.width}×${providerArt.height}</span>
                </div>
                <div class="art-option-badge">New</div>
            </div>
        `;
    } else if (providerArt && providerArt.thumb_url) {
        artHtml += `
            <div class="art-option recommended ${!defaultKeep ? 'selected' : ''}" onclick="selectQuickCleanupArtSource('provider', ${albumIdx})"
                 title="${escapeHtml(providerArt.source || 'MusicBrainz')}">
                <div class="art-option-img">
                    <img src="${escapeHtml(providerArt.thumb_url)}" alt="MusicBrainz"
                         onerror="this.parentElement.innerHTML='<span>No image</span>'" loading="lazy">
                </div>
                <div class="art-option-label">
                    <span class="art-option-country">MusicBrainz</span>
                    <span class="art-option-format">${escapeHtml(providerArt.source || '')}</span>
                </div>
                <div class="art-option-badge">New</div>
            </div>
        `;
        if (!defaultKeep && _quickCleanupState) _quickCleanupState.artReleaseId = providerArt.release_id;
    }

    // Option 3: No art
    artHtml += `
        <div class="art-option" onclick="selectQuickCleanupArtSource('none', ${albumIdx})"
             title="Don't change artwork">
            <div class="art-option-img" style="display:flex; align-items:center; justify-content:center;">
                <span style="font-size:20px; color:var(--text-muted);">✕</span>
            </div>
            <div class="art-option-label">
                <span class="art-option-country">No Art</span>
                <span class="art-option-format">Skip</span>
            </div>
        </div>
    `;

    artHtml += '</div>';
    artDiv.innerHTML = artHtml;
}

function selectQuickCleanupArtSource(source, albumIdx) {
    const artDiv = document.getElementById(`qc-art-${albumIdx}`);
    const options = artDiv.querySelectorAll('.art-option');
    options.forEach(el => el.classList.remove('selected'));

    if (source === 'keep') {
        // Keep existing embedded art — don't fetch new art
        options[0]?.classList.add('selected');
        if (_quickCleanupState) _quickCleanupState.artReleaseId = null;
    } else if (source === 'none') {
        // No art — explicitly skip artwork
        options[options.length - 1]?.classList.add('selected');
        if (_quickCleanupState) _quickCleanupState.artReleaseId = '__none__';
    } else {
        // Use provider art
        // Provider option is after "Current" (if exists), so index 1 or 0
        const providerIdx = artDiv.querySelector('.art-option.recommended') ?
            Array.from(options).indexOf(artDiv.querySelector('.art-option.recommended')) : 0;
        options[providerIdx]?.classList.add('selected');
        if (_quickCleanupState) _quickCleanupState.artReleaseId = _quickCleanupState.releaseId;
    }
}

async function loadQuickCleanupArt(albumIdx, releaseGroupId) {
    const artDiv = document.getElementById(`qc-art-${albumIdx}`);
    try {
        const options = await eel.get_art_options(releaseGroupId)();
        if (!options || options.length === 0) {
            artDiv.innerHTML = '<p style="color:var(--text-muted); font-size:12px;">No cover art found.</p>';
            return;
        }

        const recommended = options.find(o => o.recommended);
        if (recommended && _quickCleanupState) {
            _quickCleanupState.artReleaseId = recommended.release_id;
        }

        artDiv.innerHTML = `
            <h4 style="font-size:13px; font-weight:600; margin-bottom:6px;">Album Art</h4>
            <div class="art-options-row">
                ${options.map((opt, i) => `
                    <div class="art-option ${opt.recommended ? 'recommended' : ''} ${opt.release_id === (_quickCleanupState?.artReleaseId || '') ? 'selected' : ''}"
                         onclick="selectQuickCleanupArt('${opt.release_id}', ${i}, ${albumIdx})"
                         title="${escapeHtml(opt.format)} — ${escapeHtml(opt.country)} ${escapeHtml(opt.date)}">
                        <div class="art-option-img">
                            <img src="${escapeHtml(opt.thumb_url)}" alt="${escapeHtml(opt.country)}"
                                 onerror="this.parentElement.innerHTML='<span>No image</span>'" loading="lazy">
                        </div>
                        <div class="art-option-label">
                            <span class="art-option-country">${escapeHtml(opt.country || '??')}</span>
                            <span class="art-option-format">${escapeHtml(opt.format)}</span>
                        </div>
                        ${opt.recommended ? '<div class="art-option-badge">Recommended</div>' : ''}
                    </div>
                `).join('')}
            </div>
        `;
    } catch (e) {
        artDiv.innerHTML = '<p style="color:var(--text-muted); font-size:12px;">Could not load artwork.</p>';
    }
}


function selectQuickCleanupArt(releaseId, idx, albumIdx) {
    if (_quickCleanupState) {
        _quickCleanupState.artReleaseId = releaseId;
    }
    const artDiv = document.getElementById(`qc-art-${albumIdx}`);
    artDiv.querySelectorAll('.art-option').forEach(el => el.classList.remove('selected'));
    artDiv.querySelectorAll('.art-option')[idx]?.classList.add('selected');
}

async function quickCleanupApply(albumIdx) {
    if (!_quickCleanupState || !_quickCleanupState.releaseDetails) return;

    const btn = document.getElementById(`qc-apply-btn-${albumIdx}`);
    btn.disabled = true;
    btn.textContent = 'Applying...';

    const details = _quickCleanupState.releaseDetails;
    const matchedTracks = _quickCleanupState.matchedTracks;
    const originalDate = _quickCleanupState.originalDate;

    // Build album-level metadata — only include fields the user checked
    const sel = _quickCleanupState.fieldSelections || {};
    const albumMetadata = {};

    if (sel.albumartist) albumMetadata.albumartist = details.artist || '';
    if (sel.album) albumMetadata.album = details.title || '';
    if (sel.date) albumMetadata.date = originalDate;
    if (sel.genre) albumMetadata.genre = details.genre || (details.styles ? details.styles.join(', ') : '');

    // Always include structural/ID fields (these don't overwrite better data)
    albumMetadata.musicbrainz_albumid = _quickCleanupState.releaseId || '';
    if (details.artist_id) {
        albumMetadata.musicbrainz_artistid = details.artist_id;
        albumMetadata.musicbrainz_albumartistid = details.artist_id;
    }
    albumMetadata.disctotal = String(details.discs ? details.discs.length : 1);

    // Build per-track data
    const tracks = matchedTracks.map(mt => ({
        path: mt.file.path,
        title: mt.newTitle,
        artist: mt.newArtist,
        tracknumber: String(mt.newTrackNum),
        discnumber: String(mt.newDiscNum),
        musicbrainz_trackid: mt.recordingId,
        tracktotal: mt.trackTotal ? String(mt.trackTotal) : '',
    }));

    try {
        // null = keep existing art, '__none__' = skip art entirely, otherwise = fetch from release ID
        const artId = _quickCleanupState.artReleaseId === '__none__' ? '__none__' :
                      (_quickCleanupState.artReleaseId || null);
        const result = await eel.batch_reassign_album(
            tracks, albumMetadata, artId
        )();

        if (result.success) {
            showToast(`All ${result.total} tracks cleaned up successfully`, 'success');
        } else {
            showToast(`Cleaned up ${result.total - result.failed}/${result.total} tracks (${result.failed} failed)`, 'warning');
        }

        // Optimistic update: remove all old files, then rescan to be safe
        // (batch moves are complex enough that a rescan is worth it for correctness)
        _quickCleanupState = null;
        await scanLibrary();
    } catch (e) {
        showToast('Clean up failed: ' + e, 'error');
        btn.disabled = false;
        btn.textContent = 'Apply';
    }
}

function quickCleanupCancel(albumIdx) {
    _quickCleanupState = null;
    const panel = document.getElementById(`quick-cleanup-${albumIdx}`);
    if (panel) panel.classList.add('hidden');
}

// ─── Duplicates View ──────────────────────────────────────────────────────────

function toggleDuplicatesView() {
    const showDups = document.getElementById('filter-duplicates').checked;
    const dupsSection = document.getElementById('library-duplicates-section');
    const albumsSection = document.getElementById('library-albums-section');

    if (showDups && libraryData && libraryData.duplicates) {
        dupsSection.classList.remove('hidden');
        albumsSection.style.display = 'none';
        renderDuplicates(libraryData.duplicates);
    } else {
        dupsSection.classList.add('hidden');
        albumsSection.style.display = '';
    }
}

function renderDuplicates(duplicates) {
    const container = document.getElementById('library-duplicates');
    const summary = document.getElementById('duplicates-summary');

    if (!duplicates || duplicates.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted); padding:16px;">No duplicate tracks found.</p>';
        summary.textContent = '';
        return;
    }

    summary.textContent = `${duplicates.length} track${duplicates.length !== 1 ? 's' : ''} with multiple copies`;

    container.innerHTML = duplicates.map((dup, dupIdx) => {
        const copiesHtml = dup.copies.map((copy, copyIdx) => {
            return `
                <div class="lib-track dup-copy" style="padding-left:24px;">
                    <span class="track-num" style="width:auto; min-width:30px;">${copy.tracknumber || '?'}</span>
                    <span class="track-title" style="flex:0 0 auto; max-width:50%;">${escapeHtml(copy.album || 'Unknown Album')}</span>
                    <span class="track-artist">${escapeHtml(copy.albumartist || '')}</span>
                    <span style="font-size:11px; color:var(--text-muted); flex-shrink:0;">${copy.is_compilation ? 'Compilation' : 'Studio'}</span>
                    <button class="btn btn-small" style="margin-left:auto; color:var(--danger); border-color:var(--danger);"
                        onclick="deleteDuplicate(${dupIdx}, ${copyIdx})" title="Delete this copy">✕ Delete</button>
                </div>
            `;
        }).join('');

        return `
            <div class="lib-album" style="margin-bottom:8px;">
                <div class="lib-album-header" onclick="toggleAlbumTracks('dup-${dupIdx}')" style="padding:10px 16px;">
                    <div class="lib-album-info">
                        <span class="lib-album-title">${escapeHtml(dup.title)}</span>
                        <span class="lib-album-artist">${escapeHtml(dup.artist)}</span>
                    </div>
                    <div class="lib-album-meta">
                        <span>${dup.copies.length} copies</span>
                        <span class="expand-icon">▸</span>
                    </div>
                </div>
                <div class="lib-album-tracks" id="lib-album-tracks-dup-${dupIdx}" style="display:none;">
                    ${copiesHtml}
                </div>
            </div>
        `;
    }).join('');
}

async function deleteDuplicate(dupIdx, copyIdx) {
    if (!libraryData || !libraryData.duplicates) return;
    const dup = libraryData.duplicates[dupIdx];
    if (!dup) return;
    const copy = dup.copies[copyIdx];
    if (!copy) return;

    const filename = Path_basename(copy.path);
    const albumInfo = copy.album || 'Unknown Album';
    if (!confirm(`Delete "${filename}" from "${albumInfo}"?\n\nThis cannot be undone.`)) {
        return;
    }

    try {
        const result = await eel.delete_library_file(copy.path)();
        if (result.success) {
            showToast('File deleted', 'success');

            // Remove file from in-memory album data
            for (const album of libraryData.albums) {
                const idx = album.files.findIndex(f => f.path === copy.path);
                if (idx !== -1) {
                    album.files.splice(idx, 1);
                    if (album.files.length === 0) {
                        libraryData.albums = libraryData.albums.filter(a => a !== album);
                    } else {
                        _recalcAlbumStats(album);
                    }
                    break;
                }
            }

            // Rebuild stats and duplicates
            _rebuildLibraryStats();
            _rebuildDuplicates();

            // Re-render duplicates view (stay on duplicates, don't switch to albums)
            renderDuplicates(libraryData.duplicates);
        } else {
            showToast('Delete failed: ' + (result.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Delete failed: ' + e, 'error');
    }
}

