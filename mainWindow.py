import json
import shutil
from pathlib import Path

from loguru import logger
from PySide6.QtCore import Qt, Signal, QSettings, QByteArray
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
)

from CalibrationFlightWidget import CalibrationFlightWidget
from DataManager import DataManager
from FlightPlotWidget import FlightPlotWidget
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
        logger.info("Program start")
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

        self.calibrationFlightWidget = CalibrationFlightWidget(self.db)
        self.linePlotWidget = LinePlotWidget(self.db, self)
        self.flightPlotWidget = FlightPlotWidget(self.db, self)
        self.tabs.addTab(self.calibrationFlightWidget, "Calibration Flight")
        self.tabs.addTab(self.flightPlotWidget, "DRONE DATA")
        self.tabs.addTab(self.linePlotWidget, "SCAN LINE DATA")
        self.tabs.setCurrentIndex(1)
        self._previous_tab_index = self.tabs.currentIndex()

        self.setCentralWidget(self.tabs)

        self.connectSignals()

    def on_tab_changed(self, index):
        if index == 2:
            self.linePlotWidget.initialize()

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
            try:
                self.calibrationFlightWidget.save_state_to_config()
            except Exception as e:
                logger.warning(f"Failed to save calibration widget state on exit: {e}")
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

        self.recentProject_action = QAction("Recent Project", self)
        self.recentProject_action.setStatusTip("Open the most recent project")
        project_menu.addAction(self.recentProject_action)

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

        self.maps_api_key_action = QAction(QIcon(), "Google Maps API Key", self)
        self.maps_api_key_action.setStatusTip(
            "Set the Google Maps API key (stored in user settings)"
        )
        help_menu.addAction(self.maps_api_key_action)

        self.settings_action = QAction(QIcon(), "Settings", self)
        self.settings_action.setStatusTip("Show current project settings")
        help_menu.addAction(self.settings_action)

        self.about_action = QAction(QIcon(), "About", self)
        self.about_action.setStatusTip("Show information about this application")
        help_menu.addAction(self.about_action)

        self.resetProject_action.setEnabled(False)
        self.closeProject_action.setEnabled(False)
        self.convert_action.setEnabled(False)
        self.import_SEC_files_action.setEnabled(False)
        self.config_action.setEnabled(False)
        self._update_recent_project_action()

    def connectSignals(self):
        """모든 시그널을 슬롯에 연결"""
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.createProject_action.triggered.connect(self.createProjectFolder)
        self.openProject_action.triggered.connect(self.openProjectFolder)
        self.recentProject_action.triggered.connect(self.openRecentProject)
        self.resetProject_action.triggered.connect(self.resetProjectFolder)
        self.closeProject_action.triggered.connect(self.closeProjectFolder)
        self.convert_action.triggered.connect(self.convertDataToCSV)
        self.import_SEC_files_action.triggered.connect(self.import_SEC_files)
        self.exit_action.triggered.connect(self.close)
        self.config_action.triggered.connect(
            lambda checked=False: ConfigDataSettingsDialog(self).exec()
        )
        self.maps_api_key_action.triggered.connect(self.editGoogleMapsApiKey)
        self.settings_action.triggered.connect(self.showProjectSettingsDialog)
        self.about_action.triggered.connect(self.showAboutDialog)

        for w in (
            self.flightPlotWidget,
            self.calibrationFlightWidget,
            self.linePlotWidget,
        ):
            self.projectOpened.connect(w.on_project_opened)
            self.projectReset.connect(w.on_project_reset)

    def showAboutDialog(self):
        QMessageBox.about(
            self,
            "About",
            "This is the KLuxMap application \nfor magnetic data viewing, \ndeveloped by KIGAM and GEOLUX.",
        )

    def editGoogleMapsApiKey(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Google Maps API Key")
        dlg.resize(480, 140)

        layout = QVBoxLayout(dlg)
        layout.addWidget(
            QLabel("Enter your Google Maps API key (stored in user settings).", dlg)
        )

        key_edit = QLineEdit(dlg)
        key_edit.setEchoMode(QLineEdit.Password)
        current_key = self.settings.value("google_maps_api_key", "", type=str)
        if current_key:
            key_edit.setText(current_key)
        layout.addWidget(key_edit)

        show_checkbox = QCheckBox("Show key", dlg)
        show_checkbox.toggled.connect(
            lambda checked: key_edit.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        layout.addWidget(show_checkbox)

        button_row = QHBoxLayout()
        save_btn = QPushButton("Save", dlg)
        clear_btn = QPushButton("Clear", dlg)
        cancel_btn = QPushButton("Cancel", dlg)
        save_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        clear_btn.clicked.connect(lambda: key_edit.setText(""))
        button_row.addWidget(save_btn)
        button_row.addWidget(clear_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        if dlg.exec():
            new_key = key_edit.text().strip()
            if new_key:
                self.settings.setValue("google_maps_api_key", new_key)
            else:
                self.settings.remove("google_maps_api_key")
            self.settings.sync()

    def showProjectSettingsDialog(self):
        settings_path = config.file_path
        if not settings_path:
            QMessageBox.information(self, "Settings", "No project is open.")
            return

        try:
            with settings_path.open("r", encoding="utf-8") as file:
                settings_data = json.load(file)
        except FileNotFoundError:
            QMessageBox.warning(
                self,
                "Settings",
                f"Settings file not found:\n{settings_path}",
            )
            return
        except json.JSONDecodeError as e:
            QMessageBox.critical(
                self,
                "Settings",
                f"Invalid settings JSON.\nError: {e}",
            )
            return
        except Exception as e:
            QMessageBox.critical(
                self,
                "Settings",
                f"Failed to load settings.\nError: {e}",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Project Settings")
        dlg.resize(700, 500)

        layout = QVBoxLayout(dlg)
        path_label = QLabel(str(settings_path), dlg)
        layout.addWidget(path_label)

        tree = QTreeWidget(dlg)
        tree.setHeaderLabels(["Key", "Value"])
        tree.setAlternatingRowColors(True)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tree.header().setStretchLastSection(True)
        layout.addWidget(tree)

        def format_value(value):
            if value is None:
                return "null"
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        def add_item(parent, key, value):
            if isinstance(value, dict):
                item = QTreeWidgetItem(parent, [str(key), ""])
                for sub_key, sub_value in value.items():
                    add_item(item, sub_key, sub_value)
            elif isinstance(value, list):
                item = QTreeWidgetItem(parent, [str(key), f"[{len(value)}]"])
                for index, sub_value in enumerate(value):
                    add_item(item, f"[{index}]", sub_value)
            else:
                QTreeWidgetItem(parent, [str(key), format_value(value)])

        if isinstance(settings_data, dict):
            for key, value in settings_data.items():
                add_item(tree, key, value)
        elif isinstance(settings_data, list):
            for index, value in enumerate(settings_data):
                add_item(tree, f"[{index}]", value)
        else:
            add_item(tree, "value", settings_data)

        tree.expandToDepth(1)

        close_btn = QPushButton("Close", dlg)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)

        dlg.exec()

    def _update_recent_project_action(self):
        last_folder = self.settings.value("projects/last", "", type=str)
        enabled = bool(last_folder) and Path(last_folder).exists()
        self.recentProject_action.setEnabled(enabled)

    def menu_action_enable(self, action=True):
        self.closeProject_action.setEnabled(action)
        self.resetProject_action.setEnabled(action)
        self.convert_action.setEnabled(action)
        self.import_SEC_files_action.setEnabled(action)
        self.config_action.setEnabled(action)

        self.flightPlotWidget.actionEnable(action)
        self.linePlotWidget.actionEnable(action)
        self.calibrationFlightWidget.actionEnable(action)
        can_open = not action
        self.createProject_action.setEnabled(can_open)
        self.openProject_action.setEnabled(can_open)
        if can_open:
            self._update_recent_project_action()
        else:
            self.recentProject_action.setEnabled(False)

    def closeProjectFolder(self):
        project_path = config.get("project_path", "")
        if project_path:
            logger.info(f"Project closed: {project_path}")
        self.menu_action_enable(False)
        self.projectReset.emit()

    def createProjectFolder(self):
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
        self._update_recent_project_action()
        logger.info(f"Project created: {folder_path}")

    def openProjectFolder(self):
        last_folder = self.settings.value("projects/last", "", type=str)
        default_path = Path(last_folder) if last_folder else Path.home()
        if not default_path.exists():
            default_path = Path.home()
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Folder", str(default_path)
        )
        if folder_path:
            self._open_project(folder_path)

    def openRecentProject(self):
        last_folder = self.settings.value("projects/last", "", type=str)
        if not last_folder:
            QMessageBox.information(
                self,
                "Recent Project",
                "No recent project found.",
            )
            self._update_recent_project_action()
            return

        last_path = Path(last_folder)
        if not last_path.exists():
            QMessageBox.warning(
                self,
                "Recent Project",
                f"Recent project folder not found:\n{last_path}",
            )
            self._update_recent_project_action()
            return

        self._open_project(last_path)

    def _open_project(self, folder_path: str | Path):
        folder_path = Path(folder_path)
        config.set_path(folder_path / "project_settings.json")
        config.load()
        config.set("project_path", str(folder_path), save=True)
        make_project_subfolder(".processed")

        self.openProject_action.setEnabled(False)
        self.createProject_action.setEnabled(False)
        self.menu_action_enable()

        self.projectOpened.emit(str(folder_path))
        self.settings.setValue("projects/last", str(folder_path))
        self._update_recent_project_action()
        logger.info(f"Project opened: {folder_path}")

    def resetProjectFolder(self):
        project_path = Path(config.get("project_path", ""))
        if not project_path or not project_path.exists():
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
                logger.exception(
                    f"Failed to reset project folder: {project_path}"
                )
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to delete data.\nError: {e}",
                    QMessageBox.Ok,
                )

    def convertDataToCSV(self):
        dlg = ConvertDataDialog(parent=self)
        if not dlg.exec():
            return
        selection = dlg.get_selection()

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
                return
        else:
            mode = option.get("mode", "file")
            if mode == "file":
                if not files:
                    return
            else:
                if not folder:
                    return

        try:
            if files:
                last_path = Path(files[0]).parent.parent
            else:
                last_path = Path(folder).parent
            if last_path:
                config.set("data_last_dir", str(last_path), save=True)

        except Exception as e:
            logger.warning(f"Failed to save last input directory: {e}")

        mode = option.get("mode", "file")
        if files:
            logger.info(
                f"Starting data conversion: device={device}, mode=file, files={len(files)}"
            )
        else:
            logger.info(
                f"Starting data conversion: device={device}, mode={mode}, folder={folder}"
            )

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

        if not files:
            return
        imported_count = 0
        for file_path in files:
            out_file = load_SEC_file(file_path, imported_path)
            if out_file:
                imported_count += 1
        logger.info(
            f"Imported {imported_count}/{len(files)} SEC files into {imported_path}"
        )

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
