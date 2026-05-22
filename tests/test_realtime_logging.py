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


def test_settings_dialog_export_logs(qtbot: QtBot, tmp_path, monkeypatch) -> None:
    import zipfile
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    from lan_streamer.config import config

    # 1. Setup temporary directories for logs and home
    temp_log_dir = tmp_path / "logs"
    temp_log_dir.mkdir()
    temp_home_dir = tmp_path / "home"
    temp_home_dir.mkdir()

    # Create dummy log files
    dummy_log_1 = temp_log_dir / "app.log"
    dummy_log_1.write_text("Log entry 1")
    dummy_log_2 = temp_log_dir / "db.log.2026-05-22"
    dummy_log_2.write_text("Log entry 2")

    # Mock config.log_directory and Path.home()
    monkeypatch.setattr(config, "log_directory", str(temp_log_dir))
    monkeypatch.setattr(Path, "home", lambda: temp_home_dir)

    # Mock QMessageBox static methods
    info_calls = []
    warning_calls = []
    critical_calls = []

    def mock_info(parent, title, text):
        info_calls.append((title, text))
        return QMessageBox.StandardButton.Ok

    def mock_warning(parent, title, text):
        warning_calls.append((title, text))
        return QMessageBox.StandardButton.Ok

    def mock_critical(parent, title, text):
        critical_calls.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", mock_info)
    monkeypatch.setattr(QMessageBox, "warning", mock_warning)
    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    # Instantiate dialog
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    # 2. Test successful export
    dialog._export_logs()

    assert len(info_calls) == 1
    assert "Export Successful" in info_calls[0][0]

    # Verify zip file was created in home directory and has the correct contents
    zip_files = list(temp_home_dir.glob("lan_streamer_logs_*.zip"))
    assert len(zip_files) == 1
    zip_filepath = zip_files[0]

    with zipfile.ZipFile(zip_filepath, "r") as zip_ref:
        namelist = zip_ref.namelist()
        assert "app.log" in namelist
        assert "db.log.2026-05-22" in namelist
        assert zip_ref.read("app.log") == b"Log entry 1"
        assert zip_ref.read("db.log.2026-05-22") == b"Log entry 2"

    # 3. Test empty log directory
    # Clear dummy files
    dummy_log_1.unlink()
    dummy_log_2.unlink()
    dialog._export_logs()
    assert len(warning_calls) == 1
    assert "Export Failed" in warning_calls[0][0]
    assert "No log files found" in warning_calls[0][1]

    # 4. Test non-existent log directory
    monkeypatch.setattr(config, "log_directory", "/nonexistent/path/for/logs")
    dialog._export_logs()
    assert len(warning_calls) == 2
    assert "Export Failed" in warning_calls[1][0]
    assert "Log directory does not exist" in warning_calls[1][1]

    dialog.reject()
