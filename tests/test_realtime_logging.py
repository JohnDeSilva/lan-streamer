import logging
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from lan_streamer.logging_handler import qt_log_handler
from lan_streamer.ui_views import SettingsDialog


def test_qt_log_handler_buffer() -> None:
    # Clear the handler buffer
    qt_log_handler.buffer.clear()

    # Create a test log record
    logger: logging.Logger = logging.getLogger("test_logger")
    logger.setLevel(logging.DEBUG)

    formatter: logging.Formatter = logging.Formatter("[%(levelname)s] %(message)s")
    qt_log_handler.setFormatter(formatter)

    # Add handler to logger if not present
    if qt_log_handler not in logger.handlers:
        logger.addHandler(qt_log_handler)

    # Log messages
    logger.info("Info log message")
    logger.debug("Debug log message")

    assert len(qt_log_handler.buffer) == 2
    assert qt_log_handler.buffer[0] == ("[INFO] Info log message", "INFO")
    assert qt_log_handler.buffer[1] == ("[DEBUG] Debug log message", "DEBUG")


def test_settings_dialog_logs_tab(qtbot: QtBot) -> None:
    # Clear and pre-populate logs
    qt_log_handler.buffer.clear()
    qt_log_handler.buffer.append(("[INFO] Initial info message", "INFO"))
    qt_log_handler.buffer.append(("[WARNING] Initial warning message", "WARNING"))

    # Create settings dialog
    dialog: SettingsDialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # Check if the initial logs are loaded
    assert len(dialog.all_log_records) == 2
    assert dialog.all_log_records[0] == ("[INFO] Initial info message", "INFO")

    # Simulate receiving a real-time log record
    qt_log_handler.emitter.log_emitted.emit("[ERROR] Real-time error message", "ERROR")

    # Verify that the new record is appended to the dialog's local records
    assert len(dialog.all_log_records) == 3
    assert dialog.all_log_records[-1] == ("[ERROR] Real-time error message", "ERROR")

    # Verify that the text display has updated
    text_content: str = dialog.log_display.toPlainText()
    assert "Real-time error message" in text_content
    assert "[ERROR]" in text_content

    # Disconnect logging correctly on close
    dialog.reject()


def test_settings_dialog_filters_and_actions(qtbot: QtBot) -> None:
    # Pre-populate logs
    qt_log_handler.buffer.clear()
    qt_log_handler.buffer.append(("[DEBUG] Debug details", "DEBUG"))
    qt_log_handler.buffer.append(("[INFO] Normal operation", "INFO"))
    qt_log_handler.buffer.append(("[WARNING] System warning", "WARNING"))
    qt_log_handler.buffer.append(("[ERROR] System error", "ERROR"))

    dialog: SettingsDialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # 1. Test Min Level filter (INFO) - should display INFO, WARNING, ERROR (not DEBUG)
    dialog.log_level_filter.setCurrentText("INFO")
    text_content: str = dialog.log_display.toPlainText()
    assert "Debug details" not in text_content
    assert "Normal operation" in text_content
    assert "System warning" in text_content
    assert "System error" in text_content

    # 2. Test Min Level filter (WARNING) - should display WARNING, ERROR
    dialog.log_level_filter.setCurrentText("WARNING")
    text_content = dialog.log_display.toPlainText()
    assert "Normal operation" not in text_content
    assert "System warning" in text_content
    assert "System error" in text_content

    # 3. Test text search filtering (search "error")
    dialog.log_level_filter.setCurrentText("All")
    dialog.log_search_input.setText("error")
    text_content = dialog.log_display.toPlainText()
    assert "System warning" not in text_content
    assert "System error" in text_content

    # 4. Test Copy All functionality
    dialog.log_search_input.setText("")
    dialog._copy_logs_to_clipboard()
    clipboard: QApplication.clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard_text: str = clipboard.text()
        assert "Normal operation" in clipboard_text

    # 5. Test Clear View functionality
    dialog._clear_log_view()
    assert len(dialog.all_log_records) == 0
    assert dialog.log_display.toPlainText() == ""

    dialog.reject()
