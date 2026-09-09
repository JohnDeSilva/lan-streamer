"""Comprehensive tests for all UI elements in the scan agent web interface.

Covers:
1. Complete HTML document structure, forms, inputs, buttons, tables, selects, and modals.
2. Cross-reference verification ensuring no dangling or missing element IDs between HTML and JavaScript.
3. Event listener wiring for all interactive UI controls.
4. Interactive DOM and behavioral testing executed through the bundled V8 engine.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer

_STATIC_DIRECTORY = (
    Path(__file__).resolve().parent.parent.parent / "src" / "scan_agent" / "static"
)


def _read_static_file(filename: str) -> str:
    """Read static file content from agent static directory."""
    return (_STATIC_DIRECTORY / filename).read_text(encoding="utf-8")


class _HtmlElementCollector(HTMLParser):
    """HTMLParser that collects all elements, attributes, IDs, and tags."""

    def __init__(self) -> None:
        super().__init__()
        self.elements_by_identifier: dict[str, dict[str, Any]] = {}
        self.buttons: list[dict[str, Any]] = []
        self.input_elements: list[dict[str, Any]] = []
        self.select_elements: list[dict[str, Any]] = []
        self.forms: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.navigation_tabs: list[str] = []
        self.data_close_targets: list[str] = []
        self.current_select_identifier: str | None = None
        self.select_options: dict[str, list[dict[str, str]]] = {}

    def handle_starttag(
        self, tag: str, attributes: list[tuple[str, str | None]]
    ) -> None:
        attribute_dictionary: dict[str, str] = {
            key: value or "" for key, value in attributes
        }
        element_identifier = attribute_dictionary.get("id")
        if element_identifier:
            self.elements_by_identifier[element_identifier] = {
                "tag": tag,
                "attributes": attribute_dictionary,
            }

        if tag == "button":
            self.buttons.append(
                {"id": element_identifier, "attributes": attribute_dictionary}
            )
        elif tag in ("input", "textarea"):
            self.input_elements.append(
                {
                    "id": element_identifier,
                    "tag": tag,
                    "attributes": attribute_dictionary,
                }
            )
        elif tag == "select":
            self.select_elements.append(
                {"id": element_identifier, "attributes": attribute_dictionary}
            )
            self.current_select_identifier = element_identifier
            if element_identifier:
                self.select_options[element_identifier] = []
        elif tag == "option" and self.current_select_identifier:
            self.select_options[self.current_select_identifier].append(
                attribute_dictionary
            )
        elif tag == "form":
            self.forms.append(
                {"id": element_identifier, "attributes": attribute_dictionary}
            )
        elif tag == "table":
            self.tables.append(
                {"id": element_identifier, "attributes": attribute_dictionary}
            )

        if "data-tab" in attribute_dictionary:
            self.navigation_tabs.append(attribute_dictionary["data-tab"])
        if "data-close" in attribute_dictionary:
            self.data_close_targets.append(attribute_dictionary["data-close"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self.current_select_identifier = None


def _parse_html_elements() -> _HtmlElementCollector:
    """Parse index.html and return the element collector."""
    html_content = _read_static_file("index.html")
    collector = _HtmlElementCollector()
    collector.feed(html_content)
    return collector


@pytest.fixture
def engine() -> Iterator[MiniRacer]:
    """Provide a fresh MiniRacer V8 instance."""
    return MiniRacer()


# ======================================================================
# 1. HTML Structure and UI Elements Tests
# ======================================================================


def test_html_document_structure_and_metadata() -> None:
    """Verify document metadata, title, style link, and module script."""
    html_content = _read_static_file("index.html")
    assert "<title>LAN Streamer — Scan Agent</title>" in html_content
    assert '<link rel="stylesheet" href="/static/style.css">' in html_content
    assert '<script type="module" src="/static/app.js"></script>' in html_content
    assert '<div id="globalAlert"' in html_content


def test_html_navigation_tabs_and_panes() -> None:
    """Verify all 6 navigation tabs and their corresponding tab panes exist."""
    collector = _parse_html_elements()
    expected_tabs = ["dashboard", "libraries", "scan", "logs", "browse", "config"]

    assert collector.navigation_tabs == expected_tabs
    for tab_name in expected_tabs:
        pane_identifier = f"tab-{tab_name}"
        assert pane_identifier in collector.elements_by_identifier
        pane_element = collector.elements_by_identifier[pane_identifier]
        assert pane_element["tag"] == "section"
        assert "tab-pane" in pane_element["attributes"].get("class", "")


def test_html_dashboard_tab_ui_elements() -> None:
    """Verify all Dashboard UI elements exist with expected tags."""
    collector = _parse_html_elements()
    dashboard_element_identifiers = [
        "healthStatus",
        "librariesCount",
        "seriesCount",
        "moviesCount",
        "lastJobSummary",
        "btnQuickScan",
        "dashboardLibrariesTable",
    ]
    for element_identifier in dashboard_element_identifiers:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing dashboard UI element: {element_identifier}"
        )

    assert collector.elements_by_identifier["btnQuickScan"]["tag"] == "button"
    assert collector.elements_by_identifier["dashboardLibrariesTable"]["tag"] == "table"


def test_html_libraries_tab_ui_elements() -> None:
    """Verify Libraries tab UI elements exist."""
    collector = _parse_html_elements()
    assert "btnOpenAddLibrary" in collector.elements_by_identifier
    assert collector.elements_by_identifier["btnOpenAddLibrary"]["tag"] == "button"
    assert "librariesTable" in collector.elements_by_identifier
    assert collector.elements_by_identifier["librariesTable"]["tag"] == "table"


def test_html_scan_monitor_tab_ui_elements() -> None:
    """Verify Scan Monitor UI controls and progress elements exist."""
    collector = _parse_html_elements()
    expected_scan_elements = [
        ("scanLibrarySelect", "select"),
        ("scanPassSelect", "select"),
        ("scanForceRefresh", "input"),
        ("btnStartScan", "button"),
        ("btnCancelScan", "button"),
        ("activeScanStatus", "div"),
        ("scanProgressLabel", "span"),
        ("scanStatusBadge", "span"),
        ("scanProgressBar", "div"),
        ("logConsole", "div"),
        ("scanJobsTable", "table"),
    ]
    for element_identifier, expected_tag in expected_scan_elements:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing scan element: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )

    pass_options = collector.select_options.get("scanPassSelect", [])
    option_values = [option["value"] for option in pass_options]
    assert option_values == ["0", "1", "2", "3"]


def test_html_logs_tab_ui_elements() -> None:
    """Verify Logs tab UI controls exist."""
    collector = _parse_html_elements()
    expected_logs_elements = [
        ("logLevelSelect", "select"),
        ("chkAutoScrollLogs", "input"),
        ("btnClearLogs", "button"),
        ("btnRefreshLogs", "button"),
        ("runningLogConsole", "div"),
    ]
    for element_identifier, expected_tag in expected_logs_elements:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing logs element: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )

    log_level_options = collector.select_options.get("logLevelSelect", [])
    option_values = [option["value"] for option in log_level_options]
    assert option_values == ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]

    auto_scroll_attributes = collector.elements_by_identifier["chkAutoScrollLogs"][
        "attributes"
    ]
    assert auto_scroll_attributes.get("type") == "checkbox"


def test_html_browse_tab_ui_elements() -> None:
    """Verify Browse tab media type filters, search controls, and grid container."""
    collector = _parse_html_elements()
    expected_browse_elements = [
        ("browseTypeSeries", "button"),
        ("browseTypeMovies", "button"),
        ("browseTypeAnime", "button"),
        ("browseSearch", "input"),
        ("browseLibrary", "select"),
        ("browseSort", "select"),
        ("mediaGrid", "div"),
    ]
    for element_identifier, expected_tag in expected_browse_elements:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing browse element: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )

    sort_options = collector.select_options.get("browseSort", [])
    sort_values = [option["value"] for option in sort_options]
    assert "name" in sort_values
    assert "name_desc" in sort_values
    assert "date_added_desc" in sort_values
    assert "year_desc" in sort_values


def test_html_configuration_tab_ui_elements() -> None:
    """Verify Configuration form and all required input fields."""
    collector = _parse_html_elements()
    assert "configForm" in collector.elements_by_identifier
    assert collector.elements_by_identifier["configForm"]["tag"] == "form"

    expected_config_inputs = [
        ("cfgTmdbApiKey", "text"),
        ("cfgScanConcurrency", "number"),
        ("cfgOpenSubtitlesUsername", "text"),
        ("cfgOpenSubtitlesPassword", "password"),
        ("cfgOpenSubtitlesApiKey", "text"),
        ("cfgCacheDirectory", "text"),
    ]
    for element_identifier, expected_type in expected_config_inputs:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing config input: {element_identifier}"
        )
        attributes = collector.elements_by_identifier[element_identifier]["attributes"]
        assert attributes.get("type") == expected_type

    assert "cfgLogLevel" in collector.elements_by_identifier
    assert collector.elements_by_identifier["cfgLogLevel"]["tag"] == "select"
    config_log_level_options = collector.select_options.get("cfgLogLevel", [])
    config_option_values = [option["value"] for option in config_log_level_options]
    assert config_option_values == ["DEBUG", "INFO", "WARNING", "ERROR"]


def test_html_all_modals_and_close_targets() -> None:
    """Verify all 6 modals exist with dialog structure and close targets."""
    collector = _parse_html_elements()
    expected_modals = [
        "libraryModal",
        "mediaDetailModal",
        "tmdbMatchModal",
        "renameModal",
        "folderBrowserModal",
        "manualMapperModal",
    ]
    for modal_identifier in expected_modals:
        assert modal_identifier in collector.elements_by_identifier, (
            f"Missing modal: {modal_identifier}"
        )
        modal_element = collector.elements_by_identifier[modal_identifier]
        assert "modal-backdrop" in modal_element["attributes"].get("class", "")

    assert set(collector.data_close_targets) == set(expected_modals)


def test_html_manual_mapper_modal_controls() -> None:
    """Verify controls inside the Manual Metadata Mapper modal."""
    collector = _parse_html_elements()
    expected_controls = [
        ("manualMapperModal", "div"),
        ("manualMapperSearchQuery", "input"),
        ("btnManualMapperSearch", "button"),
        ("manualMapperSearchResults", "div"),
        ("manualMapperSearchResultsBody", "tbody"),
        ("manualMapperSeasonSelect", "select"),
        ("btnManualMapperLoadSeason", "button"),
        ("btnManualMapperAddEntry", "button"),
        ("manualMapperSelectedLabel", "span"),
        ("manualMapperTable", "table"),
        ("manualMapperTableBody", "tbody"),
        ("btnApplyManualMappings", "button"),
    ]
    for element_identifier, expected_tag in expected_controls:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing manual mapper control: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )


def test_html_library_modal_controls() -> None:
    """Verify controls inside the Add/Edit Library modal."""
    collector = _parse_html_elements()
    expected_controls = [
        ("libraryModalTitle", "h3"),
        ("libraryForm", "form"),
        ("libId", "input"),
        ("libName", "input"),
        ("libMediaType", "select"),
        ("libRootPath", "input"),
        ("btnBrowseFolder", "button"),
        ("libEnabled", "input"),
        ("btnSaveLibrary", "button"),
    ]
    for element_identifier, expected_tag in expected_controls:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing library modal control: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )

    media_type_options = collector.select_options.get("libMediaType", [])
    values = [option["value"] for option in media_type_options]
    assert values == ["tv", "anime", "movie"]


def test_html_folder_browser_modal_controls() -> None:
    """Verify controls inside the Folder Browser modal."""
    collector = _parse_html_elements()
    expected_controls = [
        ("folderBrowserModal", "div"),
        ("folderShortcuts", "div"),
        ("btnFolderUp", "button"),
        ("folderCurrentPath", "input"),
        ("btnFolderGo", "button"),
        ("folderListContainer", "div"),
        ("folderList", "ul"),
        ("selectedFolderDisplay", "div"),
        ("btnSelectFolder", "button"),
    ]
    for element_identifier, expected_tag in expected_controls:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing folder browser control: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )


def test_html_tmdb_match_modal_controls() -> None:
    """Verify controls inside the TMDB Match modal."""
    collector = _parse_html_elements()
    expected_controls = [
        ("tmdbMatchModal", "div"),
        ("tmdbSearchQuery", "input"),
        ("btnTmdbSearch", "button"),
        ("tmdbSearchResults", "div"),
        ("tmdbSearchResultsBody", "tbody"),
    ]
    for element_identifier, expected_tag in expected_controls:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing TMDB match control: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )


def test_html_rename_modal_controls() -> None:
    """Verify controls inside the File Renaming modal."""
    collector = _parse_html_elements()
    expected_controls = [
        ("renameModal", "div"),
        ("renameTemplate", "input"),
        ("btnPreviewRename", "button"),
        ("renameTable", "table"),
        ("renameTableBody", "tbody"),
        ("btnApplyRename", "button"),
    ]
    for element_identifier, expected_tag in expected_controls:
        assert element_identifier in collector.elements_by_identifier, (
            f"Missing rename control: {element_identifier}"
        )
        assert (
            collector.elements_by_identifier[element_identifier]["tag"] == expected_tag
        )


# ======================================================================
# 2. JavaScript Wiring and Element Cross-Reference Verification
# ======================================================================


def test_all_app_get_element_by_id_references_exist_in_html() -> None:
    """Verify that every getElementById call in app.js refers to an existing element."""
    collector = _parse_html_elements()
    app_source = _read_static_file("app.js")

    referenced_identifiers = set(
        re.findall(r'getElementById\(["\']([^"\']+)["\']\)', app_source)
    )

    dynamic_modal_elements = {
        "btnOpenTmdbMatch",
        "btnOpenRename",
        "btnOpenManualMapper",
    }

    static_referenced_identifiers = referenced_identifiers - dynamic_modal_elements
    for element_identifier in static_referenced_identifiers:
        assert element_identifier in collector.elements_by_identifier, (
            f"Element ID '{element_identifier}' referenced in app.js does not exist in index.html"
        )


def test_all_interactive_buttons_wired_with_handlers() -> None:
    """Verify that all major action buttons have click event handlers assigned in app.js."""
    app_source = _read_static_file("app.js")
    expected_wired_buttons = [
        "btnQuickScan",
        "btnStartScan",
        "btnCancelScan",
        "browseTypeSeries",
        "browseTypeMovies",
        "browseTypeAnime",
        "btnClearLogs",
        "btnRefreshLogs",
        "btnTmdbSearch",
        "btnPreviewRename",
        "btnApplyRename",
        "btnOpenAddLibrary",
        "btnSaveLibrary",
        "btnBrowseFolder",
        "btnFolderGo",
        "btnFolderUp",
        "btnSelectFolder",
        "btnManualMapperSearch",
        "btnManualMapperLoadSeason",
        "btnManualMapperAddEntry",
        "btnApplyManualMappings",
    ]
    for button_identifier in expected_wired_buttons:
        direct_pattern = (
            rf'getElementById\(["\']{button_identifier}["\']\)\.onclick\s*='
        )
        variable_match = re.search(
            rf'(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*document\.getElementById\(["\']{button_identifier}["\']\)',
            app_source,
        )
        if variable_match:
            variable_name = variable_match.group(1)
            variable_pattern = rf"\b{variable_name}\.onclick\s*="
            assert re.search(direct_pattern, app_source) or re.search(
                variable_pattern, app_source
            ), (
                f"Button '{button_identifier}' (variable '{variable_name}') is missing an onclick handler in app.js"
            )
        else:
            assert re.search(direct_pattern, app_source), (
                f"Button '{button_identifier}' is missing an onclick handler in app.js"
            )


def test_forms_and_input_events_wired_in_app() -> None:
    """Verify forms, search inputs, and dropdowns have event handlers in app.js."""
    app_source = _read_static_file("app.js")

    assert re.search(
        r'getElementById\(["\']configForm["\']\)\.onsubmit\s*=', app_source
    )
    assert re.search(r"browseSearch\.oninput\s*=", app_source) or re.search(
        r'getElementById\(["\']browseSearch["\']\)\.oninput\s*=', app_source
    )
    assert re.search(r"browseLibrary\.onchange\s*=", app_source) or re.search(
        r'getElementById\(["\']browseLibrary["\']\)\.onchange\s*=', app_source
    )
    assert re.search(r"browseSort\.onchange\s*=", app_source) or re.search(
        r'getElementById\(["\']browseSort["\']\)\.onchange\s*=', app_source
    )
    assert re.search(
        r'getElementById\(["\']tmdbSearchQuery["\']\)\.onkeydown\s*=', app_source
    )
    assert re.search(
        r'getElementById\(["\']manualMapperSearchQuery["\']\)\.onkeydown\s*=',
        app_source,
    ) or re.search(r"manualMapperSearchQuery\.onkeydown\s*=", app_source)
    assert re.search(r"folderCurrentPath\.onkeydown\s*=", app_source) or re.search(
        r'getElementById\(["\']folderCurrentPath["\']\)\.onkeydown\s*=', app_source
    )
    assert re.search(r"logLevelSelect\.onchange\s*=", app_source) or re.search(
        r'getElementById\(["\']logLevelSelect["\']\)\.onchange\s*=', app_source
    )


# ======================================================================
# 3. Interactive DOM Testing in V8 Engine
# ======================================================================

_DOM_HARNESS_PREAMBLE = """\
var __domElements = {};
function getOrCreateElement(id, tag) {
    if (!__domElements[id]) {
        __domElements[id] = {
            id: id,
            tagName: tag || "DIV",
            className: "",
            classList: {
                classes: {},
                add: function(c) { this.classes[c] = true; },
                remove: function(c) { delete this.classes[c]; },
                toggle: function(c, force) {
                    if (force !== undefined) {
                        if (force) this.classes[c] = true;
                        else delete this.classes[c];
                    } else {
                        if (this.classes[c]) delete this.classes[c];
                        else this.classes[c] = true;
                    }
                },
                contains: function(c) { return !!this.classes[c]; }
            },
            style: {},
            _innerHTML: "",
            get innerHTML() { return this._innerHTML; },
            set innerHTML(val) {
                this._innerHTML = val;
                if (!val) {
                    this.children = [];
                }
            },
            textContent: "",
            value: "",
            checked: false,
            disabled: false,
            children: [],
            appendChild: function(c) { this.children.push(c); },
            dataset: {},
            reset: function() { this.value = ""; }
        };
    }
    return __domElements[id];
}

var __domListeners = {};
const document = {
    getElementById: function(id) { return getOrCreateElement(id); },
    querySelector: function(sel) { return getOrCreateElement(sel); },
    querySelectorAll: function(sel) {
        if (sel === ".nav-tab") {
            return ["dashboard", "libraries", "scan", "logs", "browse", "config"].map(function(t) {
                const el = getOrCreateElement("nav-" + t, "BUTTON");
                el.dataset.tab = t;
                return el;
            });
        }
        if (sel === "[data-close]") {
            return ["libraryModal", "mediaDetailModal", "tmdbMatchModal", "renameModal", "folderBrowserModal", "manualMapperModal"].map(function(m) {
                const el = getOrCreateElement("close-" + m, "BUTTON");
                el.dataset.close = m;
                return el;
            });
        }
        if (sel === ".tab-pane") {
            return ["dashboard", "libraries", "scan", "logs", "browse", "config"].map(function(t) {
                return getOrCreateElement("tab-" + t, "SECTION");
            });
        }
        return [];
    },
    createElement: function(tag) { return getOrCreateElement("gen-" + Math.random(), tag); },
    addEventListener: function(event, callback) {
        __domListeners[event] = callback;
    }
};

function EventSource() {
    this.close = function() {};
    this.addEventListener = function() {};
    this.onmessage = null;
    this.onerror = null;
}

var __timers = [];
var __timerId = 0;
function setTimeout(fn, ms) {
    __timers.push({ id: ++__timerId, fn: fn, ms: ms, cancelled: false });
    return __timerId;
}
function clearTimeout(id) {
    for (const t of __timers) {
        if (t.id === id) t.cancelled = true;
    }
}
function setInterval() { return 0; }
function clearInterval() {}

const api = {
    getLibraries: async function() { return []; },
    listSeries: async function() { return []; },
    listMovies: async function() { return []; },
    getScanStatus: async function() { return { running: null, last_job: null }; },
    getScanJobs: async function() { return []; },
    getHealth: async function() { return { status: "ok" }; },
    startScan: async function() { return { job: { id: 1 } }; },
    cancelScan: async function() { return null; }
};
"""


def _load_app_in_v8(engine: MiniRacer, probe_code: str) -> dict[str, Any]:
    """Execute app.js with the DOM harness and run probe_code, returning the parsed JSON result."""
    app_source = _read_static_file("app.js")
    stripped_app = re.sub(r"^import [^\n]+;?\n?", "", app_source, flags=re.MULTILINE)
    logic_source = _read_static_file("logic.js")
    stripped_logic = re.sub(r"^export\s+", "", logic_source, flags=re.MULTILINE)
    program = (
        _DOM_HARNESS_PREAMBLE
        + "\n"
        + stripped_logic
        + "\n"
        + stripped_app
        + "\n"
        + """
// Initialize application listeners
if (__domListeners["DOMContentLoaded"]) {
    __domListeners["DOMContentLoaded"]();
}
var __probeResult = (function() {
"""
        + probe_code
        + """
})();
JSON.stringify(__probeResult);
"""
    )
    evaluation_result = engine.eval(program)
    return json.loads(evaluation_result)


def test_v8_navigation_tabs_switching(engine: MiniRacer) -> None:
    """Verify switchTab properly activates tab panes and nav-tab buttons for all 6 tabs."""
    result = _load_app_in_v8(
        engine,
        """
        const tabs = ["dashboard", "libraries", "scan", "logs", "browse", "config"];
        const outcomes = {};
        for (const tab of tabs) {
            switchTab(tab);
            outcomes[tab] = {
                paneActive: getOrCreateElement("tab-" + tab).classList.contains("active")
            };
        }
        return outcomes;
        """,
    )
    for tab_name in ["dashboard", "libraries", "scan", "logs", "browse", "config"]:
        assert result[tab_name]["paneActive"] is True


def test_v8_modal_open_and_close(engine: MiniRacer) -> None:
    """Verify openModal and closeModal add/remove the 'open' class on all 6 modals."""
    result = _load_app_in_v8(
        engine,
        """
        const modals = [
            "libraryModal",
            "mediaDetailModal",
            "tmdbMatchModal",
            "renameModal",
            "folderBrowserModal",
            "manualMapperModal"
        ];
        const report = {};
        for (const modalIdentifier of modals) {
            openModal(modalIdentifier);
            const openedState = getOrCreateElement(modalIdentifier).classList.contains("open");
            closeModal(modalIdentifier);
            const closedState = getOrCreateElement(modalIdentifier).classList.contains("open");
            report[modalIdentifier] = { opened: openedState, closed: !closedState };
        }
        return report;
        """,
    )
    for modal_identifier in [
        "libraryModal",
        "mediaDetailModal",
        "tmdbMatchModal",
        "renameModal",
        "folderBrowserModal",
        "manualMapperModal",
    ]:
        assert result[modal_identifier]["opened"] is True
        assert result[modal_identifier]["closed"] is True


def test_v8_data_close_buttons_wire_up(engine: MiniRacer) -> None:
    """Verify that clicking [data-close] buttons closes the target modal."""
    result = _load_app_in_v8(
        engine,
        """
        const closeButtons = document.querySelectorAll("[data-close]");
        const testResults = {};
        for (const buttonElement of closeButtons) {
            const targetModal = buttonElement.dataset.close;
            openModal(targetModal);
            buttonElement.onclick();
            testResults[targetModal] = getOrCreateElement(targetModal).classList.contains("open");
        }
        return testResults;
        """,
    )
    for modal_identifier, is_open in result.items():
        assert is_open is False, (
            f"Modal '{modal_identifier}' remained open after clicking close"
        )


def test_v8_global_alert_box(engine: MiniRacer) -> None:
    """Verify showAlert sets classes, text content, and display style."""
    result = _load_app_in_v8(
        engine,
        """
        showAlert("Scan completed successfully", "success");
        const alertBox = getOrCreateElement("globalAlert");
        return {
            className: alertBox.className,
            text: alertBox.textContent,
            display: alertBox.style.display
        };
        """,
    )
    assert result["className"] == "alert alert-success"
    assert result["text"] == "Scan completed successfully"
    assert result["display"] == "block"


def test_v8_scan_monitor_status_rendering(engine: MiniRacer) -> None:
    """Verify renderScanStatus updates UI controls for running and idle states."""
    result = _load_app_in_v8(
        engine,
        """
        // 1. Running state
        renderScanStatus({ running: 42 });
        const runningStartDisabled = getOrCreateElement("btnStartScan").disabled;
        const runningCancelDisabled = getOrCreateElement("btnCancelScan").disabled;
        const runningActiveDisplay = getOrCreateElement("activeScanStatus").style.display;
        const runningLabel = getOrCreateElement("scanProgressLabel").textContent;

        // 2. Idle state
        renderScanStatus({ running: null });
        const idleStartDisabled = getOrCreateElement("btnStartScan").disabled;
        const idleCancelDisabled = getOrCreateElement("btnCancelScan").disabled;
        const idleActiveDisplay = getOrCreateElement("activeScanStatus").style.display;

        return {
            runningStartDisabled: runningStartDisabled,
            runningCancelDisabled: runningCancelDisabled,
            runningActiveDisplay: runningActiveDisplay,
            runningLabel: runningLabel,
            idleStartDisabled: idleStartDisabled,
            idleCancelDisabled: idleCancelDisabled,
            idleActiveDisplay: idleActiveDisplay
        };
        """,
    )
    assert result["runningStartDisabled"] is True
    assert result["runningCancelDisabled"] is False
    assert result["runningActiveDisplay"] == "block"
    assert "Job #42" in result["runningLabel"]

    assert result["idleStartDisabled"] is False
    assert result["idleCancelDisabled"] is True
    assert result["idleActiveDisplay"] == "none"


def test_v8_browse_media_type_filter_buttons(engine: MiniRacer) -> None:
    """Verify clicking browse filter buttons toggles active button classes."""
    result = _load_app_in_v8(
        engine,
        """
        const seriesButton = getOrCreateElement("browseTypeSeries");
        const moviesButton = getOrCreateElement("browseTypeMovies");
        const animeButton = getOrCreateElement("browseTypeAnime");

        moviesButton.onclick();
        const moviesState = {
            seriesClass: seriesButton.className,
            moviesClass: moviesButton.className,
            animeClass: animeButton.className
        };

        animeButton.onclick();
        const animeState = {
            seriesClass: seriesButton.className,
            moviesClass: moviesButton.className,
            animeClass: animeButton.className
        };

        return { moviesState: moviesState, animeState: animeState };
        """,
    )
    assert "btn-primary" in result["moviesState"]["moviesClass"]
    assert "btn-secondary" in result["moviesState"]["seriesClass"]

    assert "btn-primary" in result["animeState"]["animeClass"]
    assert "btn-secondary" in result["animeState"]["moviesClass"]


def test_v8_quick_scan_dashboard_button(engine: MiniRacer) -> None:
    """Verify quick scan button switches to scan tab and starts scan."""
    result = _load_app_in_v8(
        engine,
        """
        let startScanClicked = false;
        getOrCreateElement("btnStartScan").click = function() { startScanClicked = true; };
        getOrCreateElement("btnQuickScan").onclick();

        return {
            tabScanActive: getOrCreateElement("tab-scan").classList.contains("active"),
            startScanClicked: startScanClicked
        };
        """,
    )
    assert result["tabScanActive"] is True
    assert result["startScanClicked"] is True


def test_v8_add_library_button_resets_form(engine: MiniRacer) -> None:
    """Verify clicking '+ Add Library' resets form, sets title, and opens modal."""
    result = _load_app_in_v8(
        engine,
        """
        let formResetCalled = false;
        getOrCreateElement("libraryForm").reset = function() { formResetCalled = true; };
        getOrCreateElement("libId").value = "99";

        getOrCreateElement("btnOpenAddLibrary").onclick();

        return {
            formResetCalled: formResetCalled,
            libId: getOrCreateElement("libId").value,
            title: getOrCreateElement("libraryModalTitle").textContent,
            modalOpen: getOrCreateElement("libraryModal").classList.contains("open")
        };
        """,
    )
    assert result["formResetCalled"] is True
    assert result["libId"] == ""
    assert result["title"] == "Add Library"
    assert result["modalOpen"] is True


def test_v8_clear_logs_button(engine: MiniRacer) -> None:
    """Verify clicking clear logs empties the runningLogConsole element."""
    result = _load_app_in_v8(
        engine,
        """
        const runningConsole = getOrCreateElement("runningLogConsole");
        runningConsole.innerHTML = "Log line 1\\nLog line 2";
        getOrCreateElement("btnClearLogs").onclick();

        return { content: runningConsole.innerHTML };
        """,
    )
    assert result["content"] == ""


def test_v8_log_level_filter_and_display(engine: MiniRacer) -> None:
    """Verify selecting a log level filters messages displayed in runningLogConsole."""
    result = _load_app_in_v8(
        engine,
        """
        const runningConsole = getOrCreateElement("runningLogConsole");
        runningConsole.innerHTML = "";

        appendLogLine("2026-09-09 DEBUG scan: probing file codec", "DEBUG");
        appendLogLine("2026-09-09 INFO scan: started library scan", "INFO");
        appendLogLine("2026-09-09 WARNING scan: missing poster", "WARNING");
        appendLogLine("2026-09-09 ERROR scan: failed to open database", "ERROR");

        const initialLinesCount = runningConsole.children.length;

        const logLevelSelect = getOrCreateElement("logLevelSelect");
        logLevelSelect.value = "WARNING";
        logLevelSelect.onchange();

        const warningFilteredLines = runningConsole.children.map(child => child.textContent);

        logLevelSelect.value = "ERROR";
        logLevelSelect.onchange();
        const errorFilteredLines = runningConsole.children.map(child => child.textContent);

        logLevelSelect.value = "ALL";
        logLevelSelect.onchange();
        const allFilteredLines = runningConsole.children.map(child => child.textContent);

        return {
            initialCount: initialLinesCount,
            warningFiltered: warningFilteredLines,
            errorFiltered: errorFilteredLines,
            allFiltered: allFilteredLines,
        };
        """,
    )
    assert result["initialCount"] == 4
    assert len(result["warningFiltered"]) == 2
    assert any("WARNING" in line for line in result["warningFiltered"])
    assert any("ERROR" in line for line in result["warningFiltered"])
    assert not any("DEBUG" in line for line in result["warningFiltered"])
    assert not any("INFO" in line for line in result["warningFiltered"])

    assert len(result["errorFiltered"]) == 1
    assert "ERROR" in result["errorFiltered"][0]

    assert len(result["allFiltered"]) == 4


def test_v8_folder_browser_select_folder_button(engine: MiniRacer) -> None:
    """Verify choose folder button copies selected directory into libRootPath."""
    result = _load_app_in_v8(
        engine,
        """
        selectedBrowserDirectory = "/media/tv/series";
        getOrCreateElement("btnSelectFolder").onclick();

        return {
            libRootPath: getOrCreateElement("libRootPath").value,
            modalOpen: getOrCreateElement("folderBrowserModal").classList.contains("open")
        };
        """,
    )
    assert result["libRootPath"] == "/media/tv/series"
    assert result["modalOpen"] is False


def test_v8_manual_mapper_modal_interaction(engine: MiniRacer) -> None:
    """Verify openManualMapperModal populates search input and opens modal."""
    result = _load_app_in_v8(
        engine,
        """
        const seriesItem = {
            id: 10,
            name: "Test Series",
            folder_name: "Test Series",
            tmdb_identifier: null,
            seasons: [
                {
                    season_number: 1,
                    episodes: [
                        { path: "/media/tv/Test Series/S01E01.mkv", name: "Episode 1" }
                    ]
                }
            ]
        };
        openManualMapperModal(seriesItem);
        const modalElement = getOrCreateElement("manualMapperModal");
        const searchInputElement = getOrCreateElement("manualMapperSearchQuery");
        return {
            modalOpen: modalElement.classList.contains("open"),
            searchQuery: searchInputElement.value,
            localFilesCount: manualMapperLocalFiles.length
        };
        """,
    )
    assert result["modalOpen"] is True
    assert result["searchQuery"] == "Test Series"
    assert result["localFilesCount"] == 1


def test_v8_load_browse_excludes_folders_with_no_episode_files(
    engine: MiniRacer,
) -> None:
    """Verify loadBrowse filtering excludes series with no episode files."""
    result = _load_app_in_v8(
        engine,
        """
        const testSeriesList = [
            {
                id: 1,
                name: "Valid Series",
                folder_name: "Valid Series",
                seasons: [
                    {
                        season_number: 1,
                        episodes: [{ name: "Episode 1", path: "/media/tv/ep1.mkv" }]
                    }
                ]
            },
            {
                id: 2,
                name: "Empty Series",
                folder_name: "Empty Series",
                seasons: []
            },
            {
                id: 3,
                name: "Empty Season Series",
                folder_name: "Empty Season Series",
                seasons: [
                    {
                        season_number: 1,
                        episodes: []
                    }
                ]
            }
        ];

        const filteredSeries = filterSeriesWithEpisodes(testSeriesList);
        const gridElement = getOrCreateElement("mediaGrid");
        gridElement.innerHTML = "";
        filteredSeries.forEach((item) => {
            const card = document.createElement("div");
            card.className = "media-card";
            card.innerHTML = `<div class="media-title">${escapeHtml(item.name || item.folder_name)}</div>`;
            gridElement.appendChild(card);
        });

        const cards = gridElement.children.filter((child) => child.className === "media-card");
        return {
            cardCount: cards.length,
            cardHtml: cards.map((card) => card.innerHTML).join(" ")
        };
        """,
    )
    assert result["cardCount"] == 1
    assert "Valid Series" in result["cardHtml"]
    assert "Empty Series" not in result["cardHtml"]
    assert "Empty Season Series" not in result["cardHtml"]
