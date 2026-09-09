/**
 * Main Single Page Application controller for LAN Streamer Scan Agent.
 */
import { api } from "./api.js";
import { escapeHtml, getPosterUrl, debounce, parseScanProgressStep, buildBrowseParams } from "./logic.js";

// State
let currentTab = "dashboard";
let currentBrowseType = "series";
let activeEventSource = null;
let currentDetailItem = null;
let renameTargetItem = null;
let tmdbTargetItem = null;

// Helpers
function showAlert(message, type = "success", duration = 4000) {
    const alertBox = document.getElementById("globalAlert");
    alertBox.className = `alert alert-${type}`;
    alertBox.textContent = message;
    alertBox.style.display = "block";
    if (duration > 0) {
        setTimeout(() => {
            alertBox.style.display = "none";
        }, duration);
    }
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add("open");
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove("open");
    }
}

// Tab Switching
function switchTab(tabName) {
    currentTab = tabName;
    document.querySelectorAll(".nav-tab").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tab === tabName);
    });
    document.querySelectorAll(".tab-pane").forEach((pane) => {
        pane.classList.toggle("active", pane.id === `tab-${tabName}`);
    });

    if (tabName === "dashboard") {
        loadDashboard();
    } else if (tabName === "libraries") {
        loadLibraries();
    } else if (tabName === "scan") {
        loadScanMonitor();
    } else if (tabName === "logs") {
        loadLogs();
    } else if (tabName === "browse") {
        loadBrowse();
    } else if (tabName === "config") {
        loadConfig();
    }
}

// -------------------------------------------------------------
// 1. Dashboard
// -------------------------------------------------------------
async function loadDashboard() {
    try {
        const [health, libraries, seriesList, moviesList, jobs] = await Promise.all([
            api.getHealth(),
            api.getLibraries(),
            api.listSeries(),
            api.listMovies(),
            api.getScanJobs(1),
        ]);

        const healthEl = document.getElementById("healthStatus");
        healthEl.textContent = health.status === "ok" ? "Online" : "Degraded";
        healthEl.style.color = health.status === "ok" ? "var(--accent-green)" : "var(--accent-red)";

        document.getElementById("librariesCount").textContent = libraries.length;
        document.getElementById("seriesCount").textContent = seriesList.length;
        document.getElementById("moviesCount").textContent = moviesList.length;

        // Latest job
        const lastJobSummary = document.getElementById("lastJobSummary");
        if (jobs && jobs.length > 0) {
            const job = jobs[0];
            const stats = job.stats || {};
            lastJobSummary.innerHTML = `
                <div><strong>Status:</strong> <span class="status-tag status-${job.status}">${job.status}</span> &nbsp;|&nbsp;
                <strong>Pass:</strong> ${job.pass_number} &nbsp;|&nbsp;
                <strong>Finished:</strong> ${job.finished_at || "In progress"}</div>
                <div style="margin-top: 0.5rem; font-size: 0.85rem;">
                    Series: ${stats.series || 0}, Seasons: ${stats.seasons || 0}, Episodes: ${stats.episodes || 0}, Movies: ${stats.movies || 0}
                </div>
            `;
        } else {
            lastJobSummary.textContent = "No previous scan jobs found.";
        }

        // Table
        const tbody = document.querySelector("#dashboardLibrariesTable tbody");
        tbody.innerHTML = "";
        libraries.forEach((libraryItem) => {
            const counts = libraryItem.counts || {};
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><strong>${escapeHtml(libraryItem.name)}</strong></td>
                <td><span class="status-tag status-${libraryItem.media_type === "movie" ? "done" : "running"}">${libraryItem.media_type.toUpperCase()}</span></td>
                <td><code>${escapeHtml(libraryItem.root_path)}</code></td>
                <td>${libraryItem.media_type === "movie" ? (counts.movies || 0) : (counts.series || 0)}</td>
                <td>${libraryItem.media_type === "movie" ? (counts.media_files || 0) : (counts.episodes || 0)}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        showAlert(`Failed loading dashboard: ${error.message}`, "error");
    }
}

// -------------------------------------------------------------
// 2. Libraries Management
// -------------------------------------------------------------
async function loadLibraries() {
    try {
        const libraries = await api.getLibraries();
        const tbody = document.querySelector("#librariesTable tbody");
        tbody.innerHTML = "";

        libraries.forEach((libraryItem) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${libraryItem.id}</td>
                <td><strong>${escapeHtml(libraryItem.name)}</strong></td>
                <td>${libraryItem.media_type.toUpperCase()}</td>
                <td><code>${escapeHtml(libraryItem.root_path)}</code></td>
                <td>${libraryItem.enabled ? "✅" : "❌"}</td>
                <td>
                    <button class="btn btn-secondary btn-sm" data-action="scan" data-id="${libraryItem.id}">Scan</button>
                    <button class="btn btn-secondary btn-sm" data-action="edit" data-id="${libraryItem.id}">Edit</button>
                    <button class="btn btn-danger btn-sm" data-action="delete" data-id="${libraryItem.id}">Delete</button>
                </td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        showAlert(`Failed loading libraries: ${error.message}`, "error");
    }
}

// -------------------------------------------------------------
// 3. Scan Monitor & SSE
// -------------------------------------------------------------
async function loadScanMonitor() {
    try {
        const [libraries, status, jobs] = await Promise.all([
            api.getLibraries(),
            api.getScanStatus(),
            api.getScanJobs(15),
        ]);

        const select = document.getElementById("scanLibrarySelect");
        select.innerHTML = '<option value="">All Libraries</option>';
        libraries.forEach((libraryItem) => {
            const option = document.createElement("option");
            option.value = libraryItem.id;
            option.textContent = `${libraryItem.name} (${libraryItem.media_type})`;
            select.appendChild(option);
        });

        renderScanStatus(status);
        renderScanJobs(jobs);
        initSSE();
    } catch (error) {
        showAlert(`Failed loading scan monitor: ${error.message}`, "error");
    }
}

function renderScanStatus(status) {
    const isRunning = status.running !== null;
    const btnStart = document.getElementById("btnStartScan");
    const btnCancel = document.getElementById("btnCancelScan");
    const activeDiv = document.getElementById("activeScanStatus");
    const progressLabel = document.getElementById("scanProgressLabel");
    const progressBar = document.getElementById("scanProgressBar");

    btnStart.disabled = isRunning;
    btnCancel.disabled = !isRunning;
    activeDiv.style.display = isRunning ? "block" : "none";

    if (isRunning) {
        progressLabel.textContent = `Job #${status.running} in progress...`;
        progressBar.style.width = "60%";
    }
}

function renderScanJobs(jobs) {
    const tbody = document.querySelector("#scanJobsTable tbody");
    tbody.innerHTML = "";
    jobs.forEach((job) => {
        const row = document.createElement("tr");
        const stats = job.stats ? JSON.stringify(job.stats) : "-";
        row.innerHTML = `
            <td>#${job.id}</td>
            <td>${job.library_id ? escapeHtml(String(job.library_id)) : "All"}</td>
            <td>Pass ${job.pass_number}</td>
            <td><span class="status-tag status-${job.status}">${job.status}</span></td>
            <td>${job.started_at ? new Date(job.started_at).toLocaleTimeString() : "-"}</td>
            <td>${job.finished_at ? new Date(job.finished_at).toLocaleTimeString() : "-"}</td>
            <td style="font-size: 0.8rem;"><code>${escapeHtml(stats)}</code></td>
        `;
        tbody.appendChild(row);
    });
}

function appendLogLine(text) {
    const logConsole = document.getElementById("logConsole");
    if (logConsole) {
        const line = document.createElement("div");
        line.textContent = text;
        logConsole.appendChild(line);
        logConsole.scrollTop = logConsole.scrollHeight;
    }
    const runningConsole = document.getElementById("runningLogConsole");
    if (runningConsole) {
        if (runningConsole.textContent === "Waiting for logs...") {
            runningConsole.textContent = "";
        }
        const line = document.createElement("div");
        line.textContent = text;
        runningConsole.appendChild(line);
        const autoScroll = document.getElementById("chkAutoScrollLogs");
        if (!autoScroll || autoScroll.checked) {
            runningConsole.scrollTop = runningConsole.scrollHeight;
        }
    }
}

function initSSE() {
    if (activeEventSource) {
        return;
    }
    activeEventSource = new EventSource("/api/v1/events");

    activeEventSource.addEventListener("scan.progress", (event) => {
        try {
            const progressLabel = document.getElementById("scanProgressLabel");
            const progressBar = document.getElementById("scanProgressBar");
            const step = parseScanProgressStep(event.data);
            if (step) {
                if (step.label !== null) {
                    progressLabel.textContent = step.label;
                }
                if (step.widthPercent !== null) {
                    progressBar.style.width = `${step.widthPercent}%`;
                }
            }
        } catch {
            // Ignore parse errors
        }
    });

    activeEventSource.addEventListener("scan.log", (event) => {
        try {
            const payload = JSON.parse(event.data);
            const text = payload.line || payload.message || "";
            if (text) {
                appendLogLine(text);
            }
        } catch {
            // Ignore parse errors
        }
    });

    activeEventSource.addEventListener("scan.finished", () => {
        renderScanStatus({ running: null });
        api.getScanJobs(15).then(renderScanJobs);
        showAlert("Scan job finished successfully!", "success");
    });

    activeEventSource.onerror = () => {
        // SSE disconnected, will retry automatically
    };
}

// -------------------------------------------------------------
// 4. Running Logs
// -------------------------------------------------------------
async function loadLogs() {
    initSSE();
    try {
        const logs = await api.getLogs(300);
        const runningConsole = document.getElementById("runningLogConsole");
        if (!runningConsole) return;
        runningConsole.innerHTML = "";
        if (logs.length === 0) {
            runningConsole.textContent = "No logs recorded yet.";
            return;
        }
        logs.forEach((item) => {
            const line = document.createElement("div");
            line.textContent = item.line || item.message || "";
            runningConsole.appendChild(line);
        });
        const autoScroll = document.getElementById("chkAutoScrollLogs");
        if (!autoScroll || autoScroll.checked) {
            runningConsole.scrollTop = runningConsole.scrollHeight;
        }
    } catch (error) {
        showAlert(`Failed loading logs: ${error.message}`, "error");
    }
}

// -------------------------------------------------------------
// 5. Browse (Series, Movies & Anime)
// -------------------------------------------------------------
async function populateBrowseLibraries() {
    const select = document.getElementById("browseLibrary");
    if (!select || select.children.length > 1) return;
    try {
        const libraries = await api.getLibraries();
        libraries.forEach((lib) => {
            const option = document.createElement("option");
            option.value = String(lib.id);
            option.textContent = `${lib.name} (${lib.media_type})`;
            select.appendChild(option);
        });
    } catch {
        // Ignore failure to load libraries
    }
}

async function loadBrowse() {
    await populateBrowseLibraries();
    try {
        const query = document.getElementById("browseSearch").value.trim();
        const librarySelect = document.getElementById("browseLibrary");
        const libraryIdentifier = librarySelect ? librarySelect.value : "";
        const sort = document.getElementById("browseSort").value;
        const grid = document.getElementById("mediaGrid");
        grid.innerHTML = '<div style="color: var(--text-secondary); padding: 1rem;">Loading media...</div>';

        if (currentBrowseType === "series" || currentBrowseType === "anime") {
            const parameters = buildBrowseParams(currentBrowseType, query, libraryIdentifier, sort);
            const items = await api.listSeries(parameters);
            grid.innerHTML = "";
            if (items.length === 0) {
                const label = currentBrowseType === "anime" ? "anime" : "TV series";
                grid.innerHTML = `<div style="color: var(--text-secondary); padding: 1rem;">No ${label} found. Run a library scan!</div>`;
                return;
            }
            items.forEach((item) => {
                const card = document.createElement("div");
                card.className = "media-card";
                const posterUrl = getPosterUrl(item.poster_path);
                card.innerHTML = `
                    <div class="media-poster">${posterUrl ? `<img src="${posterUrl}" style="width: 100%; height: 100%; object-fit: cover;" alt="poster">` : "No Poster"}</div>
                    <div class="media-info">
                        <div class="media-title">${escapeHtml(item.name || item.folder_name)}</div>
                        <div class="media-sub">${item.year ? item.year : ""} • ${item.seasons ? item.seasons.length : 0} Seasons</div>
                    </div>
                `;
                card.onclick = () => showSeriesDetail(item.id);
                grid.appendChild(card);
            });
        } else if (currentBrowseType === "movie") {
            const parameters = buildBrowseParams(currentBrowseType, query, libraryIdentifier, sort);
            const items = await api.listMovies(parameters);
            grid.innerHTML = "";
            if (items.length === 0) {
                grid.innerHTML = '<div style="color: var(--text-secondary); padding: 1rem;">No movies found. Run a library scan!</div>';
                return;
            }
            items.forEach((item) => {
                const card = document.createElement("div");
                card.className = "media-card";
                const posterUrl = getPosterUrl(item.poster_path);
                card.innerHTML = `
                    <div class="media-poster">${posterUrl ? `<img src="${posterUrl}" style="width: 100%; height: 100%; object-fit: cover;" alt="poster">` : "No Poster"}</div>
                    <div class="media-info">
                        <div class="media-title">${escapeHtml(item.name || item.folder_name)}</div>
                        <div class="media-sub">${item.year ? item.year : ""} ${item.runtime_seconds ? `• ${Math.round(item.runtime_seconds / 60)}m` : ""}</div>
                    </div>
                `;
                card.onclick = () => showMovieDetail(item.id);
                grid.appendChild(card);
            });
        }
    } catch (error) {
        showAlert(`Failed loading browse items: ${error.message}`, "error");
    }
}

async function showSeriesDetail(seriesId) {
    try {
        const item = await api.getSeriesDetail(seriesId);
        currentDetailItem = { ...item, mediaType: "series" };
        document.getElementById("detailTitle").textContent = item.name || item.folder_name;

        let seasonsHtml = "";
        (item.seasons || []).forEach((season) => {
            let episodesRows = "";
            (season.episodes || []).forEach((episode) => {
                const versions = (episode.versions || []).map((v) => `${v.resolution || ""} ${v.codec || ""} (${v.path || ""})`).join("<br>");
                episodesRows += `
                    <tr>
                        <td>E${episode.episode_number}</td>
                        <td><strong>${escapeHtml(episode.name || "")}</strong></td>
                        <td>${episode.air_date || "-"}</td>
                        <td>${episode.runtime_seconds ? Math.round(episode.runtime_seconds / 60) + "m" : "-"}</td>
                        <td>${episode.watched ? "✅ Watched" : "Unwatched"}</td>
                        <td style="font-size: 0.8rem;">${versions || "<em>No files</em>"}</td>
                    </tr>
                `;
            });

            seasonsHtml += `
                <div style="margin-top: 1.5rem;">
                    <h4>${escapeHtml(season.name || "Season " + season.season_number)}</h4>
                    <div class="table-container" style="margin-top: 0.5rem;">
                        <table>
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>Title</th>
                                    <th>Air Date</th>
                                    <th>Runtime</th>
                                    <th>State</th>
                                    <th>Files / Versions</th>
                                </tr>
                            </thead>
                            <tbody>${episodesRows || '<tr><td colspan="6">No episodes</td></tr>'}</tbody>
                        </table>
                    </div>
                </div>
            `;
        });

        document.getElementById("detailContent").innerHTML = `
            <div style="display: flex; gap: 1.5rem; margin-bottom: 1.5rem;">
                <div style="width: 140px; height: 210px; background: var(--bg-tertiary); flex-shrink: 0; border-radius: var(--radius-md); overflow: hidden;">
                    ${item.poster_path ? `<img src="${getPosterUrl(item.poster_path)}" style="width: 100%; height: 100%; object-fit: cover;" alt="poster">` : ""}
                </div>
                <div>
                    <h3>${escapeHtml(item.name || item.folder_name)}</h3>
                    <p style="color: var(--text-secondary); margin: 0.5rem 0;">${escapeHtml(item.overview || "No overview available.")}</p>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">
                        TMDB ID: <code>${item.tmdb_identifier || "Unmatched"}</code> • Path: <code>${item.path || ""}</code>
                    </div>
                    <div style="margin-top: 1rem; display: flex; gap: 0.75rem;">
                        <button id="btnOpenTmdbMatch" class="btn btn-secondary btn-sm">Match TMDB</button>
                        <button id="btnOpenRename" class="btn btn-secondary btn-sm">Rename Files</button>
                    </div>
                </div>
            </div>
            ${seasonsHtml}
        `;

        document.getElementById("btnOpenTmdbMatch").onclick = () => openTmdbMatchModal("series", item.id, item.name || item.folder_name);
        document.getElementById("btnOpenRename").onclick = () => openRenameModal("series", item.id);
        openModal("mediaDetailModal");
    } catch (error) {
        showAlert(`Failed loading series details: ${error.message}`, "error");
    }
}

async function showMovieDetail(movieId) {
    try {
        const item = await api.getMovieDetail(movieId);
        currentDetailItem = { ...item, mediaType: "movie" };
        document.getElementById("detailTitle").textContent = item.name || item.folder_name;

        const versionsRows = (item.versions || []).map((v) => `
            <tr>
                <td><code>${escapeHtml(v.path)}</code></td>
                <td>${v.resolution || "-"}</td>
                <td>${v.codec || "-"}</td>
                <td>${v.container || "-"}</td>
            </tr>
        `).join("");

        document.getElementById("detailContent").innerHTML = `
            <div style="display: flex; gap: 1.5rem; margin-bottom: 1.5rem;">
                <div style="width: 140px; height: 210px; background: var(--bg-tertiary); flex-shrink: 0; border-radius: var(--radius-md); overflow: hidden;">
                    ${item.poster_path ? `<img src="${getPosterUrl(item.poster_path)}" style="width: 100%; height: 100%; object-fit: cover;" alt="poster">` : ""}
                </div>
                <div>
                    <h3>${escapeHtml(item.name || item.folder_name)}</h3>
                    <p style="color: var(--text-secondary); margin: 0.5rem 0;">${escapeHtml(item.overview || "No overview available.")}</p>
                    <div style="font-size: 0.85rem; color: var(--text-muted);">
                        TMDB ID: <code>${item.tmdb_identifier || "Unmatched"}</code> • Runtime: ${item.runtime_seconds ? Math.round(item.runtime_seconds / 60) + "m" : "-"}
                    </div>
                    <div style="margin-top: 1rem; display: flex; gap: 0.75rem;">
                        <button id="btnOpenTmdbMatch" class="btn btn-secondary btn-sm">Match TMDB</button>
                    </div>
                </div>
            </div>
            <h4>Media Files (Versions)</h4>
            <div class="table-container" style="margin-top: 0.5rem;">
                <table>
                    <thead>
                        <tr>
                            <th>Path</th>
                            <th>Resolution</th>
                            <th>Codec</th>
                            <th>Container</th>
                        </tr>
                    </thead>
                    <tbody>${versionsRows || '<tr><td colspan="4">No media files</td></tr>'}</tbody>
                </table>
            </div>
        `;

        document.getElementById("btnOpenTmdbMatch").onclick = () => openTmdbMatchModal("movie", item.id, item.name || item.folder_name);
        openModal("mediaDetailModal");
    } catch (error) {
        showAlert(`Failed loading movie details: ${error.message}`, "error");
    }
}

// -------------------------------------------------------------
// TMDB Match Modal
// -------------------------------------------------------------
function openTmdbMatchModal(mediaType, mediaId, title) {
    tmdbTargetItem = { mediaType, mediaId };
    document.getElementById("tmdbSearchQuery").value = title || "";
    document.getElementById("tmdbSearchResultsBody").innerHTML = "";
    openModal("tmdbMatchModal");
}

async function searchTmdb() {
    const query = document.getElementById("tmdbSearchQuery").value.trim();
    if (!query || !tmdbTargetItem) {
        return;
    }
    const tbody = document.getElementById("tmdbSearchResultsBody");
    tbody.innerHTML = '<tr><td colspan="4">Searching TMDB...</td></tr>';
    try {
        const results = await api.searchMetadata(query, tmdbTargetItem.mediaType === "series" ? "series" : "movie");
        tbody.innerHTML = "";
        const matches = results && results.matches ? results.matches : (Array.isArray(results) ? results : []);
        if (matches.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4">No matches found</td></tr>';
            return;
        }
        matches.forEach((match) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${match.id}</td>
                <td><strong>${escapeHtml(match.name || match.title)}</strong></td>
                <td>${match.first_air_date || match.release_date || "-"}</td>
                <td><button class="btn btn-primary btn-sm" data-tmdb-id="${match.id}">Match</button></td>
            `;
            row.querySelector("button").onclick = () => applyTmdbMatch(match.id);
            tbody.appendChild(row);
        });
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="4" style="color: var(--accent-red);">${escapeHtml(error.message)}</td></tr>`;
    }
}

async function applyTmdbMatch(tmdbId) {
    if (!tmdbTargetItem) {
        return;
    }
    try {
        await api.matchMetadata(tmdbTargetItem.mediaType, tmdbTargetItem.mediaId, tmdbId);
        closeModal("tmdbMatchModal");
        showAlert("Metadata matched and episodes refreshed!", "success");
        if (currentDetailItem) {
            if (currentDetailItem.mediaType === "series") {
                showSeriesDetail(currentDetailItem.id);
            } else {
                showMovieDetail(currentDetailItem.id);
            }
        }
    } catch (error) {
        showAlert(`Failed matching metadata: ${error.message}`, "error");
    }
}

// -------------------------------------------------------------
// Rename Modal
// -------------------------------------------------------------
async function openRenameModal(mediaType, mediaId) {
    renameTargetItem = { mediaType, mediaId };
    openModal("renameModal");
    loadRenamePreview();
}

async function loadRenamePreview() {
    if (!renameTargetItem) {
        return;
    }
    const template = document.getElementById("renameTemplate").value.trim();
    const tbody = document.getElementById("renameTableBody");
    tbody.innerHTML = '<tr><td colspan="2">Calculating preview...</td></tr>';
    try {
        const preview = await api.previewRename({
            media_type: renameTargetItem.mediaType,
            media_id: renameTargetItem.mediaId,
            template,
        });
        tbody.innerHTML = "";
        if (!preview || preview.length === 0) {
            tbody.innerHTML = '<tr><td colspan="2">No renames needed</td></tr>';
            return;
        }
        preview.forEach((item) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><code>${escapeHtml(item.old_path)}</code></td>
                <td><strong style="color: var(--accent-green);">${escapeHtml(item.new_name || item.new_path)}</strong></td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="2" style="color: var(--accent-red);">${escapeHtml(error.message)}</td></tr>`;
    }
}

async function applyRename() {
    if (!renameTargetItem) {
        return;
    }
    const template = document.getElementById("renameTemplate").value.trim();
    try {
        const result = await api.applyRename({
            media_type: renameTargetItem.mediaType,
            media_id: renameTargetItem.mediaId,
            template,
            dry_run: false,
        });
        closeModal("renameModal");
        showAlert(`Renamed ${result.renamed_count || 0} files on disk!`, "success");
        if (currentDetailItem) {
            showSeriesDetail(currentDetailItem.id);
        }
    } catch (error) {
        showAlert(`Failed applying rename: ${error.message}`, "error");
    }
}

// -------------------------------------------------------------
// Folder Finder / Browser Modal
// -------------------------------------------------------------
let currentBrowserDirectory = "";
let selectedBrowserDirectory = "";

async function openFolderBrowser(initialPath) {
    currentBrowserDirectory = initialPath || document.getElementById("libRootPath").value.trim() || "";
    selectedBrowserDirectory = currentBrowserDirectory;
    openModal("folderBrowserModal");
    await loadDirectory(currentBrowserDirectory);
}

async function loadDirectory(directoryPath) {
    const listContainer = document.getElementById("folderList");
    const pathInput = document.getElementById("folderCurrentPath");
    const displaySpan = document.getElementById("selectedFolderDisplay");
    const shortcutsContainer = document.getElementById("folderShortcuts");

    listContainer.innerHTML = '<li style="padding: 1rem; color: var(--text-muted); text-align: center;">Loading folders...</li>';
    try {
        const data = await api.browseFilesystem(directoryPath);
        currentBrowserDirectory = data.current_path;
        selectedBrowserDirectory = data.current_path;
        pathInput.value = data.current_path;
        displaySpan.textContent = `Selected: ${data.current_path}`;

        // Render shortcuts
        if (data.shortcuts && data.shortcuts.length > 0) {
            shortcutsContainer.innerHTML = "";
            data.shortcuts.forEach((shortcut) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "btn btn-secondary btn-sm";
                button.style.fontSize = "0.75rem";
                button.style.padding = "0.2rem 0.5rem";
                button.textContent = shortcut;
                button.onclick = () => loadDirectory(shortcut);
                shortcutsContainer.appendChild(button);
            });
        }

        // Configure Up button
        const upButton = document.getElementById("btnFolderUp");
        if (data.parent_path) {
            upButton.disabled = false;
            upButton.onclick = () => loadDirectory(data.parent_path);
        } else {
            upButton.disabled = true;
        }

        // Render directories
        listContainer.innerHTML = "";
        if (!data.directories || data.directories.length === 0) {
            listContainer.innerHTML = '<li style="padding: 1.5rem; color: var(--text-muted); text-align: center;"><em>No subfolders in this directory</em></li>';
            return;
        }

        data.directories.forEach((dir) => {
            const item = document.createElement("li");
            item.style.padding = "0.5rem 0.75rem";
            item.style.display = "flex";
            item.style.alignItems = "center";
            item.style.gap = "8px";
            item.style.cursor = "pointer";
            item.style.borderBottom = "1px solid var(--border-color)";
            item.style.transition = "background-color 0.15s ease";
            item.innerHTML = `<span>📁</span> <span style="flex: 1; font-weight: 500;">${escapeHtml(dir.name)}</span>`;

            item.onmouseover = () => {
                if (selectedBrowserDirectory !== dir.path) {
                    item.style.backgroundColor = "rgba(255, 255, 255, 0.04)";
                }
            };
            item.onmouseout = () => {
                if (selectedBrowserDirectory !== dir.path) {
                    item.style.backgroundColor = "";
                }
            };

            // Single click: select folder
            item.onclick = () => {
                selectedBrowserDirectory = dir.path;
                displaySpan.textContent = `Selected: ${dir.path}`;
                Array.from(listContainer.children).forEach((child) => {
                    child.style.backgroundColor = "";
                });
                item.style.backgroundColor = "rgba(99, 102, 241, 0.18)";
            };

            // Double click: navigate into folder
            item.ondblclick = () => {
                loadDirectory(dir.path);
            };

            listContainer.appendChild(item);
        });
    } catch (error) {
        listContainer.innerHTML = `<li style="padding: 1rem; color: var(--accent-red); text-align: center;">${escapeHtml(error.message)}</li>`;
    }
}

// -------------------------------------------------------------
// 5. Configuration
// -------------------------------------------------------------
async function loadConfig() {
    try {
        const cfg = await api.getConfig();
        document.getElementById("cfgTmdbApiKey").value = cfg.tmdb_api_key || "";
        document.getElementById("cfgScanConcurrency").value = cfg.scan_concurrency || 8;
        document.getElementById("cfgOpenSubtitlesUsername").value = cfg.opensubtitles_username || "";
        document.getElementById("cfgOpenSubtitlesApiKey").value = cfg.opensubtitles_api_key || "";
        document.getElementById("cfgCacheDirectory").value = cfg.cache_directory || "";
    } catch (error) {
        showAlert(`Failed loading configuration: ${error.message}`, "error");
    }
}

async function saveConfig(event) {
    event.preventDefault();
    const payload = {
        tmdb_api_key: document.getElementById("cfgTmdbApiKey").value.trim(),
        scan_concurrency: parseInt(document.getElementById("cfgScanConcurrency").value, 10),
        opensubtitles_username: document.getElementById("cfgOpenSubtitlesUsername").value.trim(),
        opensubtitles_api_key: document.getElementById("cfgOpenSubtitlesApiKey").value.trim(),
        cache_directory: document.getElementById("cfgCacheDirectory").value.trim(),
    };
    const password = document.getElementById("cfgOpenSubtitlesPassword").value;
    if (password) {
        payload.opensubtitles_password = password;
    }

    try {
        await api.updateConfig(payload);
        showAlert("Configuration saved successfully!", "success");
    } catch (error) {
        showAlert(`Failed saving configuration: ${error.message}`, "error");
    }
}

// -------------------------------------------------------------
// Initialization & Global Event Listeners
// -------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    // Navigation
    document.querySelectorAll(".nav-tab").forEach((btn) => {
        btn.onclick = () => switchTab(btn.dataset.tab);
    });

    // Close Modals
    document.querySelectorAll("[data-close]").forEach((btn) => {
        btn.onclick = () => closeModal(btn.dataset.close);
    });

    // Dashboard
    document.getElementById("btnQuickScan").onclick = () => {
        switchTab("scan");
        document.getElementById("btnStartScan").click();
    };

    // Scan Monitor
    document.getElementById("btnStartScan").onclick = async () => {
        const libraryId = document.getElementById("scanLibrarySelect").value || null;
        const passNumber = parseInt(document.getElementById("scanPassSelect").value, 10);
        const forceRefresh = document.getElementById("scanForceRefresh").checked;
        try {
            await api.startScan({ library_id: libraryId, pass_number: passNumber, force_refresh: forceRefresh });
            renderScanStatus({ running: "new" });
            showAlert("Scan job queued and started", "success");
        } catch (error) {
            showAlert(`Could not start scan: ${error.message}`, "error");
        }
    };

    document.getElementById("btnCancelScan").onclick = async () => {
        try {
            await api.cancelScan();
            showAlert("Cancel request sent", "success");
        } catch (error) {
            showAlert(`Could not cancel scan: ${error.message}`, "error");
        }
    };

    // Browse filters
    const btnTypeSeries = document.getElementById("browseTypeSeries");
    const btnTypeMovies = document.getElementById("browseTypeMovies");
    const btnTypeAnime = document.getElementById("browseTypeAnime");

    function updateBrowseTypeButtons(activeType) {
        currentBrowseType = activeType;
        if (btnTypeSeries) btnTypeSeries.className = activeType === "series" ? "btn btn-primary" : "btn btn-secondary";
        if (btnTypeMovies) btnTypeMovies.className = activeType === "movie" ? "btn btn-primary" : "btn btn-secondary";
        if (btnTypeAnime) btnTypeAnime.className = activeType === "anime" ? "btn btn-primary" : "btn btn-secondary";
        const librarySelect = document.getElementById("browseLibrary");
        if (librarySelect) librarySelect.value = "";
        loadBrowse();
    }

    if (btnTypeSeries) {
        btnTypeSeries.onclick = () => updateBrowseTypeButtons("series");
    }
    if (btnTypeMovies) {
        btnTypeMovies.onclick = () => updateBrowseTypeButtons("movie");
    }
    if (btnTypeAnime) {
        btnTypeAnime.onclick = () => updateBrowseTypeButtons("anime");
    }

    const browseSearch = document.getElementById("browseSearch");
    if (browseSearch) {
        browseSearch.oninput = debounce(loadBrowse, 300);
    }
    const browseSort = document.getElementById("browseSort");
    if (browseSort) {
        browseSort.onchange = loadBrowse;
    }
    const browseLibrary = document.getElementById("browseLibrary");
    if (browseLibrary) {
        browseLibrary.onchange = loadBrowse;
    }

    // Logs controls
    const btnClearLogs = document.getElementById("btnClearLogs");
    if (btnClearLogs) {
        btnClearLogs.onclick = () => {
            const runningConsole = document.getElementById("runningLogConsole");
            if (runningConsole) runningConsole.innerHTML = "";
        };
    }
    const btnRefreshLogs = document.getElementById("btnRefreshLogs");
    if (btnRefreshLogs) {
        btnRefreshLogs.onclick = () => loadLogs();
    }

    // TMDB Match modal
    document.getElementById("btnTmdbSearch").onclick = searchTmdb;
    document.getElementById("tmdbSearchQuery").onkeydown = (e) => {
        if (e.key === "Enter") searchTmdb();
    };

    // Rename modal
    document.getElementById("btnPreviewRename").onclick = loadRenamePreview;
    document.getElementById("btnApplyRename").onclick = applyRename;

    // Config form
    document.getElementById("configForm").onsubmit = saveConfig;

    // Library CRUD
    document.getElementById("btnOpenAddLibrary").onclick = () => {
        document.getElementById("libraryForm").reset();
        document.getElementById("libId").value = "";
        document.getElementById("libraryModalTitle").textContent = "Add Library";
        openModal("libraryModal");
    };

    document.getElementById("btnSaveLibrary").onclick = async () => {
        const id = document.getElementById("libId").value;
        const name = document.getElementById("libName").value.trim();
        const mediaType = document.getElementById("libMediaType").value;
        const rootPath = document.getElementById("libRootPath").value.trim();
        const enabled = document.getElementById("libEnabled").checked;

        if (!name || !rootPath) {
            showAlert("Name and root path are required", "error");
            return;
        }

        try {
            if (id) {
                await api.updateLibrary(id, { name, root_path: rootPath, enabled });
            } else {
                await api.createLibrary({ name, media_type: mediaType, root_path: rootPath, enabled });
            }
            closeModal("libraryModal");
            loadLibraries();
            showAlert("Library saved successfully", "success");
        } catch (error) {
            showAlert(`Failed saving library: ${error.message}`, "error");
        }
    };

    // Folder Finder / Browser
    const btnBrowseFolder = document.getElementById("btnBrowseFolder");
    if (btnBrowseFolder) {
        btnBrowseFolder.onclick = () => openFolderBrowser(document.getElementById("libRootPath").value.trim());
    }
    const btnFolderGo = document.getElementById("btnFolderGo");
    if (btnFolderGo) {
        btnFolderGo.onclick = () => {
            const enteredPath = document.getElementById("folderCurrentPath").value.trim();
            if (enteredPath) {
                loadDirectory(enteredPath);
            }
        };
    }
    const folderCurrentPath = document.getElementById("folderCurrentPath");
    if (folderCurrentPath) {
        folderCurrentPath.onkeydown = (event) => {
            if (event.key === "Enter") {
                const enteredPath = folderCurrentPath.value.trim();
                if (enteredPath) {
                    loadDirectory(enteredPath);
                }
            }
        };
    }
    const btnSelectFolder = document.getElementById("btnSelectFolder");
    if (btnSelectFolder) {
        btnSelectFolder.onclick = () => {
            if (selectedBrowserDirectory) {
                document.getElementById("libRootPath").value = selectedBrowserDirectory;
            }
            closeModal("folderBrowserModal");
        };
    }

    document.querySelector("#librariesTable tbody").onclick = async (event) => {
        const button = event.target.closest("button");
        if (!button) return;
        const action = button.dataset.action;
        const id = button.dataset.id;

        if (action === "scan") {
            switchTab("scan");
            document.getElementById("scanLibrarySelect").value = id;
            document.getElementById("btnStartScan").click();
        } else if (action === "edit") {
            try {
                const libraries = await api.getLibraries();
                const libraryItem = libraries.find((item) => item.id === id);
                if (!libraryItem) return;
                document.getElementById("libId").value = libraryItem.id;
                document.getElementById("libName").value = libraryItem.name;
                document.getElementById("libMediaType").value = libraryItem.media_type;
                document.getElementById("libRootPath").value = libraryItem.root_path || "";
                document.getElementById("libEnabled").checked = libraryItem.enabled !== false;
                document.getElementById("libraryModalTitle").textContent = "Edit Library";
                openModal("libraryModal");
            } catch (error) {
                showAlert(`Failed loading library for edit: ${error.message}`, "error");
            }
        } else if (action === "delete") {
            if (confirm(`Are you sure you want to delete library "${id}"?`)) {
                try {
                    await api.deleteLibrary(id);
                    loadLibraries();
                    showAlert("Library deleted", "success");
                } catch (error) {
                    showAlert(`Could not delete library: ${error.message}`, "error");
                }
            }
        }
    };

    // Initial load
    initSSE();
    loadDashboard();
});
