import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QDialog,
    QLineEdit,
    QMessageBox,
    QFileDialog,
    QFrame,
    QSizePolicy,
    QFormLayout,
    QMenu,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QScrollArea,
    QGroupBox,
    QSpinBox,
)
from PySide6.QtCore import (
    Qt,
    Signal,
    Slot,
    QObject,
    QSize,
    QFileSystemWatcher,
    QTimer,
    QPoint,
)

from PySide6.QtGui import (
    QPixmap,
    QIcon,
    QFont,
    QColor,
    QAction,
    QCloseEvent,
    QTextCursor,
    QPainter,
    QPen,
)

from .config import config
from . import db
from .jellyfin import jellyfin_client
from .tmdb import tmdb_client
from .backend import (
    ScanWorker,
    CleanupWorker,
    JellyfinPullWorker,
    JellyfinPushWorker,
    ScanAllLibrariesWorker,
    CleanupAllLibrariesWorker,
    RuntimeExtractionWorker,
)

logger = logging.getLogger(__name__)


def get_application_stylesheet() -> str:
    """Returns a premium, rich dark mode stylesheet implementing modern aesthetic standards."""
    return """
    QWidget {
        background-color: #191919;
        color: #FFFFFF;
        font-family: 'Inter', 'Roboto', sans-serif;
        font-size: 14px;
    }
    QPushButton {
        background-color: #2a2a2a;
        border: 1px solid #444444;
        border-radius: 6px;
        padding: 6px 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #3a3a3a;
        border-color: #2a82da;
        color: #2a82da;
    }
    QPushButton:pressed {
        background-color: #202020;
    }
    QPushButton:disabled {
        background-color: #151515;
        color: #666666;
        border-color: #222222;
    }
    QPushButton#accentButton {
        background-color: #2a82da;
        color: #ffffff;
        border: none;
    }
    QPushButton#accentButton:hover {
        background-color: #3592ea;
    }
    QLineEdit, QComboBox {
        background-color: #222222;
        border: 1px solid #444444;
        border-radius: 6px;
        padding: 5px 10px;
        color: #ffffff;
    }
    QLineEdit:focus, QComboBox:focus {
        border-color: #2a82da;
    }
    QListWidget, QTableWidget {
        background-color: #1e1e1e;
        border: 1px solid #333333;
        border-radius: 8px;
    }
    QListWidget::item:hover, QTableWidget::item:hover {
        background-color: #282828;
        border-radius: 4px;
    }
    QListWidget::item:selected, QTableWidget::item:selected {
        background-color: #2a82da;
        color: #ffffff;
        border-radius: 4px;
    }
    QHeaderView::section {
        background-color: #222222;
        color: #aaaaaa;
        padding: 5px;
        border: none;
        border-bottom: 1px solid #444444;
        font-weight: bold;
    }
    QTabWidget::pane {
        border: 1px solid #333333;
        border-radius: 6px;
        background-color: #1e1e1e;
    }
    QTabBar::tab {
        background-color: #222222;
        color: #888888;
        padding: 8px 16px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #1e1e1e;
        color: #ffffff;
        border-bottom: 2px solid #2a82da;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background-color: #2a2a2a;
        color: #ffffff;
    }
    QScrollBar:vertical {
        border: none;
        background-color: #191919;
        width: 10px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background-color: #444444;
        border-radius: 5px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #555555;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    """


# ---------------------------------------------------------------------------
# Custom progress widgets for the Library Management tab
# ---------------------------------------------------------------------------


class SegmentedProgressBar(QWidget):
    """
    A custom progress bar divided into labelled library segments.
    Within each library segment, root-directory sub-segments are drawn as
    darker shaded inner regions.  Progress is filled from left to right within
    each segment independently.
    """

    # State constants for each segment
    STATE_PENDING = 0
    STATE_ACTIVE = 1
    STATE_DONE = 2

    # Colours
    _COLOR_BG = QColor("#1e1e1e")
    _COLOR_BORDER = QColor("#444444")
    _COLOR_LABEL = QColor("#ffffff")
    _COLOR_PENDING_FILL = QColor("#2a2a2a")
    _COLOR_ACTIVE_LIB = QColor("#1565c0")
    _COLOR_DONE_LIB = QColor("#1b5e20")
    _COLOR_ROOT_DIVIDER = QColor("#555555")
    _COLOR_ACTIVE_ROOT = QColor("#1976d2")
    _COLOR_DONE_ROOT = QColor("#2e7d32")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Ordered list of library names
        self._library_order: List[str] = []
        # {library_name: {"roots": [root_dir, ...], "root_totals": {root: int},
        #                  "root_done": {root: int}, "state": STATE_*}}
        self._libraries: Dict[str, Any] = {}
        # {root_dir: state}
        self._root_states: Dict[str, int] = {}

    def init_from_tree(self, tree: Dict[str, Any]) -> None:
        """Called once with the pre-discovery tree structure."""
        self._library_order = list(tree.keys())
        self._libraries = {}
        self._root_states = {}
        for lib_name, lib_data in tree.items():
            roots = list(lib_data.get("roots", {}).keys())
            self._libraries[lib_name] = {
                "roots": roots,
                "root_totals": {r: len(lib_data["roots"][r]) for r in roots},
                "root_done": {r: 0 for r in roots},
                "state": self.STATE_PENDING,
            }
            for r in roots:
                self._root_states[r] = self.STATE_PENDING
        self.update()

    def mark_library_active(self, library_name: str) -> None:
        if library_name in self._libraries:
            self._libraries[library_name]["state"] = self.STATE_ACTIVE
            for r in self._libraries[library_name]["roots"]:
                self._root_states[r] = self.STATE_PENDING
            self.update()

    def mark_library_done(self, library_name: str) -> None:
        if library_name in self._libraries:
            self._libraries[library_name]["state"] = self.STATE_DONE
            for r in self._libraries[library_name]["roots"]:
                self._root_states[r] = self.STATE_DONE
            self.update()

    def advance_root(self, root_dir: str) -> None:
        """Increment the done counter for a root directory."""
        for lib_name, lib_data in self._libraries.items():
            if root_dir in lib_data["root_done"]:
                lib_data["root_done"][root_dir] = min(
                    lib_data["root_done"][root_dir] + 1,
                    lib_data["root_totals"].get(root_dir, 1),
                )
                lib_data["state"] = self.STATE_ACTIVE
                self._root_states[root_dir] = self.STATE_ACTIVE
                self.update()
                return

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        padding = 2
        label_height = 16
        bar_top = label_height + padding
        bar_height = h - bar_top - padding

        num_libs = len(self._library_order)
        if num_libs == 0:
            painter.fillRect(0, bar_top, w, bar_height, self._COLOR_BG)
            painter.end()
            return

        lib_width = w / num_libs

        for idx, lib_name in enumerate(self._library_order):
            lib_data = self._libraries.get(lib_name, {})
            state = lib_data.get("state", self.STATE_PENDING)
            lx = int(idx * lib_width)
            lw = int(lib_width) - 1

            # Background
            if state == self.STATE_DONE:
                bg = self._COLOR_DONE_LIB
            elif state == self.STATE_ACTIVE:
                bg = self._COLOR_ACTIVE_LIB
            else:
                bg = self._COLOR_PENDING_FILL
            painter.fillRect(lx, bar_top, lw, bar_height, bg)

            # Draw root-directory sub-segments
            roots = lib_data.get("roots", [])
            num_roots = len(roots)
            if num_roots > 1:
                root_w = lw / num_roots
                for ridx, root_dir in enumerate(roots):
                    rx = lx + int(ridx * root_w)
                    rw = int(root_w) - 1
                    root_state = self._root_states.get(root_dir, self.STATE_PENDING)
                    root_total = lib_data.get("root_totals", {}).get(root_dir, 1) or 1
                    root_done = lib_data.get("root_done", {}).get(root_dir, 0)

                    if root_state == self.STATE_DONE or state == self.STATE_DONE:
                        painter.fillRect(
                            rx, bar_top, rw, bar_height, self._COLOR_DONE_ROOT
                        )
                    elif state == self.STATE_ACTIVE:
                        fill_fraction = root_done / root_total
                        fill_w = int(rw * fill_fraction)
                        painter.fillRect(
                            rx, bar_top, fill_w, bar_height, self._COLOR_ACTIVE_ROOT
                        )

                    # Root divider line
                    if ridx > 0:
                        painter.setPen(QPen(self._COLOR_ROOT_DIVIDER, 1))
                        painter.drawLine(rx, bar_top, rx, bar_top + bar_height)

            # Library border
            painter.setPen(QPen(self._COLOR_BORDER, 1))
            painter.drawRect(lx, bar_top, lw, bar_height)

            # Library label (above the bar)
            painter.setPen(QPen(self._COLOR_LABEL, 1))
            font = painter.font()
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                lx + 4, 0, lw - 4, label_height, Qt.AlignmentFlag.AlignVCenter, lib_name
            )

            # Library separator
            if idx > 0:
                painter.setPen(QPen(self._COLOR_BORDER, 2))
                painter.drawLine(lx, bar_top, lx, bar_top + bar_height)

        painter.end()


class ScanProgressTree(QWidget):
    """
    Scrollable, collapsible tree showing the real-time scan progress.

    Hierarchy:
      Library  →  Root directory  →  Series/Movie folder
        (TV only)  →  Season  →  Episode file

    Movie libraries do NOT show individual file nodes.
    Each node carries a status icon: ⏳ pending · ⚙ processing · ✓ done · ⊘ skipped.
    """

    _ICON_PENDING = "⏳"
    _ICON_PROCESSING = "⚙"
    _ICON_DONE = "✓"
    _ICON_SKIPPED = "⊘"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Control bar
        ctrl_bar = QHBoxLayout()
        expand_btn = QPushButton("Expand All")
        collapse_btn = QPushButton("Collapse All")
        expand_btn.setFixedHeight(24)
        collapse_btn.setFixedHeight(24)
        expand_btn.clicked.connect(self._on_expand_all)
        collapse_btn.clicked.connect(self._on_collapse_all)
        ctrl_bar.addWidget(expand_btn)
        ctrl_bar.addWidget(collapse_btn)
        ctrl_bar.addStretch()
        layout.addLayout(ctrl_bar)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setAnimated(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setMinimumHeight(200)
        self._tree.setStyleSheet(
            "QTreeWidget { background-color: #161616; border: 1px solid #333; }"
            "QTreeWidget::item { padding: 2px 4px; }"
        )
        layout.addWidget(self._tree)

        # Lookup maps
        self._lib_nodes: Dict[str, QTreeWidgetItem] = {}
        self._lib_types: Dict[str, str] = {}  # library → "tv" | "movie"
        self._folder_nodes: Dict[
            str, QTreeWidgetItem
        ] = {}  # key = "library|root|folder"
        self._season_nodes: Dict[
            str, QTreeWidgetItem
        ] = {}  # key = "library|folder|season"
        self._file_nodes: Dict[str, QTreeWidgetItem] = {}  # key = file path

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _folder_key(self, library: str, root: str, folder: str) -> str:
        return f"{library}|{root}|{folder}"

    def _season_key(self, library: str, folder: str, season: str) -> str:
        return f"{library}|{folder}|{season}"

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_from_tree(self, tree: Dict[str, Any]) -> None:
        """Builds the initial tree with all folder, season, and file nodes in pending state."""
        self._tree.clear()
        self._lib_nodes.clear()
        self._lib_types.clear()
        self._folder_nodes.clear()
        self._season_nodes.clear()
        self._file_nodes.clear()

        for lib_name, lib_data in tree.items():
            lib_type: str = lib_data.get("type", "tv")
            self._lib_types[lib_name] = lib_type

            lib_item = QTreeWidgetItem(
                self._tree, [f"{self._ICON_PENDING}  {lib_name}"]
            )
            lib_item.setForeground(0, QColor("#aaaaaa"))
            lib_font = QFont("Inter", 11, QFont.Weight.Bold)
            lib_item.setFont(0, lib_font)
            self._lib_nodes[lib_name] = lib_item

            for root_dir, folders_dict in lib_data.get("roots", {}).items():
                root_label = root_dir
                root_item = QTreeWidgetItem(
                    lib_item, [f"{self._ICON_PENDING}  {root_label}"]
                )
                root_item.setForeground(0, QColor("#888888"))
                root_item.setData(0, Qt.ItemDataRole.UserRole, root_dir)

                for folder_name, folder_info in folders_dict.items():
                    folder_item = QTreeWidgetItem(
                        root_item, [f"{self._ICON_PENDING}  {folder_name}"]
                    )
                    folder_item.setForeground(0, QColor("#888888"))
                    key = self._folder_key(lib_name, root_dir, folder_name)
                    self._folder_nodes[key] = folder_item

                    # For TV libraries, populate seasons and episodes upfront
                    if lib_type == "tv":
                        seasons_dict = folder_info.get("seasons", {})
                        for season_name, episodes_list in seasons_dict.items():
                            s_key = self._season_key(lib_name, folder_name, season_name)
                            season_item = QTreeWidgetItem(
                                folder_item, [f"{self._ICON_PENDING}  {season_name}"]
                            )
                            season_item.setForeground(0, QColor("#888888"))
                            self._season_nodes[s_key] = season_item

                            for ep_name in episodes_list:
                                ep_path = str(
                                    Path(root_dir) / folder_name / season_name / ep_name
                                )
                                ep_item = QTreeWidgetItem(
                                    season_item, [f"{self._ICON_PENDING}  {ep_name}"]
                                )
                                ep_item.setForeground(0, QColor("#888888"))
                                self._file_nodes[ep_path] = ep_item

        # Expand libraries, roots, and series folders, but leave seasons collapsed
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is not None:
                item.setExpanded(True)
                for j in range(item.childCount()):
                    root_item = item.child(j)
                    if root_item is not None:
                        root_item.setExpanded(True)
                        for k in range(root_item.childCount()):
                            folder_item = root_item.child(k)
                            if folder_item is not None:
                                folder_item.setExpanded(True)
                                for m in range(folder_item.childCount()):
                                    season_item = folder_item.child(m)
                                    if season_item is not None:
                                        season_item.setExpanded(False)

    # ------------------------------------------------------------------
    # Library-level state
    # ------------------------------------------------------------------

    def mark_library_active(self, library_name: str) -> None:
        node = self._lib_nodes.get(library_name)
        if node:
            node.setText(0, f"{self._ICON_PROCESSING}  {library_name}")
            node.setForeground(0, QColor("#2196f3"))

    def mark_library_done(self, library_name: str) -> None:
        node = self._lib_nodes.get(library_name)
        if node:
            node.setText(0, f"{self._ICON_DONE}  {library_name}")
            node.setForeground(0, QColor("#4caf50"))

    # ------------------------------------------------------------------
    # Folder-level state (series / movie folder)
    # ------------------------------------------------------------------

    def _find_folder_node(self, library: str, folder: str) -> Optional[QTreeWidgetItem]:
        """Return the folder node for the first matching root key."""
        for key, node in self._folder_nodes.items():
            if key.startswith(f"{library}|") and key.endswith(f"|{folder}"):
                return node
        return None

    def mark_folder_active(self, library: str, root: str, folder: str) -> None:
        key = self._folder_key(library, root, folder)
        node = self._folder_nodes.get(key)
        if node:
            node.setText(0, f"{self._ICON_PROCESSING}  {folder}")
            node.setForeground(0, QColor("#2196f3"))
            self._tree.scrollToItem(node)

    def mark_folder_done(
        self, library: str, root: str, folder: str, skipped: bool = False
    ) -> None:
        key = self._folder_key(library, root, folder)
        node = self._folder_nodes.get(key)
        if node:
            if skipped:
                node.setText(0, f"{self._ICON_SKIPPED}  {folder}")
                node.setForeground(0, QColor("#888888"))
            else:
                node.setText(0, f"{self._ICON_DONE}  {folder}")
                node.setForeground(0, QColor("#4caf50"))

    # ------------------------------------------------------------------
    # Season-level state (TV only — nodes created dynamically)
    # ------------------------------------------------------------------

    def mark_season_active(self, library: str, folder: str, season: str) -> None:
        """Create the season node under its parent series folder if not yet present."""
        key = self._season_key(library, folder, season)
        if key in self._season_nodes:
            node = self._season_nodes[key]
            node.setText(0, f"{self._ICON_PROCESSING}  {season}")
            node.setForeground(0, QColor("#2196f3"))
            self._tree.scrollToItem(node)
            return

        # Create node under the series folder
        parent_node = self._find_folder_node(library, folder)
        if parent_node is None:
            return
        season_item = QTreeWidgetItem(
            parent_node, [f"{self._ICON_PROCESSING}  {season}"]
        )
        season_item.setForeground(0, QColor("#2196f3"))
        self._season_nodes[key] = season_item
        parent_node.setExpanded(True)
        self._tree.scrollToItem(season_item)

    def mark_season_done(self, library: str, folder: str, season: str) -> None:
        key = self._season_key(library, folder, season)
        node = self._season_nodes.get(key)
        if node:
            node.setText(0, f"{self._ICON_DONE}  {season}")
            node.setForeground(0, QColor("#4caf50"))

    # ------------------------------------------------------------------
    # File-level state (episodes under seasons for TV; skipped for movies)
    # ------------------------------------------------------------------

    def mark_file_active(
        self, file_path: str, library: str, folder: str, season: str = ""
    ) -> None:
        """Add an episode file node.  For movie libraries this is a no-op."""
        lib_type = self._lib_types.get(library, "tv")
        if lib_type == "movie":
            return  # movie libraries don't show individual files

        file_name = Path(file_path).name

        if file_path in self._file_nodes:
            file_item = self._file_nodes[file_path]
            file_item.setText(0, f"{self._ICON_PROCESSING}  {file_name}")
            file_item.setForeground(0, QColor("#2196f3"))
            self._tree.scrollToItem(file_item)
            return

        # Prefer the season node as parent; fall back to folder node
        parent_node: Optional[QTreeWidgetItem] = None
        if season:
            season_key = self._season_key(library, folder, season)
            parent_node = self._season_nodes.get(season_key)
        if parent_node is None:
            parent_node = self._find_folder_node(library, folder)
        if parent_node is None:
            return

        file_item = QTreeWidgetItem(
            parent_node, [f"{self._ICON_PROCESSING}  {file_name}"]
        )
        file_item.setForeground(0, QColor("#2196f3"))
        self._file_nodes[file_path] = file_item
        parent_node.setExpanded(True)
        self._tree.scrollToItem(file_item)

    def mark_file_done(self, file_path: str) -> None:
        node = self._file_nodes.get(file_path)
        if node:
            file_name = Path(file_path).name
            node.setText(0, f"{self._ICON_DONE}  {file_name}")
            node.setForeground(0, QColor("#4caf50"))

    # ------------------------------------------------------------------
    # Reset / expand / collapse
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._tree.clear()
        self._lib_nodes.clear()
        self._lib_types.clear()
        self._folder_nodes.clear()
        self._season_nodes.clear()
        self._file_nodes.clear()

    @Slot()
    def _on_expand_all(self) -> None:
        self._tree.expandAll()

    @Slot()
    def _on_collapse_all(self) -> None:
        self._tree.collapseAll()


class LibraryScanProgressBar(QWidget):
    """
    A custom progress bar divided into labelled root directory segments.
    Within each root directory segment, series/movie folders are drawn as sub-segments.
    Progress is filled independently as series/movies are processed.
    """

    STATE_PENDING = 0
    STATE_ACTIVE = 1
    STATE_DONE = 2

    # Colours (harmonious dark theme colors)
    _COLOR_BG = QColor("#1f2937")
    _COLOR_BORDER = QColor("#374151")
    _COLOR_LABEL = QColor("#f3f4f6")
    _COLOR_PENDING_FILL = QColor("#111827")
    _COLOR_ACTIVE_ROOT = QColor("#1e3a8a")
    _COLOR_DONE_ROOT = QColor("#064e3b")
    _COLOR_ROOT_DIVIDER = QColor("#374151")
    _COLOR_ACTIVE_FOLDER = QColor("#3b82f6")
    _COLOR_DONE_FOLDER = QColor("#10b981")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(16)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._roots_order: List[str] = []
        self._roots: Dict[str, Any] = {}

    def init_from_roots(
        self, roots: Dict[str, List[str]], roots_order: List[str]
    ) -> None:
        """Called with the initial discovery {root_dir: [folder1, folder2, ...]}."""
        self._roots_order = [r for r in roots_order if r in roots]
        self._roots = {}
        for root_dir in self._roots_order:
            folders = roots[root_dir]
            self._roots[root_dir] = {
                "folders": folders,
                "folder_states": {f: self.STATE_PENDING for f in folders},
                "state": self.STATE_PENDING,
            }
        self.update()

    def mark_folder_active(self, root_dir: str, folder_name: str) -> None:
        if root_dir in self._roots:
            self._roots[root_dir]["state"] = self.STATE_ACTIVE
            if folder_name in self._roots[root_dir]["folder_states"]:
                self._roots[root_dir]["folder_states"][folder_name] = self.STATE_ACTIVE
            self.update()

    def mark_folder_done(self, root_dir: str, folder_name: str) -> None:
        if root_dir in self._roots:
            if folder_name in self._roots[root_dir]["folder_states"]:
                self._roots[root_dir]["folder_states"][folder_name] = self.STATE_DONE

            # Check if all folders in this root are done
            states = self._roots[root_dir]["folder_states"].values()
            if all(s == self.STATE_DONE for s in states):
                self._roots[root_dir]["state"] = self.STATE_DONE
            self.update()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        padding = 1
        bar_top = padding
        bar_height = h - 2 * padding

        num_roots = len(self._roots_order)
        if num_roots == 0:
            painter.fillRect(0, bar_top, w, bar_height, self._COLOR_BG)
            painter.end()
            return

        root_width = w / num_roots

        for idx, root_dir in enumerate(self._roots_order):
            root_data = self._roots.get(root_dir, {})
            state = root_data.get("state", self.STATE_PENDING)
            rx = int(idx * root_width)
            rw = int(root_width) - 1

            # Background for this root segment
            if state == self.STATE_DONE:
                bg = self._COLOR_DONE_ROOT
            elif state == self.STATE_ACTIVE:
                bg = self._COLOR_ACTIVE_ROOT
            else:
                bg = self._COLOR_PENDING_FILL
            painter.fillRect(rx, bar_top, rw, bar_height, bg)

            # Draw folder sub-segments sorted by state to guarantee left-to-right fill
            folders = root_data.get("folders", [])
            num_folders = len(folders)
            if num_folders > 0:
                folder_w = rw / num_folders

                # Count counts of each state
                states_count = {
                    self.STATE_PENDING: 0,
                    self.STATE_ACTIVE: 0,
                    self.STATE_DONE: 0,
                }
                for folder_name in folders:
                    folder_state = root_data.get("folder_states", {}).get(
                        folder_name, self.STATE_PENDING
                    )
                    states_count[folder_state] += 1

                # Create an ordered list of states: DONE first, then ACTIVE, then PENDING
                ordered_states = (
                    [self.STATE_DONE] * states_count[self.STATE_DONE]
                    + [self.STATE_ACTIVE] * states_count[self.STATE_ACTIVE]
                    + [self.STATE_PENDING] * states_count[self.STATE_PENDING]
                )

                for fidx, folder_state in enumerate(ordered_states):
                    fx = rx + int(fidx * folder_w)
                    fw = int(folder_w) - 1

                    if folder_state == self.STATE_DONE or state == self.STATE_DONE:
                        painter.fillRect(
                            fx, bar_top, fw, bar_height, self._COLOR_DONE_FOLDER
                        )
                    elif folder_state == self.STATE_ACTIVE:
                        painter.fillRect(
                            fx, bar_top, fw, bar_height, self._COLOR_ACTIVE_FOLDER
                        )
                    else:
                        painter.fillRect(
                            fx, bar_top, fw, bar_height, self._COLOR_PENDING_FILL
                        )

                    # Folder divider line
                    if fidx > 0:
                        painter.setPen(QPen(self._COLOR_ROOT_DIVIDER, 1))
                        painter.drawLine(fx, bar_top, fx, bar_top + bar_height)

            # Root border
            painter.setPen(QPen(self._COLOR_BORDER, 1))
            painter.drawRect(rx, bar_top, rw, bar_height)

            # Root separator line
            if idx > 0:
                painter.setPen(QPen(self._COLOR_BORDER, 2))
                painter.drawLine(rx, bar_top, rx, bar_top + bar_height)

        painter.end()


class Controller(QObject):
    """
    Core Application Logic Controller managing native UI synchronization and persistence layer interactions.
    Enforces strict zero-abbreviation variable naming standard.
    """

    library_loaded = Signal()
    series_selected = Signal(str)
    movie_selected = Signal(str)
    status_changed = Signal(str)
    playback_requested = Signal(str)
    metadata_dialog_requested = Signal(str)
    rename_dialog_requested = Signal(str)
    jellyfin_dialog_requested = Signal(str)
    series_details_requested = Signal(str)
    episode_details_requested = Signal(str, str)
    movie_details_requested = Signal(str, str)
    episode_metadata_dialog_requested = Signal(str, str)
    global_progress_updated = Signal(str, int, int)
    detail_progress_updated = Signal(str, dict)
    scan_completed = Signal()

    file_system_watcher: QFileSystemWatcher
    debounce_timer: QTimer

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.current_library_name: str = ""
        self.cached_library_data: Dict[str, Any] = {}
        self.selected_series_name: str = ""
        self.sort_mode: str = config.sort_mode
        self.sort_descending: bool = config.sort_descending
        self.filter_out_watched: bool = config.filter_out_watched
        self.scan_worker_instance: Optional[ScanWorker] = None
        self.cleanup_worker_instance: Optional[CleanupWorker] = None
        self.pull_worker_instance: Optional[JellyfinPullWorker] = None
        self.push_worker_instance: Optional[JellyfinPushWorker] = None
        self.scan_all_worker_instance: Optional[ScanAllLibrariesWorker] = None
        self.cleanup_all_worker_instance: Optional[CleanupAllLibrariesWorker] = None
        self.runtime_worker_instance: Optional[RuntimeExtractionWorker] = None
        self.merge_subtitle_worker_instance: Optional[Any] = None
        self.embed_metadata_worker_instance: Optional[Any] = None
        self.is_video_playing: bool = False

        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(2000)
        self.debounce_timer.timeout.connect(self._on_debounce_timeout)

        self.file_system_watcher = QFileSystemWatcher(self)
        self.file_system_watcher.directoryChanged.connect(self._on_directory_changed)

    def select_library(self, library_name: str) -> None:
        logger.info(f"Controller loading library: {library_name}")
        self.current_library_name = library_name
        self.status_changed.emit(f"Loading library: {library_name}...")

        library_config = config.libraries.get(library_name, {})

        existing_directories = self.file_system_watcher.directories()
        if existing_directories:
            self.file_system_watcher.removePaths(existing_directories)

        root_directories: List[str] = library_config.get("paths", [])
        for directory_path in root_directories:
            if Path(directory_path).is_dir():
                self.file_system_watcher.addPath(directory_path)

        if library_config.get("type", "tv") == "movie":
            self.cached_library_data = db.load_movie_library(library_name)
        else:
            self.cached_library_data = db.load_library(library_name)
        self._cache_series_metrics()
        self.selected_series_name = ""

        self.status_changed.emit("Library loaded successfully.")
        self.library_loaded.emit()

    def _on_directory_changed(self, path_string: str) -> None:
        logger.info(
            f"Directory modification detected on '{path_string}'. Automated background scanning disabled."
        )

    def _on_debounce_timeout(self) -> None:
        pass

    def _cache_series_metrics(self) -> None:
        for series_name, series_data in self.cached_library_data.items():
            if "seasons" not in series_data:
                is_watched = bool(series_data.get("watched"))
                series_data["metrics"] = {
                    "total_episodes": 1,
                    "watched_episodes": 1 if is_watched else 0,
                    "max_date_added": series_data.get("date_added") or 0,
                    "max_air_date": str(series_data.get("year") or ""),
                    "last_played_at": series_data.get("last_played_at") or 0,
                }
            else:
                total_episodes: int = 0
                watched_episodes: int = 0
                max_date_added: int = 0
                max_air_date: str = ""
                last_played_at: int = 0

                for season_data in series_data.get("seasons", {}).values():
                    for episode_record in season_data.get("episodes", []):
                        total_episodes += 1
                        if episode_record.get("watched"):
                            watched_episodes += 1
                        added_timestamp: int = episode_record.get("date_added") or 0
                        if added_timestamp > max_date_added:
                            max_date_added = added_timestamp
                        air_date_string: str = episode_record.get("air_date") or ""
                        if air_date_string > max_air_date:
                            max_air_date = air_date_string
                        lp: int = episode_record.get("last_played_at") or 0
                        if lp > last_played_at:
                            last_played_at = lp

                series_data["metrics"] = {
                    "total_episodes": total_episodes,
                    "watched_episodes": watched_episodes,
                    "max_date_added": max_date_added,
                    "max_air_date": max_air_date,
                    "last_played_at": last_played_at,
                }

    def select_series(self, series_name: str) -> None:
        if series_name in self.cached_library_data:
            self.selected_series_name = series_name
            self.series_selected.emit(series_name)

    def select_movie(self, movie_name: str) -> None:
        if movie_name in self.cached_library_data:
            self.selected_series_name = movie_name
            self.movie_selected.emit(movie_name)

    def set_sort_mode(self, mode: str) -> None:
        if self.sort_mode != mode:
            logger.info(f"Sort mode changed from '{self.sort_mode}' to '{mode}'")
            self.sort_mode = mode
            config.sort_mode = mode
            config.save()
            self.library_loaded.emit()

    def set_sort_descending(self, descending: bool) -> None:
        if self.sort_descending != descending:
            logger.info(
                f"Sort direction changed to {'descending' if descending else 'ascending'}"
            )
            self.sort_descending = descending
            config.sort_descending = descending
            config.save()
            self.library_loaded.emit()

    def set_filter_out_watched(self, enabled: bool) -> None:
        if self.filter_out_watched != enabled:
            self.filter_out_watched = enabled
            config.filter_out_watched = enabled
            config.save()
            self.library_loaded.emit()

    def mark_episode_watched(self, absolute_path: str, watched: bool) -> None:
        logger.info(
            f"Controller marking episode watched={watched} for path: {absolute_path}"
        )
        db.update_episode_watched_status(absolute_path, watched)

        # Update cached state in memory
        for series_data in self.cached_library_data.values():
            if "seasons" not in series_data:
                if series_data.get("path") == absolute_path:
                    series_data["watched"] = watched
                    break
            else:
                for season_data in series_data.get("seasons", {}).values():
                    for episode_record in season_data.get("episodes", []):
                        if episode_record.get("path") == absolute_path:
                            episode_record["watched"] = watched
                            break

        self._cache_series_metrics()

        if not self.is_video_playing:
            self.library_loaded.emit()

    def mark_season_watched(self, series_name: str, season_name: str) -> None:
        logger.info(
            f"Controller marking season watched for series '{series_name}', season '{season_name}'"
        )
        db.update_season_watched_status(
            self.current_library_name, series_name, season_name, True
        )

        series_data: Dict[str, Any] = self.cached_library_data.get(series_name, {})
        season_data: Dict[str, Any] = series_data.get("seasons", {}).get(
            season_name, {}
        )
        for episode_record in season_data.get("episodes", []):
            episode_record["watched"] = True

        self._cache_series_metrics()
        if not self.is_video_playing:
            self.library_loaded.emit()

    def mark_series_watched(self, series_name: str) -> None:
        logger.info(f"Controller marking entire series watched: '{series_name}'")
        db.update_series_watched_status(self.current_library_name, series_name, True)

        series_data: Dict[str, Any] = self.cached_library_data.get(series_name, {})
        for season_data in series_data.get("seasons", {}).values():
            for episode_record in season_data.get("episodes", []):
                episode_record["watched"] = True

        self._cache_series_metrics()
        if not self.is_video_playing:
            self.library_loaded.emit()

    def trigger_scan(self, force_refresh: bool = False) -> None:
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        if (
            self.scan_worker_instance is not None
            and self.scan_worker_instance.isRunning()
        ):
            logger.info(
                "ScanWorker is already actively running. Skipping redundant automatic scan trigger."
            )
            return

        library_config = config.libraries.get(self.current_library_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        library_type: str = library_config.get("type", "tv")
        self.status_changed.emit(
            f"Scanning library '{self.current_library_name}' (force={force_refresh})..."
        )

        self.scan_worker_instance = ScanWorker(
            root_directories=root_directories,
            library_type=library_type,
            existing_library=self.cached_library_data,
            force_refresh=force_refresh,
            cleanup=False,
        )
        self.scan_worker_instance.finished.connect(self._on_scan_finished)
        self.scan_worker_instance.partial_result.connect(self._on_scan_partial)
        self.scan_worker_instance.error.connect(self._on_worker_error)
        self.scan_worker_instance.detail_progress.connect(
            self.detail_progress_updated.emit
        )
        self.scan_worker_instance.start()

    def _on_scan_partial(self, partial_library: Dict[str, Any]) -> None:
        if self.current_library_name:
            # We create a shallow copy/update of cached data to not lose references while UI re-renders
            self.cached_library_data = partial_library
            self._cache_series_metrics()
            if not self.is_video_playing:
                self.library_loaded.emit()

    def _on_scan_finished(self, updated_library: Dict[str, Any]) -> None:
        if self.current_library_name:
            library_config = config.libraries.get(self.current_library_name, {})
            if library_config.get("type", "tv") == "movie":
                db.save_movie_library(self.current_library_name, updated_library)
            else:
                db.save_library(self.current_library_name, updated_library)
            self.cached_library_data = updated_library
            self._cache_series_metrics()
            if (
                self.scan_worker_instance
                and self.scan_worker_instance.unavailable_directories
            ):
                for directory_name in self.scan_worker_instance.unavailable_directories:
                    self.status_changed.emit(
                        f"root directory {directory_name} is unavailable check connection to {directory_name}"
                    )
            else:
                self.status_changed.emit("Library scan completed successfully.")
            if not self.is_video_playing:
                self.library_loaded.emit()
                if self.selected_series_name:
                    if library_config.get("type", "tv") == "movie":
                        self.movie_selected.emit(self.selected_series_name)
                    else:
                        self.series_selected.emit(self.selected_series_name)
        self.scan_completed.emit()

    def trigger_cleanup(self) -> None:
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        library_config = config.libraries.get(self.current_library_name, {})
        root_directories: List[str] = library_config.get("paths", [])
        self.status_changed.emit(
            f"Cleaning up missing files in '{self.current_library_name}'..."
        )

        self.cleanup_worker_instance = CleanupWorker(
            library_name=self.current_library_name, root_directories=root_directories
        )
        self.cleanup_worker_instance.finished.connect(self._on_cleanup_finished)
        self.cleanup_worker_instance.error.connect(self._on_worker_error)
        self.cleanup_worker_instance.start()

    def _on_cleanup_finished(self, statistics: Dict[str, Any]) -> None:
        self.select_library(self.current_library_name)
        series_removed: int = statistics.get("series", 0)
        seasons_removed: int = statistics.get("seasons", 0)
        episodes_removed: int = statistics.get("episodes", 0)
        self.status_changed.emit(
            f"Cleanup finished: removed {series_removed} series, {seasons_removed} seasons, {episodes_removed} episodes."
        )

    def trigger_jellyfin_pull(self) -> None:
        if not jellyfin_client.is_configured():
            self.status_changed.emit("Jellyfin is not configured.")
            return

        self.status_changed.emit("Pulling watch history from Jellyfin...")
        self.pull_worker_instance = JellyfinPullWorker()
        self.pull_worker_instance.finished.connect(self._on_pull_finished)
        self.pull_worker_instance.error.connect(self._on_worker_error)
        self.pull_worker_instance.start()

    def _on_pull_finished(self, updated_count: int) -> None:
        if self.current_library_name:
            self.select_library(self.current_library_name)
        self.status_changed.emit(
            f"Watch history pulled successfully: updated {updated_count} episodes."
        )

    def trigger_jellyfin_push(self) -> None:
        if not jellyfin_client.is_configured():
            self.status_changed.emit("Jellyfin is not configured.")
            return

        self.status_changed.emit("Pushing local watch history to Jellyfin...")
        self.push_worker_instance = JellyfinPushWorker()
        self.push_worker_instance.finished.connect(self._on_push_finished)
        self.push_worker_instance.error.connect(self._on_worker_error)
        self.push_worker_instance.start()

    def _on_push_finished(self, pushed_count: int) -> None:
        self.status_changed.emit(
            f"Watch history pushed successfully: synchronized {pushed_count} episodes."
        )

    def trigger_scan_all(self, force_refresh: bool = False) -> None:
        if (
            self.scan_all_worker_instance is not None
            and self.scan_all_worker_instance.isRunning()
        ):
            logger.info("ScanAllLibrariesWorker is already running.")
            return

        self.status_changed.emit("Scanning all libraries...")
        self.scan_all_worker_instance = ScanAllLibrariesWorker(
            force_refresh=force_refresh
        )
        self.scan_all_worker_instance.library_progress.connect(
            self.global_progress_updated.emit
        )
        self.scan_all_worker_instance.detail_progress.connect(
            self.detail_progress_updated.emit
        )
        self.scan_all_worker_instance.finished.connect(self._on_scan_all_finished)
        self.scan_all_worker_instance.error.connect(self._on_worker_error)
        self.scan_all_worker_instance.start()

    def _on_scan_all_finished(self) -> None:
        if (
            self.scan_all_worker_instance
            and self.scan_all_worker_instance.unavailable_directories
        ):
            for directory_name in self.scan_all_worker_instance.unavailable_directories:
                self.status_changed.emit(
                    f"root directory {directory_name} is unavailable check connection to {directory_name}"
                )
        else:
            self.status_changed.emit(
                "Global multi-library scan completed successfully."
            )
        if self.current_library_name:
            if self.current_library_name == "Combined View":
                self.library_loaded.emit()
            else:
                self.select_library(self.current_library_name)
        self.scan_completed.emit()

    def trigger_cleanup_all(self) -> None:
        if (
            self.cleanup_all_worker_instance is not None
            and self.cleanup_all_worker_instance.isRunning()
        ):
            logger.info("CleanupAllLibrariesWorker is already running.")
            return

        self.status_changed.emit("Cleaning up all libraries...")
        self.cleanup_all_worker_instance = CleanupAllLibrariesWorker()
        self.cleanup_all_worker_instance.library_progress.connect(
            self.global_progress_updated.emit
        )
        self.cleanup_all_worker_instance.finished.connect(self._on_cleanup_all_finished)
        self.cleanup_all_worker_instance.error.connect(self._on_worker_error)
        self.cleanup_all_worker_instance.start()

    def _on_cleanup_all_finished(self) -> None:
        self.status_changed.emit("Global multi-library cleanup completed successfully.")
        if self.current_library_name:
            self.select_library(self.current_library_name)

    def trigger_runtime_extraction(self) -> None:
        if (
            self.runtime_worker_instance is not None
            and self.runtime_worker_instance.isRunning()
        ):
            logger.info("RuntimeExtractionWorker is already running.")
            return

        self.status_changed.emit("Extracting missing video runtimes in background...")
        self.runtime_worker_instance = RuntimeExtractionWorker()
        self.runtime_worker_instance.progress_updated.connect(self._on_runtime_progress)
        self.runtime_worker_instance.finished.connect(self._on_runtime_finished)
        self.runtime_worker_instance.error.connect(self._on_worker_error)
        self.runtime_worker_instance.start()

    def _on_runtime_progress(self, completed_count: int, total_count: int) -> None:
        self.global_progress_updated.emit(
            "Extracting Runtimes", completed_count, total_count
        )

    def _on_runtime_finished(self, updated_count: int) -> None:
        self.status_changed.emit(
            f"Runtime extraction completed: updated {updated_count} videos."
        )
        if self.current_library_name:
            self.select_library(self.current_library_name)

    def _on_worker_error(self, error_message: str) -> None:
        self.status_changed.emit(f"Worker Error: {error_message}")
        logger.error(f"Background execution fault: {error_message}")
        self.scan_completed.emit()

    def _download_provider_artwork(
        self,
        target_dict: Dict[str, Any],
        match_dictionary: Dict[str, Any],
        is_movie: bool,
    ) -> None:
        if match_dictionary.get("poster_path"):
            raw_poster_path: str = match_dictionary.get("poster_path", "")
            tmdb_identifier_value: str = target_dict.get("tmdb_identifier", "")
            if raw_poster_path and tmdb_identifier_value:
                prefix = "tmdb_movie_" if is_movie else "tmdb_series_"
                cached_image_path: Optional[str] = tmdb_client.download_image(
                    raw_poster_path, f"{prefix}{tmdb_identifier_value}"
                )
                target_dict["poster_path"] = cached_image_path or raw_poster_path
            else:
                target_dict["poster_path"] = raw_poster_path

    def _sync_tmdb_episodes_for_series(
        self, series_record: Dict[str, Any], new_tmdb_identifier: str
    ) -> None:
        for season_folder_name, season_data_dict in series_record.get(
            "seasons", {}
        ).items():
            if season_folder_name.lower() == "specials":
                target_season_number: int = 0
            else:
                parsed_season_match = re.search(r"\d+", season_folder_name)
                target_season_number = (
                    int(parsed_season_match.group()) if parsed_season_match else -1
                )

            if target_season_number >= 0:
                fetched_episodes_list = tmdb_client.get_episodes(
                    new_tmdb_identifier, target_season_number
                )
                for episode_item_dict in season_data_dict.get("episodes", []):
                    episode_filename: str = str(
                        episode_item_dict.get("name")
                        or Path(str(episode_item_dict.get("path", ""))).name
                    )
                    matched_tmdb_episode: Optional[Dict[str, Any]] = None

                    episode_number_match = re.search(
                        r"[Ss]\d+[Ee](\d+)", episode_filename
                    )
                    if episode_number_match:
                        target_episode_number: int = int(episode_number_match.group(1))
                        for candidate_episode in fetched_episodes_list:
                            if (
                                candidate_episode.get("episode_number")
                                == target_episode_number
                            ):
                                matched_tmdb_episode = candidate_episode
                                break
                    else:
                        stem_lower: str = Path(episode_filename).stem.lower()
                        for candidate_episode in fetched_episodes_list:
                            candidate_name: str = str(
                                candidate_episode.get("name") or ""
                            ).lower()
                            if candidate_name and candidate_name in stem_lower:
                                matched_tmdb_episode = candidate_episode
                                break

                    if matched_tmdb_episode:
                        matched_id_str: str = str(matched_tmdb_episode.get("id", ""))
                        episode_item_dict["tmdb_identifier"] = matched_id_str
                        episode_item_dict["tmdb_episode_identifier"] = matched_id_str
                        if matched_tmdb_episode.get("name"):
                            episode_item_dict["tmdb_name"] = matched_tmdb_episode.get(
                                "name", ""
                            )
                        if matched_tmdb_episode.get("episode_number") is not None:
                            episode_item_dict["tmdb_number"] = matched_tmdb_episode.get(
                                "episode_number"
                            )
                        if matched_tmdb_episode.get("air_date"):
                            episode_item_dict["air_date"] = matched_tmdb_episode.get(
                                "air_date", ""
                            )
                        if matched_tmdb_episode.get("runtime"):
                            episode_item_dict["runtime"] = matched_tmdb_episode.get(
                                "runtime", 0
                            )

    def apply_metadata_match(
        self, series_name: str, match_dictionary: Dict[str, Any]
    ) -> None:
        logger.info(
            f"Controller applying metadata match for '{series_name}': {match_dictionary}"
        )
        if series_name not in self.cached_library_data:
            return

        library_config = config.libraries.get(self.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        target_dict: Dict[str, Any] = (
            series_record if is_movie else series_record.get("metadata", {})
        )

        provider_name: str = match_dictionary.get("provider", "TMDB")
        target_identifier: str = match_dictionary.get("id", "")

        if provider_name == "Jellyfin":
            target_dict["jellyfin_id"] = target_identifier
            tmdb_id_mapped: str = match_dictionary.get("tmdb_id", "")
            if tmdb_id_mapped:
                target_dict["tmdb_identifier"] = tmdb_id_mapped
        else:
            target_dict["tmdb_identifier"] = target_identifier

        if match_dictionary.get("name"):
            target_dict["tmdb_name"] = match_dictionary.get("name", "")
        if match_dictionary.get("overview"):
            target_dict["overview"] = match_dictionary.get("overview", "")

        self._download_provider_artwork(target_dict, match_dictionary, is_movie)

        if not is_movie and match_dictionary.get("first_air_date"):
            target_dict["first_air_date"] = match_dictionary.get("first_air_date", "")
        elif is_movie and match_dictionary.get("first_air_date"):
            air_date_str = match_dictionary.get("first_air_date", "")
            if air_date_str:
                try:
                    target_dict["year"] = int(air_date_str.split("-")[0])
                except ValueError:
                    pass

        target_dict["locked_metadata"] = True
        if not is_movie:
            series_record["metadata"] = target_dict

            new_tmdb_identifier: str = target_dict.get("tmdb_identifier", "")
            if new_tmdb_identifier:
                self._sync_tmdb_episodes_for_series(series_record, new_tmdb_identifier)

        if self.current_library_name:
            if is_movie:
                db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            else:
                db.save_library(self.current_library_name, self.cached_library_data)

        self.status_changed.emit(
            f"Successfully applied metadata match to '{series_name}'."
        )
        self.library_loaded.emit()
        if self.selected_series_name == series_name:
            if is_movie:
                self.movie_selected.emit(series_name)
            else:
                self.series_selected.emit(series_name)

    def apply_jellyfin_watch_match(
        self, series_name: str, match_dictionary: Dict[str, Any]
    ) -> None:
        logger.info(
            f"Controller applying Jellyfin watch history match for '{series_name}': {match_dictionary}"
        )
        if series_name not in self.cached_library_data:
            return

        library_config = config.libraries.get(self.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        target_dict: Dict[str, Any] = (
            series_record if is_movie else series_record.get("metadata", {})
        )

        target_identifier: str = match_dictionary.get("id", "")
        target_dict["jellyfin_id"] = target_identifier

        if self.current_library_name:
            if is_movie:
                db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            else:
                db.save_library(self.current_library_name, self.cached_library_data)

        self.status_changed.emit(
            f"Successfully linked Jellyfin watch history for '{series_name}'."
        )
        self.library_loaded.emit()
        if self.selected_series_name == series_name:
            if is_movie:
                self.movie_selected.emit(series_name)
            else:
                self.series_selected.emit(series_name)

    def apply_episode_metadata_match(
        self, series_name: str, episode_path: str, match_dictionary: Dict[str, Any]
    ) -> None:
        logger.info(
            f"Controller applying episode metadata match for '{series_name}' at '{episode_path}': {match_dictionary}"
        )
        if series_name not in self.cached_library_data:
            return

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        episode_found: bool = False

        for season_data in series_record.get("seasons", {}).values():
            for episode_record in season_data.get("episodes", []):
                if episode_record.get("path") == episode_path:
                    target_identifier: str = str(match_dictionary.get("id", ""))
                    episode_record["tmdb_identifier"] = target_identifier
                    episode_record["tmdb_episode_identifier"] = target_identifier
                    if match_dictionary.get("name"):
                        episode_record["tmdb_name"] = match_dictionary.get("name", "")
                    if match_dictionary.get("episode_number") is not None:
                        episode_record["tmdb_number"] = match_dictionary.get(
                            "episode_number"
                        )
                    if match_dictionary.get("air_date"):
                        episode_record["air_date"] = match_dictionary.get(
                            "air_date", ""
                        )
                    if match_dictionary.get("runtime"):
                        episode_record["runtime"] = match_dictionary.get("runtime", 0)
                    episode_found = True
                    break
            if episode_found:
                break

        if episode_found:
            if self.current_library_name:
                db.save_library(self.current_library_name, self.cached_library_data)

            self.status_changed.emit(
                f"Successfully applied episode metadata match to '{series_name}'."
            )
            self.library_loaded.emit()
            if self.selected_series_name == series_name:
                self.series_selected.emit(series_name)

    def update_episode_metadata(
        self, series_name: str, episode_path: str, metadata_dictionary: Dict[str, Any]
    ) -> None:
        """Persists manual metadata overrides for a specific episode."""
        logger.info(
            f"Controller updating episode metadata for '{series_name}' at '{episode_path}'"
        )
        if series_name not in self.cached_library_data:
            return

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        episode_found: bool = False

        for season_data in series_record.get("seasons", {}).values():
            for episode_record in season_data.get("episodes", []):
                if episode_record.get("path") == episode_path:
                    for key, value in metadata_dictionary.items():
                        episode_record[key] = value
                    episode_found = True
                    break
            if episode_found:
                break

        if episode_found:
            if self.current_library_name:
                db.save_library(self.current_library_name, self.cached_library_data)
            self.library_loaded.emit()
            if self.selected_series_name == series_name:
                self.series_selected.emit(series_name)

    def toggle_series_lock(self, series_name: str, locked: bool) -> None:
        """
        Updates the locked_metadata flag for a series or movie and persists it to the database.
        """
        logger.info(f"Controller toggling lock for '{series_name}' to {locked}")
        if series_name not in self.cached_library_data:
            return

        library_config = config.libraries.get(self.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        series_record: Dict[str, Any] = self.cached_library_data[series_name]
        if is_movie:
            series_record["locked_metadata"] = locked
            if self.current_library_name:
                db.save_movie_library(
                    self.current_library_name, self.cached_library_data
                )
            self.movie_selected.emit(series_name)
        else:
            if "metadata" not in series_record:
                series_record["metadata"] = {}
            series_record["metadata"]["locked_metadata"] = locked
            if self.current_library_name:
                db.save_library(self.current_library_name, self.cached_library_data)
            self.series_selected.emit(series_name)

        self.library_loaded.emit()

    def trigger_series_refresh(self, series_name: str) -> None:
        """Triggers a background RefreshSeriesWorker for the specified series or movie."""
        if not self.current_library_name:
            self.status_changed.emit("Select a library first.")
            return

        if self.scan_worker_instance and self.scan_worker_instance.isRunning():
            self.status_changed.emit("A scan is already in progress.")
            return

        library_config = config.libraries.get(self.current_library_name, {})
        library_type = library_config.get("type", "tv")
        root_directories = library_config.get("paths", [])

        self.status_changed.emit(f"Refreshing metadata for '{series_name}'...")

        from .backend import RefreshSeriesWorker

        self.refresh_worker_instance = RefreshSeriesWorker(
            library_name=self.current_library_name,
            item_name=series_name,
            library_type=library_type,
            root_directories=root_directories,
            existing_library=self.cached_library_data,
        )
        self.refresh_worker_instance.finished.connect(self._on_refresh_finished)
        self.refresh_worker_instance.error.connect(self._on_worker_error)
        self.refresh_worker_instance.start()

    def _on_refresh_finished(self, updated_library: Dict[str, Any]) -> None:
        if self.current_library_name:
            self.cached_library_data = updated_library
            self._cache_series_metrics()
            self.status_changed.emit("Metadata refresh completed successfully.")
            if not self.is_video_playing:
                self.library_loaded.emit()
                if self.selected_series_name:
                    library_config = config.libraries.get(self.current_library_name, {})
                    if library_config.get("type", "tv") == "movie":
                        self.movie_selected.emit(self.selected_series_name)
                    else:
                        self.series_selected.emit(self.selected_series_name)

    def refresh_episode_metadata(self, series_name: str, episode_path: str) -> None:
        """
        Queries TMDB directly for the specific episode's metadata and updates it,
        bypassing lock status (since targeted).
        """
        logger.info(
            f"Controller refreshing episode metadata for '{series_name}' at '{episode_path}'"
        )
        if series_name not in self.cached_library_data:
            return

        series_record = self.cached_library_data[series_name]
        series_tmdb_id = series_record.get("metadata", {}).get("tmdb_identifier")
        if not series_tmdb_id:
            logger.warning(
                "Cannot refresh episode metadata because series has no TMDB identifier"
            )
            return

        target_episode: Optional[Dict[str, Any]] = None
        target_season_name: Optional[str] = None
        for season_name, season_data in series_record.get("seasons", {}).items():
            for ep in season_data.get("episodes", []):
                if ep.get("path") == episode_path:
                    target_episode = ep
                    target_season_name = season_name
                    break
            if target_episode:
                break

        if not target_episode or target_season_name is None:
            logger.warning("Episode not found in cache")
            return

        if target_season_name.lower() == "specials":
            season_index = 0
        else:
            import re

            m = re.search(r"\d+", target_season_name)
            season_index = int(m.group()) if m else 1

        episode_num = target_episode.get("episode_number") or target_episode.get(
            "tmdb_number"
        )
        if episode_num is None:
            logger.warning("Episode has no episode number")
            return

        try:
            tmdb_episodes = tmdb_client.get_episodes(series_tmdb_id, season_index)
            matched_ep = None
            for ep in tmdb_episodes:
                if ep.get("episode_number") == episode_num:
                    matched_ep = ep
                    break

            if matched_ep:
                target_episode["tmdb_name"] = matched_ep.get("name", "")
                target_episode["name"] = matched_ep.get("name", "")
                target_episode["overview"] = matched_ep.get("overview", "")
                target_episode["air_date"] = matched_ep.get("air_date", "")
                target_episode["runtime"] = matched_ep.get("runtime", 0)

                db.save_library(self.current_library_name, self.cached_library_data)
                self.library_loaded.emit()
                if self.selected_series_name == series_name:
                    self.series_selected.emit(series_name)
                logger.info("Successfully refreshed episode metadata from TMDB")
            else:
                logger.warning(
                    f"Could not find episode {episode_num} in TMDB season {season_index}"
                )
        except Exception:
            logger.exception("Failed to refresh episode metadata from TMDB")

    def update_movie_metadata(
        self, movie_name: str, movie_path: str, metadata: Dict[str, Any]
    ) -> None:
        """
        Updates movie metadata in the database and refreshes local cache.
        Strictly typed with no abbreviations.
        """
        if movie_name not in self.cached_library_data:
            return

        movie_data = self.cached_library_data[movie_name]
        movie_data.update(metadata)

        # Persistence
        db.save_library(self.current_library_name, self.cached_library_data)
        self._cache_series_metrics()
        self.library_loaded.emit()

    def merge_subtitles(self, video_path: str, subtitle_paths: List[str]) -> None:
        """Triggers background ffmpeg worker to merge external subtitles into video file."""
        if (
            self.merge_subtitle_worker_instance
            and self.merge_subtitle_worker_instance.isRunning()
        ):
            self.status_changed.emit("Subtitle merge already in progress.")
            return

        from .backend import SubtitleMergeWorker

        self.status_changed.emit("Merging external subtitles into video file...")
        self.merge_subtitle_worker_instance = SubtitleMergeWorker(
            video_path, subtitle_paths
        )
        self.merge_subtitle_worker_instance.finished.connect(
            self._on_subtitle_merge_finished
        )
        self.merge_subtitle_worker_instance.error.connect(self._on_worker_error)
        self.merge_subtitle_worker_instance.start()

    def _on_subtitle_merge_finished(self, final_path: str) -> None:
        self.status_changed.emit("Subtitles merged successfully.")
        # Trigger scan to update metadata/details if needed
        self.trigger_scan(force_refresh=False)

    def embed_metadata(self, video_path: str, metadata: Dict[str, str]) -> None:
        """Triggers background ffmpeg worker to embed metadata into video file."""
        if (
            self.embed_metadata_worker_instance
            and self.embed_metadata_worker_instance.isRunning()
        ):
            self.status_changed.emit("Metadata embedding already in progress.")
            return

        from .backend import MetadataEmbedWorker

        self.status_changed.emit("Embedding metadata into video file...")
        self.embed_metadata_worker_instance = MetadataEmbedWorker(video_path, metadata)
        self.embed_metadata_worker_instance.finished.connect(
            self._on_metadata_embed_finished
        )
        self.embed_metadata_worker_instance.error.connect(self._on_worker_error)
        self.embed_metadata_worker_instance.start()

    def _on_metadata_embed_finished(self, final_path: str) -> None:
        self.status_changed.emit("Metadata embedded successfully.")
        self.trigger_scan(force_refresh=False)

    def embed_metadata_series(self, series_name: str) -> None:
        """Triggers background worker to embed metadata for all episodes in a series."""
        if (
            self.embed_metadata_worker_instance
            and self.embed_metadata_worker_instance.isRunning()
        ):
            self.status_changed.emit("Metadata embedding already in progress.")
            return

        if series_name not in self.cached_library_data:
            return

        series_record = self.cached_library_data[series_name]
        all_episodes = []
        for season in series_record.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                all_episodes.append(ep)

        if not all_episodes:
            self.status_changed.emit("No episodes found in series.")
            return

        from .backend import SeriesMetadataEmbedWorker

        self.status_changed.emit(f"Embedding metadata for series '{series_name}'...")
        self.embed_metadata_worker_instance = SeriesMetadataEmbedWorker(
            series_name, all_episodes
        )
        self.embed_metadata_worker_instance.progress_updated.connect(
            self.global_progress_updated.emit
        )
        self.embed_metadata_worker_instance.finished.connect(
            lambda: self.status_changed.emit("Series metadata embedding finished.")
        )
        self.embed_metadata_worker_instance.error.connect(self._on_worker_error)
        self.embed_metadata_worker_instance.start()

    def update_series_name(self, old_name: str, new_name: str) -> None:
        """Renames a series in the database and updates cache."""
        if old_name not in self.cached_library_data or not new_name:
            return

        series_data = self.cached_library_data.pop(old_name)
        self.cached_library_data[new_name] = series_data

        db.save_library(self.current_library_name, self.cached_library_data)
        self._cache_series_metrics()
        self.library_loaded.emit()
        # Trigger re-selection to update UI
        self.selected_series_name = new_name
        self.series_selected.emit(new_name)

    def apply_rename_batch(self, preview_results: List[Dict[str, Any]]) -> None:
        logger.info(
            f"Controller executing batch renames for {len(preview_results)} files."
        )
        from .renamer import perform_rename

        def on_rename_success(old_path_string: str, new_path_string: str) -> None:
            db.update_episode_path(old_path_string, new_path_string)
            for series_dictionary in self.cached_library_data.values():
                for season_dictionary in series_dictionary.get("seasons", {}).values():
                    for episode_dictionary in season_dictionary.get("episodes", []):
                        if episode_dictionary.get("path") == old_path_string:
                            episode_dictionary["path"] = new_path_string
                            path_instance = Path(new_path_string)
                            episode_dictionary["name"] = path_instance.name
                            break

        perform_rename(preview_results, on_rename_success)

        if self.current_library_name:
            db.save_library(self.current_library_name, self.cached_library_data)

        self.status_changed.emit("Batch renaming completed successfully.")
        self.library_loaded.emit()
        if self.selected_series_name:
            self.series_selected.emit(self.selected_series_name)

    def set_video_playing(self, is_playing: bool) -> None:
        logger.info(f"Controller setting video playing state: {is_playing}")
        self.is_video_playing = is_playing
        if not is_playing:
            self.library_loaded.emit()
            if self.selected_series_name:
                library_config = config.libraries.get(self.current_library_name, {})
                if library_config.get("type", "tv") == "movie":
                    self.movie_selected.emit(self.selected_series_name)
                else:
                    self.series_selected.emit(self.selected_series_name)


class LibraryGridView(QWidget):
    """
    Responsive Grid View displaying series items using custom layout sizing.
    Conforms strictly to zero-abbreviation variable naming and strict typing requirements.
    """

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.series_list_widget: QListWidget = QListWidget()
        self.library_selector: QComboBox = QComboBox()
        self.sort_label: QLabel = QLabel("Sort By:")
        self.sort_selector: QComboBox = QComboBox()
        self.order_label: QLabel = QLabel("Order:")
        self.order_selector: QComboBox = QComboBox()
        self.sort_order_container: QWidget = QWidget()
        self.filter_watched_checkbox: QCheckBox = QCheckBox("Hide Watched")
        self.cached_icons: Dict[str, QIcon] = {}
        self._last_order_mode: Optional[str] = None
        self.scan_progress_bar: LibraryScanProgressBar = LibraryScanProgressBar()
        self.scan_status_label: QLabel = QLabel()

        self._setup_ui()
        self._wire_signals()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Top Filters Row
        top_toolbar_layout: QHBoxLayout = QHBoxLayout()
        top_toolbar_layout.setSpacing(10)

        top_toolbar_layout.addWidget(QLabel("Library:"))
        self.library_selector.setMinimumWidth(150)
        top_toolbar_layout.addWidget(self.library_selector)

        # Sort & Order Container to easily hide them in Combined View
        sort_order_layout: QHBoxLayout = QHBoxLayout(self.sort_order_container)
        sort_order_layout.setContentsMargins(15, 0, 15, 0)
        sort_order_layout.setSpacing(10)

        sort_order_layout.addWidget(self.sort_label)
        self.sort_selector.addItems(
            ["Alphabetical", "Recently Added", "Recently Aired", "Next Up"]
        )
        self.sort_selector.setCurrentText(self.controller.sort_mode)
        sort_order_layout.addWidget(self.sort_selector)

        sort_order_layout.addWidget(self.order_label)
        sort_order_layout.addWidget(self.order_selector)

        top_toolbar_layout.addWidget(self.sort_order_container)

        self.filter_watched_checkbox.setChecked(self.controller.filter_out_watched)
        top_toolbar_layout.addWidget(self.filter_watched_checkbox)

        top_toolbar_layout.addStretch()

        settings_button: QPushButton = QPushButton("Settings...")
        settings_button.setObjectName("openSettingsButton")
        settings_button.clicked.connect(self.open_settings_dialog)
        top_toolbar_layout.addWidget(settings_button)

        main_layout.addLayout(top_toolbar_layout)

        # Bottom Actions Row
        self.actions_toolbar_widget = QWidget()
        actions_toolbar_layout: QHBoxLayout = QHBoxLayout(self.actions_toolbar_widget)
        actions_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        actions_toolbar_layout.setSpacing(10)

        scan_button: QPushButton = QPushButton("Scan New Files")
        scan_button.clicked.connect(lambda: self.controller.trigger_scan(False))
        actions_toolbar_layout.addWidget(scan_button)

        refresh_all_button: QPushButton = QPushButton("Refresh Metadata")
        refresh_all_button.clicked.connect(lambda: self.controller.trigger_scan(True))
        actions_toolbar_layout.addWidget(refresh_all_button)

        pull_history_button: QPushButton = QPushButton("Pull Watch History")
        pull_history_button.clicked.connect(self.controller.trigger_jellyfin_pull)
        actions_toolbar_layout.addWidget(pull_history_button)

        push_history_button: QPushButton = QPushButton("Push Watch History")
        push_history_button.clicked.connect(self.controller.trigger_jellyfin_push)
        actions_toolbar_layout.addWidget(push_history_button)

        cleanup_button: QPushButton = QPushButton("Cleanup")
        cleanup_button.clicked.connect(self.controller.trigger_cleanup)
        actions_toolbar_layout.addWidget(cleanup_button)

        actions_toolbar_layout.addStretch()
        main_layout.addWidget(self.actions_toolbar_widget)

        # Combined Actions Row
        self.combined_actions_toolbar_widget: QWidget = QWidget()
        combined_actions_toolbar_layout: QHBoxLayout = QHBoxLayout(
            self.combined_actions_toolbar_widget
        )
        combined_actions_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        combined_actions_toolbar_layout.setSpacing(10)

        combined_scan_button: QPushButton = QPushButton("Scan New Files")
        combined_scan_button.clicked.connect(self.trigger_combined_scan)
        combined_actions_toolbar_layout.addWidget(combined_scan_button)

        combined_actions_toolbar_layout.addStretch()
        self.combined_actions_toolbar_widget.setVisible(False)
        main_layout.addWidget(self.combined_actions_toolbar_widget)

        # Series Responsive List/Grid Widget
        self.series_list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.series_list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.series_list_widget.setSpacing(15)
        self.series_list_widget.setIconSize(QSize(160, 220))
        self.series_list_widget.setGridSize(QSize(190, 280))
        self.series_list_widget.setMovement(QListWidget.Movement.Static)

        main_layout.addWidget(self.series_list_widget)

        # Combined View Scroll Area
        self.combined_scroll_area: QScrollArea = QScrollArea()
        self.combined_scroll_area.setWidgetResizable(True)
        self.combined_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.combined_scroll_area.setVisible(False)
        self.combined_scroll_content = QWidget()
        self.combined_scroll_layout = QVBoxLayout(self.combined_scroll_content)
        self.combined_scroll_layout.setSpacing(25)
        self.combined_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.combined_scroll_area.setWidget(self.combined_scroll_content)
        main_layout.addWidget(self.combined_scroll_area)

        # Add status label and progress bar at the very bottom
        self.scan_status_label.setStyleSheet(
            "font-weight: bold; color: #f3f4f6; font-size: 13px;"
        )
        self.scan_status_label.setVisible(False)
        main_layout.addWidget(self.scan_status_label)

        self.scan_progress_bar.setVisible(False)
        main_layout.addWidget(self.scan_progress_bar)

    def _wire_signals(self) -> None:
        self.controller.library_loaded.connect(self.populate_grid)
        self.library_selector.currentTextChanged.connect(self.on_library_changed)
        self.sort_selector.currentTextChanged.connect(self.controller.set_sort_mode)
        self.order_selector.currentTextChanged.connect(self.on_order_changed)
        self.filter_watched_checkbox.toggled.connect(
            self.controller.set_filter_out_watched
        )
        self.series_list_widget.itemClicked.connect(self.on_item_clicked)
        self.controller.detail_progress_updated.connect(self._on_detail_progress)
        self.controller.scan_completed.connect(self._on_scan_completed)

    @Slot(str, dict)
    def _on_detail_progress(self, event: str, payload: Dict[str, Any]) -> None:
        root = payload.get("root", "")
        folder = payload.get("folder", "")
        if event == "init_library_scan":
            roots = payload.get("roots", {})
            roots_order = payload.get("roots_order", [])
            self.scan_progress_bar.init_from_roots(roots, roots_order)
            self.scan_progress_bar.setVisible(True)
            self.scan_status_label.setText("Starting library scan...")
            self.scan_status_label.setVisible(True)
        elif event == "init_tree":
            roots_dict: Dict[str, List[str]] = {}
            roots_order: List[str] = []
            tree = payload.get("tree", {})
            for lib_name, lib_data in tree.items():
                roots_data = lib_data.get("roots", {})
                for root_dir, folders_dict in roots_data.items():
                    roots_order.append(root_dir)
                    roots_dict[root_dir] = list(folders_dict.keys())
            self.scan_progress_bar.init_from_roots(roots_dict, roots_order)
            self.scan_progress_bar.setVisible(True)
            self.scan_status_label.setText("Starting global library scan...")
            self.scan_status_label.setVisible(True)
        elif event == "start_folder":
            self.scan_progress_bar.mark_folder_active(root, folder)
            library_name: str = payload.get("library", "")
            library_prefix: str = f" [{library_name}]" if library_name else ""
            self.scan_status_label.setText(
                f"Scanning{library_prefix}: {root} > {folder}"
            )
            self.scan_status_label.setVisible(True)
        elif event == "finish_folder":
            self.scan_progress_bar.mark_folder_done(root, folder)

    @Slot()
    def _on_scan_completed(self) -> None:
        self.scan_progress_bar.setVisible(False)
        self.scan_status_label.setVisible(False)

    def populate_libraries(self, library_names: List[str]) -> None:
        self.library_selector.blockSignals(True)
        self.library_selector.clear()
        options = []
        if config.enable_combined_view:
            options.append("Combined View")
        options.extend(library_names)
        self.library_selector.addItems(options)

        current = self.controller.current_library_name
        if current and current in options:
            self.library_selector.setCurrentText(current)
            self.on_library_changed(current)
        else:
            if options:
                self.library_selector.setCurrentText(options[0])
                self.on_library_changed(options[0])
        self.library_selector.blockSignals(False)

    @Slot()
    def open_settings_dialog(self) -> None:
        dialog_instance = SettingsDialog(self.controller, self)
        dialog_instance.exec()
        self.populate_libraries(sorted(config.libraries.keys()))

    @Slot(str)
    def on_library_changed(self, library_name: str) -> None:
        if library_name == "Combined View":
            self.controller.current_library_name = "Combined View"
            self.series_list_widget.setVisible(False)
            if hasattr(self, "actions_toolbar_widget"):
                self.actions_toolbar_widget.setVisible(False)
            if hasattr(self, "combined_actions_toolbar_widget"):
                self.combined_actions_toolbar_widget.setVisible(True)
            self.sort_order_container.setVisible(False)
            self.combined_scroll_area.setVisible(True)
            self.populate_combined_view()
        else:
            self.series_list_widget.setVisible(True)
            if hasattr(self, "actions_toolbar_widget"):
                self.actions_toolbar_widget.setVisible(True)
            if hasattr(self, "combined_actions_toolbar_widget"):
                self.combined_actions_toolbar_widget.setVisible(False)
            self.sort_order_container.setVisible(True)
            self.combined_scroll_area.setVisible(False)
            if library_name:
                self.controller.select_library(library_name)

    @Slot()
    def trigger_combined_scan(self) -> None:
        self.controller.trigger_scan_all(False)

    @Slot(str)
    def on_order_changed(self, text: str) -> None:
        if not text:
            return
        if self.controller.sort_mode == "Alphabetical":
            descending = text == "Z-A"
        else:
            descending = text == "Oldest to Newest"
        logger.debug(
            f"Order dropdown changed to '{text}', sort_descending={descending}"
        )
        self.controller.set_sort_descending(descending)

    @Slot()
    def populate_grid(self) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return
        if self.library_selector.currentText() == "Combined View":
            self.populate_combined_view()
            return
        self.order_selector.blockSignals(True)
        current_sort_mode: str = self.controller.sort_mode
        show_order: bool = current_sort_mode != "Next Up"
        self.order_label.setVisible(show_order)
        self.order_selector.setVisible(show_order)
        if show_order:
            if current_sort_mode != self._last_order_mode:
                self.order_selector.clear()
                if current_sort_mode == "Alphabetical":
                    self.order_selector.addItems(["A-Z", "Z-A"])
                else:
                    self.order_selector.addItems(
                        ["Newest to Oldest", "Oldest to Newest"]
                    )
                self._last_order_mode = current_sort_mode
            if current_sort_mode == "Alphabetical":
                self.order_selector.setCurrentText(
                    "Z-A" if self.controller.sort_descending else "A-Z"
                )
            else:
                self.order_selector.setCurrentText(
                    "Oldest to Newest"
                    if self.controller.sort_descending
                    else "Newest to Oldest"
                )
        else:
            self._last_order_mode = None
        self.order_selector.blockSignals(False)
        # Build list of displayable series structured records
        series_entries: List[Dict[str, Any]] = []
        for series_name, series_data in self.controller.cached_library_data.items():
            metrics_dictionary: Dict[str, Any] = series_data.get("metrics", {})
            is_movie: bool = "seasons" not in series_data
            metadata_dictionary: Dict[str, Any] = (
                series_data if is_movie else series_data.get("metadata", {})
            )

            total_episodes: int = metrics_dictionary.get("total_episodes", 0)
            watched_episodes: int = metrics_dictionary.get("watched_episodes", 0)
            max_date_added: int = metrics_dictionary.get("max_date_added", 0)
            max_air_date: str = metrics_dictionary.get("max_air_date", "")

            is_fully_watched: bool = (
                total_episodes > 0 and watched_episodes == total_episodes
            )
            if self.controller.filter_out_watched and is_fully_watched:
                continue

            first_air_date: str = (
                str(metadata_dictionary.get("year", ""))
                if is_movie
                else metadata_dictionary.get("first_air_date", "")
            )
            effective_air_date: str = max(max_air_date, first_air_date)
            poster_path_string: str = metadata_dictionary.get("poster_path", "")

            last_played_at = metrics_dictionary.get("last_played_at", 0)
            is_next_up_candidate = False
            if total_episodes > 0 and not is_fully_watched:
                if watched_episodes > 0 or last_played_at > 0:
                    is_next_up_candidate = True

            series_entries.append(
                {
                    "name": series_name,
                    "poster_path": poster_path_string,
                    "date_added": max_date_added,
                    "effective_air_date": effective_air_date,
                    "watched_count": watched_episodes,
                    "total_count": total_episodes,
                    "is_movie": is_movie,
                    "last_played_at": last_played_at,
                    "is_fully_watched": is_fully_watched,
                    "is_next_up_candidate": is_next_up_candidate,
                }
            )

        # Apply sorting logic
        sort_mode_value: str = self.controller.sort_mode
        sort_descending: bool = self.controller.sort_descending
        logger.debug(
            f"Sorting {len(series_entries)} entries by '{sort_mode_value}' "
            f"(descending={sort_descending})"
        )
        if sort_mode_value == "Recently Added":
            series_entries.sort(
                key=lambda entry: entry["date_added"], reverse=not sort_descending
            )
        elif sort_mode_value == "Recently Aired":
            series_entries.sort(
                key=lambda entry: entry["effective_air_date"],
                reverse=not sort_descending,
            )
        elif sort_mode_value == "Next Up":
            if not sort_descending:
                series_entries.sort(
                    key=lambda entry: (
                        not entry["is_next_up_candidate"],
                        -entry["last_played_at"],
                        entry["name"].lower(),
                    )
                )
            else:
                series_entries.sort(
                    key=lambda entry: (
                        not entry["is_next_up_candidate"],
                        entry["last_played_at"],
                        entry["name"].lower(),
                    )
                )
        else:
            series_entries.sort(
                key=lambda entry: entry["name"].lower(), reverse=sort_descending
            )

        current_item_count: int = self.series_list_widget.count()
        target_item_count: int = len(series_entries)
        poster_role: int = int(Qt.ItemDataRole.UserRole) + 1

        # Render items into the responsive icon grid via delta in-place synchronization
        for row_index, entry_record in enumerate(series_entries):
            series_title: str = entry_record["name"]
            watched_count: int = entry_record["watched_count"]
            total_count: int = entry_record["total_count"]
            is_movie: bool = entry_record["is_movie"]
            poster_path_value: str = entry_record["poster_path"]

            if is_movie:
                status_string: str = "Watched" if watched_count > 0 else "Unwatched"
                display_label: str = f"{series_title}\n({status_string})"
            else:
                display_label: str = f"{series_title}\n({watched_count}/{total_count})"

            list_item: Optional[QListWidgetItem] = None
            if row_index < current_item_count:
                list_item = self.series_list_widget.item(row_index)

            if list_item is not None:
                if list_item.text() != display_label:
                    list_item.setText(display_label)
                if list_item.data(Qt.ItemDataRole.UserRole) != series_title:
                    list_item.setData(Qt.ItemDataRole.UserRole, series_title)
                    list_item.setToolTip(series_title)

                stored_poster: Any = list_item.data(poster_role)
                if stored_poster != poster_path_value:
                    list_item.setData(poster_role, poster_path_value)
                    self._assign_item_icon(list_item, poster_path_value)
            else:
                new_item: QListWidgetItem = QListWidgetItem(display_label)
                new_item.setData(Qt.ItemDataRole.UserRole, series_title)
                new_item.setData(poster_role, poster_path_value)
                new_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                new_item.setToolTip(series_title)
                self._assign_item_icon(new_item, poster_path_value)
                self.series_list_widget.addItem(new_item)

        while self.series_list_widget.count() > target_item_count:
            last_row_index: int = self.series_list_widget.count() - 1
            self.series_list_widget.takeItem(last_row_index)

    def _assign_item_icon(
        self, item_target: QListWidgetItem, poster_path_value: str
    ) -> None:
        if poster_path_value in self.cached_icons:
            item_target.setIcon(self.cached_icons[poster_path_value])
            return

        icon_assigned: bool = False
        if poster_path_value:
            poster_path_object = Path(poster_path_value)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    scaled_pixmap = pixmap_instance.scaled(
                        160,
                        220,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    loaded_icon = QIcon(scaled_pixmap)
                    self.cached_icons[poster_path_value] = loaded_icon
                    item_target.setIcon(loaded_icon)
                    icon_assigned = True

        if not icon_assigned:
            if "" not in self.cached_icons:
                fallback_pixmap = QPixmap(160, 220)
                fallback_pixmap.fill(QColor(40, 40, 40))
                self.cached_icons[""] = QIcon(fallback_pixmap)
            item_target.setIcon(self.cached_icons[""])

    @Slot(QListWidgetItem)
    def on_item_clicked(self, item_target: QListWidgetItem) -> None:
        title: str = item_target.data(Qt.ItemDataRole.UserRole)
        if title:
            library_config = config.libraries.get(
                self.controller.current_library_name, {}
            )
            if library_config.get("type") == "movie":
                self.controller.select_movie(title)
            else:
                self.controller.select_series(title)

    def populate_combined_view(self) -> None:
        # Clear existing widgets in combined_scroll_layout
        while self.combined_scroll_layout.count():
            layout_item = self.combined_scroll_layout.takeAt(0)
            if layout_item is not None:
                w = layout_item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()

        enabled_rows = [
            row for row in config.combined_views if row.get("enabled", True)
        ]
        if not enabled_rows:
            empty_label = QLabel(
                "No rows configured or enabled in Combined View settings."
            )
            empty_label.setStyleSheet("font-size: 16px; color: #888888; padding: 20px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.combined_scroll_layout.addWidget(empty_label)
            return

        for row in enabled_rows:
            libraries = row.get("libraries", [])
            row_name = row.get("name", "Row")
            sort_by = row.get("sort_by", "Alphabetical")
            filter_mode = row.get("filter_mode", "All")

            items = db.get_combined_smart_row(libraries, sort_by, filter_mode)
            max_items = row.get("max_items", 20)
            items = items[:max_items]

            if not items:
                continue

            # Create a row container
            row_container = QWidget()
            row_layout = QVBoxLayout(row_container)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            # Header
            header_label = QLabel(f"<b>{row_name}</b>")
            header_label.setStyleSheet("font-size: 18px; color: #2a82da;")
            row_layout.addWidget(header_label)

            # Horizontal List Widget
            h_list = QListWidget()
            h_list.setFlow(QListWidget.Flow.LeftToRight)
            h_list.setWrapping(False)
            h_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            h_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            h_list.setViewMode(QListWidget.ViewMode.IconMode)
            h_list.setIconSize(QSize(120, 165))
            h_list.setGridSize(QSize(145, 210))
            h_list.setMovement(QListWidget.Movement.Static)
            h_list.setResizeMode(QListWidget.ResizeMode.Adjust)
            h_list.setFixedHeight(225)
            h_list.setStyleSheet(
                """
                QListWidget {
                    background-color: transparent;
                    border: none;
                }
                QListWidget::item {
                    border: 1px solid #333333;
                    border-radius: 6px;
                    background-color: #222222;
                    margin-right: 10px;
                }
                QListWidget::item:hover {
                    background-color: #333333;
                    border: 1px solid #2a82da;
                }
                """
            )

            # Populate items
            for media_item in items:
                item_type = media_item.get("type")  # "season", "series", "movie"
                name = media_item.get("name") or media_item.get("series_name") or ""
                poster_path = media_item.get("poster_path") or ""
                watched_count = media_item.get("watched_count", 0)
                total_count = media_item.get("total_count", 0)

                if item_type == "season":
                    season_name = media_item.get("season_name") or ""
                    display_label = (
                        f"{name}\n{season_name} ({watched_count}/{total_count})"
                    )
                elif item_type == "series":
                    display_label = f"{name}\n({watched_count}/{total_count})"
                else:  # movie
                    status_string = "Watched" if watched_count > 0 else "Unwatched"
                    display_label = f"{name}\n({status_string})"

                list_item = QListWidgetItem(display_label)
                list_item.setData(Qt.ItemDataRole.UserRole, media_item)
                list_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                list_item.setToolTip(display_label)

                self._assign_item_icon_with_size(list_item, poster_path, 120, 165)
                h_list.addItem(list_item)

            h_list.itemClicked.connect(self.on_combined_item_clicked)
            row_layout.addWidget(h_list)
            self.combined_scroll_layout.addWidget(row_container)

        self.combined_scroll_layout.addStretch()

    def _assign_item_icon_with_size(
        self,
        item_target: QListWidgetItem,
        poster_path_value: str,
        width: int,
        height: int,
    ) -> None:
        cache_key = f"{poster_path_value}_{width}_{height}"
        if cache_key in self.cached_icons:
            item_target.setIcon(self.cached_icons[cache_key])
            return

        icon_assigned: bool = False
        if poster_path_value:
            poster_path_object = Path(poster_path_value)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    scaled_pixmap = pixmap_instance.scaled(
                        width,
                        height,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    loaded_icon = QIcon(scaled_pixmap)
                    self.cached_icons[cache_key] = loaded_icon
                    item_target.setIcon(loaded_icon)
                    icon_assigned = True

        if not icon_assigned:
            fallback_key = f"fallback_{width}_{height}"
            if fallback_key not in self.cached_icons:
                fallback_pixmap = QPixmap(width, height)
                fallback_pixmap.fill(QColor(40, 40, 40))
                self.cached_icons[fallback_key] = QIcon(fallback_pixmap)
            item_target.setIcon(self.cached_icons[fallback_key])

    @Slot(QListWidgetItem)
    def on_combined_item_clicked(self, item_target: QListWidgetItem) -> None:
        item_data = item_target.data(Qt.ItemDataRole.UserRole)
        if not item_data:
            return

        item_type = item_data.get("type")  # "season", "series", "movie"
        library_name = item_data.get("library_name")

        if library_name:
            self.controller.current_library_name = library_name

        if item_type == "movie":
            movie_name = item_data.get("name")
            if movie_name:
                self.controller.select_library(library_name)
                self.controller.select_movie(movie_name)
        else:
            series_name = item_data.get("name") or item_data.get("series_name")
            if series_name:
                self.controller.select_library(library_name)
                self.controller.select_series(series_name)


class SeriesDetailView(QWidget):
    """
    Presents exhaustive series structure tabs, season tables, and direct execution actions.
    Enforces strict typing and zero-abbreviation naming standard.
    """

    back_requested = Signal()

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.title_label: QLabel = QLabel()
        self.overview_label: QLabel = QLabel()
        self.poster_label: QLabel = QLabel()
        self.seasons_tab_widget: QTabWidget = QTabWidget()
        self._current_series_name: str = ""
        self._season_tables: Dict[str, QTableWidget] = {}

        self._setup_ui()
        self.controller.series_selected.connect(self.populate_series_details)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Header Panel
        header_layout: QHBoxLayout = QHBoxLayout()
        header_layout.setSpacing(20)

        back_button: QPushButton = QPushButton("← Back to Library")
        back_button.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignTop)

        self.poster_label.setFixedSize(180, 260)
        self.poster_label.setStyleSheet(
            "background-color: #222222; border: 1px solid #444444; border-radius: 6px;"
        )
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.poster_label, 0, Qt.AlignmentFlag.AlignTop)

        info_layout: QVBoxLayout = QVBoxLayout()
        info_layout.setSpacing(10)

        self.title_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        self.overview_label.setFont(QFont("Inter", 13))
        self.overview_label.setWordWrap(True)
        self.overview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        info_layout.addWidget(self.overview_label)

        # Actions Panel
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        series_details_button: QPushButton = QPushButton("Series Details")
        series_details_button.setObjectName("seriesDetailsButton")
        series_details_button.clicked.connect(
            lambda: self.controller.series_details_requested.emit(
                self.controller.selected_series_name
            )
        )
        actions_layout.addWidget(series_details_button)

        actions_layout.addStretch()
        info_layout.addLayout(actions_layout)

        header_layout.addLayout(info_layout)
        main_layout.addLayout(header_layout)

        # Horizontal Divider Line
        divider_line: QFrame = QFrame()
        divider_line.setFrameShape(QFrame.Shape.HLine)
        divider_line.setFrameShadow(QFrame.Shadow.Sunken)
        divider_line.setStyleSheet("border-color: #333333;")
        main_layout.addWidget(divider_line)

        # Seasons Table Container Tabs
        main_layout.addWidget(self.seasons_tab_widget)

    @Slot()
    def _on_mark_series_watched(self) -> None:
        if not self.controller.selected_series_name:
            return
        self.controller.mark_series_watched(self.controller.selected_series_name)
        self.populate_series_details(self._current_series_name)

    @Slot(str)
    def _on_mark_season_watched(self, season_name: str) -> None:
        if not self.controller.selected_series_name:
            return
        self.controller.mark_season_watched(
            self.controller.selected_series_name, season_name
        )
        self.populate_series_details(self._current_series_name)

    @Slot(str)
    def populate_series_details(self, series_name: str) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return

        is_opening: bool = self._current_series_name != series_name
        self._current_series_name = series_name
        self._season_tables = {}

        series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )
        metadata_dictionary: Dict[str, Any] = series_record.get("metadata", {})

        metadata_dictionary: Dict[str, Any] = series_record.get("metadata", {})

        series_display_title: str = metadata_dictionary.get("tmdb_name") or series_name
        self.title_label.setText(series_display_title)
        self.overview_label.setText(
            metadata_dictionary.get("overview") or "No overview available."
        )

        # Load dynamic poster fragment
        poster_path_string: str = metadata_dictionary.get("poster_path", "")
        pixmap_assigned: bool = False
        if poster_path_string:
            poster_path_object = Path(poster_path_string)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    self.poster_label.setPixmap(
                        pixmap_instance.scaled(
                            180,
                            260,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    pixmap_assigned = True

        if not pixmap_assigned:
            self.poster_label.clear()
            self.poster_label.setText("No Poster")

        # Clear and repopulate Season Tabs
        self.seasons_tab_widget.clear()
        seasons_dictionary: Dict[str, Any] = series_record.get("seasons", {})

        try:
            sorted_season_names: List[str] = sorted(
                seasons_dictionary.keys(), key=db.natural_sort_key
            )
        except AttributeError:
            sorted_season_names = sorted(seasons_dictionary.keys())

        for season_name in sorted_season_names:
            season_data: Dict[str, Any] = seasons_dictionary.get(season_name, {})
            episodes_list: List[Dict[str, Any]] = season_data.get("episodes", [])

            # Create an explicit QTableWidget layout for absolute robust item targeting under automated tests
            episode_table: QTableWidget = QTableWidget()
            episode_table.setColumnCount(5)
            episode_table.setHorizontalHeaderLabels(
                ["Details", "#", "Episode Title", "Air Date", "Runtime"]
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.ResizeMode.Stretch
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.horizontalHeader().setSectionResizeMode(
                4, QHeaderView.ResizeMode.ResizeToContents
            )
            episode_table.setSelectionBehavior(
                QTableWidget.SelectionBehavior.SelectRows
            )
            episode_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            episode_table.verticalHeader().setVisible(False)
            episode_table.setShowGrid(False)

            episode_table.setRowCount(len(episodes_list))

            def make_cell_clicked_slot(
                episode_list: List[Dict[str, Any]],
            ) -> Callable[[int, int], None]:
                def slot(row: int, col: int) -> None:
                    if col == 2:  # Title column
                        target_path = episode_list[row].get("path", "")
                        if target_path:
                            self.controller.playback_requested.emit(target_path)

                return slot

            episode_table.cellClicked.connect(make_cell_clicked_slot(episodes_list))

            for row_index, episode_record in enumerate(episodes_list):
                tmdb_number_value: Optional[int] = episode_record.get("tmdb_number")
                number_string: str = (
                    str(tmdb_number_value)
                    if tmdb_number_value is not None
                    else str(row_index + 1)
                )

                tmdb_name_value: Optional[str] = episode_record.get("tmdb_name")
                title_string: str = (
                    tmdb_name_value
                    if tmdb_name_value
                    else episode_record.get("name", "Unknown")
                )

                absolute_path: str = episode_record.get("path", "")
                is_watched: bool = bool(episode_record.get("watched", False))
                air_date_string: str = episode_record.get("air_date") or ""
                runtime_value: int = episode_record.get("runtime", 0)
                runtime_string: str = f"{runtime_value} min" if runtime_value else ""

                # Column 0: Details Button
                details_button: QPushButton = QPushButton("Details")
                details_button.setObjectName(f"detailsEpisodeButton_{row_index}")

                def make_details_slot(
                    target_series: str, target_path: str
                ) -> Callable[[], None]:
                    return lambda: self.controller.episode_details_requested.emit(
                        target_series, target_path
                    )

                details_button.clicked.connect(
                    make_details_slot(series_name, absolute_path)
                )

                details_container: QWidget = QWidget()
                details_layout: QHBoxLayout = QHBoxLayout(details_container)
                details_layout.setContentsMargins(2, 2, 2, 2)
                details_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                details_layout.addWidget(details_button)
                episode_table.setCellWidget(row_index, 0, details_container)

                # Determine distinctive color: unwatched blue (#0e5296), watched grey (#888888)
                text_color: QColor = (
                    QColor("#888888") if is_watched else QColor("#0e5296")
                )

                # Render table item entities cleanly
                number_item: QTableWidgetItem = QTableWidgetItem(number_string)
                number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                number_item.setForeground(text_color)
                episode_table.setItem(row_index, 1, number_item)

                title_item: QTableWidgetItem = QTableWidgetItem(title_string)
                title_item.setToolTip("Click to play episode")
                title_item.setForeground(text_color)
                episode_table.setItem(row_index, 2, title_item)

                air_date_item: QTableWidgetItem = QTableWidgetItem(air_date_string)
                air_date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                air_date_item.setForeground(text_color)
                episode_table.setItem(row_index, 3, air_date_item)

                runtime_item: QTableWidgetItem = QTableWidgetItem(runtime_string)
                runtime_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                runtime_item.setForeground(text_color)
                episode_table.setItem(row_index, 4, runtime_item)

            def make_context_menu_slot(
                table: QTableWidget, season: str, episode_list: List[Dict[str, Any]]
            ) -> Callable[[QPoint], None]:
                def show_context_menu(position: QPoint) -> None:
                    item: Optional[QTableWidgetItem] = table.itemAt(position)
                    if not item:
                        return
                    row: int = item.row()
                    episode: Dict[str, Any] = episode_list[row]
                    menu: QMenu = QMenu(table)

                    is_watched: bool = bool(episode.get("watched", False))
                    action_text: str = (
                        "Mark as Unwatched" if is_watched else "Mark as Watched"
                    )
                    toggle_action: QAction = QAction(action_text, table)

                    def handle_toggle() -> None:
                        target_path: str = episode.get("path", "")
                        if target_path:
                            new_status: bool = not is_watched
                            self.controller.mark_episode_watched(
                                target_path, new_status
                            )
                            self.populate_series_details(self._current_series_name)

                    toggle_action.triggered.connect(handle_toggle)
                    menu.addAction(toggle_action)
                    menu.exec(table.viewport().mapToGlobal(position))

                return show_context_menu

            episode_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            episode_table.customContextMenuRequested.connect(
                make_context_menu_slot(episode_table, season_name, episodes_list)
            )

            # Create season_page container to house the table and mark season watched button cleanly
            season_page: QWidget = QWidget()
            season_layout: QVBoxLayout = QVBoxLayout(season_page)
            season_layout.setContentsMargins(0, 5, 0, 0)
            season_layout.setSpacing(10)

            season_actions_layout: QHBoxLayout = QHBoxLayout()
            mark_season_button: QPushButton = QPushButton("Mark season as watched")
            mark_season_button.setObjectName(f"markSeasonWatchedButton_{season_name}")

            def make_season_watched_slot(
                target_season: str,
            ) -> Callable[[], None]:
                return lambda: self._on_mark_season_watched(target_season)

            mark_season_button.clicked.connect(make_season_watched_slot(season_name))
            season_actions_layout.addWidget(mark_season_button)
            season_actions_layout.addStretch()
            season_layout.addLayout(season_actions_layout)

            self._season_tables[season_name] = episode_table
            season_layout.addWidget(episode_table)

            self.seasons_tab_widget.addTab(season_page, season_name)

        if is_opening and sorted_season_names:
            target_tab_index: int = 0
            for index_position, season_name in enumerate(sorted_season_names):
                season_data_record = seasons_dictionary.get(season_name, {})
                has_unwatched: bool = False
                for ep in season_data_record.get("episodes", []):
                    if not ep.get("watched"):
                        has_unwatched = True
                        break
                if has_unwatched:
                    target_tab_index = index_position
                    break
            self.seasons_tab_widget.setCurrentIndex(target_tab_index)

    def trigger_episode_playback_by_row(
        self, season_tab_index: int, row_index: int
    ) -> None:
        """Test Helper triggering playback by simulating a click on the episode title cell."""
        target_widget: Optional[QWidget] = self.seasons_tab_widget.widget(
            season_tab_index
        )
        if target_widget:
            table_target = target_widget.findChild(QTableWidget)
            if table_target:
                table_target.cellClicked.emit(row_index, 2)


class MetadataMatchDialog(QDialog):
    """
    Search modal to retrieve metadata from external matching provider APIs.
    Strictly typesafe with zero abbreviations.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: Controller = controller_instance
        self.search_input: QLineEdit = QLineEdit()
        self.results_table: QTableWidget = QTableWidget()
        self.search_results_list: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Match Metadata: {series_name}")
        self.resize(800, 500)
        self._setup_ui()
        self.search_input.setText(series_name)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Top Form Filters Row
        top_row_layout: QHBoxLayout = QHBoxLayout()
        top_row_layout.setSpacing(10)

        top_row_layout.addWidget(QLabel("Search Query:"))
        self.search_input.setMinimumWidth(250)
        top_row_layout.addWidget(self.search_input)

        search_button: QPushButton = QPushButton("Search")
        search_button.setObjectName("metadataSearchTriggerButton")
        search_button.clicked.connect(self.execute_search)
        top_row_layout.addWidget(search_button)

        main_layout.addLayout(top_row_layout)

        # Search Results Matrix Table
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(
            ["Provider ID", "Series Title", "First Air Date", "Overview"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.results_table)

        # Bottom Form Actions Buttons
        bottom_buttons_layout: QHBoxLayout = QHBoxLayout()
        bottom_buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeMetadataMatchDialogButton")
        cancel_button.clicked.connect(self.reject)
        bottom_buttons_layout.addWidget(cancel_button)

        apply_button: QPushButton = QPushButton("Apply Selected Match")
        apply_button.setObjectName("accentButton")
        apply_button.clicked.connect(self.apply_selected)
        bottom_buttons_layout.addWidget(apply_button)

        main_layout.addLayout(bottom_buttons_layout)

    @Slot()
    def execute_search(self) -> None:
        query_string: str = self.search_input.text().strip()
        if not query_string:
            return

        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.search_results_list = []

        library_config = config.libraries.get(self.controller.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        if is_movie:
            raw_results = tmdb_client.search_movie_full(query_string)
            for item_data in raw_results:
                self.search_results_list.append(
                    {
                        "id": str(item_data.get("id", "")),
                        "tmdb_id": str(item_data.get("id", "")),
                        "name": item_data.get("title", ""),
                        "first_air_date": item_data.get("release_date", ""),
                        "overview": item_data.get("overview", ""),
                        "poster_path": item_data.get("poster_path", ""),
                        "provider": "TMDB",
                    }
                )
        else:
            raw_results = tmdb_client.search_series_full(query_string)
            for item_data in raw_results:
                self.search_results_list.append(
                    {
                        "id": str(item_data.get("id", "")),
                        "tmdb_id": str(item_data.get("id", "")),
                        "name": item_data.get("name", ""),
                        "first_air_date": item_data.get("first_air_date", ""),
                        "overview": item_data.get("overview", ""),
                        "poster_path": item_data.get("poster_path", ""),
                        "provider": "TMDB",
                    }
                )

        self.results_table.setRowCount(len(self.search_results_list))
        for row_index, result_dictionary in enumerate(self.search_results_list):
            id_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["id"])
            self.results_table.setItem(row_index, 0, id_item)

            name_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["name"])
            self.results_table.setItem(row_index, 1, name_item)

            date_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["first_air_date"]
            )
            self.results_table.setItem(row_index, 2, date_item)

            overview_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["overview"]
            )
            self.results_table.setItem(row_index, 3, overview_item)

    @Slot()
    def apply_selected(self) -> None:
        selected_rows: List[int] = [
            item.row() for item in self.results_table.selectedItems()
        ]
        if not selected_rows:
            QMessageBox.warning(
                self, "Selection Required", "Please select a match result first."
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        self.controller.apply_metadata_match(self.series_name, match_record)
        self.accept()


class JellyfinMatchDialog(QDialog):
    """
    Search modal to retrieve series or movie IDs specifically from Jellyfin for watch history correlation.
    Strictly typesafe with zero abbreviations.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: Controller = controller_instance
        self.search_input: QLineEdit = QLineEdit()
        self.results_table: QTableWidget = QTableWidget()
        self.search_results_list: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Match Jellyfin Watch History: {series_name}")
        self.resize(800, 500)
        self._setup_ui()
        self.search_input.setText(series_name)

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Top Form Filters Row
        top_row_layout: QHBoxLayout = QHBoxLayout()
        top_row_layout.setSpacing(10)

        top_row_layout.addWidget(QLabel("Search Query:"))
        self.search_input.setMinimumWidth(250)
        top_row_layout.addWidget(self.search_input)

        search_button: QPushButton = QPushButton("Search Jellyfin")
        search_button.setObjectName("jellyfinSearchTriggerButton")
        search_button.clicked.connect(self.execute_search)
        top_row_layout.addWidget(search_button)

        main_layout.addLayout(top_row_layout)

        # Search Results Matrix Table
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(
            ["Jellyfin ID", "Series Title", "Production Year", "Overview"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.results_table)

        # Bottom Form Actions Buttons
        bottom_buttons_layout: QHBoxLayout = QHBoxLayout()
        bottom_buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeJellyfinMatchDialogButton")
        cancel_button.clicked.connect(self.reject)
        bottom_buttons_layout.addWidget(cancel_button)

        apply_button: QPushButton = QPushButton("Link Selected Match")
        apply_button.setObjectName("accentButton")
        apply_button.clicked.connect(self.apply_selected)
        bottom_buttons_layout.addWidget(apply_button)

        main_layout.addLayout(bottom_buttons_layout)

    @Slot()
    def execute_search(self) -> None:
        query_string: str = self.search_input.text().strip()
        if not query_string:
            return

        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.search_results_list = []

        library_config = config.libraries.get(self.controller.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"

        if is_movie:
            raw_results: List[Dict[str, Any]] = jellyfin_client.search_movie(
                query_string
            )
        else:
            raw_results = jellyfin_client.search_series(query_string)

        for item_data in raw_results:
            production_year_value: str = str(item_data.get("ProductionYear", ""))
            first_air_date_value: str = (
                production_year_value if production_year_value else ""
            )

            self.search_results_list.append(
                {
                    "id": str(item_data.get("Id", "")),
                    "name": item_data.get("Name", ""),
                    "first_air_date": first_air_date_value,
                    "overview": item_data.get("Overview", ""),
                    "provider": "Jellyfin",
                }
            )

        self.results_table.setRowCount(len(self.search_results_list))
        for row_index, result_dictionary in enumerate(self.search_results_list):
            id_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["id"])
            self.results_table.setItem(row_index, 0, id_item)

            name_item: QTableWidgetItem = QTableWidgetItem(result_dictionary["name"])
            self.results_table.setItem(row_index, 1, name_item)

            date_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["first_air_date"]
            )
            self.results_table.setItem(row_index, 2, date_item)

            overview_item: QTableWidgetItem = QTableWidgetItem(
                result_dictionary["overview"]
            )
            self.results_table.setItem(row_index, 3, overview_item)

    @Slot()
    def apply_selected(self) -> None:
        selected_rows: List[int] = [
            item.row() for item in self.results_table.selectedItems()
        ]
        if not selected_rows:
            QMessageBox.warning(
                self, "Selection Required", "Please select a match result first."
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        self.controller.apply_jellyfin_watch_match(self.series_name, match_record)
        self.accept()


class SubtitleSearchDialog(QDialog):
    """
    Search and download subtitles from OpenSubtitles.com.
    """

    def __init__(
        self,
        media_name: str,
        media_record: Dict[str, Any],
        controller_instance: "Controller",
        is_movie: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.media_name = media_name
        self.media_record = media_record
        self.controller = controller_instance
        self.is_movie = is_movie
        self.results: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Search Subtitles: {media_name}")
        self.resize(800, 500)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        self.query_edit = QLineEdit()

        if self.is_movie:
            tmdb_name = self.media_record.get("tmdb_name") or self.media_name
            year = self.media_record.get("year", "")
            default_query = f"{tmdb_name} {year}".strip()
        else:
            series_record = self.controller.cached_library_data.get(self.media_name, {})
            tmdb_name = (
                series_record.get("metadata", {}).get("tmdb_name") or self.media_name
            )
            season_num = self.media_record.get("season_number", 1)
            episode_num = self.media_record.get("tmdb_number", 1)
            default_query = f"{tmdb_name} S{season_num:02d}E{episode_num:02d}"

        self.query_edit.setText(default_query)
        search_layout.addWidget(QLabel("Query:"))
        search_layout.addWidget(self.query_edit)

        self.lang_edit = QLineEdit("en")
        self.lang_edit.setFixedWidth(50)
        search_layout.addWidget(QLabel("Languages:"))
        search_layout.addWidget(self.lang_edit)

        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._on_search_clicked)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(
            ["Language", "Filename", "Rating", "Downloads"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.results_table)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._on_download_clicked)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        buttons.addWidget(self.download_btn)
        layout.addLayout(buttons)

        self.results_table.itemSelectionChanged.connect(
            lambda: self.download_btn.setEnabled(
                len(self.results_table.selectedItems()) > 0
            )
        )

    def _on_search_clicked(self) -> None:
        from .opensubtitles import opensubtitles_client

        query = self.query_edit.text().strip()
        langs = self.lang_edit.text().strip()

        tmdb_id = None
        season_num = None
        episode_num = None

        if self.is_movie:
            tmdb_id_str = self.media_record.get("tmdb_id")
            tmdb_id = (
                int(tmdb_id_str) if tmdb_id_str and str(tmdb_id_str).isdigit() else None
            )
        else:
            series_record = self.controller.cached_library_data.get(self.media_name, {})
            tmdb_id_str = series_record.get("metadata", {}).get("tmdb_id")
            tmdb_id = (
                int(tmdb_id_str) if tmdb_id_str and str(tmdb_id_str).isdigit() else None
            )
            season_num = self.media_record.get("season_number")
            episode_num = self.media_record.get("tmdb_number")

        self.results = opensubtitles_client.search_subtitles(
            query=query if not tmdb_id else None,
            tmdb_id=tmdb_id,
            season_number=season_num,
            episode_number=episode_num,
            languages=langs,
        )

        self.results_table.setRowCount(0)
        for res in self.results:
            attr = res.get("attributes", {})
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            self.results_table.setItem(
                row, 0, QTableWidgetItem(attr.get("language", ""))
            )
            self.results_table.setItem(
                row, 1, QTableWidgetItem(attr.get("release", ""))
            )
            self.results_table.setItem(
                row, 2, QTableWidgetItem(str(attr.get("ratings", 0)))
            )
            self.results_table.setItem(
                row, 3, QTableWidgetItem(str(attr.get("download_count", 0)))
            )

        if not self.results:
            QMessageBox.information(self, "Search", "No subtitles found.")

    def _on_download_clicked(self) -> None:
        from .opensubtitles import opensubtitles_client

        selected_row = self.results_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.results):
            return

        subtitle_data = self.results[selected_row]
        file_id = (
            subtitle_data.get("attributes", {}).get("files", [{}])[0].get("file_id")
        )
        if not file_id:
            QMessageBox.warning(self, "Download", "No file ID found for this subtitle.")
            return

        download_url = opensubtitles_client.get_download_link(file_id)
        if not download_url:
            QMessageBox.warning(
                self,
                "Download",
                "Could not get download link. Check your credentials in Settings.",
            )
            return

        content = opensubtitles_client.download_subtitle(download_url)
        if not content:
            QMessageBox.warning(
                self, "Download", "Failed to download subtitle content."
            )
            return

        # Save next to video file
        video_path = Path(self.media_record.get("path", ""))
        if not video_path.exists():
            QMessageBox.warning(self, "Download", "Video file not found on disk.")
            return

        lang = subtitle_data.get("attributes", {}).get("language", "en")
        sub_path = video_path.with_suffix(f".{lang}.srt")

        try:
            with open(sub_path, "wb") as f:
                f.write(content)
            QMessageBox.information(self, "Download", f"Subtitle saved to:\n{sub_path}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Download", f"Error saving subtitle: {e}")


class EpisodeDetailsDialog(QDialog):
    """
    Comprehensive multi-tab interface for viewing/editing episode metadata
    and inspecting technical file characteristics.
    """

    def __init__(
        self,
        series_name: str,
        episode_path: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.episode_path: str = episode_path
        self.controller: Controller = controller_instance
        self.episode_record: Dict[str, Any] = {}

        # UI Elements for Tab 1 (Metadata)
        self.title_edit: QLineEdit = QLineEdit()
        self.runtime_edit: QLineEdit = QLineEdit()
        self.air_date_edit: QLineEdit = QLineEdit()
        self.locked_checkbox: QCheckBox = QCheckBox("Locked Metadata")

        # UI Elements for Tab 2 (File Info)
        self.path_label: QLabel = QLabel()
        self.size_label: QLabel = QLabel()
        self.type_label: QLabel = QLabel()
        self.codec_label: QLabel = QLabel()
        self.resolution_label: QLabel = QLabel()
        self.audio_list: QListWidget = QListWidget()
        self.subtitle_list: QListWidget = QListWidget()
        self.external_sub_list: QListWidget = QListWidget()
        self.merge_button: QPushButton = QPushButton(
            "Combine Subtitles into Video File"
        )

        self.setWindowTitle(f"Episode Details: {Path(episode_path).name}")
        self.resize(700, 600)
        self._load_data()
        self._setup_ui()
        self._refresh_file_info()

    def _load_data(self) -> None:
        series_data = self.controller.cached_library_data.get(self.series_name, {})
        for season in series_data.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                if ep.get("path") == self.episode_path:
                    self.episode_record = ep
                    break
            if self.episode_record:
                break

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._create_metadata_tab(), "Metadata")
        tabs.addTab(self._create_file_info_tab(), "File Information")
        main_layout.addWidget(tabs)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Changes")
        save_btn.setObjectName("accentButton")
        save_btn.clicked.connect(self._on_save_clicked)
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(save_btn)
        main_layout.addLayout(buttons_layout)

    def _create_metadata_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)

        form = QGridLayout()
        form.addWidget(QLabel("Title:"), 0, 0)
        form.addWidget(self.title_edit, 0, 1)

        form.addWidget(QLabel("Runtime (min):"), 1, 0)
        form.addWidget(self.runtime_edit, 1, 1)

        form.addWidget(QLabel("Air Date:"), 2, 0)
        form.addWidget(self.air_date_edit, 2, 1)

        layout.addLayout(form)
        layout.addWidget(self.locked_checkbox)

        refresh_btn = QPushButton("Refresh Metadata")
        refresh_btn.setObjectName("refreshMetadataButton")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(refresh_btn)

        search_btn = QPushButton("Search TMDB for this Episode...")
        search_btn.clicked.connect(self._on_search_tmdb_clicked)
        layout.addWidget(search_btn)

        embed_btn = QPushButton("Embed Metadata into Video File")
        embed_btn.clicked.connect(self._on_embed_clicked)
        layout.addWidget(embed_btn)

        layout.addStretch()

        # Populate
        self.title_edit.setText(
            self.episode_record.get("tmdb_name")
            or self.episode_record.get("name")
            or ""
        )
        self.runtime_edit.setText(str(self.episode_record.get("runtime") or ""))
        self.air_date_edit.setText(self.episode_record.get("air_date") or "")
        self.locked_checkbox.setChecked(
            bool(self.episode_record.get("locked_metadata", False))
        )

        return widget

    def _create_file_info_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Path:</b>"), 0, 0)
        self.path_label.setWordWrap(True)
        grid.addWidget(self.path_label, 0, 1)

        grid.addWidget(QLabel("<b>Size:</b>"), 1, 0)
        grid.addWidget(self.size_label, 1, 1)

        grid.addWidget(QLabel("<b>Type:</b>"), 2, 0)
        grid.addWidget(self.type_label, 2, 1)

        grid.addWidget(QLabel("<b>Codec:</b>"), 3, 0)
        grid.addWidget(self.codec_label, 3, 1)

        grid.addWidget(QLabel("<b>Resolution:</b>"), 4, 0)
        grid.addWidget(self.resolution_label, 4, 1)

        layout.addLayout(grid)

        layout.addWidget(QLabel("<b>Internal Audio Tracks:</b>"))
        self.audio_list.setMaximumHeight(100)
        layout.addWidget(self.audio_list)

        layout.addWidget(QLabel("<b>Internal Subtitle Tracks:</b>"))
        self.subtitle_list.setMaximumHeight(100)
        layout.addWidget(self.subtitle_list)

        layout.addWidget(QLabel("<b>Detected External Subtitles:</b>"))
        self.external_sub_list.setMaximumHeight(100)
        layout.addWidget(self.external_sub_list)

        self.merge_button.setObjectName("accentButton")
        self.merge_button.clicked.connect(self._on_merge_clicked)
        layout.addWidget(self.merge_button)

        osub_btn = QPushButton("Search OpenSubtitles.com for Subtitles...")
        osub_btn.clicked.connect(self._on_search_osub_clicked)
        layout.addWidget(osub_btn)

        layout.addStretch()

        return widget

    def _refresh_file_info(self) -> None:
        from .scanner import get_detailed_file_info, SUBTITLE_EXTENSIONS

        info = get_detailed_file_info(self.episode_path)

        self.path_label.setText(self.episode_path)
        size_mb = info["size_bytes"] / (1024 * 1024)
        self.size_label.setText(f"{size_mb:.2f} MB")
        self.type_label.setText(info["video_type"])
        self.codec_label.setText(info.get("video_codec", "Unknown"))
        self.resolution_label.setText(info["resolution"])

        self.audio_list.clear()
        for track in info["audio_tracks"]:
            self.audio_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        self.subtitle_list.clear()
        for track in info["subtitle_tracks"]:
            self.subtitle_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        # Detect external subtitles
        self.external_sub_list.clear()
        ext_subs = []
        parent_dir = Path(self.episode_path).parent
        stem = Path(self.episode_path).stem
        if parent_dir.exists():
            for f in parent_dir.iterdir():
                if f.suffix.lower() in SUBTITLE_EXTENSIONS and f.stem.startswith(stem):
                    ext_subs.append(str(f.absolute()))
                    self.external_sub_list.addItem(f.name)

        self.merge_button.setEnabled(len(ext_subs) > 0)
        self._ext_subs = ext_subs

    @Slot()
    def _on_save_clicked(self) -> None:
        metadata = {
            "tmdb_name": self.title_edit.text(),
            "air_date": self.air_date_edit.text(),
            "locked_metadata": self.locked_checkbox.isChecked(),
        }
        try:
            metadata["runtime"] = (
                int(self.runtime_edit.text()) if self.runtime_edit.text() else 0
            )
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Runtime must be a number.")
            return

        self.controller.update_episode_metadata(
            self.series_name, self.episode_path, metadata
        )
        self.accept()

    @Slot()
    def _on_search_tmdb_clicked(self) -> None:
        # Trigger the existing EpisodeMatchDialog
        self.controller.episode_metadata_dialog_requested.emit(
            self.series_name, self.episode_path
        )
        # Close this one as the metadata might change
        self.reject()

    @Slot()
    def _on_refresh_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Refresh",
            "Are you sure you want to refresh metadata for this episode from TMDB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.refresh_episode_metadata(
                self.series_name, self.episode_path
            )
            # Reload data and update UI fields
            self._load_data()
            self.title_edit.setText(
                self.episode_record.get("tmdb_name")
                or self.episode_record.get("name")
                or ""
            )
            self.runtime_edit.setText(str(self.episode_record.get("runtime") or ""))
            self.air_date_edit.setText(self.episode_record.get("air_date") or "")
            self.locked_checkbox.setChecked(
                bool(self.episode_record.get("locked_metadata", False))
            )

    @Slot()
    def _on_embed_clicked(self) -> None:
        """Collects current UI metadata and triggers embedding."""
        metadata = {
            "title": self.title_edit.text(),
            "show": self.series_name,
            "episode_id": str(self.episode_record.get("tmdb_number") or ""),
            "date": self.air_date_edit.text(),
        }

        confirm = QMessageBox.question(
            self,
            "Confirm Embedding",
            "This will rewrite the video container to embed the metadata. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.embed_metadata(self.episode_path, metadata)
            self.accept()

    @Slot()
    def _on_merge_clicked(self) -> None:
        if not self._ext_subs:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Merge",
            f"This will merge {len(self._ext_subs)} subtitle files into the video container. "
            "The original video file will be replaced. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.merge_subtitles(self.episode_path, self._ext_subs)
            self.accept()

    @Slot()
    def _on_search_osub_clicked(self) -> None:
        dialog = SubtitleSearchDialog(
            self.series_name,
            self.episode_record,
            self.controller,
            is_movie=False,
            parent=self,
        )
        if dialog.exec():
            self._refresh_file_info()


class MovieDetailsDialog(QDialog):
    """
    Comprehensive multi-tab interface for viewing/editing movie metadata
    and inspecting technical file characteristics.
    """

    def __init__(
        self,
        movie_name: str,
        movie_path: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.movie_name: str = movie_name
        self.movie_path: str = movie_path
        self.controller: Controller = controller_instance
        self.movie_record: Dict[str, Any] = self.controller.cached_library_data.get(
            movie_name, {}
        )

        # UI Elements for Tab 1 (Metadata)
        self.title_edit: QLineEdit = QLineEdit()
        self.runtime_edit: QLineEdit = QLineEdit()
        self.year_edit: QLineEdit = QLineEdit()
        self.rating_edit: QLineEdit = QLineEdit()
        self.genre_edit: QLineEdit = QLineEdit()
        self.locked_checkbox: QCheckBox = QCheckBox(
            "Lock Metadata (Prevents automatic updates during scans)"
        )
        self.locked_checkbox.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.locked_checkbox.setStyleSheet("color: #ff9800;")

        # UI Elements for Tab 2 (File Info)
        self.path_label: QLabel = QLabel()
        self.size_label: QLabel = QLabel()
        self.type_label: QLabel = QLabel()
        self.codec_label: QLabel = QLabel()
        self.resolution_label: QLabel = QLabel()
        self.audio_list: QListWidget = QListWidget()
        self.subtitle_list: QListWidget = QListWidget()
        self.external_sub_list: QListWidget = QListWidget()
        self.merge_button: QPushButton = QPushButton(
            "Combine Subtitles into Video File"
        )

        self.setWindowTitle(f"Movie Details: {Path(movie_path).name}")
        self.resize(700, 650)
        self._setup_ui()
        self._refresh_file_info()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._create_metadata_tab(), "Metadata")
        tabs.addTab(self._create_file_info_tab(), "File Information")
        main_layout.addWidget(tabs)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save Changes")
        save_btn.setObjectName("accentButton")
        save_btn.clicked.connect(self._on_save_clicked)
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(save_btn)
        main_layout.addLayout(buttons_layout)

    def _create_metadata_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)

        form = QGridLayout()
        form.addWidget(QLabel("Title:"), 0, 0)
        form.addWidget(self.title_edit, 0, 1)

        form.addWidget(QLabel("Runtime (min):"), 1, 0)
        form.addWidget(self.runtime_edit, 1, 1)

        form.addWidget(QLabel("Release Year:"), 2, 0)
        form.addWidget(self.year_edit, 2, 1)

        form.addWidget(QLabel("Rating:"), 3, 0)
        form.addWidget(self.rating_edit, 3, 1)

        form.addWidget(QLabel("Genre:"), 4, 0)
        form.addWidget(self.genre_edit, 4, 1)

        layout.addLayout(form)
        layout.addWidget(self.locked_checkbox)

        search_btn = QPushButton("Search TMDB for this Movie...")
        search_btn.clicked.connect(self._on_search_tmdb_clicked)
        layout.addWidget(search_btn)

        refresh_btn = QPushButton("Refresh Movie Metadata")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(refresh_btn)

        embed_btn = QPushButton("Embed Metadata into Video File")
        embed_btn.clicked.connect(self._on_embed_clicked)
        layout.addWidget(embed_btn)

        layout.addStretch()

        # Populate
        self.title_edit.setText(
            self.movie_record.get("tmdb_name") or self.movie_record.get("name") or ""
        )
        self.runtime_edit.setText(str(self.movie_record.get("runtime") or ""))
        self.year_edit.setText(str(self.movie_record.get("year") or ""))
        self.rating_edit.setText(self.movie_record.get("rating") or "")
        self.genre_edit.setText(self.movie_record.get("genre") or "")
        self.locked_checkbox.setChecked(
            bool(self.movie_record.get("locked_metadata", False))
        )

        return widget

    def _create_file_info_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Path:</b>"), 0, 0)
        self.path_label.setWordWrap(True)
        grid.addWidget(self.path_label, 0, 1)

        grid.addWidget(QLabel("<b>Size:</b>"), 1, 0)
        grid.addWidget(self.size_label, 1, 1)

        grid.addWidget(QLabel("<b>Type:</b>"), 2, 0)
        grid.addWidget(self.type_label, 2, 1)

        grid.addWidget(QLabel("<b>Codec:</b>"), 3, 0)
        grid.addWidget(self.codec_label, 3, 1)

        grid.addWidget(QLabel("<b>Resolution:</b>"), 4, 0)
        grid.addWidget(self.resolution_label, 4, 1)

        layout.addLayout(grid)

        layout.addWidget(QLabel("<b>Internal Audio Tracks:</b>"))
        self.audio_list.setMaximumHeight(100)
        layout.addWidget(self.audio_list)

        layout.addWidget(QLabel("<b>Internal Subtitle Tracks:</b>"))
        self.subtitle_list.setMaximumHeight(100)
        layout.addWidget(self.subtitle_list)

        layout.addWidget(QLabel("<b>Detected External Subtitles:</b>"))
        self.external_sub_list.setMaximumHeight(100)
        layout.addWidget(self.external_sub_list)

        self.merge_button.setObjectName("accentButton")
        self.merge_button.clicked.connect(self._on_merge_clicked)
        layout.addWidget(self.merge_button)

        osub_btn = QPushButton("Search OpenSubtitles.com for Subtitles...")
        osub_btn.clicked.connect(self._on_search_osub_clicked)
        layout.addWidget(osub_btn)

        layout.addStretch()

        return widget

    def _refresh_file_info(self) -> None:
        from .scanner import get_detailed_file_info, SUBTITLE_EXTENSIONS

        info = get_detailed_file_info(self.movie_path)

        self.path_label.setText(self.movie_path)
        size_mb = info["size_bytes"] / (1024 * 1024)
        self.size_label.setText(f"{size_mb:.2f} MB")
        self.type_label.setText(info["video_type"])
        self.codec_label.setText(info.get("video_codec", "Unknown"))
        self.resolution_label.setText(info["resolution"])

        self.audio_list.clear()
        for track in info["audio_tracks"]:
            self.audio_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        self.subtitle_list.clear()
        for track in info["subtitle_tracks"]:
            self.subtitle_list.addItem(
                f"Track {track['index']}: {track['codec']} ({track['language']}) {track['title']}"
            )

        # Detect external subtitles
        self.external_sub_list.clear()
        ext_subs = []
        parent_dir = Path(self.movie_path).parent
        stem = Path(self.movie_path).stem
        if parent_dir.exists():
            for f in parent_dir.iterdir():
                if f.suffix.lower() in SUBTITLE_EXTENSIONS and f.stem.startswith(stem):
                    ext_subs.append(str(f.absolute()))
                    self.external_sub_list.addItem(f.name)

        self.merge_button.setEnabled(len(ext_subs) > 0)
        self._ext_subs = ext_subs

    @Slot()
    def _on_save_clicked(self) -> None:
        metadata = {
            "tmdb_name": self.title_edit.text(),
            "rating": self.rating_edit.text(),
            "genre": self.genre_edit.text(),
            "locked_metadata": self.locked_checkbox.isChecked(),
        }
        try:
            metadata["runtime"] = (
                int(self.runtime_edit.text()) if self.runtime_edit.text() else 0
            )
            metadata["year"] = (
                int(self.year_edit.text()) if self.year_edit.text() else 0
            )
        except ValueError:
            QMessageBox.warning(
                self, "Invalid Input", "Runtime and Year must be numbers."
            )
            return

        self.controller.update_movie_metadata(
            self.movie_name, self.movie_path, metadata
        )
        self.accept()

    @Slot()
    def _on_search_tmdb_clicked(self) -> None:
        # Trigger the existing EpisodeMatchDialog (which handles movies too)
        self.controller.episode_metadata_dialog_requested.emit(
            self.movie_name, self.movie_path
        )
        self.reject()

    @Slot()
    def _on_refresh_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Refresh",
            f"Are you sure you want to refresh metadata for '{self.movie_name}' from TMDB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.trigger_series_refresh(self.movie_name)
            self.accept()

    @Slot()
    def _on_embed_clicked(self) -> None:
        """Collects current UI metadata and triggers embedding."""
        metadata = {
            "title": self.title_edit.text(),
            "date": self.year_edit.text(),
            "genre": self.genre_edit.text(),
        }

        confirm = QMessageBox.question(
            self,
            "Confirm Embedding",
            "This will rewrite the video container to embed the metadata. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.embed_metadata(self.movie_path, metadata)
            self.accept()

    @Slot()
    def _on_merge_clicked(self) -> None:
        if not self._ext_subs:
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Merge",
            f"This will merge {len(self._ext_subs)} subtitle files into the video container. "
            "The original video file will be replaced. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.merge_subtitles(self.movie_path, self._ext_subs)
            self.accept()

    @Slot()
    def _on_search_osub_clicked(self) -> None:
        dialog = SubtitleSearchDialog(
            self.movie_name,
            self.movie_record,
            self.controller,
            is_movie=True,
            parent=self,
        )
        if dialog.exec():
            self._refresh_file_info()


class SeriesDetailsDialog(QDialog):
    """
    Comprehensive dialog for managing series-level metadata and bulk actions.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: Controller = controller_instance
        self.series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            series_name, {}
        )

        self.setWindowTitle(f"Series Details: {series_name}")
        self.resize(700, 550)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        form = QFormLayout()
        self.name_edit = QLineEdit(self.series_name)
        form.addRow("Series Name:", self.name_edit)

        # Paths
        paths = set()
        for season in self.series_record.get("seasons", {}).values():
            for ep in season.get("episodes", []):
                p = ep.get("path", "")
                if p:
                    # Attempt to find the series folder (2 levels up from episode file)
                    try:
                        paths.add(str(Path(p).parent.parent))
                    except Exception:
                        paths.add(str(Path(p).parent))

        paths_label = QLabel("\n".join(sorted(list(paths))))
        paths_label.setWordWrap(True)
        form.addRow("Series Path(s):", paths_label)

        # Jellyfin Status
        metadata = self.series_record.get("metadata", {})
        jellyfin_id = metadata.get("jellyfin_id", "")
        self.jellyfin_status_label = QLabel()
        self.jellyfin_status_label.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        if jellyfin_client.is_configured():
            if jellyfin_id:
                self.jellyfin_status_label.setText("Jellyfin Sync: Matched")
                self.jellyfin_status_label.setStyleSheet("color: #43a047;")
            else:
                self.jellyfin_status_label.setText("⚠️ Jellyfin Sync: Not Matched")
                self.jellyfin_status_label.setStyleSheet("color: #e53935;")
        else:
            self.jellyfin_status_label.setVisible(False)
        form.addRow("Sync Status:", self.jellyfin_status_label)

        self.locked_checkbox = QCheckBox(
            "Lock Metadata (Prevents automatic updates during scans)"
        )
        self.locked_checkbox.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.locked_checkbox.setStyleSheet("color: #ff9800;")
        library_config = config.libraries.get(self.controller.current_library_name, {})
        is_movie = library_config.get("type", "tv") == "movie"
        if is_movie:
            is_locked = bool(self.series_record.get("locked_metadata", False))
        else:
            is_locked = bool(metadata.get("locked_metadata", False))
        self.locked_checkbox.setChecked(is_locked)
        form.addRow("Metadata Lock:", self.locked_checkbox)

        layout.addLayout(form)

        # Buttons
        match_meta_btn = QPushButton("Match Series Metadata...")
        match_meta_btn.clicked.connect(self._on_match_meta_clicked)
        layout.addWidget(match_meta_btn)

        refresh_btn = QPushButton("Refresh Series Metadata")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(refresh_btn)

        match_jellyfin_btn = QPushButton("Match Jellyfin Watch History...")
        match_jellyfin_btn.clicked.connect(self._on_match_jellyfin_clicked)
        if not jellyfin_client.is_configured():
            match_jellyfin_btn.setEnabled(False)
        layout.addWidget(match_jellyfin_btn)

        rename_btn = QPushButton("Rename Files...")
        rename_btn.clicked.connect(self._on_rename_clicked)
        layout.addWidget(rename_btn)

        embed_btn = QPushButton("Embed Metadata into All Video Files")
        embed_btn.setObjectName("accentButton")
        embed_btn.clicked.connect(self._on_embed_clicked)
        layout.addWidget(embed_btn)

        mark_watched_btn = QPushButton("Mark Series as Watched")
        mark_watched_btn.clicked.connect(self._on_mark_watched_clicked)
        layout.addWidget(mark_watched_btn)

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save_clicked)
        buttons.addWidget(close_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

    def _on_match_meta_clicked(self) -> None:
        self.controller.metadata_dialog_requested.emit(self.series_name)
        self.accept()

    def _on_refresh_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Refresh",
            f"Are you sure you want to refresh metadata for '{self.series_name}' from TMDB?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.trigger_series_refresh(self.series_name)
            self.accept()

    def _on_match_jellyfin_clicked(self) -> None:
        self.controller.jellyfin_dialog_requested.emit(self.series_name)
        self.accept()

    def _on_rename_clicked(self) -> None:
        self.controller.rename_dialog_requested.emit(self.series_name)
        self.accept()

    def _on_embed_clicked(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirm Bulk Embedding",
            "This will rewrite the video containers for ALL episodes in this series. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.controller.embed_metadata_series(self.series_name)
            self.accept()

    def _on_mark_watched_clicked(self) -> None:
        self.controller.mark_series_watched(self.series_name)
        self.accept()

    def _on_save_clicked(self) -> None:
        new_name = self.name_edit.text()
        locked = self.locked_checkbox.isChecked()
        if new_name != self.series_name:
            self.controller.update_series_name(self.series_name, new_name)
        self.controller.toggle_series_lock(
            new_name if new_name != self.series_name else self.series_name, locked
        )
        self.accept()


class EpisodeMatchDialog(QDialog):
    """
    Modal dialog allowing users to match metadata on TMDB for an individual episode of a show.
    Conforms strictly to zero-abbreviation variable naming and strict static typing standards.
    """

    def __init__(
        self,
        series_name: str,
        episode_path: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.episode_path: str = episode_path
        self.controller: Controller = controller_instance
        self.season_selector: QComboBox = QComboBox()
        self.results_table: QTableWidget = QTableWidget()
        self.search_results_list: List[Dict[str, Any]] = []

        series_record: Dict[str, Any] = self.controller.cached_library_data.get(
            self.series_name, {}
        )
        metadata_dictionary: Dict[str, Any] = series_record.get("metadata", {})
        self.tmdb_identifier: str = metadata_dictionary.get("tmdb_identifier", "")

        if not self.tmdb_identifier:
            matched_series = tmdb_client.search_series(self.series_name)
            if matched_series:
                self.tmdb_identifier = str(matched_series.get("id", ""))

        self.setWindowTitle(f"Match Episode Metadata: {series_name}")
        self.resize(900, 500)
        self._setup_ui()
        self._populate_seasons()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        top_row_layout: QHBoxLayout = QHBoxLayout()
        top_row_layout.setSpacing(10)
        top_row_layout.addWidget(QLabel("TMDB Season:"))
        self.season_selector.setMinimumWidth(200)
        self.season_selector.currentTextChanged.connect(self.on_season_changed)
        top_row_layout.addWidget(self.season_selector)
        top_row_layout.addStretch()
        main_layout.addLayout(top_row_layout)

        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(
            ["Episode #", "Episode Title", "Air Date", "Overview"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.results_table)

        bottom_buttons_layout: QHBoxLayout = QHBoxLayout()
        bottom_buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeEpisodeMatchDialogButton")
        cancel_button.clicked.connect(self.reject)
        bottom_buttons_layout.addWidget(cancel_button)

        apply_button: QPushButton = QPushButton("Apply Selected Match")
        apply_button.setObjectName("accentButton")
        apply_button.clicked.connect(self.apply_selected)
        bottom_buttons_layout.addWidget(apply_button)

        main_layout.addLayout(bottom_buttons_layout)

    def _populate_seasons(self) -> None:
        seasons_list: List[Dict[str, Any]] = []
        if self.tmdb_identifier:
            seasons_list = tmdb_client.get_seasons(self.tmdb_identifier)

        self.season_selector.blockSignals(True)
        for season_dictionary in seasons_list:
            season_number_value: int = season_dictionary.get("season_number", 0)
            season_name_value: str = (
                season_dictionary.get("name") or f"Season {season_number_value}"
            )
            self.season_selector.addItem(season_name_value, season_number_value)
        self.season_selector.blockSignals(False)

        if self.season_selector.count() > 0:
            self.on_season_changed(self.season_selector.currentText())

    @Slot(str)
    def on_season_changed(self, season_text: str) -> None:
        if not self.tmdb_identifier or self.season_selector.count() == 0:
            return

        season_number_value: Any = self.season_selector.currentData()
        if season_number_value is None:
            return

        season_number_int: int = int(season_number_value)
        self.results_table.clearContents()
        self.results_table.setRowCount(0)
        self.search_results_list = []

        episodes_data: List[Dict[str, Any]] = tmdb_client.get_episodes(
            self.tmdb_identifier, season_number_int
        )

        for episode_dictionary in episodes_data:
            episode_identifier_str: str = str(episode_dictionary.get("id", ""))
            episode_number_int: int = episode_dictionary.get("episode_number", 0)
            episode_name_str: str = episode_dictionary.get("name", "")
            air_date_str: str = episode_dictionary.get("air_date", "")
            overview_str: str = episode_dictionary.get("overview", "")
            runtime_int: int = episode_dictionary.get("runtime", 0)

            self.search_results_list.append(
                {
                    "id": episode_identifier_str,
                    "episode_number": episode_number_int,
                    "name": episode_name_str,
                    "air_date": air_date_str,
                    "overview": overview_str,
                    "runtime": runtime_int,
                }
            )

        self.results_table.setRowCount(len(self.search_results_list))
        for row_index, record_dictionary in enumerate(self.search_results_list):
            number_item: QTableWidgetItem = QTableWidgetItem(
                str(record_dictionary["episode_number"])
            )
            number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results_table.setItem(row_index, 0, number_item)

            name_item: QTableWidgetItem = QTableWidgetItem(record_dictionary["name"])
            self.results_table.setItem(row_index, 1, name_item)

            date_item: QTableWidgetItem = QTableWidgetItem(
                record_dictionary["air_date"]
            )
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results_table.setItem(row_index, 2, date_item)

            overview_item: QTableWidgetItem = QTableWidgetItem(
                record_dictionary["overview"]
            )
            self.results_table.setItem(row_index, 3, overview_item)

    @Slot()
    def apply_selected(self) -> None:
        selected_rows: List[int] = [
            item.row() for item in self.results_table.selectedItems()
        ]
        if not selected_rows:
            QMessageBox.warning(
                self,
                "Selection Required",
                "Please select an episode match result first.",
            )
            return

        target_row_index: int = selected_rows[0]
        match_record: Dict[str, Any] = self.search_results_list[target_row_index]
        self.controller.apply_episode_metadata_match(
            self.series_name, self.episode_path, match_record
        )
        self.accept()


class RenamePreviewDialog(QDialog):
    """
    Dialog displaying generated file renaming mapping previews for consistent file hygiene.
    Conforms strictly to standard static typing and naming constraints.
    """

    def __init__(
        self,
        series_name: str,
        controller_instance: Controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.series_name: str = series_name
        self.controller: Controller = controller_instance
        self.template_input: QLineEdit = QLineEdit()
        self.preview_table: QTableWidget = QTableWidget()
        self.preview_results_list: List[Dict[str, Any]] = []

        self.setWindowTitle(f"Rename Preview: {series_name}")
        self.resize(900, 600)
        self._setup_ui()
        self.template_input.setText(
            "{SeriesTitle} S{SeasonNumber:02}E{EpisodeNumber:02} - {EpisodeTitle}"
        )
        self.generate_preview()

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Template Header Box
        template_layout: QHBoxLayout = QHBoxLayout()
        template_layout.setSpacing(10)

        template_layout.addWidget(QLabel("Naming Template:"))
        self.template_input.setMinimumWidth(400)
        template_layout.addWidget(self.template_input)

        preview_trigger_button: QPushButton = QPushButton("Update Preview")
        preview_trigger_button.setObjectName("renamePreviewTriggerButton")
        preview_trigger_button.clicked.connect(self.generate_preview)
        template_layout.addWidget(preview_trigger_button)

        main_layout.addLayout(template_layout)

        # Preview Data Table
        self.preview_table.setColumnCount(2)
        self.preview_table.setHorizontalHeaderLabels(
            ["Original Target Filename", "New Standardized Filename"]
        )
        self.preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.preview_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.preview_table)

        # Action Execution Toolbar
        actions_layout: QHBoxLayout = QHBoxLayout()
        actions_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Cancel")
        cancel_button.setObjectName("closeRenameFilesDialogButton")
        cancel_button.clicked.connect(self.reject)
        actions_layout.addWidget(cancel_button)

        apply_renames_button: QPushButton = QPushButton("Apply Renames")
        apply_renames_button.setObjectName("accentButton")
        apply_renames_button.clicked.connect(self.apply_renames)
        actions_layout.addWidget(apply_renames_button)

        main_layout.addLayout(actions_layout)

    @Slot()
    def generate_preview(self) -> None:
        template_string: str = self.template_input.text().strip()
        if (
            not template_string
            or self.series_name not in self.controller.cached_library_data
        ):
            return

        series_dictionary: Dict[str, Any] = self.controller.cached_library_data[
            self.series_name
        ]
        from .renamer import get_rename_preview

        self.preview_results_list = get_rename_preview(
            series_dictionary, template_string
        )

        self.preview_table.setRowCount(len(self.preview_results_list))
        for row_index, preview_dictionary in enumerate(self.preview_results_list):
            old_name_str: str = preview_dictionary.get("old_name", "")
            if not old_name_str and "old_path" in preview_dictionary:
                old_name_str = Path(preview_dictionary["old_path"]).name

            old_item: QTableWidgetItem = QTableWidgetItem(old_name_str)
            self.preview_table.setItem(row_index, 0, old_item)

            new_item: QTableWidgetItem = QTableWidgetItem(
                preview_dictionary.get("new_name", "")
            )
            self.preview_table.setItem(row_index, 1, new_item)

    @Slot()
    def apply_renames(self) -> None:
        if not self.preview_results_list:
            return

        self.controller.apply_rename_batch(self.preview_results_list)
        self.accept()


class SettingsDialog(QDialog):
    """
    Configuration modal encapsulating system directory management and operational behaviors.
    """

    def __init__(
        self,
        controller_instance: Optional[Controller] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.controller: Optional[Controller] = controller_instance
        self.setWindowTitle("Application Configuration")
        self.resize(800, 700)

        self.force_refresh_checkbox: QCheckBox = QCheckBox(
            "Force refresh metadata (update/search TMDB)"
        )
        self.global_progress_bar: SegmentedProgressBar = SegmentedProgressBar()
        self.global_progress_bar.setVisible(False)
        self.scan_progress_tree: ScanProgressTree = ScanProgressTree()
        self.scan_progress_tree.setVisible(False)
        if self.controller is not None:
            self.controller.global_progress_updated.connect(self._on_global_progress)
            self.controller.detail_progress_updated.connect(self._on_detail_progress)

        self.jellyfin_url_input: QLineEdit = QLineEdit()
        self.jellyfin_key_input: QLineEdit = QLineEdit()
        self.tmdb_key_input: QLineEdit = QLineEdit()
        self.opensubtitles_username_input: QLineEdit = QLineEdit()
        self.opensubtitles_password_input: QLineEdit = QLineEdit()
        self.opensubtitles_api_key_input: QLineEdit = QLineEdit()

        self.staged_libraries: Dict[str, Dict[str, Any]] = {}
        self.library_name_input: QLineEdit = QLineEdit()
        self.library_type_input: QComboBox = QComboBox()
        self.library_selector: QComboBox = QComboBox()
        self.directory_list_widget: QListWidget = QListWidget()

        self.use_embedded_checkbox: QCheckBox = QCheckBox(
            "Use Embedded Video Player (uncheck for Standalone VLC)"
        )
        self.enable_caching_checkbox: QCheckBox = QCheckBox(
            "Enable Media Stream Caching"
        )
        self.enable_hw_accel_checkbox: QCheckBox = QCheckBox(
            "Enable Hardware Acceleration Decoding"
        )
        self.enable_next_episode_popup_checkbox: QCheckBox = QCheckBox(
            "Enable Next Episode Autoplay Popup"
        )
        self.watched_threshold_input: QLineEdit = QLineEdit()
        self.max_cache_size_input: QLineEdit = QLineEdit()

        self.db_path_input: QLineEdit = QLineEdit()
        self.log_dir_input: QLineEdit = QLineEdit()
        self.log_retention_input: QLineEdit = QLineEdit()
        self.log_saving_mode_selector: QComboBox = QComboBox()
        self.log_level_selector: QComboBox = QComboBox()

        self.backup_directory_input: QLineEdit = QLineEdit()
        self.config_backup_frequency_input: QLineEdit = QLineEdit()
        self.database_backup_frequency_input: QLineEdit = QLineEdit()
        self.config_backup_retention_input: QLineEdit = QLineEdit()
        self.database_backup_retention_input: QLineEdit = QLineEdit()

        self.log_level_filter: QComboBox = QComboBox()
        self.log_search_input: QLineEdit = QLineEdit()
        self.log_autoscroll_checkbox: QCheckBox = QCheckBox()
        self.log_display: QPlainTextEdit = QPlainTextEdit()
        self.all_log_records: List[Tuple[str, str]] = []
        self._logging_connected: bool = False

        self.staged_combined_views: List[Dict[str, Any]] = []
        self.enable_combined_view_checkbox: QCheckBox = QCheckBox(
            "Enable Combined Library View"
        )
        self.combined_views_list_widget: QListWidget = QListWidget()
        self.row_properties_group: QGroupBox = QGroupBox("Row Properties")
        self.row_name_input: QLineEdit = QLineEdit()
        self.row_enabled_checkbox: QCheckBox = QCheckBox("Enabled")
        self.row_sort_selector: QComboBox = QComboBox()
        self.row_filter_selector: QComboBox = QComboBox()
        self.row_max_items_spinbox: QSpinBox = QSpinBox()
        self.row_libraries_container: QScrollArea = QScrollArea()
        self.row_libraries_layout: QVBoxLayout = QVBoxLayout()

        self._setup_ui()
        self._load_config()

    def _create_header_with_info(self, text: str, info_text: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        header = QLabel(f"<b>{text}</b>")
        header.setStyleSheet("font-size: 14px;")
        layout.addWidget(header)

        info_btn = QPushButton("?")
        info_btn.setFixedSize(20, 20)
        info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        info_btn.setToolTip("Click for details on how to get these credentials")
        info_btn.setFlat(True)
        info_btn.setStyleSheet(
            """
            QPushButton {
                color: #3498db;
                font-weight: bold;
                font-size: 16px;
                border: none;
                background: none;
                padding: 0;
            }
            QPushButton:hover {
                text-decoration: underline;
                color: #2980b9;
            }
        """
        )
        info_btn.clicked.connect(
            lambda: QMessageBox.information(self, f"About {text}", info_text)
        )
        layout.addWidget(info_btn)
        layout.addStretch()

        return container

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        tab_container: QTabWidget = QTabWidget()

        # Connectivity Configuration Pane
        connectivity_tab: QWidget = QWidget()
        connectivity_layout: QGridLayout = QGridLayout(connectivity_tab)
        connectivity_layout.setSpacing(12)
        connectivity_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Jellyfin Section
        jelly_header = self._create_header_with_info(
            "Jellyfin Server",
            "Jellyfin credentials allow Lan Streamer to sync your watch history.\n\n"
            "- Server URL: The address of your Jellyfin server (e.g. http://192.168.1.50:8096)\n"
            "- API Token: Create this in Jellyfin Dashboard -> Dashboard -> API Keys.",
        )
        connectivity_layout.addWidget(jelly_header, 0, 0, 1, 2)
        connectivity_layout.addWidget(QLabel("Server URL:"), 1, 0)
        connectivity_layout.addWidget(self.jellyfin_url_input, 1, 1)
        connectivity_layout.addWidget(QLabel("API Token:"), 2, 0)
        self.jellyfin_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.jellyfin_key_input, 2, 1)

        # TMDB Section
        tmdb_header = self._create_header_with_info(
            "The Movie Database (TMDB)",
            "TMDB is used to fetch posters, descriptions, and episode metadata.\n\n"
            "- API Key: Create a free key at https://www.themoviedb.org/settings/api",
        )
        connectivity_layout.addWidget(tmdb_header, 3, 0, 1, 2)
        connectivity_layout.addWidget(QLabel("API Key:"), 4, 0)
        self.tmdb_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.tmdb_key_input, 4, 1)

        # OpenSubtitles Section
        osub_header = self._create_header_with_info(
            "OpenSubtitles.com",
            "Allows searching and downloading subtitles directly.\n\n"
            "- Username/Password: Your personal OpenSubtitles.com account.\n"
            "- API Key: MANDATORY for the app to connect. Create a free 'Consumer Key' "
            "at https://www.opensubtitles.com/en/consumers",
        )
        connectivity_layout.addWidget(osub_header, 5, 0, 1, 2)
        connectivity_layout.addWidget(QLabel("Username:"), 6, 0)
        connectivity_layout.addWidget(self.opensubtitles_username_input, 6, 1)
        connectivity_layout.addWidget(QLabel("Password:"), 7, 0)
        self.opensubtitles_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.opensubtitles_password_input, 7, 1)
        connectivity_layout.addWidget(QLabel("API Key:"), 8, 0)
        self.opensubtitles_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        connectivity_layout.addWidget(self.opensubtitles_api_key_input, 8, 1)

        connectivity_layout.setRowStretch(9, 1)

        # Libraries Management Pane
        libraries_tab: QWidget = QWidget()
        libraries_layout: QVBoxLayout = QVBoxLayout(libraries_tab)
        libraries_layout.setSpacing(12)

        # Create Library Group
        create_layout: QHBoxLayout = QHBoxLayout()
        create_layout.addWidget(QLabel("New Library Name:"))
        self.library_name_input.setPlaceholderText("e.g. Movies, Documentaries")
        create_layout.addWidget(self.library_name_input)

        create_layout.addWidget(QLabel("Type:"))
        self.library_type_input.addItems(["TV Shows", "Movies"])
        create_layout.addWidget(self.library_type_input)

        add_library_button: QPushButton = QPushButton("Create Library")
        add_library_button.clicked.connect(self.add_staged_library)
        create_layout.addWidget(add_library_button)
        libraries_layout.addLayout(create_layout)

        # Divider
        divider_frame: QFrame = QFrame()
        divider_frame.setFrameShape(QFrame.Shape.HLine)
        divider_frame.setFrameShadow(QFrame.Shadow.Sunken)
        libraries_layout.addWidget(divider_frame)

        # Select Library Group
        select_layout: QHBoxLayout = QHBoxLayout()
        select_layout.addWidget(QLabel("Configure Library:"))
        self.library_selector.setMinimumWidth(200)
        self.library_selector.currentTextChanged.connect(self._on_library_selected)
        select_layout.addWidget(self.library_selector)

        delete_library_button: QPushButton = QPushButton("Remove Library")
        delete_library_button.clicked.connect(self.remove_staged_library)
        select_layout.addWidget(delete_library_button)
        select_layout.addStretch()
        libraries_layout.addLayout(select_layout)

        # Mapped Directories List
        libraries_layout.addWidget(QLabel("Mapped Root Directories:"))
        libraries_layout.addWidget(self.directory_list_widget)

        # Directory Operations
        dir_buttons_layout: QHBoxLayout = QHBoxLayout()
        add_dir_button: QPushButton = QPushButton("Add Directory...")
        add_dir_button.clicked.connect(self.add_staged_directory)
        dir_buttons_layout.addWidget(add_dir_button)

        remove_dir_button: QPushButton = QPushButton("Remove Selected Directory")
        remove_dir_button.clicked.connect(self.remove_staged_directory)
        dir_buttons_layout.addWidget(remove_dir_button)
        dir_buttons_layout.addStretch()
        libraries_layout.addLayout(dir_buttons_layout)

        # Combined View Setup Pane
        combined_tab: QWidget = QWidget()
        combined_tab_main_layout: QVBoxLayout = QVBoxLayout(combined_tab)
        combined_tab_main_layout.setContentsMargins(10, 10, 10, 10)
        combined_tab_main_layout.setSpacing(10)

        # Checkbox to enable/disable combined view
        combined_tab_main_layout.addWidget(self.enable_combined_view_checkbox)

        # Content container
        combined_content_widget = QWidget()
        combined_layout: QHBoxLayout = QHBoxLayout(combined_content_widget)
        combined_layout.setContentsMargins(0, 0, 0, 0)
        combined_layout.setSpacing(15)
        combined_tab_main_layout.addWidget(combined_content_widget)

        # Connect enable checkbox to setEnabled of the content container
        self.enable_combined_view_checkbox.toggled.connect(
            combined_content_widget.setEnabled
        )

        # Left Column: List and List Controls
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Configure rows for Combined Library View:"))
        left_layout.addWidget(self.combined_views_list_widget)

        list_btn_layout = QHBoxLayout()
        move_up_btn = QPushButton("Move Up")
        move_up_btn.clicked.connect(self.move_combined_view_row_up)
        move_down_btn = QPushButton("Move Down")
        move_down_btn.clicked.connect(self.move_combined_view_row_down)
        delete_btn = QPushButton("Delete Row")
        delete_btn.clicked.connect(self.delete_combined_view_row)

        list_btn_layout.addWidget(move_up_btn)
        list_btn_layout.addWidget(move_down_btn)
        list_btn_layout.addWidget(delete_btn)
        left_layout.addLayout(list_btn_layout)

        add_row_btn = QPushButton("Add New Row")
        add_row_btn.clicked.connect(self.add_combined_view_row)
        left_layout.addWidget(add_row_btn)

        combined_layout.addWidget(left_column, 2)

        # Right Column: Properties Group
        properties_layout = QVBoxLayout(self.row_properties_group)
        properties_layout.setSpacing(10)

        properties_layout.addWidget(QLabel("Row Display Name:"))
        properties_layout.addWidget(self.row_name_input)
        self.row_name_input.textChanged.connect(self._on_row_property_changed)

        properties_layout.addWidget(self.row_enabled_checkbox)
        self.row_enabled_checkbox.stateChanged.connect(self._on_row_property_changed)

        # Sort and filter settings (all rows are now configured similarly to smart rows)
        properties_layout.addWidget(QLabel("Sort By:"))
        self.row_sort_selector.addItems(
            ["Alphabetical", "Recently Added", "Recently Aired", "Next Up"]
        )
        self.row_sort_selector.currentTextChanged.connect(self._on_row_property_changed)
        properties_layout.addWidget(self.row_sort_selector)

        properties_layout.addWidget(QLabel("Filter Mode:"))
        self.row_filter_selector.addItems(["All", "Watched", "Unwatched"])
        self.row_filter_selector.currentTextChanged.connect(
            self._on_row_property_changed
        )
        properties_layout.addWidget(self.row_filter_selector)

        # Max items setting
        properties_layout.addWidget(QLabel("Max Items:"))
        self.row_max_items_spinbox.setRange(1, 1000)
        self.row_max_items_spinbox.setValue(20)
        self.row_max_items_spinbox.valueChanged.connect(self._on_row_property_changed)
        properties_layout.addWidget(self.row_max_items_spinbox)

        # Libraries Checklist
        properties_layout.addWidget(
            QLabel("Aggregated Libraries (none checked = all):")
        )
        libs_widget = QWidget()
        libs_widget.setLayout(self.row_libraries_layout)
        self.row_libraries_container.setWidget(libs_widget)
        self.row_libraries_container.setWidgetResizable(True)
        self.row_libraries_container.setMinimumHeight(150)
        properties_layout.addWidget(self.row_libraries_container)

        properties_layout.addStretch()
        combined_layout.addWidget(self.row_properties_group, 3)

        self.combined_views_list_widget.currentRowChanged.connect(
            self._on_combined_view_selected
        )

        # Video Player Settings Pane
        player_tab: QWidget = QWidget()
        player_layout: QVBoxLayout = QVBoxLayout(player_tab)
        player_layout.setSpacing(15)

        player_layout.addWidget(self.use_embedded_checkbox)
        player_layout.addWidget(self.enable_caching_checkbox)
        player_layout.addWidget(self.enable_hw_accel_checkbox)
        player_layout.addWidget(self.enable_next_episode_popup_checkbox)

        threshold_layout: QHBoxLayout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Watched Threshold (% of video length):"))
        self.watched_threshold_input.setFixedWidth(80)
        threshold_layout.addWidget(self.watched_threshold_input)
        threshold_layout.addStretch()
        player_layout.addLayout(threshold_layout)

        cache_size_layout: QHBoxLayout = QHBoxLayout()
        cache_size_layout.addWidget(QLabel("Max Cache Size (GB):"))
        self.max_cache_size_input.setFixedWidth(80)
        cache_size_layout.addWidget(self.max_cache_size_input)
        cache_size_layout.addStretch()
        player_layout.addLayout(cache_size_layout)

        player_layout.addStretch()

        # Advanced Settings Pane
        advanced_tab: QWidget = QWidget()
        advanced_layout: QVBoxLayout = QVBoxLayout(advanced_tab)
        advanced_layout.setSpacing(15)
        advanced_layout.setContentsMargins(10, 10, 10, 10)

        # 1. Database Settings Group
        db_frame: QFrame = QFrame()
        db_frame.setObjectName("dbGroupFrame")
        db_frame.setStyleSheet(
            "QFrame#dbGroupFrame { background-color: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        db_group_layout: QGridLayout = QGridLayout(db_frame)
        db_group_layout.setContentsMargins(15, 15, 15, 15)
        db_group_layout.setSpacing(10)
        db_group_layout.setColumnStretch(1, 1)

        db_title: QLabel = QLabel("Database Settings")
        db_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #2a82da;")
        db_group_layout.addWidget(db_title, 0, 0, 1, 3)

        db_path_label: QLabel = QLabel("Database File Path:")
        db_group_layout.addWidget(db_path_label, 1, 0)
        db_group_layout.addWidget(self.db_path_input, 1, 1)
        browse_db_button: QPushButton = QPushButton("Browse File...")
        browse_db_button.clicked.connect(self.browse_database_path)
        db_group_layout.addWidget(browse_db_button, 1, 2)

        db_freq_label: QLabel = QLabel("Database Backup Freq (Days):")
        db_group_layout.addWidget(db_freq_label, 2, 0)
        self.database_backup_frequency_input.setToolTip(
            "Setting this to 0 backs up every time the application starts"
        )
        db_group_layout.addWidget(self.database_backup_frequency_input, 2, 1)

        db_ret_label: QLabel = QLabel("Database Backup Retention (Days):")
        db_group_layout.addWidget(db_ret_label, 3, 0)
        db_group_layout.addWidget(self.database_backup_retention_input, 3, 1)

        restore_database_button: QPushButton = QPushButton("Restore Database...")
        restore_database_button.clicked.connect(self.trigger_restore_database)
        db_group_layout.addWidget(restore_database_button, 4, 1)

        advanced_layout.addWidget(db_frame)

        # 2. Log Settings Group
        logs_frame: QFrame = QFrame()
        logs_frame.setObjectName("logsGroupFrame")
        logs_frame.setStyleSheet(
            "QFrame#logsGroupFrame { background-color: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        logs_group_layout: QGridLayout = QGridLayout(logs_frame)
        logs_group_layout.setContentsMargins(15, 15, 15, 15)
        logs_group_layout.setSpacing(10)
        logs_group_layout.setColumnStretch(1, 1)

        logs_title: QLabel = QLabel("Log Settings")
        logs_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #2a82da;")
        logs_group_layout.addWidget(logs_title, 0, 0, 1, 3)

        log_dir_label: QLabel = QLabel("Logs Directory:")
        logs_group_layout.addWidget(log_dir_label, 1, 0)
        logs_group_layout.addWidget(self.log_dir_input, 1, 1)
        browse_log_button: QPushButton = QPushButton("Browse Folder...")
        browse_log_button.clicked.connect(self.browse_log_directory)
        logs_group_layout.addWidget(browse_log_button, 1, 2)

        log_level_label: QLabel = QLabel("Log Level:")
        logs_group_layout.addWidget(log_level_label, 2, 0)
        self.log_level_selector.addItems(
            ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        )
        logs_group_layout.addWidget(self.log_level_selector, 2, 1)

        log_saving_label: QLabel = QLabel("Log Saving Mode (Restart Required):")
        logs_group_layout.addWidget(log_saving_label, 3, 0)
        self.log_saving_mode_selector.addItems(
            ["Single Global File", "Divided Service Logs"]
        )
        logs_group_layout.addWidget(self.log_saving_mode_selector, 3, 1)

        log_ret_label: QLabel = QLabel("Max Log Retention Days:")
        logs_group_layout.addWidget(log_ret_label, 4, 0)
        logs_group_layout.addWidget(self.log_retention_input, 4, 1)

        advanced_layout.addWidget(logs_frame)

        # 3. Configuration Settings Group
        config_frame: QFrame = QFrame()
        config_frame.setObjectName("configGroupFrame")
        config_frame.setStyleSheet(
            "QFrame#configGroupFrame { background-color: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        config_group_layout: QGridLayout = QGridLayout(config_frame)
        config_group_layout.setContentsMargins(15, 15, 15, 15)
        config_group_layout.setSpacing(10)
        config_group_layout.setColumnStretch(1, 1)

        config_title: QLabel = QLabel("Configuration & System Backup Settings")
        config_title.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #2a82da;"
        )
        config_group_layout.addWidget(config_title, 0, 0, 1, 3)

        backup_dir_label: QLabel = QLabel("Backup Directory:")
        config_group_layout.addWidget(backup_dir_label, 1, 0)
        config_group_layout.addWidget(self.backup_directory_input, 1, 1)
        browse_backup_button: QPushButton = QPushButton("Browse Folder...")
        browse_backup_button.clicked.connect(self.browse_backup_directory)
        config_group_layout.addWidget(browse_backup_button, 1, 2)

        config_freq_label: QLabel = QLabel("Config Backup Freq (Days):")
        config_group_layout.addWidget(config_freq_label, 2, 0)
        self.config_backup_frequency_input.setToolTip(
            "Setting this to 0 backs up every time the application starts"
        )
        config_group_layout.addWidget(self.config_backup_frequency_input, 2, 1)

        config_ret_label: QLabel = QLabel("Config Backup Retention (Days):")
        config_group_layout.addWidget(config_ret_label, 3, 0)
        config_group_layout.addWidget(self.config_backup_retention_input, 3, 1)

        restore_config_button: QPushButton = QPushButton("Restore Config...")
        restore_config_button.clicked.connect(self.trigger_restore_config)
        config_group_layout.addWidget(restore_config_button, 4, 1)

        advanced_layout.addWidget(config_frame)

        advanced_layout.addStretch()

        # Library Management Pane
        management_tab: QWidget = QWidget()
        management_layout: QVBoxLayout = QVBoxLayout(management_tab)
        management_layout.setSpacing(15)

        scan_all_button: QPushButton = QPushButton("Scan New Files (All Libraries)")
        scan_all_button.setObjectName("accentButton")
        scan_all_button.clicked.connect(self.trigger_global_scan_files)
        management_layout.addWidget(scan_all_button)

        cleanup_all_button: QPushButton = QPushButton("Cleanup All Libraries")
        cleanup_all_button.clicked.connect(self.trigger_global_cleanup)
        management_layout.addWidget(cleanup_all_button)

        extract_runtime_button: QPushButton = QPushButton(
            "Extract Missing Video Runtimes (Background)"
        )
        extract_runtime_button.clicked.connect(self.trigger_global_runtime_extraction)
        management_layout.addWidget(extract_runtime_button)

        # Refresh Metadata Group
        refresh_frame: QFrame = QFrame()
        refresh_frame.setStyleSheet(
            "QFrame { background-color: #222222; border: 1px solid #333333; border-radius: 6px; }"
        )
        refresh_layout: QVBoxLayout = QVBoxLayout(refresh_frame)
        refresh_layout.setSpacing(10)

        refresh_all_button: QPushButton = QPushButton(
            "Refresh Metadata (All Libraries)"
        )
        refresh_all_button.clicked.connect(self.trigger_global_refresh_metadata)
        refresh_layout.addWidget(refresh_all_button)

        refresh_layout.addWidget(self.force_refresh_checkbox)
        management_layout.addWidget(refresh_frame)

        # Jellyfin Sync Group
        jellyfin_frame: QFrame = QFrame()
        jellyfin_frame.setStyleSheet(
            "QFrame { background-color: #222222; border: 1px solid #333333; border-radius: 6px; }"
        )
        jellyfin_layout: QVBoxLayout = QVBoxLayout(jellyfin_frame)
        jellyfin_layout.setSpacing(10)

        pull_all_button: QPushButton = QPushButton(
            "Pull Watch History from Jellyfin (All Libraries)"
        )
        pull_all_button.clicked.connect(self.trigger_global_jellyfin_pull)
        jellyfin_layout.addWidget(pull_all_button)

        push_all_button: QPushButton = QPushButton(
            "Push Watch History to Jellyfin (All Libraries)"
        )
        push_all_button.clicked.connect(self.trigger_global_jellyfin_push)
        jellyfin_layout.addWidget(push_all_button)
        management_layout.addWidget(jellyfin_frame)

        management_layout.addSpacing(10)
        management_layout.addWidget(QLabel("Global Operation Progress:"))
        management_layout.addWidget(self.global_progress_bar)
        management_layout.addSpacing(4)
        management_layout.addWidget(QLabel("Scan Detail:"))
        management_layout.addWidget(self.scan_progress_tree)

        management_layout.addStretch()

        # Running Logs Tab
        logs_tab: QWidget = QWidget()
        logs_layout: QVBoxLayout = QVBoxLayout(logs_tab)
        logs_layout.setSpacing(10)
        logs_layout.setContentsMargins(10, 10, 10, 10)

        # Control panel layout
        control_layout: QHBoxLayout = QHBoxLayout()
        control_layout.setSpacing(10)

        control_layout.addWidget(QLabel("Min Level:"))
        self.log_level_filter.clear()
        self.log_level_filter.addItems(
            ["All", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        )
        self.log_level_filter.setCurrentText("INFO")
        self.log_level_filter.currentTextChanged.connect(self._on_log_filter_changed)
        control_layout.addWidget(self.log_level_filter)

        control_layout.addWidget(QLabel("Filter Text:"))
        self.log_search_input.setPlaceholderText("Search logs...")
        self.log_search_input.textChanged.connect(self._on_log_filter_changed)
        control_layout.addWidget(self.log_search_input)

        self.log_autoscroll_checkbox.setText("Auto-scroll")
        self.log_autoscroll_checkbox.setChecked(True)
        control_layout.addWidget(self.log_autoscroll_checkbox)

        clear_logs_button: QPushButton = QPushButton("Clear View")
        clear_logs_button.clicked.connect(self._clear_log_view)
        control_layout.addWidget(clear_logs_button)

        copy_logs_button: QPushButton = QPushButton("Copy All")
        copy_logs_button.clicked.connect(self._copy_logs_to_clipboard)
        control_layout.addWidget(copy_logs_button)

        export_logs_button: QPushButton = QPushButton("Export Logs")
        export_logs_button.clicked.connect(self._export_logs)
        control_layout.addWidget(export_logs_button)

        logs_layout.addLayout(control_layout)

        # PlainTextEdit display configuration
        self.log_display.setReadOnly(True)
        log_font: QFont = QFont("Courier New", 10)
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_display.setFont(log_font)
        self.log_display.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #121212;
                color: #dcdcdc;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 10px;
            }
            """
        )
        logs_layout.addWidget(self.log_display)

        # Add tabs in the requested order
        tab_container.addTab(management_tab, "Library Management")
        tab_container.addTab(player_tab, "Video Player")
        tab_container.addTab(libraries_tab, "Libraries Setup")
        tab_container.addTab(combined_tab, "Combined View")
        tab_container.addTab(connectivity_tab, "Remote API's")
        tab_container.addTab(advanced_tab, "Advanced")
        tab_container.addTab(logs_tab, "Logs")

        main_layout.addWidget(tab_container)

        # Dialog Standard Action Buttons
        buttons_layout: QHBoxLayout = QHBoxLayout()
        buttons_layout.addStretch()

        cancel_button: QPushButton = QPushButton("Discard")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)

        save_button: QPushButton = QPushButton("Save Settings")
        save_button.setObjectName("accentButton")
        save_button.clicked.connect(self.save_config)
        buttons_layout.addWidget(save_button)

        main_layout.addLayout(buttons_layout)

    def _load_config(self) -> None:
        self.jellyfin_url_input.setText(config.jellyfin_url)
        self.jellyfin_key_input.setText(config.jellyfin_api_key)
        self.tmdb_key_input.setText(config.tmdb_api_key)
        self.opensubtitles_username_input.setText(config.opensubtitles_username)
        self.opensubtitles_password_input.setText(config.opensubtitles_password)
        self.opensubtitles_api_key_input.setText(config.opensubtitles_api_key)

        self.use_embedded_checkbox.setChecked(config.use_embedded_player)
        self.enable_caching_checkbox.setChecked(config.enable_caching)
        self.enable_hw_accel_checkbox.setChecked(config.enable_hw_accel)
        self.enable_next_episode_popup_checkbox.setChecked(
            config.enable_next_episode_popup
        )
        self.watched_threshold_input.setText(str(int(config.watched_threshold * 100)))
        self.max_cache_size_input.setText(str(config.max_cache_size_gb))

        self.db_path_input.setText(config.database_path)
        self.log_dir_input.setText(config.log_directory)
        self.log_retention_input.setText(str(config.max_log_retention_days))
        self.log_saving_mode_selector.setCurrentText(
            "Divided Service Logs"
            if config.divide_logs_by_service
            else "Single Global File"
        )
        self.log_level_selector.setCurrentText(config.log_level.upper())

        self.backup_directory_input.setText(config.backup_directory)
        self.config_backup_frequency_input.setText(str(config.config_backup_frequency))
        self.database_backup_frequency_input.setText(
            str(config.database_backup_frequency)
        )
        self.config_backup_retention_input.setText(str(config.config_backup_retention))
        self.database_backup_retention_input.setText(
            str(config.database_backup_retention)
        )

        self.staged_libraries = {
            library_name: {
                "type": library_config.get("type", "tv"),
                "paths": list(library_config.get("paths", [])),
            }
            for library_name, library_config in config.libraries.items()
        }
        self._refresh_library_selector()

        self.enable_combined_view_checkbox.setChecked(config.enable_combined_view)
        self.staged_combined_views = [dict(row) for row in config.combined_views]
        self._refresh_combined_views_list()

        # Populate initial logs from the buffer
        from .logging_handler import qt_log_handler

        self.all_log_records = list(qt_log_handler.buffer)
        self._refresh_log_display()

        # Connect live log signals
        qt_log_handler.emitter.log_emitted.connect(self._on_log_emitted)
        self._logging_connected = True

    def _refresh_combined_views_list(self) -> None:
        self.combined_views_list_widget.blockSignals(True)
        current_idx = self.combined_views_list_widget.currentRow()
        self.combined_views_list_widget.clear()
        for idx, row in enumerate(self.staged_combined_views):
            status = "Enabled" if row.get("enabled", True) else "Disabled"
            self.combined_views_list_widget.addItem(
                f"{row.get('name', 'Unnamed')} - {status}"
            )
        if current_idx >= 0 and current_idx < len(self.staged_combined_views):
            self.combined_views_list_widget.setCurrentRow(current_idx)
        else:
            if self.staged_combined_views:
                self.combined_views_list_widget.setCurrentRow(0)
        self.combined_views_list_widget.blockSignals(False)
        self._on_combined_view_selected()

    def _get_default_row_name(self, row: Dict[str, Any]) -> str:
        libs = row.get("libraries", [])
        lib_str = ", ".join(libs) if libs else "All Libraries"
        sort_str = row.get("sort_by", "Alphabetical")
        filter_str = row.get("filter_mode", "All")
        return f"{lib_str} - {sort_str} - {filter_str}"

    @Slot()
    def _on_combined_view_selected(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            self.row_properties_group.setEnabled(False)
            return

        self.row_properties_group.setEnabled(True)
        row = self.staged_combined_views[row_idx]

        self.row_name_input.blockSignals(True)
        self.row_enabled_checkbox.blockSignals(True)
        self.row_sort_selector.blockSignals(True)
        self.row_filter_selector.blockSignals(True)
        self.row_max_items_spinbox.blockSignals(True)

        self.row_name_input.setText(row.get("name", ""))
        self.row_enabled_checkbox.setChecked(row.get("enabled", True))

        self.row_sort_selector.setCurrentText(row.get("sort_by", "Alphabetical"))
        self.row_filter_selector.setCurrentText(row.get("filter_mode", "All"))
        self.row_max_items_spinbox.setValue(row.get("max_items", 20))

        self.row_name_input.blockSignals(False)
        self.row_enabled_checkbox.blockSignals(False)
        self.row_sort_selector.blockSignals(False)
        self.row_filter_selector.blockSignals(False)
        self.row_max_items_spinbox.blockSignals(False)

        # Clear libraries list layout
        while self.row_libraries_layout.count():
            layout_item = self.row_libraries_layout.takeAt(0)
            if layout_item is not None:
                w = layout_item.widget()
                if w is not None:
                    w.deleteLater()

        selected_libs = row.get("libraries", [])
        for lib_name in sorted(self.staged_libraries.keys()):
            cb = QCheckBox(lib_name)
            cb.setChecked(lib_name in selected_libs)
            cb.stateChanged.connect(self._on_row_library_toggled)
            self.row_libraries_layout.addWidget(cb)

    @Slot()
    def _on_row_property_changed(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            return

        row = self.staged_combined_views[row_idx]
        old_default = self._get_default_row_name(row)
        current_name = self.row_name_input.text().strip()

        row["enabled"] = self.row_enabled_checkbox.isChecked()
        row["sort_by"] = self.row_sort_selector.currentText()
        row["filter_mode"] = self.row_filter_selector.currentText()
        row["max_items"] = self.row_max_items_spinbox.value()

        new_default = self._get_default_row_name(row)
        if (
            current_name == ""
            or current_name == old_default
            or current_name == "New Smart Row"
        ):
            row["name"] = new_default
            self.row_name_input.blockSignals(True)
            self.row_name_input.setText(new_default)
            self.row_name_input.blockSignals(False)
        else:
            row["name"] = current_name

        status = "Enabled" if row["enabled"] else "Disabled"
        item = self.combined_views_list_widget.item(row_idx)
        if item:
            item.setText(f"{row['name']} - {status}")

    @Slot()
    def _on_row_library_toggled(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            return
        row = self.staged_combined_views[row_idx]
        old_default = self._get_default_row_name(row)
        current_name = self.row_name_input.text().strip()

        selected_libs = []
        for i in range(self.row_libraries_layout.count()):
            layout_item = self.row_libraries_layout.itemAt(i)
            if layout_item is not None:
                widget = layout_item.widget()
                if isinstance(widget, QCheckBox) and widget.isChecked():
                    selected_libs.append(widget.text())
        row["libraries"] = selected_libs

        new_default = self._get_default_row_name(row)
        if (
            current_name == ""
            or current_name == old_default
            or current_name == "New Smart Row"
        ):
            row["name"] = new_default
            self.row_name_input.blockSignals(True)
            self.row_name_input.setText(new_default)
            self.row_name_input.blockSignals(False)

            # Update item list text
            status = "Enabled" if row.get("enabled", True) else "Disabled"
            item = self.combined_views_list_widget.item(row_idx)
            if item:
                item.setText(f"{row['name']} - {status}")

    @Slot()
    def add_combined_view_row(self) -> None:
        new_row = {
            "enabled": True,
            "libraries": [],
            "sort_by": "Alphabetical",
            "filter_mode": "All",
            "max_items": 20,
        }
        new_row["name"] = self._get_default_row_name(new_row)
        self.staged_combined_views.append(new_row)
        logger.debug(f"Added combined view row: '{new_row['name']}'")
        self._refresh_combined_views_list()
        self.combined_views_list_widget.setCurrentRow(
            len(self.staged_combined_views) - 1
        )

    @Slot()
    def delete_combined_view_row(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views):
            return
        deleted_name: str = self.staged_combined_views[row_idx].get("name", "Unnamed")
        del self.staged_combined_views[row_idx]
        logger.debug(f"Deleted combined view row at index {row_idx}: '{deleted_name}'")
        self._refresh_combined_views_list()

    @Slot()
    def move_combined_view_row_up(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx <= 0 or row_idx >= len(self.staged_combined_views):
            return
        self.staged_combined_views[row_idx], self.staged_combined_views[row_idx - 1] = (
            self.staged_combined_views[row_idx - 1],
            self.staged_combined_views[row_idx],
        )
        logger.debug(f"Moved combined view row from index {row_idx} to {row_idx - 1}")
        self._refresh_combined_views_list()
        self.combined_views_list_widget.setCurrentRow(row_idx - 1)

    @Slot()
    def move_combined_view_row_down(self) -> None:
        row_idx = self.combined_views_list_widget.currentRow()
        if row_idx < 0 or row_idx >= len(self.staged_combined_views) - 1:
            return
        self.staged_combined_views[row_idx], self.staged_combined_views[row_idx + 1] = (
            self.staged_combined_views[row_idx + 1],
            self.staged_combined_views[row_idx],
        )
        logger.debug(f"Moved combined view row from index {row_idx} to {row_idx + 1}")
        self._refresh_combined_views_list()
        self.combined_views_list_widget.setCurrentRow(row_idx + 1)

    def _refresh_library_selector(self) -> None:
        self.library_selector.blockSignals(True)
        self.library_selector.clear()
        self.library_selector.addItems(sorted(self.staged_libraries.keys()))
        self.library_selector.blockSignals(False)
        self._refresh_directory_list()

    @Slot(str)
    def _on_library_selected(self, library_name: str) -> None:
        self._refresh_directory_list()

    def _refresh_directory_list(self) -> None:
        self.directory_list_widget.clear()
        selected_library: str = self.library_selector.currentText()
        if selected_library in self.staged_libraries:
            self.directory_list_widget.addItems(
                self.staged_libraries[selected_library].get("paths", [])
            )

    @Slot()
    def add_staged_library(self) -> None:
        new_library_name: str = self.library_name_input.text().strip()
        new_library_type: str = (
            "movie" if self.library_type_input.currentText() == "Movies" else "tv"
        )
        if not new_library_name:
            return
        if new_library_name in self.staged_libraries:
            QMessageBox.warning(
                self,
                "Duplicate Library",
                f"Library '{new_library_name}' already exists.",
            )
            return

        self.staged_libraries[new_library_name] = {
            "type": new_library_type,
            "paths": [],
        }
        self.library_name_input.clear()
        self._refresh_library_selector()
        self.library_selector.setCurrentText(new_library_name)

    @Slot()
    def remove_staged_library(self) -> None:
        selected_library: str = self.library_selector.currentText()
        if not selected_library:
            return

        del self.staged_libraries[selected_library]
        self._refresh_library_selector()

    @Slot()
    def add_staged_directory(self) -> None:
        selected_library: str = self.library_selector.currentText()
        if not selected_library:
            QMessageBox.warning(
                self, "No Library Selected", "Please select or create a library first."
            )
            return

        chosen_directory: str = QFileDialog.getExistingDirectory(
            self, "Select Root Directory"
        )
        if chosen_directory:
            paths: List[str] = self.staged_libraries[selected_library].get("paths", [])
            if chosen_directory not in paths:
                paths.append(chosen_directory)
                self.staged_libraries[selected_library]["paths"] = paths
                self._refresh_directory_list()

    @Slot()
    def remove_staged_directory(self) -> None:
        selected_library: str = self.library_selector.currentText()
        selected_item: Optional[QListWidgetItem] = (
            self.directory_list_widget.currentItem()
        )
        if not selected_library or selected_item is None:
            return

        directory_path: str = selected_item.text()
        paths: List[str] = self.staged_libraries[selected_library].get("paths", [])
        if directory_path in paths:
            paths.remove(directory_path)
            self.staged_libraries[selected_library]["paths"] = paths
            self._refresh_directory_list()

    @Slot()
    def browse_database_path(self) -> None:
        chosen_file, _ = QFileDialog.getSaveFileName(
            self,
            "Select Database File",
            self.db_path_input.text(),
            "Database Files (*.db);;All Files (*)",
        )
        if chosen_file:
            self.db_path_input.setText(chosen_file)

    @Slot()
    def browse_log_directory(self) -> None:
        chosen_dir: str = QFileDialog.getExistingDirectory(
            self, "Select Log Directory", self.log_dir_input.text()
        )
        if chosen_dir:
            self.log_dir_input.setText(chosen_dir)

    @Slot()
    def save_config(self) -> None:
        db_freq = 0
        db_ret = 0
        try:
            db_freq = int(self.database_backup_frequency_input.text().strip())
        except ValueError:
            pass
        try:
            db_ret = int(self.database_backup_retention_input.text().strip())
        except ValueError:
            pass

        cfg_freq = 0
        cfg_ret = 0
        try:
            cfg_freq = int(self.config_backup_frequency_input.text().strip())
        except ValueError:
            pass
        try:
            cfg_ret = int(self.config_backup_retention_input.text().strip())
        except ValueError:
            pass

        warnings: List[str] = []
        if db_freq > 0 and db_ret < db_freq:
            warnings.append(
                f"- Database Backup Retention ({db_ret} days) is less than its backup frequency ({db_freq} days)."
            )
        if cfg_freq > 0 and cfg_ret < cfg_freq:
            warnings.append(
                f"- Config Backup Retention ({cfg_ret} days) is less than its backup frequency ({cfg_freq} days)."
            )

        if warnings:
            warning_text = (
                "The following backup settings have retention times less than their backup frequencies:\n\n"
                + "\n".join(warnings)
                + "\n\nThis may result in backup files being cleaned up before a new backup is created.\n\nDo you want to save these settings anyway?"
            )
            confirm = QMessageBox.question(
                self,
                "Backup Retention Warning",
                warning_text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm == QMessageBox.StandardButton.No:
                return

        config.jellyfin_url = self.jellyfin_url_input.text().strip()
        config.jellyfin_api_key = self.jellyfin_key_input.text().strip()
        config.tmdb_api_key = self.tmdb_key_input.text().strip()
        config.opensubtitles_username = self.opensubtitles_username_input.text().strip()
        config.opensubtitles_password = self.opensubtitles_password_input.text().strip()
        config.opensubtitles_api_key = self.opensubtitles_api_key_input.text().strip()
        config.sync_history_on_start = False

        config.use_embedded_player = self.use_embedded_checkbox.isChecked()
        config.enable_caching = self.enable_caching_checkbox.isChecked()
        config.enable_hw_accel = self.enable_hw_accel_checkbox.isChecked()
        config.enable_next_episode_popup = (
            self.enable_next_episode_popup_checkbox.isChecked()
        )
        try:
            parsed_threshold = float(self.watched_threshold_input.text().strip())
            if parsed_threshold > 1.0:
                config.watched_threshold = parsed_threshold / 100.0
            else:
                config.watched_threshold = parsed_threshold
        except ValueError:
            pass

        try:
            config.max_cache_size_gb = float(self.max_cache_size_input.text().strip())
        except ValueError:
            pass

        if self.db_path_input.text().strip():
            config.database_path = self.db_path_input.text().strip()
        if self.log_dir_input.text().strip():
            config.log_directory = self.log_dir_input.text().strip()

        config.log_level = self.log_level_selector.currentText()
        try:
            config.max_log_retention_days = int(self.log_retention_input.text().strip())
        except ValueError:
            pass

        config.divide_logs_by_service = (
            self.log_saving_mode_selector.currentText() == "Divided Service Logs"
        )

        if self.backup_directory_input.text().strip():
            config.backup_directory = self.backup_directory_input.text().strip()

        try:
            config.config_backup_frequency = int(
                self.config_backup_frequency_input.text().strip()
            )
        except ValueError:
            pass

        try:
            config.database_backup_frequency = int(
                self.database_backup_frequency_input.text().strip()
            )
        except ValueError:
            pass

        try:
            config.config_backup_retention = int(
                self.config_backup_retention_input.text().strip()
            )
        except ValueError:
            pass

        try:
            config.database_backup_retention = int(
                self.database_backup_retention_input.text().strip()
            )
        except ValueError:
            pass

        config.libraries = self.staged_libraries
        config.enable_combined_view = self.enable_combined_view_checkbox.isChecked()
        config.combined_views = self.staged_combined_views
        config.save()
        from .logging_handler import set_application_log_level

        set_application_log_level(config.log_level)
        self.accept()

    @Slot()
    def browse_backup_directory(self) -> None:
        chosen_directory: str = QFileDialog.getExistingDirectory(
            self, "Select Backup Directory", self.backup_directory_input.text()
        )
        if chosen_directory:
            self.backup_directory_input.setText(chosen_directory)

    @Slot()
    def trigger_restore_config(self) -> None:
        chosen_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Configuration Backup to Restore",
            self.backup_directory_input.text(),
            "JSON Files (*.json);;All Files (*)",
        )
        if chosen_file:
            from .backup import restore_config_backup

            success: bool = restore_config_backup(chosen_file)
            if success:
                QMessageBox.information(
                    self,
                    "Restore Successful",
                    "Configuration successfully restored and reloaded.",
                )
                self._load_config()
            else:
                QMessageBox.critical(
                    self,
                    "Restore Failed",
                    "Failed to restore configuration. Ensure the file is valid.",
                )

    @Slot()
    def trigger_restore_database(self) -> None:
        chosen_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database Backup to Restore",
            self.backup_directory_input.text(),
            "Database Files (*.db);;All Files (*)",
        )
        if chosen_file:
            from .backup import restore_database_backup

            success: bool = restore_database_backup(chosen_file)
            if success:
                QMessageBox.information(
                    self,
                    "Restore Successful",
                    "Database successfully restored from backup.",
                )
            else:
                QMessageBox.critical(
                    self,
                    "Restore Failed",
                    "Failed to restore database. Ensure the file is uncorrupted.",
                )

    @Slot(str, int, int)
    def _on_global_progress(
        self, library_name: str, completed_count: int, total_count: int
    ) -> None:
        self.global_progress_bar.setVisible(True)
        self.global_progress_bar.mark_library_done(library_name)

    @Slot(str, dict)
    def _on_detail_progress(self, event: str, payload: Dict[str, Any]) -> None:
        """Routes granular scan events to the SegmentedProgressBar and ScanProgressTree."""
        library = payload.get("library", "")
        root = payload.get("root", "")
        folder = payload.get("folder", "")
        season = payload.get("season", "")
        file_path = payload.get("file", "")

        if event == "init_tree":
            tree = payload.get("tree", {})
            self.global_progress_bar.init_from_tree(tree)
            self.scan_progress_tree.init_from_tree(tree)
            self.global_progress_bar.setVisible(True)
            self.scan_progress_tree.setVisible(True)

        elif event == "start_library":
            self.global_progress_bar.mark_library_active(library)
            self.scan_progress_tree.mark_library_active(library)

        elif event == "finish_library":
            self.global_progress_bar.mark_library_done(library)
            self.scan_progress_tree.mark_library_done(library)

        elif event == "start_folder":
            self.global_progress_bar.advance_root(root)
            self.scan_progress_tree.mark_folder_active(library, root, folder)

        elif event == "finish_folder":
            skipped = payload.get("skipped", False)
            self.scan_progress_tree.mark_folder_done(
                library, root, folder, skipped=skipped
            )

        elif event == "start_season":
            self.scan_progress_tree.mark_season_active(library, folder, season)

        elif event == "finish_season":
            self.scan_progress_tree.mark_season_done(library, folder, season)

        elif event == "start_file":
            self.scan_progress_tree.mark_file_active(file_path, library, folder, season)

        elif event == "finish_file":
            self.scan_progress_tree.mark_file_done(file_path)

    def _show_scan_progress_widgets(self) -> None:
        self.scan_progress_tree.reset()
        self.global_progress_bar.setVisible(True)
        self.scan_progress_tree.setVisible(True)

    @Slot()
    def trigger_global_scan_files(self) -> None:
        if self.controller is not None:
            self._show_scan_progress_widgets()
            self.controller.trigger_scan_all(False)

    @Slot()
    def trigger_global_cleanup(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.controller.trigger_cleanup_all()

    @Slot()
    def trigger_global_runtime_extraction(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.controller.trigger_runtime_extraction()

    @Slot()
    def trigger_global_refresh_metadata(self) -> None:
        if self.controller is not None:
            self._show_scan_progress_widgets()
            self.controller.trigger_scan_all(self.force_refresh_checkbox.isChecked())

    @Slot()
    def trigger_global_jellyfin_pull(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.controller.trigger_jellyfin_pull()
            QTimer.singleShot(
                2000,
                lambda: self._complete_jellyfin_progress("Jellyfin pull completed."),
            )

    @Slot()
    def trigger_global_jellyfin_push(self) -> None:
        if self.controller is not None:
            self.global_progress_bar.setVisible(True)
            self.controller.trigger_jellyfin_push()
            QTimer.singleShot(
                2000,
                lambda: self._complete_jellyfin_progress("Jellyfin push completed."),
            )

    def _complete_jellyfin_progress(self, message_text: str) -> None:
        pass  # Segmented bar has no text format; completion is driven by mark_library_done

    @Slot(str)
    def _on_log_filter_changed(self, text: str) -> None:
        self._refresh_log_display()

    @Slot()
    def _clear_log_view(self) -> None:
        self.all_log_records.clear()
        self._refresh_log_display()

    @Slot()
    def _copy_logs_to_clipboard(self) -> None:
        from PySide6.QtWidgets import QApplication

        log_text: str = "\n".join(
            [formatted_message for formatted_message, _ in self.all_log_records]
        )
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(log_text)

    @Slot()
    def _export_logs(self) -> None:
        import zipfile
        from datetime import datetime
        from pathlib import Path

        log_dir = Path(config.log_directory)
        if not log_dir.is_dir():
            QMessageBox.warning(
                self,
                "Export Failed",
                f"Log directory does not exist or is not a directory: {log_dir}",
            )
            return

        log_files = [f for f in log_dir.glob("*.log*") if f.is_file()]
        if not log_files:
            QMessageBox.warning(
                self,
                "Export Failed",
                f"No log files found in the log directory: {log_dir}",
            )
            return

        try:
            home_dir = Path.home()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"lan_streamer_logs_{timestamp}.zip"
            zip_filepath = home_dir / zip_filename

            with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for file_path in log_files:
                    zip_file.write(file_path, arcname=file_path.name)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Logs successfully exported to:\n{zip_filepath}",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred while exporting logs:\n{e}",
            )

    def _refresh_log_display(self) -> None:
        self.log_display.clear()
        search_term: str = self.log_search_input.text().strip().lower()
        selected_level: str = self.log_level_filter.currentText()
        level_threshold: int = self._get_level_value(selected_level)
        matching_lines: List[str] = []
        for formatted_message, level_name in self.all_log_records:
            record_level_val: int = self._get_level_value(level_name)
            if record_level_val < level_threshold:
                continue
            if search_term and search_term not in formatted_message.lower():
                continue
            html_line: str = self._format_log_to_html(formatted_message, level_name)
            matching_lines.append(html_line)
        self.log_display.appendHtml("<br>".join(matching_lines))
        if self.log_autoscroll_checkbox.isChecked():
            self._scroll_to_bottom()

    def _get_level_value(self, level_name: str) -> int:
        levels: Dict[str, int] = {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
            "CRITICAL": 50,
        }
        return levels.get(level_name.upper(), 0)

    def _format_log_to_html(self, message: str, level_name: str) -> str:
        import html

        escaped_message: str = html.escape(message)
        colors: Dict[str, str] = {
            "DEBUG": "#7f8c8d",
            "INFO": "#2ecc71",
            "WARNING": "#f1c40f",
            "ERROR": "#e74c3c",
            "CRITICAL": "#e74c3c; font-weight: bold; background-color: #2c3e50;",
        }
        color: str = colors.get(level_name.upper(), "#ffffff")
        level_tag: str = f"[{level_name}]"
        colored_tag: str = (
            f'<span style="color: {color}; font-weight: bold;">{level_tag}</span>'
        )
        return escaped_message.replace(level_tag, colored_tag, 1)

    @Slot(str, str)
    def _on_log_emitted(self, formatted_message: str, level_name: str) -> None:
        self.all_log_records.append((formatted_message, level_name))
        if len(self.all_log_records) > 1000:
            self.all_log_records.pop(0)
        search_term: str = self.log_search_input.text().strip().lower()
        selected_level: str = self.log_level_filter.currentText()
        level_threshold: int = self._get_level_value(selected_level)
        record_level_val: int = self._get_level_value(level_name)
        if record_level_val >= level_threshold:
            if not search_term or search_term in formatted_message.lower():
                html_line: str = self._format_log_to_html(formatted_message, level_name)
                self.log_display.appendHtml(html_line)
                if self.log_autoscroll_checkbox.isChecked():
                    self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:

        self.log_display.moveCursor(QTextCursor.MoveOperation.End)

    def _disconnect_logging(self) -> None:
        if getattr(self, "_logging_connected", False):
            try:
                from .logging_handler import qt_log_handler

                qt_log_handler.emitter.log_emitted.disconnect(self._on_log_emitted)
            except RuntimeError, TypeError:
                pass
            self._logging_connected = False

    def closeEvent(self, event: QCloseEvent) -> None:
        self._disconnect_logging()
        super().closeEvent(event)

    def accept(self) -> None:
        self._disconnect_logging()
        super().accept()

    def reject(self) -> None:
        self._disconnect_logging()
        super().reject()


class MovieDetailView(QWidget):
    """
    Presents exhaustive movie structure, overview, and direct execution actions.
    Enforces strict typing and zero-abbreviation naming standard.
    """

    back_requested = Signal()

    def __init__(
        self, controller_instance: Controller, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.controller: Controller = controller_instance
        self.title_label: QLabel = QLabel()
        self.overview_label: QLabel = QLabel()
        self.poster_label: QLabel = QLabel()
        self.metadata_label: QLabel = QLabel()
        self.play_button: QPushButton = QPushButton("▶ Play Movie")

        self._setup_ui()
        self.controller.movie_selected.connect(self.populate_movie_details)
        self._current_movie_path: str = ""

    def _setup_ui(self) -> None:
        main_layout: QVBoxLayout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Header Panel
        header_layout: QHBoxLayout = QHBoxLayout()
        header_layout.setSpacing(20)

        back_button: QPushButton = QPushButton("← Back to Library")
        back_button.clicked.connect(self.back_requested.emit)
        header_layout.addWidget(back_button, 0, Qt.AlignmentFlag.AlignTop)

        self.poster_label.setFixedSize(180, 260)
        self.poster_label.setStyleSheet(
            "background-color: #222222; border: 1px solid #444444; border-radius: 6px;"
        )
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.poster_label, 0, Qt.AlignmentFlag.AlignTop)

        info_layout: QVBoxLayout = QVBoxLayout()
        info_layout.setSpacing(10)

        self.title_label.setFont(QFont("Inter", 24, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        self.metadata_label.setFont(QFont("Inter", 12))
        self.metadata_label.setStyleSheet("color: #aaaaaa;")
        info_layout.addWidget(self.metadata_label)

        self.overview_label.setFont(QFont("Inter", 13))
        self.overview_label.setWordWrap(True)
        self.overview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        info_layout.addWidget(self.overview_label)

        # Action Buttons Row
        actions_row_layout: QHBoxLayout = QHBoxLayout()
        actions_row_layout.setSpacing(10)

        self.play_button.setObjectName("accentButton")
        self.play_button.clicked.connect(self._on_play_clicked)
        actions_row_layout.addWidget(self.play_button)

        details_button: QPushButton = QPushButton("Movie Details")
        details_button.setObjectName("movieDetailsButton")
        details_button.clicked.connect(
            lambda: self.controller.movie_details_requested.emit(
                self.controller.selected_series_name, self._current_movie_path
            )
        )
        actions_row_layout.addWidget(details_button)

        actions_row_layout.addStretch()
        info_layout.addLayout(actions_row_layout)

        header_layout.addLayout(info_layout)
        main_layout.addLayout(header_layout)

        # Horizontal Divider Line
        divider_line: QFrame = QFrame()
        divider_line.setFrameShape(QFrame.Shape.HLine)
        divider_line.setFrameShadow(QFrame.Shadow.Sunken)
        divider_line.setStyleSheet("border-color: #333333;")
        main_layout.addWidget(divider_line)

        main_layout.addStretch()

    @Slot(str)
    def populate_movie_details(self, movie_name: str) -> None:
        if getattr(self.controller, "is_video_playing", False):
            return
        movie_record: Dict[str, Any] = self.controller.cached_library_data.get(
            movie_name, {}
        )
        self._current_movie_path = movie_record.get("path", "")

        movie_display_title: str = movie_record.get("tmdb_name") or movie_name
        self.title_label.setText(movie_display_title)
        self.overview_label.setText(
            movie_record.get("overview") or "No overview available."
        )

        year: int = movie_record.get("year", 0)
        runtime: int = movie_record.get("runtime", 0)
        rating: str = movie_record.get("rating", "")
        genre: str = movie_record.get("genre", "")

        metadata_parts = []
        if year:
            metadata_parts.append(str(year))
        if runtime:
            metadata_parts.append(f"{runtime} min")
        if rating:
            metadata_parts.append(f"★ {rating}")
        if genre:
            metadata_parts.append(genre)

        self.metadata_label.setText(" • ".join(metadata_parts))

        poster_path_string: str = movie_record.get("poster_path", "")
        pixmap_assigned: bool = False
        if poster_path_string:
            poster_path_object = Path(poster_path_string)
            if poster_path_object.is_file():
                pixmap_instance = QPixmap(str(poster_path_object))
                if not pixmap_instance.isNull():
                    self.poster_label.setPixmap(
                        pixmap_instance.scaled(
                            180,
                            260,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    pixmap_assigned = True

        if not pixmap_assigned:
            self.poster_label.clear()
            self.poster_label.setText("No Poster")

    @Slot()
    def _on_play_clicked(self) -> None:
        if self._current_movie_path:
            self.controller.playback_requested.emit(self._current_movie_path)
