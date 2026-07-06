import os
import sys
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QProgressBar,
    QApplication,
)
from PySide6.QtCore import Slot, QProcess
from PySide6.QtGui import QCloseEvent

from lan_streamer.ui_views.proxy import QMessageBox
from lan_streamer.system.updater import DownloadWorker, InstallWorker

logger: logging.Logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """
    Dialog displaying a new update version, release notes,
    and a progress bar while downloading the updated executable.
    """

    def __init__(
        self,
        current_version: str,
        new_version: str,
        release_notes: str,
        download_url: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        logger.info(
            f"Initializing UpdateDialog (current: {current_version}, new: {new_version})"
        )

        self.current_version = current_version
        self.new_version = new_version
        self.download_url = download_url
        self.worker: Optional[DownloadWorker] = None
        self.install_worker: Optional[InstallWorker] = None
        self.use_in_place = False

        self.setWindowTitle("Update Available")
        self.resize(600, 450)
        self.setMinimumSize(500, 350)

        # Main Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(15)
        self.main_layout.setContentsMargins(20, 20, 20, 20)

        # Header Title
        self.title_label = QLabel("A new version of LAN Streamer is available!")
        self.title_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #2a82da;"
        )
        self.main_layout.addWidget(self.title_label)

        # Version details
        self.version_label = QLabel(
            f"Current Version: {self.current_version}   →   New Version: {self.new_version}"
        )
        self.version_label.setStyleSheet(
            "font-size: 13px; color: #94A3B8; font-weight: 500;"
        )
        self.main_layout.addWidget(self.version_label)

        # Release notes title
        self.notes_title = QLabel("Release Notes:")
        self.notes_title.setStyleSheet("font-weight: bold; color: #E2E8F0;")
        self.main_layout.addWidget(self.notes_title)

        # Release notes text
        self.text_browser = QTextBrowser()
        self.text_browser.setMarkdown(release_notes)
        self.text_browser.setStyleSheet(
            "QTextBrowser { background-color: #16161a; border: 1px solid #2d2d35; border-radius: 8px; padding: 10px; color: #E2E8F0; }"
        )
        self.main_layout.addWidget(self.text_browser)

        # Buttons layout
        self.buttons_layout = QHBoxLayout()
        self.buttons_layout.addStretch()

        self.ignore_button = QPushButton("Ignore")
        self.ignore_button.clicked.connect(self.reject)
        self.buttons_layout.addWidget(self.ignore_button)

        self.download_button = QPushButton("Download")
        self.download_button.setObjectName("accentButton")
        self.download_button.clicked.connect(self.start_download)
        self.buttons_layout.addWidget(self.download_button)

        self.main_layout.addLayout(self.buttons_layout)

        # Progress elements (hidden initially)
        self.progress_container = QWidget()
        self.progress_layout = QVBoxLayout(self.progress_container)
        self.progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_layout.setSpacing(10)

        self.progress_label = QLabel("Downloading update...")
        self.progress_label.setStyleSheet("color: #94A3B8;")
        self.progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_layout.addWidget(self.progress_bar)

        self.main_layout.addWidget(self.progress_container)
        self.progress_container.setVisible(False)

    @Slot()
    def start_download(self) -> None:
        logger.info(
            f"UpdateDialog: starting download process for URL: {self.download_url}"
        )
        logger.info(
            f"UpdateDialog: checked frozen status: {getattr(sys, 'frozen', False)}, "
            f"platform: {sys.platform}"
        )
        self.ignore_button.setVisible(False)
        self.download_button.setVisible(False)
        self.progress_container.setVisible(True)

        self.use_in_place = sys.platform.startswith("linux") and getattr(
            sys, "frozen", False
        )
        download_path = None

        if self.use_in_place:
            try:
                executable_path = Path(sys.executable).resolve()
                download_path = executable_path.parent / f"{executable_path.name}.tmp"
                # Check write permission to the parent directory
                if os.access(executable_path.parent, os.W_OK):
                    logger.info(
                        f"UpdateDialog: Linux frozen environment detected. Using target directory of currently "
                        f"running executable to stage download: {download_path}"
                    )
                else:
                    logger.warning(
                        f"UpdateDialog: Linux frozen environment detected, but parent directory {executable_path.parent} "
                        f"is not writable. Falling back to updates directory."
                    )
                    self.use_in_place = False
            except Exception as exception:
                logger.warning(
                    f"UpdateDialog: Error checking in-place update feasibility: {exception}. "
                    f"Falling back to updates directory."
                )
                self.use_in_place = False

        if not self.use_in_place:
            asset_name = self.download_url.split("/")[-1]
            updates_directory = Path.home() / ".config" / "lan-streamer" / "updates"
            try:
                updates_directory.mkdir(parents=True, exist_ok=True)
                logger.info(
                    f"UpdateDialog: created updates directory: {updates_directory}"
                )
            except Exception:
                logger.exception(
                    "UpdateDialog: failed to create updates directory, using current directory"
                )
                updates_directory = Path(".")
            download_path = updates_directory / asset_name

        logger.info(
            f"UpdateDialog: determined staging path: {download_path} (in_place: {self.use_in_place})"
        )

        self.worker = DownloadWorker(self.download_url, str(download_path))
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    @Slot(int, int)
    def on_progress(self, bytes_read: int, total_bytes: int) -> None:
        if total_bytes > 0:
            percentage = int((bytes_read / total_bytes) * 100)
            self.progress_bar.setValue(percentage)
            megabytes_read = bytes_read / (1024 * 1024)
            megabytes_total = total_bytes / (1024 * 1024)
            self.progress_label.setText(
                f"Downloading update... {megabytes_read:.1f} MB / {megabytes_total:.1f} MB ({percentage}%)"
            )
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText("Downloading update...")

    @Slot(bool, str)
    def on_finished(self, success: bool, error_message_or_path: str) -> None:
        logger.info(
            f"UpdateDialog: download completed (success={success}, path_or_error={error_message_or_path})"
        )
        if success:
            if self.use_in_place:
                self.progress_label.setText("Installing update in-place...")
                logger.info(
                    f"UpdateDialog: starting in-place installation using InstallWorker (source: {error_message_or_path}, "
                    f"target: {sys.executable})"
                )
                self.install_worker = InstallWorker(
                    error_message_or_path, sys.executable
                )
                self.install_worker.finished.connect(self.on_install_finished)
                self.install_worker.start()
            else:
                self.progress_label.setText(
                    "Download complete! Launching updater and closing..."
                )
                self.progress_bar.setValue(100)

                program_path = Path(error_message_or_path)
                if sys.platform != "win32":
                    try:
                        logger.info(
                            f"UpdateDialog: making downloaded program executable at: {program_path}"
                        )
                        os.chmod(program_path, 0o755)
                    except Exception as exception:
                        logger.error(
                            f"UpdateDialog: failed to chmod downloaded update: {exception}"
                        )

                # Open/execute program
                if sys.platform == "darwin":
                    logger.info(
                        f"UpdateDialog: launching update on macOS using 'open': {program_path}"
                    )
                    QProcess.startDetached("open", [str(program_path)])
                else:
                    logger.info(f"UpdateDialog: launching update: {program_path}")
                    QProcess.startDetached(str(program_path))

                # Close the current running application
                self.accept()
                QApplication.quit()
        else:
            logger.error(f"UpdateDialog: download failed: {error_message_or_path}")
            QMessageBox.critical(
                self,
                "Download Failed",
                f"Failed to download the update:\n{error_message_or_path}",
            )
            self.progress_container.setVisible(False)
            self.ignore_button.setVisible(True)
            self.download_button.setVisible(True)

    @Slot(bool, str)
    def on_install_finished(self, success: bool, error_message: str) -> None:
        logger.info(
            f"UpdateDialog: in-place installation completed (success={success}, error_message={error_message})"
        )
        if success:
            logger.info(
                f"UpdateDialog: in-place installation successful. Launching updated executable "
                f"'{sys.executable}' and quitting."
            )
            self.progress_label.setText(
                "Installation complete! Launching updated version..."
            )
            self.progress_bar.setValue(100)

            # Start the updated executable
            QProcess.startDetached(sys.executable)

            self.accept()
            QApplication.quit()
        else:
            logger.error(f"UpdateDialog: in-place installation failed: {error_message}")
            QMessageBox.critical(
                self,
                "Installation Failed",
                f"Failed to install the update in-place:\n{error_message}",
            )
            self.progress_container.setVisible(False)
            self.ignore_button.setVisible(True)
            self.download_button.setVisible(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info(
            f"UpdateDialog: close event triggered (worker_running={self.worker and self.worker.isRunning()})"
        )
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Download",
                "An update is downloading. Do you want to cancel the download and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                logger.info("UpdateDialog: cancelling active download worker")
                self.worker.cancel()
                self.worker.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
