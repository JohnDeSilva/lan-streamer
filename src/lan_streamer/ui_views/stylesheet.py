def get_application_stylesheet() -> str:
    """Returns a premium, rich dark mode stylesheet implementing modern aesthetic standards."""
    return """
    /* Main Background & Typography */
    QWidget {
        background-color: #0f0f11;
        color: #E2E8F0;
        font-family: 'Inter', 'Outfit', 'Roboto', sans-serif;
        font-size: 13px;
    }

    /* Dialog Windows */
    QDialog {
        background-color: #0f0f11;
        border: 1px solid #2d2d35;
        border-radius: 12px;
    }

    /* Standard Buttons */
    QPushButton {
        background-color: #1c1c22;
        border: 1px solid #3d3d47;
        border-radius: 6px;
        padding: 7px 14px;
        color: #F8FAFC;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #26262f;
        border-color: #2a82da;
        color: #38bdf8;
    }
    QPushButton:pressed {
        background-color: #121217;
    }
    QPushButton:disabled {
        background-color: #121215;
        color: #475569;
        border-color: #1e1e24;
    }

    /* Accent Buttons */
    QPushButton#accentButton {
        background-color: #2a82da;
        color: #ffffff;
        border: none;
    }
    QPushButton#accentButton:hover {
        background-color: #3592ea;
        color: #ffffff;
    }
    QPushButton#playButton, QPushButton#playEpisodeButton {
        background-color: #e05b35;
        color: #ffffff;
        border: none;
        font-size: 14px;
        padding: 8px 16px;
    }
    QPushButton#playButton:hover, QPushButton#playEpisodeButton:hover {
        background-color: #ea6b46;
        color: #ffffff;
    }

    /* Inputs & Selectors */
    QLineEdit, QComboBox {
        background-color: #1a1a1f;
        border: 1px solid #3d3d47;
        border-radius: 6px;
        padding: 6px 12px;
        color: #F8FAFC;
    }
    QLineEdit:focus, QComboBox:focus {
        border-color: #2a82da;
        background-color: #202027;
    }
    QComboBox::drop-down {
        border: none;
        padding-right: 10px;
    }
    QComboBox QAbstractItemView {
        background-color: #16161a;
        border: 1px solid #2d2d35;
        selection-background-color: #2a82da;
        selection-color: #ffffff;
    }

    /* List & Grid Cards */
    QListWidget {
        background-color: transparent;
        border: none;
    }
    QListWidget::item {
        background-color: #16161a;
        border: 1px solid #2d2d35;
        border-radius: 8px;
        margin: 5px;
        padding: 10px;
        color: #E2E8F0;
    }
    QListWidget::item:hover {
        background-color: #212126;
        border: 1px solid #2a82da;
    }
    QListWidget::item:selected {
        background-color: #2a82da;
        color: #ffffff;
        border: 1px solid #2a82da;
    }

    /* Tables & Trees */
    QTableWidget, QTreeWidget, QTreeView {
        background-color: #16161a;
        border: 1px solid #2d2d35;
        border-radius: 8px;
        gridline-color: transparent;
        color: #E2E8F0;
    }
    QTableWidget::item, QTreeWidget::item, QTreeView::item {
        padding: 6px;
        border-bottom: 1px solid #22222a;
    }
    QTableWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {
        background-color: #202025;
    }
    QTableWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {
        background-color: #2a82da;
        color: #ffffff;
    }
    QHeaderView::section {
        background-color: #1c1c22;
        color: #94A3B8;
        padding: 6px;
        border: none;
        border-bottom: 1px solid #2d2d35;
        font-weight: bold;
    }

    /* Tabs styling */
    QTabWidget::pane {
        border: 1px solid #2d2d35;
        border-radius: 8px;
        background-color: #16161a;
    }
    QTabBar::tab {
        background-color: #1c1c22;
        color: #94A3B8;
        padding: 8px 16px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
        border: 1px solid #2d2d35;
        border-bottom: none;
    }
    QTabBar::tab:selected {
        background-color: #16161a;
        color: #F8FAFC;
        border-bottom: 2px solid #2a82da;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background-color: #262630;
        color: #ffffff;
    }

    /* Sleek Scrollbars */
    QScrollBar:vertical {
        border: none;
        background-color: #0f0f11;
        width: 8px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background-color: #2d2d35;
        border-radius: 4px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #475569;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar:horizontal {
        border: none;
        background-color: #0f0f11;
        height: 8px;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background-color: #2d2d35;
        border-radius: 4px;
        min-width: 20px;
    }
    QScrollBar::handle:horizontal:hover {
        background-color: #475569;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }

    /* Progress Bars */
    QProgressBar {
        background-color: #1e1e24;
        border: 1px solid #3d3d47;
        border-radius: 6px;
        text-align: center;
        color: #ffffff;
        font-weight: bold;
    }
    QProgressBar::chunk {
        background-color: #2a82da;
        border-radius: 5px;
    }
    """
