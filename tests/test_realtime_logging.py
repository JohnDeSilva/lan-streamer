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


def test_config_path_expansion(tmp_path, monkeypatch) -> None:
    import json
    import importlib
    from pathlib import Path

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    config_dir = fake_home / ".config" / "lan-streamer"
    config_dir.mkdir(parents=True)
    temp_config_file = config_dir / "config.json"

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("HOME", str(fake_home))

    config_data = {
        "database_path": "~/library.db",
        "log_directory": "~/logs",
        "cache_directory": "~/cache",
        "backup_directory": "~/backups",
    }
    with open(temp_config_file, "w") as f:
        json.dump(config_data, f)

    import lan_streamer.config

    try:
        importlib.reload(lan_streamer.config)
        cfg = lan_streamer.config.config

        expected_db = str(fake_home / "library.db")
        expected_log = str(fake_home / "logs")
        expected_cache = str(fake_home / "cache")
        expected_backup = str(fake_home / "backups")

        assert cfg.database_path == expected_db
        assert cfg.log_directory == expected_log
        assert cfg.cache_directory == expected_cache
        assert cfg.backup_directory == expected_backup
    finally:
        monkeypatch.undo()
        importlib.reload(lan_streamer.config)


def test_divided_service_logging_realtime_flow(tmp_path) -> None:
    import logging
    from lan_streamer.config import config
    from lan_streamer.logging_handler import (
        setup_qt_logging,
        qt_log_handler,
        SERVICE_LOGGERS,
    )

    # Use temporary directory for logs
    config.log_directory = str(tmp_path)
    config.divide_logs_by_service = True

    # Setup the logger configuration
    log_formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")

    # Save original handlers and propagate settings to restore later
    original_handlers = {}
    original_propagate = {}

    # Clear existing handlers from root and service loggers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    for logger_name in SERVICE_LOGGERS:
        lg = logging.getLogger(logger_name)
        original_handlers[logger_name] = lg.handlers[:]
        original_propagate[logger_name] = lg.propagate
        lg.handlers.clear()

    qt_log_handler.buffer.clear()

    try:
        # Re-run file configuration helper setup from main.py
        # To simulate main.py behavior without initializing whole QApplication
        logger_to_filename = {
            "lan_streamer.db": "db.log",
            "lan_streamer.backend": "backend.log",
            "lan_streamer.scanner": "scanner.log",
            "lan_streamer.jellyfin": "jellyfin.log",
            "lan_streamer.tmdb": "tmdb.log",
            "lan_streamer.player_widget": "player.log",
            "lan_streamer.player": "player.log",
            "lan_streamer.backup": "backup.log",
            "lan_streamer.opensubtitles": "opensubtitles.log",
            "lan_streamer.wakelock": "wakelock.log",
            "lan_streamer.ui_views": "ui.log",
            "lan_streamer.main": "ui.log",
            "lan_streamer.renamer": "renamer.log",
        }

        file_handlers = {}

        def add_file_handler(
            logger_object: logging.Logger,
            filename: str,
            formatter: logging.Formatter,
        ) -> None:
            from logging.handlers import TimedRotatingFileHandler

            if filename not in file_handlers:
                handler = TimedRotatingFileHandler(
                    filename,
                    when="midnight",
                    interval=1,
                    backupCount=config.max_log_retention_days,
                )
                handler.setFormatter(formatter)
                file_handlers[filename] = handler
            else:
                handler = file_handlers[filename]
            logger_object.addHandler(handler)
            logger_object.propagate = False

        for logger_name in SERVICE_LOGGERS:
            filename = logger_to_filename.get(logger_name, "app.log")
            add_file_handler(
                logging.getLogger(logger_name),
                str(tmp_path / filename),
                log_formatter,
            )

        setup_qt_logging(log_formatter)

        # 1. Test standard service logger (e.g. lan_streamer.main)
        main_logger = logging.getLogger("lan_streamer.main")
        main_logger.setLevel(logging.INFO)
        main_logger.info("Test message main")

        # 2. Test sub-logger of a service logger (e.g. lan_streamer.db.session)
        db_sub_logger = logging.getLogger("lan_streamer.db.session")
        db_sub_logger.setLevel(logging.WARNING)
        db_sub_logger.warning("Test message db session")

        db_log_file = tmp_path / "db.log"
        ui_log_file = tmp_path / "ui.log"

        # Explicitly close file handlers to flush to disk
        for handler in file_handlers.values():
            handler.close()

        assert db_log_file.exists()
        assert ui_log_file.exists()

        with open(db_log_file, "r") as f:
            db_content = f.read()
            assert "Test message db session" in db_content

        with open(ui_log_file, "r") as f:
            ui_content = f.read()
            assert "Test message main" in ui_content

        # Assertions for qt_log_handler buffer
        buffer_records = list(qt_log_handler.buffer)
        assert len(buffer_records) == 2
        assert any("Test message main" in record[0] for record in buffer_records)
        assert any("Test message db session" in record[0] for record in buffer_records)

    finally:
        # Restore original handlers and propagate settings
        for logger_name in SERVICE_LOGGERS:
            lg = logging.getLogger(logger_name)
            for h in lg.handlers[:]:
                h.close()
                lg.removeHandler(h)
            for h in original_handlers[logger_name]:
                lg.addHandler(h)
            lg.propagate = original_propagate[logger_name]


def test_set_application_log_level() -> None:
    import logging
    from lan_streamer.logging_handler import set_application_log_level, SERVICE_LOGGERS

    root_logger = logging.getLogger()
    original_root_level = root_logger.level
    original_service_levels = {
        name: logging.getLogger(name).level for name in SERVICE_LOGGERS
    }

    try:
        set_application_log_level("DEBUG")
        assert root_logger.level == logging.DEBUG
        for name in SERVICE_LOGGERS:
            assert logging.getLogger(name).level == logging.DEBUG

        set_application_log_level("WARNING")
        assert root_logger.level == logging.WARNING
        for name in SERVICE_LOGGERS:
            assert logging.getLogger(name).level == logging.WARNING
    finally:
        root_logger.setLevel(original_root_level)
        for name in SERVICE_LOGGERS:
            logging.getLogger(name).setLevel(original_service_levels[name])
