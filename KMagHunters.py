import os
import shutil
import sys

os.environ.setdefault("QT_API", "pyside6")  # 선택사항

import matplotlib

matplotlib.use("QtAgg")  # pyplot import 전에 단 1회

from loguru import logger
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplashScreen,
    QTabWidget,
)

from CalibrationFlightWidget import CalibrationFlightWidget
from DataManager import DataManager
from FligthPlotWidget import FlightPlotWidget
from LinePlotWidget import LinePlotWidget
from myConvertDlg import (
    ConvertDataDialog,
    convert_with_progress,
)
from myResource import load_SEC_file, make_project_subfolder, resource_path
from mySettings import config, mySettings
from myWidgets import ConfigDataSettingsDialog, browse_directory, browse_files

SPLASH_IMAGE = "splash_screen.png"
VIEWER_ICON = "viewer.png"
TITLE = "KMagHunters NEO V0.0.1"


class KMagHunters(QMainWindow):
    projectOpened = Signal(str)
    projectReset = Signal()

    def __init__(self):
        super().__init__()
        self.settings = mySettings()

        logger.info("Progrma Start")
        self.cfg = self.settings.settings
        self.db = DataManager(self.settings)
        self.initUI()
        self.resize(1400, 900)

    def initUI(self):
        self.setWindowTitle(TITLE)
        self.setWindowIcon(QIcon(resource_path(VIEWER_ICON)))
        self.setWindowFlags(
            Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint  # ⬅️ 최대화 버튼 추가
            | Qt.WindowCloseButtonHint
        )
        self.createMenuBar()

        # ─── 탭 위젯 생성 ────────────────────────────────────
        self.tabs = QTabWidget(self)

        self.CalibPlotWidget = CalibrationFlightWidget(self.settings, self.db)
        self.LinePlotWidget = LinePlotWidget(self.settings, self.db)
        self.FligtPlotWidget = FlightPlotWidget(self.settings, self.db)

        self.tabs.addTab(self.CalibPlotWidget, "Calibration Flight")
        self.tabs.addTab(self.FligtPlotWidget, "DRONE DATA")
        self.tabs.addTab(self.LinePlotWidget, "SCAN LINE DATA")
        self.tabs.setCurrentIndex(1)
        self._previous_tab_index = self.tabs.currentIndex()

        self.setCentralWidget(self.tabs)

        self.connectSignals()

    def connectSignals(self):
        """모든 시그널-슬롯 연결"""
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.openProject_action.triggered.connect(self.openProjectFolder)
        self.resetProject_action.triggered.connect(self.resetProjectFolder)
        self.convert_action.triggered.connect(self.convertDataToCSV)
        self.import_SEC_files_action.triggered.connect(self.import_SEC_files)
        self.exit_action.triggered.connect(self.close)
        self.config_action.triggered.connect(
            lambda checked=False: ConfigDataSettingsDialog(self).exec()
        )
        self.about_action.triggered.connect(self.showAboutDialog)

        for w in (self.FligtPlotWidget, self.CalibPlotWidget, self.LinePlotWidget):
            self.projectOpened.connect(w.on_project_opened)
            self.projectReset.connect(w.on_project_reset)

    def on_tab_changed(self, index):
        logger.debug(f"on_tab_changed {index} from {self._previous_tab_index}")
        if index == 2:
            self.LinePlotWidget.initialize()

        self._previous_tab_index = index

    def closeEvent(self, event):
        user_response = QMessageBox.question(
            self,
            "Exit Confirmation",
            "Are you sure you want to exit?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if user_response == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()
        self.settings.write(self.settings.settings)

    def createMenuBar(self):
        menu_bar = self.menuBar()

        # Project 메뉴
        project_menu = menu_bar.addMenu("&Project")

        self.openProject_action = QAction("&Open Project Folder", self)
        self.openProject_action.setShortcut("Ctrl+O")
        self.openProject_action.setStatusTip("Open a project folder")
        project_menu.addAction(self.openProject_action)

        self.resetProject_action = QAction("&Reset Project Folder", self)
        self.resetProject_action.setShortcut("Ctrl+R")
        self.resetProject_action.setStatusTip("Reset Data in project folder")
        project_menu.addAction(self.resetProject_action)

        self.exit_action = QAction("&Exit", self)
        self.exit_action.setShortcut("Ctrl+X")
        self.exit_action.setStatusTip("Exit application")
        project_menu.addAction(self.exit_action)

        # Convert 메뉴
        convert_menu = menu_bar.addMenu("&Convert")

        self.convert_action = QAction("&Convert to CSV", self)
        self.convert_action.setShortcut("Ctrl+C")
        self.convert_action.setStatusTip("Convert Data to CSV")
        convert_menu.addAction(self.convert_action)

        self.import_SEC_files_action = QAction("Import IAGA-2002 FILE", self)
        self.import_SEC_files_action.setStatusTip("import IAGA-2002 file open")
        convert_menu.addAction(self.import_SEC_files_action)

        self.config_action = QAction("&Boundary Info", self)
        self.config_action.setShortcut("Ctrl+B")
        self.config_action.setStatusTip("Boundary Information")
        convert_menu.addAction(self.config_action)

        # Help 메뉴
        help_menu = menu_bar.addMenu("Help")

        self.about_action = QAction(QIcon(), "About", self)
        self.about_action.setStatusTip("Show information about this application")
        help_menu.addAction(self.about_action)

        # 초기 비활성화
        self.resetProject_action.setEnabled(False)
        self.convert_action.setEnabled(False)
        self.import_SEC_files_action.setEnabled(False)
        self.config_action.setEnabled(False)

    def showAboutDialog(self):
        QMessageBox.about(
            self,
            "About",
            "This is the KMagHunters application \nfor magnetic data viewing, \ndeveloped by KIGAM and GEOLUX.",
        )

    def menu_action_enable(self):
        self.resetProject_action.setEnabled(True)
        self.convert_action.setEnabled(True)
        self.import_SEC_files_action.setEnabled(True)
        self.config_action.setEnabled(True)

        self.FligtPlotWidget.actionEnable()
        self.LinePlotWidget.actionEnable()
        self.CalibPlotWidget.actionEnable()

    def openProjectFolder(self):
        logger.debug("Event : openProjectFolder")
        default = self.cfg["init"].get("project_path", "")
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Folder", os.path.dirname(default)
        )
        if folder_path:
            logger.debug(f"openProjectFolder {folder_path}")
            self.cfg["init"]["project_path"] = folder_path
            config.set_path(os.path.join(folder_path, "project_settings.json"))
            config.load()
            config.set("project_path", folder_path, save=True)
            make_project_subfolder(".processed")

            self.openProject_action.setEnabled(False)
            self.menu_action_enable()

            self.projectOpened.emit(folder_path)

    def resetProjectFolder(self):
        logger.debug("Event : resetProjectFolder")

        project_path = config.get("project_path", "")
        if not project_path:
            logger.debug("No project path found")
            return

        # 경고 메시지
        reply = QMessageBox.warning(
            self,
            "WARNING",
            "All data in the project folder will be deleted.\n"
            "This action cannot be undone.\n\n"
            f"Path: {project_path}\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # 폴더 내 모든 파일/폴더 삭제
                for item in os.listdir(project_path):
                    item_path = os.path.join(project_path, item)
                    logger.debug(f"Deleting item: {item_path}")
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)

                logger.info(f"All data deleted in project folder: {project_path}")

                QMessageBox.information(
                    self,
                    "Completed",
                    "All data in the project folder has been deleted.",
                    QMessageBox.Ok,
                )
                config.clear()
                config.set_path(os.path.join(project_path, "project_settings.json"))
                config.set("project_path", project_path, save=True)
                make_project_subfolder(".processed")
                self.projectReset.emit()

            except Exception as e:
                logger.error(f"Failed to reset project folder: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to delete data.\nError: {e}",
                    QMessageBox.Ok,
                )
        else:
            logger.debug("resetProjectFolder cancelled by user")

    def convertDataToCSV(self):
        logger.debug("Event : convertDataToCSV")

        dlg = ConvertDataDialog(parent=self)
        if not dlg.exec():
            return
        selection = dlg.get_selection()

        logger.debug(f"Selection: {selection}")
        config.set("dataloaddlg", selection, save=True)

        device = selection.get("device", "")
        option = selection.get("option", "")

        start_dir = config.get("data_last_dir", "")

        # 장치별 파일 필터 매핑
        filter_by_device = {
            "Mag Hawk V2022": "Mag Hawk data (*.dat);;All files (*)",
            "Mag Hawk V2023": "Mag Hawk data (*.dat);;All files (*)",
            "Mag Hawk V2025": "Mag Hawk data (*.dat);;All files (*)",
            "Mag Arrow": "Mag Arrow data (*.csv);;All files (*)",
        }

        # 디바이스 유효성 체크
        if device not in filter_by_device:
            logger.warning(f"Unknown device: {device}")
            return

        # 파일/폴더 선택 통합 처리
        files, folder = self._pick_input(
            device=device,
            option=option,
            start_dir=start_dir,
            filter_str=filter_by_device[device],
        )

        # 사용자가 취소한 경우 처리
        if device == "Mag Arrow":
            if not files:
                logger.info("No files selected for Mag Hawk Arrow. Cancelled by user.")
                return
            logger.debug(f"Selected {len(files)} file(s) for Arrow: {files}")
        else:
            mode = option["mode"]  # "file" or "folder" (V2022/23/25)
            # V2022/23/25
            if mode == "file":
                if not files:
                    logger.info(f"No files selected for {device}. Cancelled by user.")
                    return
                logger.debug(f"Selected {len(files)} file(s) for {device}: {files}")
            else:
                if not folder:
                    logger.info(
                        f"No directory selected for {device}. Cancelled by user."
                    )
                    return
                logger.debug(f"Selected directory for {device}: {folder}")

        # 마지막 사용 경로 저장
        try:
            if files:
                last_path = os.path.dirname(os.path.dirname(files[0]))
            else:
                last_path = os.path.dirname(folder)
            logger.debug(f"Last path: {last_path}")
            if last_path:
                config.set("data_last_dir", last_path, save=True)

        except Exception as e:
            logger.error(f"Failed to save last dir: {e}")

        convert_with_progress(
            files=files, folder=folder, selection=selection, parent=self
        )

    def _pick_input(self, device: str, option: str, start_dir: str, filter_str: str):
        """
        Returns (files, folder)
        - Arrow: always multi-file selection
        - V2022/23/25: 'file' -> multi-file, 'folder' -> directory
        """
        files, folder = [], ""
        if device == "Mag Arrow" or option.get("mode") == "file":
            caption_str = "Select Mag Data Files"
            files = (
                browse_files(
                    parent=self,
                    initial_dir=start_dir,
                    filter_str=filter_str,
                    caption=caption_str,
                )
                or []
            )
        else:
            caption_str = "Select Mag Data Folder"
            folder = (
                browse_directory(
                    parent=self, initial_dir=start_dir, caption=caption_str
                )
                or ""
            )
        return files, folder

    def import_SEC_files(self):
        logger.debug("import_SEC_file")
        # 0) 프로젝트가 열려있는지 확인
        imported_path = make_project_subfolder("Diurnal Data Folder")
        if not imported_path:
            return

        # 1) 파일 다이얼로그로 SEC 파일 선택
        files = (
            browse_files(
                parent=self,
                initial_dir="",
                filter_str=" Files (*.sec)",
                caption="Select IAGA-2002 File to Import",
            )
            or []
        )

        logger.debug(f"{len(files)} SEC files selected: {files}")
        # 사용자가 취소 클릭했으면 종료
        if not files:
            logger.debug("Import SEC file selection canceled")
            return
        # 파일 복사
        for file_path in files:
            out_file = load_SEC_file(file_path, imported_path)
            logger.debug(f"SEC FIle imported to {out_file}")


if __name__ == "__main__":

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

    try:
        win = KMagHunters()
        win.show()
    except Exception as err:
        logger.critical(repr(err))
        sys.exit(1)

    # time.sleep(1)
    splash.finish(win)
    sys.exit(app.exec())
