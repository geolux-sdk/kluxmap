import shutil
from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt, Signal, QSettings, QByteArray
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
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
from mySettings import config
from myWidgets import (
    ConfigDataSettingsDialog,
    CreateProjectDialog,
    browse_directory,
    browse_files,
)

VIEWER_ICON = "viewer.png"


class KLuxMap(QMainWindow):
    projectOpened = Signal(str)
    projectReset = Signal()

    def __init__(self, title: str = ""):
        super().__init__()
        self.title = title
        self.settings = QSettings("Geolux", "KLuxMap")
        logger.info("Progrma Start")
        self.db = DataManager()
        self.initUI()
        self._restore_window()

    def initUI(self):
        self.setWindowTitle(self.title)
        self.setWindowIcon(QIcon(resource_path(VIEWER_ICON)))
        self.setWindowFlags(
            Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.createMenuBar()

        self.tabs = QTabWidget(self)

        self.CalibPlotWidget = CalibrationFlightWidget(self.db)
        self.LinePlotWidget = LinePlotWidget(self.db)
        self.FligtPlotWidget = FlightPlotWidget(self.db)
        logger.debug("Widgets created")
        self.tabs.addTab(self.CalibPlotWidget, "Calibration Flight")
        self.tabs.addTab(self.FligtPlotWidget, "DRONE DATA")
        self.tabs.addTab(self.LinePlotWidget, "SCAN LINE DATA")
        self.tabs.setCurrentIndex(1)
        self._previous_tab_index = self.tabs.currentIndex()

        self.setCentralWidget(self.tabs)

        self.connectSignals()
        logger.debug("UI initialized")

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
            self._save_window()
            event.accept()
        else:
            event.ignore()

    def createMenuBar(self):
        menu_bar = self.menuBar()

        project_menu = menu_bar.addMenu("&Project")

        self.createProject_action = QAction("&Create Project Folder", self)
        self.createProject_action.setShortcut("Ctrl+M")
        self.createProject_action.setStatusTip("Create a project folder")
        project_menu.addAction(self.createProject_action)

        self.openProject_action = QAction("&Open Project Folder", self)
        self.openProject_action.setShortcut("Ctrl+O")
        self.openProject_action.setStatusTip("Open a project folder")
        project_menu.addAction(self.openProject_action)

        self.resetProject_action = QAction("&Reset Project Folder", self)
        self.resetProject_action.setShortcut("Ctrl+R")
        self.resetProject_action.setStatusTip("Reset Data in project folder")
        project_menu.addAction(self.resetProject_action)

        self.closeProject_action = QAction("Close Project Folder", self)
        self.closeProject_action.setStatusTip("Close this project folder")
        project_menu.addAction(self.closeProject_action)

        self.exit_action = QAction("&Exit", self)
        self.exit_action.setShortcut("Ctrl+X")
        self.exit_action.setStatusTip("Exit application")
        project_menu.addAction(self.exit_action)

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

        help_menu = menu_bar.addMenu("Help")

        self.about_action = QAction(QIcon(), "About", self)
        self.about_action.setStatusTip("Show information about this application")
        help_menu.addAction(self.about_action)

        self.resetProject_action.setEnabled(False)
        self.closeProject_action.setEnabled(False)
        self.convert_action.setEnabled(False)
        self.import_SEC_files_action.setEnabled(False)
        self.config_action.setEnabled(False)

    def connectSignals(self):
        """모든 시그널을 슬롯에 연결"""
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.createProject_action.triggered.connect(self.createProjectFolder)
        self.openProject_action.triggered.connect(self.openProjectFolder)
        self.resetProject_action.triggered.connect(self.resetProjectFolder)
        self.closeProject_action.triggered.connect(self.closeProjectFolder)
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

    def showAboutDialog(self):
        QMessageBox.about(
            self,
            "About",
            "This is the KLuxMap application \nfor magnetic data viewing, \ndeveloped by KIGAM and GEOLUX.",
        )

    def menu_action_enable(self, action=True):
        self.closeProject_action.setEnabled(action)
        self.resetProject_action.setEnabled(action)
        self.convert_action.setEnabled(action)
        self.import_SEC_files_action.setEnabled(action)
        self.config_action.setEnabled(action)

        self.FligtPlotWidget.actionEnable(action)
        self.LinePlotWidget.actionEnable(action)
        self.CalibPlotWidget.actionEnable(action)
        action = not action
        self.createProject_action.setEnabled(action)
        self.openProject_action.setEnabled(action)

    def closeProjectFolder(self):
        logger.debug("Event : closeProjectFolder")
        self.menu_action_enable(False)
        self.projectReset.emit()

    def createProjectFolder(self):
        logger.debug("Event : createProjectFolder")
        dlg = CreateProjectDialog(parent=self)
        if not dlg.exec():
            return
        selection = dlg.selection

        folder_path = selection.get("project_path", "")

        if not folder_path:
            return
        direction_degree = selection.get("direction", 0)
        direction_degree_str = selection.get("direction_str", "")
        config.set_path(str(Path(folder_path) / "project_settings.json"))

        Path(folder_path).mkdir(exist_ok=True)

        config.set("direction", direction_degree)
        config.set("direction_str", direction_degree_str)
        config.set("project_path", folder_path, save=True)

        make_project_subfolder(".processed")

        self.openProject_action.setEnabled(False)
        self.createProject_action.setEnabled(False)
        self.menu_action_enable(True)
        self.projectOpened.emit(folder_path)
        self.settings.setValue("projects/last", str(folder_path))

    def openProjectFolder(self):
        logger.debug("Event : openProjectFolder")
        last_folder = self.settings.value("projects/last", "", type=str)
        default_path = Path(last_folder) if last_folder else Path.home()
        if not default_path.exists():
            default_path = Path.home()
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Folder", str(default_path)
        )
        if folder_path:
            logger.debug(f"openProjectFolder {folder_path}")

            config.set_path(Path(folder_path) / "project_settings.json")
            config.load()
            config.set("project_path", folder_path, save=True)
            make_project_subfolder(".processed")

            self.openProject_action.setEnabled(False)
            self.createProject_action.setEnabled(False)
            self.menu_action_enable()

            self.projectOpened.emit(folder_path)
            self.settings.setValue("projects/last", str(folder_path))

    def resetProjectFolder(self):
        logger.debug("Event : resetProjectFolder")

        project_path = Path(config.get("project_path", ""))
        if not project_path or not project_path.exists():
            logger.debug("No project path found")
            return

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
                for item in project_path.iterdir():
                    logger.debug(f"Deleting item: {item}")
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)

                logger.info(f"All data deleted in project folder: {project_path}")

                QMessageBox.information(
                    self,
                    "Completed",
                    "All data in the project folder has been deleted.",
                    QMessageBox.Ok,
                )
                config.clear()
                config.set_path(project_path / "project_settings.json")
                config.set("project_path", str(project_path), save=True)
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
        option = selection.get("option", {}) or {}

        start_dir = config.get("data_last_dir", "")

        filter_by_device = {
            "Mag Hawk V2022": "Mag Hawk data (*.dat);;All files (*)",
            "Mag Hawk V2023": "Mag Hawk data (*.dat);;All files (*)",
            "Mag Hawk V2025": "Mag Hawk data (*.dat);;All files (*)",
            "Mag Arrow": "Mag Arrow data (*.csv);;All files (*)",
        }

        if device not in filter_by_device:
            logger.warning(f"Unknown device: {device}")
            return

        files, folder = self._pick_input(
            device=device,
            option=option,
            start_dir=start_dir,
            filter_str=filter_by_device[device],
        )

        if device == "Mag Arrow":
            if not files:
                logger.info("No files selected for Mag Hawk Arrow. Cancelled by user.")
                return
            logger.debug(f"Selected {len(files)} file(s) for Arrow: {files}")
        else:
            mode = option.get("mode", "file")
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

        try:
            if files:
                last_path = Path(files[0]).parent.parent
            else:
                last_path = Path(folder).parent
            logger.debug(f"Last path: {last_path}")
            if last_path:
                config.set("data_last_dir", str(last_path), save=True)

        except Exception as e:
            logger.error(f"Failed to save last dir: {e}")

        convert_with_progress(
            files=files, folder=folder, selection=selection, parent=self
        )

    def _pick_input(
        self, device: str, option: dict, start_dir: str, filter_str: str
    ):
        files, folder = [], ""
        if device == "Mag Arrow" or option.get("mode", "file") == "file":
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
        imported_path = make_project_subfolder("Diurnal Data Folder")
        if not imported_path:
            return

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
        if not files:
            logger.debug("Import SEC file selection canceled")
            return
        for file_path in files:
            out_file = load_SEC_file(file_path, imported_path)
            logger.debug(f"SEC FIle imported to {out_file}")

    def _restore_window(self):
        geo = self.settings.value("window/geometry", None)
        if isinstance(geo, QByteArray):
            try:
                if self.restoreGeometry(geo):
                    return
            except Exception as e:
                logger.warning(f"Failed to restore geometry: {e}")
        self.resize(1400, 900)

    def _save_window(self):
        try:
            self.settings.setValue("window/geometry", self.saveGeometry())
        except Exception as e:
            logger.warning(f"Failed to save geometry: {e}")
