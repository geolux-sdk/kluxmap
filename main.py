import os
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from mainWindow import KLuxMap, resource_path

TITLE = "KLuxMap V1.0.2"
APP_NAME = "KLuxMap"
APP_DIR = Path.home() / f".{APP_NAME}"
LOG_DIR = APP_DIR / "log"
SPLASH_IMAGE = "splash_screen.png"


def _setup_logging() -> None:
    """Configure loguru sinks: DEBUG to file (10 MB rotation, 14-day retention); console only when debug env is set."""

    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.remove()
    file_path = LOG_DIR / f"{APP_NAME}_{datetime.now():%Y%m%d_%H%M%S}.log"
    logger.add(
        file_path,
        level="DEBUG",
        rotation="10 MB",
        retention="14 days",
    )

    debug_env = os.getenv("DEBUG", "").lower() in {"1", "true", "yes", "debug"}
    if debug_env:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.debug("Console logger disabled (set DEBUG=1 to enable)")

    logger.info(f"loguru initialized. Log file: {file_path}")


def main():
    # Ensure logger sinks are set up (no settings.json persistence)
    _setup_logging()

    QApplication.setStyle("Fusion")
    app = QApplication(sys.argv)
    app.setStyleSheet(
        """     
        QGroupBox {font-family: Segoe UI; font-weight: bold; font-size: 12px;} 
        QPushButton {font-family: Segoe UI;  font-size: 12px;}
        QLabel {font-family: Segoe UI;  font-size: 12px;}
        QLineEdit {font-family: Segoe UI; font-size: 12px;}
        QCheckBox {font-family: Segoe UI; font-size: 12px;}
        QRadioButton {font-family: Segoe UI; font-size: 12px;}
        QComboBox {font-family: Segoe UI; font-size: 12px;}
        QTabWidget {font-family: Segoe UI; font-size: 12px;}
        QStatusBar {font-family: Segoe UI; padding-left: 10px; background: #C0C0C0; color:black;}
        QListWidget {font-family: Segoe UI; font-size: 14px;}
        QListWidget::item {font-family:  Segoe UI; font-size: 14px; padding: 4px;}
        QTableWidget {font-family: Segoe UI; font-size: 12px;}
        QTableWidget::item { padding: 4px; }
        QTableWidget::item:selected {background-color: #3399FF; color: black;}
        QListWidget::item:selected {background-color: #3399FF;  color: white;}
        QListWidget::item:selected:!active {background-color: #3399FF; color: white;}
        """
    )

    splash_pix = QPixmap(resource_path(SPLASH_IMAGE))
    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.setMask(splash_pix.mask())
    splash.show()

    # try:
    win = KLuxMap(title= TITLE)
    win.show()
    # except Exception as err:
    #     logger.critical(repr(err))
    #     sys.exit(1)

    splash.finish(win)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
