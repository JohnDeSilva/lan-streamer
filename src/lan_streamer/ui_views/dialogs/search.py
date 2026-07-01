"""
Search dialog with debounced autocomplete for series and movie discovery.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lan_streamer import db
from lan_streamer.ui_views.proxy import QPixmap

logger = logging.getLogger(__name__)


class SearchDialog(QDialog):
    """
    Modal dialog for searching series and movies by name with debounced autocomplete.

    Emits ``item_selected(item_name, library_name, item_type)`` when a result is
    chosen by the user via click or activation (Enter / double-click).
    ``item_type`` is ``\"series\"`` or ``\"movie\"``.

    .. py:data:: item_selected

        :type: Signal(str, str, str)
        :emit: ``item_selected(item_name, library_name, item_type)``
    """

    item_selected = Signal(str, str, str)  # item_name, library_name, item_type

    def __init__(
        self,
        library_name: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Initialise the search dialog.

        Args:
            library_name: Optional library name to restrict the search scope.
            parent: Optional parent QWidget.
        """
        super().__init__(parent)
        self._library_name: Optional[str] = library_name
        self._cached_icons: Dict[str, QIcon] = {}

        title = "Search"
        if library_name:
            title += f" - {library_name}"
        self.setWindowTitle(title)
        self.resize(450, 500)

        self._setup_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the dialog layout: search input + results list."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(
            """
            QLineEdit {
                padding: 8px 12px;
                font-size: 14px;
                border: 2px solid #444444;
                border-radius: 6px;
                background-color: #1a1a1a;
                color: #f3f4f6;
            }
            QLineEdit:focus {
                border-color: #2a82da;
            }
            """
        )
        layout.addWidget(self.search_input)

        # Results list
        self.results_list = QListWidget()
        self.results_list.setStyleSheet(
            """
            QListWidget {
                background-color: #222222;
                border: 1px solid #444444;
                border-radius: 6px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #333333;
                color: #f3f4f6;
            }
            QListWidget::item:hover {
                background-color: #2a82da;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #1a6bb5;
                color: #ffffff;
            }
            """
        )
        layout.addWidget(self.results_list)

        # Debounce timer (single-shot, 300 ms)
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setInterval(300)
        self.debounce_timer.setSingleShot(True)

    def _wire_signals(self) -> None:
        """Connect UI signals to their slots."""
        self.search_input.textChanged.connect(self._on_text_changed)
        self.debounce_timer.timeout.connect(self._execute_search)
        self.results_list.itemClicked.connect(self._on_item_clicked)
        self.results_list.itemActivated.connect(self._on_item_clicked)

    # ------------------------------------------------------------------
    # Search logic
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_text_changed(self, text: str) -> None:
        """Restart the debounce timer whenever the query text changes."""
        self.debounce_timer.stop()
        if len(text.strip()) < 2:
            self.results_list.clear()
            return
        self.debounce_timer.start()

    @Slot()
    def _execute_search(self) -> None:
        """Perform the actual database search (called after debounce)."""
        query_text = self.search_input.text().strip()
        if len(query_text) < 2:
            return

        library_names: Optional[List[str]] = None
        if self._library_name:
            library_names = [self._library_name]

        results = db.search_media_names(query_text, library_names)

        self.results_list.clear()
        for result in results:
            item_name = result.get("name", "")
            result_library_name = result.get("library_name", "")
            poster_path = result.get("poster_path", "")
            item_type = result.get("type", "series")

            type_label = "Series" if item_type == "series" else "Movie"
            display_text = f"{item_name}\n({type_label} - {result_library_name})"
            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.ItemDataRole.UserRole, item_name)
            list_item.setData(Qt.ItemDataRole.UserRole + 1, result_library_name)
            list_item.setData(Qt.ItemDataRole.UserRole + 2, item_type)
            list_item.setToolTip(f"{item_name} ({type_label}, {result_library_name})")

            # Try to load poster thumbnail
            if poster_path:
                self._assign_thumbnail_icon(list_item, poster_path)

            self.results_list.addItem(list_item)

        if not results:
            empty_item = QListWidgetItem("No results found")
            empty_item.setFlags(empty_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            empty_item.setForeground(QColor(136, 136, 136))
            self.results_list.addItem(empty_item)

    def _assign_thumbnail_icon(
        self, item_target: QListWidgetItem, poster_path_value: str
    ) -> None:
        """Load a 32x48 thumbnail icon for the given poster path into the item.

        Results are cached in ``self._cached_icons`` by path to avoid
        repeated disk reads.
        """
        cache_key = f"search_{poster_path_value}"
        if cache_key in self._cached_icons:
            item_target.setIcon(self._cached_icons[cache_key])
            return

        poster_path_object = Path(poster_path_value)
        if poster_path_object.is_file():
            pixmap_instance = QPixmap(str(poster_path_object))
            if not pixmap_instance.isNull():
                scaled_pixmap = pixmap_instance.scaled(
                    32,
                    48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                loaded_icon = QIcon(scaled_pixmap)
                self._cached_icons[cache_key] = loaded_icon
                item_target.setIcon(loaded_icon)

    # ------------------------------------------------------------------
    # User interaction
    # ------------------------------------------------------------------

    @Slot(QListWidgetItem)
    def _on_item_clicked(self, item_target: QListWidgetItem) -> None:
        """Emit ``item_selected`` with the chosen item and close dialog."""
        item_name = item_target.data(Qt.ItemDataRole.UserRole)
        result_library_name = item_target.data(Qt.ItemDataRole.UserRole + 1)
        item_type = item_target.data(Qt.ItemDataRole.UserRole + 2) or "series"
        if item_name and result_library_name:
            logger.info(
                "Search result selected: '%s' (Type: %s, Library: %s)",
                item_name,
                item_type,
                result_library_name,
            )
            self.item_selected.emit(item_name, result_library_name, item_type)
            self.accept()
