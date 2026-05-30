import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QFont


logger = logging.getLogger(__name__)


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

    def init_from_tree(
        self,
        tree: Dict[str, Any],
        library_order: Optional[List[str]] = None,
        library_config_source: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """Called once with the pre-discovery tree structure."""
        self._library_order = [lib for lib in library_order if lib in tree] if library_order is not None else list(tree.keys())
        self._libraries = {}
        self._root_states = {}

        if library_config_source is None:
            from lan_streamer.system.config import config
            library_config_source = config.libraries

        for lib_name in self._library_order:
            lib_data = tree[lib_name]
            raw_roots = lib_data.get("roots", {})
            config_paths = library_config_source.get(lib_name, {}).get("paths", [])
            roots = []
            for path in config_paths:
                if path in raw_roots:
                    roots.append(path)
            for path in raw_roots.keys():
                if path not in roots:
                    roots.append(path)

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

    def init_from_tree(
        self,
        tree: Dict[str, Any],
        library_order: Optional[List[str]] = None,
        library_config_source: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """Builds the initial tree with all folder, season, and file nodes in pending state."""
        self._tree.clear()
        self._lib_nodes.clear()
        self._lib_types.clear()
        self._folder_nodes.clear()
        self._season_nodes.clear()
        self._file_nodes.clear()

        self._library_order = [lib for lib in library_order if lib in tree] if library_order is not None else list(tree.keys())

        if library_config_source is None:
            from lan_streamer.system.config import config
            library_config_source = config.libraries

        for lib_name in self._library_order:
            lib_data = tree[lib_name]
            lib_type: str = lib_data.get("type", "tv")
            self._lib_types[lib_name] = lib_type

            lib_item = QTreeWidgetItem(
                self._tree, [f"{self._ICON_PENDING}  {lib_name}"]
            )
            lib_item.setForeground(0, QColor("#aaaaaa"))
            lib_font = QFont("Inter", 11, QFont.Weight.Bold)
            lib_item.setFont(0, lib_font)
            self._lib_nodes[lib_name] = lib_item

            raw_roots = lib_data.get("roots", {})
            config_paths = library_config_source.get(lib_name, {}).get("paths", [])
            roots = []
            for path in config_paths:
                if path in raw_roots:
                    roots.append(path)
            for path in raw_roots.keys():
                if path not in roots:
                    roots.append(path)

            for root_dir in roots:
                folders_dict = raw_roots[root_dir]
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
