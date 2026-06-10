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
from lan_streamer.system.updater import DownloadWorker

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
        logger.info(f"Starting update download from: {self.download_url}")
        self.ignore_button.setVisible(False)
        self.download_button.setVisible(False)
        self.progress_container.setVisible(True)

        asset_name = self.download_url.split("/")[-1]
        updates_dir = Path.home() / ".config" / "lan-streamer" / "updates"
        try:
            updates_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.exception(
                "Failed to create updates directory, using current directory"
            )
            updates_dir = Path(".")

        download_path = updates_dir / asset_name

        self.worker = DownloadWorker(self.download_url, str(download_path))
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    @Slot(int, int)
    def on_progress(self, bytes_read: int, total_bytes: int) -> None:
        if total_bytes > 0:
            pct = int((bytes_read / total_bytes) * 100)
            self.progress_bar.setValue(pct)
            mb_read = bytes_read / (1024 * 1024)
            mb_total = total_bytes / (1024 * 1024)
            self.progress_label.setText(
                f"Downloading update... {mb_read:.1f} MB / {mb_total:.1f} MB ({pct}%)"
            )
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText("Downloading update...")

    @Slot(bool, str)
    def on_finished(self, success: bool, error_msg_or_path: str) -> None:
        if success:
            logger.info(f"Download complete: {error_msg_or_path}")
            self.progress_label.setText(
                "Download complete! Launching updater and closing..."
            )
            self.progress_bar.setValue(100)

            program_path = Path(error_msg_or_path)
            if sys.platform != "win32":
                try:
                    os.chmod(program_path, 0o755)
                except Exception as e:
                    logger.error(f"Failed to chmod downloaded update: {e}")

            # Open/execute program
            if sys.platform == "darwin":
                QProcess.startDetached("open", [str(program_path)])
            else:
                QProcess.startDetached(str(program_path))

            # Close the current running application
            self.accept()
            QApplication.quit()
        else:
            logger.error(f"Download failed: {error_msg_or_path}")
            QMessageBox.critical(
                self,
                "Download Failed",
                f"Failed to download the update:\n{error_msg_or_path}",
            )
            self.progress_container.setVisible(False)
            self.ignore_button.setVisible(True)
            self.download_button.setVisible(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Download",
                "An update is downloading. Do you want to cancel the download and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.worker.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
