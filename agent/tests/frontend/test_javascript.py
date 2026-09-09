"""JavaScript client-logic tests executed through the bundled V8 engine.

The SPA static assets (api.js / logic.js / app.js) are ES modules that cannot
be executed "as-is" by a bare V8 context. Each test composes a single
evaluation program that:

* injects browser shims (fetch, URLSearchParams, timers, document),
* strips ``export`` keywords from the module source,
* runs a small probe script,
* captures the outcome into the ``__result`` global for Python to read back.

Async probes (api.js) resolve through V8's microtask queue, which is flushed by
the polling loop in ``_eval_js``.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer

_STATIC_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "scan_agent" / "static"
)

_API_SOURCE = "__API_SOURCE__"
_LOGIC_SOURCE = "__LOGIC_SOURCE__"
_APP_SOURCE = "__APP_SOURCE__"
_PROBE = "__PROBE__"
_SETUP = "__SETUP__"

_EXPORT_RE = re.compile(r"^export\s+", re.MULTILINE)
_IMPORT_STRIP_RE = re.compile(r"^import [^\n]+;?\n?", re.MULTILINE)


def _read_static(filename: str) -> str:
    return (_STATIC_DIR / filename).read_text(encoding="utf-8")


def _strip_exports(source: str) -> str:
    return _EXPORT_RE.sub("", source)


_API_PREAMBLE = """\
const __fetchLog = [];
let __mockResponse = null;
let __mockError = null;

function fetch(url, config) {
    __fetchLog.push({ url: url, config: config ? JSON.parse(JSON.stringify(config)) : null });
    if (__mockError !== null) {
        return Promise.reject(__mockError);
    }
    return Promise.resolve(__mockResponse);
}

function URLSearchParams(init) {
    this.__pairs = [];
    if (typeof init === "string") {
        if (init) {
            this.__pairs.push(init);
        }
    } else if (init) {
        for (const key of Object.keys(init)) {
            this.__pairs.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(init[key])));
        }
    }
}
URLSearchParams.prototype.toString = function () {
    return this.__pairs.join("&");
};

function mockResponse(status, body) {
    const statusTexts = { 404: "Not Found", 500: "Internal Server Error", 409: "Conflict", 204: "No Content" };
    return {
        ok: status >= 200 && status < 300,
        status: status,
        statusText: (statusTexts[status] !== undefined) ? statusTexts[status] : "HTTP " + status,
        json: async () => {
            if (body !== null && typeof body === "object") {
                return body;
            }
            throw new SyntaxError("Unexpected token < in JSON");
        },
    };
}

async function tryCall(fn) {
    try {
        const value = await fn();
        return { resolved: true, value: value };
    } catch (error) {
        return { resolved: false, message: String((error && error.message) || error) };
    }
}

__API_SOURCE__

var __result = null;
(async () => {
    const __out = { fetchLog: __fetchLog };
    try {
        __PROBE__
        __result = JSON.stringify(__out);
    } catch (error) {
        __out.__error = String((error && error.message) || error);
        __result = JSON.stringify(__out);
    }
})();
"""


def _api_program(probe_js: str) -> str:
    return _API_PREAMBLE.replace(
        _API_SOURCE, _strip_exports(_read_static("api.js"))
    ).replace(_PROBE, probe_js)


_LOGIC_PROGRAM = """\
var __timers = [];
var __timerId = 0;
function setTimeout(fn, ms) {
    __timers.push({ id: ++__timerId, fn: fn, ms: ms, cancelled: false });
    return __timerId;
}
function setInterval() { return 0; }
function clearTimeout(id) {
    for (const timer of __timers) {
        if (timer.id === id) {
            timer.cancelled = true;
        }
    }
}
function clearInterval() {}

__LOGIC_SOURCE__

__SETUP__

var __result = JSON.stringify({
__PROBE__
});
"""


def _logic_program(setup_js: str, probe_js: str) -> str:
    return (
        _LOGIC_PROGRAM.replace(_LOGIC_SOURCE, _strip_exports(_read_static("logic.js")))
        .replace(_SETUP, setup_js)
        .replace(_PROBE, probe_js)
    )


_APP_LOAD_PROGRAM = """\
const document = { addEventListener: () => {} };

__APP_SOURCE__

var __result = JSON.stringify({ loaded: true });
"""


def _app_load_program() -> str:
    app_source = _IMPORT_STRIP_RE.sub("", _read_static("app.js"))
    return _APP_LOAD_PROGRAM.replace(_APP_SOURCE, app_source)


def _eval_js(engine: MiniRacer, program: str, *, timeout: float = 3.0) -> object:
    engine.eval(program)
    deadline = time.monotonic() + timeout
    raw_result = None
    while time.monotonic() < deadline:
        raw_result = engine.eval("__result")
        if raw_result is not None:
            return json.loads(raw_result)
        time.sleep(0.002)
    raise AssertionError("JavaScript program timed out without setting __result")


@pytest.fixture
def engine() -> Iterator[MiniRacer]:
    return MiniRacer()


def _api_test(engine: MiniRacer, probe_js: str) -> dict[str, object]:
    raw_result = _eval_js(engine, _api_program(probe_js))
    assert isinstance(raw_result, dict)
    return raw_result


def _logic_test(engine: MiniRacer, setup_js: str, probe_js: str) -> dict[str, object]:
    raw_result = _eval_js(engine, _logic_program(setup_js, probe_js))
    assert isinstance(raw_result, dict)
    return raw_result


def test_api_request_get_health(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockResponse = mockResponse(200, { status: "ok" });
        __out.health = await api.getHealth();
        """,
    )
    assert result["health"] == {"status": "ok"}
    assert result["fetchLog"] == [
        {
            "url": "/api/v1/health",
            "config": {"headers": {"Content-Type": "application/json"}},
        }
    ]


def test_api_request_serializes_json_body(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockResponse = mockResponse(200, {});
        await api.startScan({ library_id: "tv", pass_number: 3 });
        """,
    )
    entry = result["fetchLog"][0]
    assert entry["url"] == "/api/v1/scan"
    assert entry["config"]["method"] == "POST"
    assert json.loads(entry["config"]["body"]) == {"library_id": "tv", "pass_number": 3}
    assert entry["config"]["headers"]["Content-Type"] == "application/json"


def test_api_request_204_returns_null(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockResponse = mockResponse(204, null);
        __out.value = await api.cancelScan();
        """,
    )
    assert result["value"] is None
    assert result["fetchLog"][0]["url"] == "/api/v1/scan/cancel"
    assert result["fetchLog"][0]["config"]["method"] == "POST"


def test_api_request_non_ok_uses_error_detail(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockResponse = mockResponse(409, { detail: "a scan is already running" });
        __out.result = await tryCall(() => api.startScan({ library_id: "tv" }));
        """,
    )
    assert result["result"] == {
        "resolved": False,
        "message": "a scan is already running",
    }


def test_api_request_non_ok_falls_back_to_status_text(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockResponse = mockResponse(500, "<html>boom</html>");
        __out.result = await tryCall(() => api.updateConfig({}));
        """,
    )
    assert result["result"] == {"resolved": False, "message": "Internal Server Error"}


def test_api_request_network_error_propagates(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockError = new Error("network unreachable");
        __out.result = await tryCall(() => api.getHealth());
        """,
    )
    assert result["result"] == {"resolved": False, "message": "network unreachable"}


def test_api_browse_directory_path_is_encoded(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockResponse = mockResponse(200, []);
        await api.browseFilesystem("/media/Anime Collection");
        """,
    )
    assert result["fetchLog"][0]["url"] == (
        "/api/v1/filesystem/browse?path=%2Fmedia%2FAnime%20Collection"
    )


def test_api_metadata_search_encodes_query(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        __mockResponse = mockResponse(200, []);
        await api.searchMetadata("B: The Beginning", "series");
        """,
    )
    assert result["fetchLog"][0]["url"] == (
        "/api/v1/services/metadata/search?query=B%3A%20The%20Beginning&type=series"
    )


def test_api_endpoint_builders(engine: MiniRacer) -> None:
    result = _api_test(
        engine,
        """
        const expectations = {
            getHealth: { url: "/api/v1/health", call: () => api.getHealth() },
            getConfig: { url: "/api/v1/config", call: () => api.getConfig() },
            updateConfig: { url: "/api/v1/config", method: "PUT", call: () => api.updateConfig({ verify_https: true }) },
            getLibraries: { url: "/api/v1/libraries", call: () => api.getLibraries() },
            createLibrary: { url: "/api/v1/libraries", method: "POST", call: () => api.createLibrary({ name: "TV" }) },
            updateLibrary: { url: "/api/v1/libraries/7", method: "PATCH", call: () => api.updateLibrary(7, { name: "TV" }) },
            deleteLibrary: { url: "/api/v1/libraries/9", method: "DELETE", call: () => api.deleteLibrary(9) },
            browseFilesystem: { url: "/api/v1/filesystem/browse?path=%2Ftmp", call: () => api.browseFilesystem("/tmp") },
            startScan: { url: "/api/v1/scan", method: "POST", call: () => api.startScan({}) },
            cancelScan: { url: "/api/v1/scan/cancel", method: "POST", call: () => api.cancelScan() },
            getScanStatus: { url: "/api/v1/scan/status", call: () => api.getScanStatus() },
            getScanJobs: { url: "/api/v1/scan/jobs?limit=5", call: () => api.getScanJobs(5) },
            getLogs: { url: "/api/v1/scan/logs?limit=50", call: () => api.getLogs(50) },
            getLogsWithLevel: { url: "/api/v1/scan/logs?limit=50&level=DEBUG", call: () => api.getLogs(50, "DEBUG") },
            listSeries: { url: "/api/v1/library/series?query=a&sort=year", call: () => api.listSeries({ query: "a", sort: "year" }) },
            listEpisodes: { url: "/api/v1/library/episodes?library_type=anime", call: () => api.listEpisodes({ library_type: "anime" }) },
            getSeriesDetail: { url: "/api/v1/library/series/42", call: () => api.getSeriesDetail(42) },
            listMovies: { url: "/api/v1/library/movies", call: () => api.listMovies({}) },
            getMovieDetail: { url: "/api/v1/library/movies/9", call: () => api.getMovieDetail(9) },
            matchMetadata: { url: "/api/v1/services/metadata/series/5/match", method: "POST", call: () => api.matchMetadata("series", 5, "123") },
            previewRename: { url: "/api/v1/services/rename/preview?dir=%2Ft&pattern=video", call: () => api.previewRename({ dir: "/t", pattern: "video" }) },
            applyRename: { url: "/api/v1/services/rename/apply", method: "POST", call: () => api.applyRename({}) },
            listSubtitles: { url: "/api/v1/services/subtitles?media_type=series&media_id=5", call: () => api.listSubtitles("series", 5) },
            downloadSubtitle: { url: "/api/v1/services/subtitles/f-1/download", method: "POST", call: () => api.downloadSubtitle("f-1", {}) },
            getTmdbSeriesSeasons: { url: "/api/v1/services/metadata/tmdb/series/99/seasons", call: () => api.getTmdbSeriesSeasons("99") },
            getTmdbSeasonEpisodes: { url: "/api/v1/services/metadata/tmdb/series/99/episodes?season_number=2", call: () => api.getTmdbSeasonEpisodes("99", 2) },
            applyManualMetadataMappings: { url: "/api/v1/services/metadata/series/42/manual-map", method: "POST", call: () => api.applyManualMetadataMappings(42, []) },
        };
        __out.endpoints = {};
        for (const name of Object.keys(expectations)) {
            __mockResponse = mockResponse(200, {});
            const expectation = expectations[name];
            await expectation.call();
            const entry = __fetchLog[__fetchLog.length - 1];
            __out.endpoints[name] = { url: entry.url, method: entry.config.method || "GET" };
        }
        """,
    )
    endpoints = {
        "getHealth": ("/api/v1/health", "GET"),
        "getConfig": ("/api/v1/config", "GET"),
        "updateConfig": ("/api/v1/config", "PUT"),
        "getLibraries": ("/api/v1/libraries", "GET"),
        "createLibrary": ("/api/v1/libraries", "POST"),
        "updateLibrary": ("/api/v1/libraries/7", "PATCH"),
        "deleteLibrary": ("/api/v1/libraries/9", "DELETE"),
        "browseFilesystem": ("/api/v1/filesystem/browse?path=%2Ftmp", "GET"),
        "startScan": ("/api/v1/scan", "POST"),
        "cancelScan": ("/api/v1/scan/cancel", "POST"),
        "getScanStatus": ("/api/v1/scan/status", "GET"),
        "getScanJobs": ("/api/v1/scan/jobs?limit=5", "GET"),
        "getLogs": ("/api/v1/scan/logs?limit=50", "GET"),
        "getLogsWithLevel": ("/api/v1/scan/logs?limit=50&level=DEBUG", "GET"),
        "listSeries": ("/api/v1/library/series?query=a&sort=year", "GET"),
        "listEpisodes": ("/api/v1/library/episodes?library_type=anime", "GET"),
        "getSeriesDetail": ("/api/v1/library/series/42", "GET"),
        "listMovies": ("/api/v1/library/movies", "GET"),
        "getMovieDetail": ("/api/v1/library/movies/9", "GET"),
        "matchMetadata": ("/api/v1/services/metadata/series/5/match", "POST"),
        "previewRename": (
            "/api/v1/services/rename/preview?dir=%2Ft&pattern=video",
            "GET",
        ),
        "applyRename": ("/api/v1/services/rename/apply", "POST"),
        "listSubtitles": (
            "/api/v1/services/subtitles?media_type=series&media_id=5",
            "GET",
        ),
        "downloadSubtitle": ("/api/v1/services/subtitles/f-1/download", "POST"),
        "getTmdbSeriesSeasons": (
            "/api/v1/services/metadata/tmdb/series/99/seasons",
            "GET",
        ),
        "getTmdbSeasonEpisodes": (
            "/api/v1/services/metadata/tmdb/series/99/episodes?season_number=2",
            "GET",
        ),
        "applyManualMetadataMappings": (
            "/api/v1/services/metadata/series/42/manual-map",
            "POST",
        ),
    }
    for name, (url, method) in endpoints.items():
        assert result["endpoints"][name] == {"url": url, "method": method}


def test_logic_get_poster_url(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        "",
        """
        emptyString: getPosterUrl(""),
        nullValue: getPosterUrl(null),
        undefinedValue: getPosterUrl(undefined),
        absoluteHttp: getPosterUrl("http://localhost:8800/poster.jpg"),
        absoluteHttps: getPosterUrl("https://image.tmdb.org/t/p/w500/ab12.jpg"),
        tmdbSingleSegment: getPosterUrl("/ab12.jpg"),
        localDirectoryPath: getPosterUrl("/media/series/invincible season 1/S01E01.mkv"),
        relativePath: getPosterUrl("poster.jpg"),
        """,
    )
    assert result == {
        "emptyString": "",
        "nullValue": "",
        "undefinedValue": "",
        "absoluteHttp": "http://localhost:8800/poster.jpg",
        "absoluteHttps": "https://image.tmdb.org/t/p/w500/ab12.jpg",
        "tmdbSingleSegment": "https://image.tmdb.org/t/p/w500/ab12.jpg",
        "localDirectoryPath": (
            "/api/v1/images/poster?path=%2Fmedia%2Fseries%2Finvincible%20season%201%2FS01E01.mkv"
        ),
        "relativePath": "/api/v1/images/poster?path=poster.jpg",
    }


def test_logic_escape_html(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        "",
        """
        nullValue: escapeHtml(null),
        emptyString: escapeHtml(""),
        plainText: escapeHtml("hello world"),
        markup: escapeHtml('Tom & Jerry <bold> > ok "quoted"'),
        numericInput: escapeHtml(123),
        zeroInput: escapeHtml(0),
        falseInput: escapeHtml(false),
        """,
    )
    assert result == {
        "nullValue": "",
        "emptyString": "",
        "plainText": "hello world",
        "markup": "Tom &amp; Jerry &lt;bold&gt; &gt; ok &quot;quoted&quot;",
        "numericInput": "123",
        "zeroInput": "",
        "falseInput": "",
    }


def test_logic_debounce_coalesces_rapid_calls(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        """
        const calls = [];
        const debounced = debounce((value) => calls.push(value), 300);
        debounced(1);
        debounced(2);
        debounced(3);
        const scheduled = __timers.filter((timer) => !timer.cancelled);
        scheduled.forEach((timer) => timer.fn());
        const receiver = { value: null };
        const receiverDebounced = debounce(function (next) { this.value = next; }, 300);
        receiverDebounced.call(receiver, "x");
        const receiverTimer = __timers.filter((timer) => !timer.cancelled).pop();
        receiverTimer.fn();
        """,
        """
        scheduledTimerCount: scheduled.length,
        callsAfterFlush: calls,
        receiverValue: receiver.value,
        scheduledTimerMs: scheduled[0].ms,
        """,
    )
    assert result == {
        "scheduledTimerCount": 1,
        "callsAfterFlush": [3],
        "receiverValue": "x",
        "scheduledTimerMs": 300,
    }


def test_logic_progress_step_for_event(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        "",
        """
        libraryStart: progressStepForEvent({ type: "library_start", library: "TV Shows" }),
        passStartOne: progressStepForEvent({ type: "pass_start", pass: 1 }),
        offlineScan: progressStepForEvent({ type: "start_offline_scan" }),
        passStartTwo: progressStepForEvent({ type: "pass_start", pass: 2 }),
        metadataResolution: progressStepForEvent({ type: "start_metadata_resolution" }),
        passStartThree: progressStepForEvent({ type: "pass_start", pass: 3 }),
        technicalProbe: progressStepForEvent({ type: "start_technical_probe" }),
        seasonFinished: progressStepForEvent({ type: "season_finished", series: "Invincible", season: "S01E01" }),
        movieFinished: progressStepForEvent({ type: "movie_finished", movie: "Dune" }),
        libraryFinished: progressStepForEvent({ type: "library_finished", library: "Movies" }),
        unknownType: progressStepForEvent({ type: "flibbit" }),
        nullPayload: progressStepForEvent(null),
        unsupportedPass: progressStepForEvent({ type: "pass_start", pass: 99 }),
        """,
    )
    assert result == {
        "libraryStart": {"label": "Scanning library: TV Shows...", "widthPercent": 10},
        "passStartOne": {"label": "Pass 1: Discovering files...", "widthPercent": 30},
        "offlineScan": {"label": "Pass 1: Discovering files...", "widthPercent": 30},
        "passStartTwo": {"label": "Pass 2: Resolving metadata...", "widthPercent": 60},
        "metadataResolution": {
            "label": "Pass 2: Resolving metadata...",
            "widthPercent": 60,
        },
        "passStartThree": {
            "label": "Pass 3: Probing technical properties (ffprobe)...",
            "widthPercent": 85,
        },
        "technicalProbe": {
            "label": "Pass 3: Probing technical properties (ffprobe)...",
            "widthPercent": 85,
        },
        "seasonFinished": {
            "label": "Scanned Invincible - S01E01",
            "widthPercent": None,
        },
        "movieFinished": {"label": "Scanned Dune", "widthPercent": None},
        "libraryFinished": {"label": "Finished library: Movies", "widthPercent": 100},
        "unknownType": None,
        "nullPayload": None,
        "unsupportedPass": None,
    }


def test_logic_parse_scan_progress_step(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        "",
        """
        validPayload: parseScanProgressStep('{"type":"library_start","library":"TV"}'),
        invalidJson: parseScanProgressStep("{not json"),
        unknownType: parseScanProgressStep('{"type":"nope"}'),
        """,
    )
    assert result == {
        "validPayload": {"label": "Scanning library: TV...", "widthPercent": 10},
        "invalidJson": None,
        "unknownType": None,
    }


def test_app_imports_logic_helpers() -> None:
    app_source = _read_static("app.js")
    logic_source = _read_static("logic.js")

    for helper in (
        "getPosterUrl",
        "escapeHtml",
        "debounce",
        "parseScanProgressStep",
        "buildBrowseParams",
        "filterLibrariesForBrowseType",
        "matchEpisodesSequentially",
        "buildManualMappingPayload",
    ):
        assert re.search(rf"function {helper}\s*\(", logic_source)
        assert re.search(rf"\b{helper}\s*\(", app_source)
        assert not re.search(rf"function {helper}\s*\(", app_source)


def test_logic_match_episodes_sequentially(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        """
        const tmdbEpisodes = [
            { id: 101, name: "Pilot", episode_number: 1 },
            { id: 102, name: "Second", episode_number: 2 },
            { id: 103, name: "Third", episode_number: 3 },
        ];
        const localFiles = [
            { path: "/media/Show/S01E01.mkv", tmdb_episode_identifier: null },
            { path: "/media/Show/S01E02.mkv", tmdb_episode_identifier: 102 },
        ];
        """,
        """
        matched: matchEpisodesSequentially(tmdbEpisodes, localFiles),
        emptyTmdb: matchEpisodesSequentially([], localFiles),
        emptyLocal: matchEpisodesSequentially(tmdbEpisodes, []),
        nullInputs: matchEpisodesSequentially(null, null),
        """,
    )
    assert result["emptyTmdb"] == []
    assert len(result["matched"]) == 3
    assert result["matched"][0]["mappedPath"] == "/media/Show/S01E01.mkv"
    assert result["matched"][1]["mappedPath"] == "/media/Show/S01E02.mkv"
    assert result["matched"][2]["mappedPath"] is None
    assert result["emptyLocal"][0]["mappedPath"] is None
    assert result["nullInputs"] == []


def test_logic_build_manual_mapping_payload(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        """
        const rows = [
            {
                path: "/media/Show/S01E01.mkv",
                tmdbIdentifier: 999,
                tmdbEpisodeIdentifier: 101,
                name: "Pilot",
                episodeNumber: 1,
                seasonNumber: 1,
                airDate: "2024-01-01",
                overview: "First episode",
                runtimeSeconds: 1800,
            },
            {
                path: "",
                name: "Unmapped",
            },
        ];
        """,
        """
        payload: buildManualMappingPayload(rows),
        emptyPayload: buildManualMappingPayload([]),
        nullPayload: buildManualMappingPayload(null),
        """,
    )
    assert result["emptyPayload"] == {"episode_mappings": []}
    assert result["nullPayload"] == {"episode_mappings": []}
    assert len(result["payload"]["episode_mappings"]) == 1
    mapping = result["payload"]["episode_mappings"][0]
    assert mapping["path"] == "/media/Show/S01E01.mkv"
    assert mapping["tmdb_identifier"] == "999"
    assert mapping["tmdb_episode_identifier"] == "101"
    assert mapping["name"] == "Pilot"
    assert mapping["episode_number"] == 1
    assert mapping["season_number"] == 1
    assert mapping["air_date"] == "2024-01-01"
    assert mapping["overview"] == "First episode"
    assert mapping["runtime_seconds"] == 1800


def test_logic_filter_libraries_for_browse_type(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        """
        const allLibs = [
            { id: "tv", name: "TV Shows", media_type: "tv" },
            { id: "anime", name: "Anime Collection", media_type: "anime" },
            { id: "movie", name: "Movies", media_type: "movie" },
            { id: "docs", name: "Docuseries", media_type: "tv" },
        ];
        """,
        """
        seriesLibs: filterLibrariesForBrowseType(allLibs, "series"),
        animeLibs: filterLibrariesForBrowseType(allLibs, "anime"),
        movieLibs: filterLibrariesForBrowseType(allLibs, "movie"),
        emptyInput: filterLibrariesForBrowseType([], "series"),
        nullInput: filterLibrariesForBrowseType(null, "series"),
        """,
    )
    assert result == {
        "seriesLibs": [
            {"id": "tv", "name": "TV Shows", "media_type": "tv"},
            {"id": "docs", "name": "Docuseries", "media_type": "tv"},
        ],
        "animeLibs": [
            {"id": "anime", "name": "Anime Collection", "media_type": "anime"},
        ],
        "movieLibs": [
            {"id": "movie", "name": "Movies", "media_type": "movie"},
        ],
        "emptyInput": [],
        "nullInput": [],
    }


def test_logic_build_browse_params(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        "",
        """
        seriesParams: buildBrowseParams("series", "Breaking", "1", "name"),
        animeParams: buildBrowseParams("anime", "Frieren", "2", "year_desc"),
        movieParams: buildBrowseParams("movie", "", "", "date_added"),
        seriesDefaults: buildBrowseParams("series"),
        animeDefaults: buildBrowseParams("anime"),
        movieDefaults: buildBrowseParams("movie"),
        """,
    )
    assert result == {
        "seriesParams": {
            "library_type": "tv",
            "query": "Breaking",
            "library_id": "1",
            "sort": "name",
        },
        "animeParams": {
            "library_type": "anime",
            "query": "Frieren",
            "library_id": "2",
            "sort": "year_desc",
        },
        "movieParams": {
            "sort": "date_added",
        },
        "seriesDefaults": {
            "library_type": "tv",
        },
        "animeDefaults": {
            "library_type": "anime",
        },
        "movieDefaults": {},
    }


def test_logic_resolve_log_level(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        "",
        """
        nullValue: resolveLogLevel(null),
        plainString: resolveLogLevel("Just a regular message"),
        stringError: resolveLogLevel("ERROR: something broke"),
        stringWarning: resolveLogLevel("2026-09-09 WARNING scan: missing dir"),
        stringDebug: resolveLogLevel("[DEBUG] detail trace"),
        objectExplicitLevel: resolveLogLevel({ level: "WARNING", message: "Hello" }),
        objectImplicitLevel: resolveLogLevel({ message: "ERROR: critical failure" }),
        objectDefaultLevel: resolveLogLevel({ message: "just info" }),
        """,
    )
    assert result == {
        "nullValue": "INFO",
        "plainString": "INFO",
        "stringError": "ERROR",
        "stringWarning": "WARNING",
        "stringDebug": "DEBUG",
        "objectExplicitLevel": "WARNING",
        "objectImplicitLevel": "ERROR",
        "objectDefaultLevel": "INFO",
    }


def test_logic_is_log_level_visible(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        "",
        """
        allFilterDebug: isLogLevelVisible("DEBUG", "ALL"),
        allFilterInfo: isLogLevelVisible("INFO", "ALL"),
        allFilterError: isLogLevelVisible("ERROR", "ALL"),

        debugFilterDebug: isLogLevelVisible("DEBUG", "DEBUG"),
        debugFilterInfo: isLogLevelVisible("INFO", "DEBUG"),

        infoFilterDebug: isLogLevelVisible("DEBUG", "INFO"),
        infoFilterInfo: isLogLevelVisible("INFO", "INFO"),
        infoFilterWarning: isLogLevelVisible("WARNING", "INFO"),
        infoFilterError: isLogLevelVisible("ERROR", "INFO"),

        warningFilterInfo: isLogLevelVisible("INFO", "WARNING"),
        warningFilterWarning: isLogLevelVisible("WARNING", "WARNING"),
        warningFilterError: isLogLevelVisible("ERROR", "WARNING"),

        errorFilterWarning: isLogLevelVisible("WARNING", "ERROR"),
        errorFilterError: isLogLevelVisible("ERROR", "ERROR"),
        """,
    )
    assert result == {
        "allFilterDebug": True,
        "allFilterInfo": True,
        "allFilterError": True,
        "debugFilterDebug": True,
        "debugFilterInfo": True,
        "infoFilterDebug": False,
        "infoFilterInfo": True,
        "infoFilterWarning": True,
        "infoFilterError": True,
        "warningFilterInfo": False,
        "warningFilterWarning": True,
        "warningFilterError": True,
        "errorFilterWarning": False,
        "errorFilterError": True,
    }


def test_app_module_loads_cleanly(engine: MiniRacer) -> None:
    result = _eval_js(engine, _app_load_program())
    assert result == {"loaded": True}


def test_filter_series_with_episodes(engine: MiniRacer) -> None:
    result = _logic_test(
        engine,
        setup_js="""
        const testSeriesList = [
            {
                id: 1,
                name: "Series With Episodes",
                seasons: [
                    {
                        season_number: 1,
                        episodes: [{ name: "Ep 1", path: "/media/tv/ep1.mkv" }]
                    }
                ]
            },
            {
                id: 2,
                name: "Empty Series (No Seasons)",
                seasons: []
            },
            {
                id: 3,
                name: "Empty Season Series",
                seasons: [
                    {
                        season_number: 1,
                        episodes: []
                    }
                ]
            },
            {
                id: 4,
                name: "Null Seasons Series",
                seasons: null
            }
        ];
        const filtered = filterSeriesWithEpisodes(testSeriesList);
        """,
        probe_js="""
        initialCount: testSeriesList.length,
        filteredCount: filtered.length,
        retainedName: filtered[0].name,
        handlesEmptyInput: filterSeriesWithEpisodes([]).length,
        handlesNullInput: filterSeriesWithEpisodes(null).length
        """,
    )
    assert result == {
        "initialCount": 4,
        "filteredCount": 1,
        "retainedName": "Series With Episodes",
        "handlesEmptyInput": 0,
        "handlesNullInput": 0,
    }
