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
