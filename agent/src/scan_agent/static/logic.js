/**
 * Pure, DOM-free client logic for the LAN Streamer Scan Agent SPA.
 *
 * These helpers intentionally avoid browser globals (document, fetch,
 * EventSource) so they can be unit-tested in isolation through the bundled V8
 * engine (see agent/tests/test_javascript.py).
 */

export function getPosterUrl(posterPath) {
    if (!posterPath) return "";
    if (posterPath.startsWith("http://") || posterPath.startsWith("https://")) {
        return posterPath;
    }
    if (posterPath.startsWith("/") && !posterPath.includes("/", 1)) {
        return `https://image.tmdb.org/t/p/w500${posterPath}`;
    }
    return `/api/v1/images/poster?path=${encodeURIComponent(posterPath)}`;
}

export function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

export function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

/**
 * Construct query parameters for browsing media.
 *
 * Maps UI browse type ("series", "anime", "movie") to API parameters.
 * "series" maps to { library_type: "tv" }, while "anime" maps to { library_type: "anime" }.
 */
export function buildBrowseParams(browseType, query = "", libraryIdentifier = "", sort = "") {
    const parameters = {};
    if (browseType === "series") {
        parameters.library_type = "tv";
    } else if (browseType === "anime") {
        parameters.library_type = "anime";
    }
    if (sort) {
        parameters.sort = sort;
    }
    if (query) {
        parameters.query = query;
    }
    if (libraryIdentifier) {
        parameters.library_id = libraryIdentifier;
    }
    return parameters;
}

/**
 * Map an SSE "scan.progress" payload to a UI update step.
 *
 * Returns `{ label, widthPercent }` where `label` is the text to show and
 * `widthPercent` is the progress-bar width (or `null` to leave it unchanged),
 * or `null` when the event type is not handled.
 */
export function progressStepForEvent(payload) {
    if (!payload) {
        return null;
    }
    const pass = payload.pass;
    if (payload.type === "library_start") {
        return { label: `Scanning library: ${payload.library}...`, widthPercent: 10 };
    }
    if (payload.type === "start_offline_scan" || (payload.type === "pass_start" && pass === 1)) {
        return { label: "Pass 1: Discovering files...", widthPercent: 30 };
    }
    if (payload.type === "start_metadata_resolution" || (payload.type === "pass_start" && pass === 2)) {
        return { label: "Pass 2: Resolving metadata...", widthPercent: 60 };
    }
    if (payload.type === "start_technical_probe" || (payload.type === "pass_start" && pass === 3)) {
        return { label: "Pass 3: Probing technical properties (ffprobe)...", widthPercent: 85 };
    }
    if (payload.type === "season_finished") {
        return { label: `Scanned ${payload.series} - ${payload.season}`, widthPercent: null };
    }
    if (payload.type === "movie_finished") {
        return { label: `Scanned ${payload.movie}`, widthPercent: null };
    }
    if (payload.type === "library_finished") {
        return { label: `Finished library: ${payload.library}`, widthPercent: 100 };
    }
    return null;
}

/**
 * Parse a raw SSE "scan.progress" event payload into a UI update step,
 * returning `null` for unparseable or unhandled payloads.
 */
export function parseScanProgressStep(rawData) {
    let payload;
    try {
        payload = JSON.parse(rawData);
    } catch {
        return null;
    }
    return progressStepForEvent(payload);
}

/**
 * Filter an array of library definitions by the active browse type.
 *
 * "series" matches libraries with media_type "tv", "anime" matches "anime",
 * and "movie" matches "movie".
 */
export function filterLibrariesForBrowseType(libraries, browseType) {
    if (!Array.isArray(libraries)) {
        return [];
    }
    const targetMediaType = browseType === "series" ? "tv" : browseType;
    return libraries.filter((library) => library && library.media_type === targetMediaType);
}

/**
 * Auto-match TMDB episodes with local series files.
 *
 * Checks first whether a local file has a matching TMDB episode identifier,
 * otherwise defaults sequentially by list index.
 */
export function matchEpisodesSequentially(tmdbEpisodes, localFiles) {
    if (!Array.isArray(tmdbEpisodes)) {
        return [];
    }
    const safeLocalFiles = Array.isArray(localFiles) ? localFiles : [];
    return tmdbEpisodes.map((tmdbEpisode, index) => {
        let matchedPath = null;
        if (tmdbEpisode && tmdbEpisode.id) {
            const matchingFile = safeLocalFiles.find(
                (file) => file && String(file.tmdb_episode_identifier) === String(tmdbEpisode.id)
            );
            if (matchingFile && matchingFile.path) {
                matchedPath = matchingFile.path;
            }
        }
        if (!matchedPath && safeLocalFiles[index] && safeLocalFiles[index].path) {
            matchedPath = safeLocalFiles[index].path;
        }
        return {
            tmdbEpisode: tmdbEpisode,
            mappedPath: matchedPath,
        };
    });
}

/**
 * Build request payload for manual metadata mapping from UI table rows.
 */
export function buildManualMappingPayload(mappingRows) {
    if (!Array.isArray(mappingRows)) {
        return { episode_mappings: [] };
    }
    const episodeMappings = [];
    for (const row of mappingRows) {
        if (!row || !row.path) {
            continue;
        }
        episodeMappings.push({
            path: row.path,
            tmdb_identifier: row.tmdbIdentifier ? String(row.tmdbIdentifier) : null,
            tmdb_episode_identifier: row.tmdbEpisodeIdentifier ? String(row.tmdbEpisodeIdentifier) : null,
            name: row.name || null,
            episode_number: row.episodeNumber !== undefined && row.episodeNumber !== null ? Number(row.episodeNumber) : null,
            season_number: row.seasonNumber !== undefined && row.seasonNumber !== null ? Number(row.seasonNumber) : null,
            air_date: row.airDate || null,
            overview: row.overview || null,
            runtime_seconds: row.runtimeSeconds !== undefined && row.runtimeSeconds !== null ? Number(row.runtimeSeconds) : null,
        });
    }
    return { episode_mappings: episodeMappings };
}
