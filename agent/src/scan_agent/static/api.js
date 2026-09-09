/**
 * API client wrapper for LAN Streamer Scan Agent REST endpoints.
 */
const API_BASE = "/api/v1";

export async function request(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {}),
    };

    const config = {
        ...options,
        headers,
    };

    if (config.body && typeof config.body === "object") {
        config.body = JSON.stringify(config.body);
    }

    const response = await fetch(url, config);
    if (!response.ok) {
        let errorDetail = response.statusText;
        try {
            const data = await response.json();
            if (data && data.detail) {
                errorDetail = data.detail;
            }
        } catch {
            // Ignore json parse error on non-json error responses
        }
        throw new Error(errorDetail || `HTTP ${response.status}`);
    }

    if (response.status === 204) {
        return null;
    }
    return await response.json();
}

export const api = {
    // Health & System
    getHealth: () => request("/health"),
    getConfig: () => request("/config"),
    updateConfig: (payload) => request("/config", { method: "PUT", body: payload }),

    // Libraries
    getLibraries: () => request("/libraries"),
    createLibrary: (payload) => request("/libraries", { method: "POST", body: payload }),
    updateLibrary: (id, payload) => request(`/libraries/${id}`, { method: "PATCH", body: payload }),
    deleteLibrary: (id) => request(`/libraries/${id}`, { method: "DELETE" }),
    browseFilesystem: (directoryPath) => {
        const search = directoryPath ? `?path=${encodeURIComponent(directoryPath)}` : "";
        return request(`/filesystem/browse${search}`);
    },

    // Scanning
    startScan: (payload) => request("/scan", { method: "POST", body: payload }),
    cancelScan: () => request("/scan/cancel", { method: "POST" }),
    getScanStatus: () => request("/scan/status"),
    getScanJobs: (limit = 20) => request(`/scan/jobs?limit=${limit}`),
    getLogs: (limit = 200) => request(`/scan/logs?limit=${limit}`),

    // Library Browser
    listSeries: (params = {}) => {
        const search = new URLSearchParams(params).toString();
        return request(`/library/series${search ? "?" + search : ""}`);
    },
    listEpisodes: (params = {}) => {
        const search = new URLSearchParams(params).toString();
        return request(`/library/episodes${search ? "?" + search : ""}`);
    },
    getSeriesDetail: (id) => request(`/library/series/${id}`),
    listMovies: (params = {}) => {
        const search = new URLSearchParams(params).toString();
        return request(`/library/movies${search ? "?" + search : ""}`);
    },
    getMovieDetail: (id) => request(`/library/movies/${id}`),

    // Metadata Services
    searchMetadata: (query, mediaType) =>
        request(`/services/metadata/search?query=${encodeURIComponent(query)}&type=${mediaType}`),
    matchMetadata: (mediaType, mediaId, tmdbIdentifier) =>
        request(`/services/metadata/${mediaType}/${mediaId}/match`, {
            method: "POST",
            body: { tmdb_identifier: String(tmdbIdentifier) },
        }),

    // Renaming
    previewRename: (params) => {
        const search = new URLSearchParams(params).toString();
        return request(`/services/rename/preview?${search}`);
    },
    applyRename: (payload) => request("/services/rename/apply", { method: "POST", body: payload }),

    // Subtitles
    listSubtitles: (mediaType, mediaId) =>
        request(`/services/subtitles?media_type=${mediaType}&media_id=${mediaId}`),
    searchSubtitles: (mediaType, mediaId) =>
        request(`/services/subtitles/search?media_type=${mediaType}&media_id=${mediaId}`),
    downloadSubtitle: (fileId, payload) =>
        request(`/services/subtitles/${fileId}/download`, { method: "POST", body: payload }),
};
