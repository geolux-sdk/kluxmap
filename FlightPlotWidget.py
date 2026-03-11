import math
import os
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from pyproj import Transformer

GOOGLE_MAPS_API_KEY_HARDCODED = "AIzaSyD1zF_979D6PEvhKJvI9ZvSf27UZ-MtqYw"

MAP_TYPE_OPTIONS = (
    ("None", "none"),
    ("Roadmap", "roadmap"),
    ("Satellite", "satellite"),
    ("Hybrid", "hybrid"),
    ("Terrain", "terrain"),
)

# Widget imports
from PySide6.QtCore import Qt, QSize, QSettings, QSignalBlocker, Slot
from PySide6.QtGui import (
    QAction,
    QCursor,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from DataManager import DataManager
from kriging_dialog import ColorbarRangeDialog
from myResource import resource_path
from mySettings import config
from myWidgets import DataSettingsDialog, OrthogonalPolygonDrawer
from segment_utils import subtract_intervals


class FlightPlotWidget(QWidget):

    def __init__(
        self, db: DataManager, main_window: Optional[QWidget] = None
    ) -> None:
        super().__init__()
        self.main_window: Optional[QWidget] = main_window

        self.db: DataManager = db

        self._linecut_point = None
        self._plot_df_by_file = {}
        self._line_base_df_by_file = {}
        self._line_base_intervals_by_file = {}
        self._line_plot_df_by_file = {}
        self._line_intervals_by_file = {}
        self._line_cut_points = {}
        self._line_delete_points = {}
        self._line_append_links = {}
        self._line_append_cross_links = []
        self._line_append_groups_by_file = {}
        self._line_append_cross_groups = []
        self._line_append_selected = []
        self._linecut_preview = None
        self._line_undo_stack = []
        self._line_redo_stack = []
        self.df = pd.DataFrame()

        self._is_panning = False
        self._last_mouse_pos = None
        self._line_is_panning = False
        self._line_last_mouse_pos = None

        config.get("filters", {})
        # Always start with no background map; do not persist a default map type.
        self.map_type = "none"
        self._map_pixmap: Optional[QPixmap] = None
        self._map_image = None
        self._map_extent = None
        self._last_epsg = None
        self._map_cache: dict = {}
        self._map_artist = None
        self._line_map_artist = None
        self._scatter_by_file = {}
        self._color_scatter = None
        self._overlay_artists = []
        self._legend = None
        self._actions_enabled = False
        self.line_fig = None
        self.line_ax = None
        self.line_canvas = None

        self._line_plot_state_hash = None
        self._line_base_state_hash = None

        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        # Toolbar
        toolbar = QToolBar(self)
        toolbar.setIconSize(QSize(32, 32))

        self.actionOpenFileBrowser = QAction(
            QIcon(resource_path("imag_data_import.png")),
            "&Open File Browser",
            self,
        )
        self.actionOpenFileBrowser.setStatusTip("Open project browser")

        self.actionDataCutDisp = QAction(
            QIcon(resource_path("imag_cut.png")), "Line Cut", self
        )
        self.actionDataCutDisp.setStatusTip("Line Cut")
        self.actionDataCutDisp.setCheckable(True)

        self.actionDataConfig = QAction(
            QIcon(resource_path("filter.png")), "Trim Filters", self
        )
        self.actionDataConfig.setStatusTip("Trim filter settings")

        self.actionDataJoinDisp = QAction(
            QIcon(resource_path("imag_sum.png")), "Line Append", self
        )
        self.actionDataJoinDisp.setStatusTip("Line Append")
        self.actionDataJoinDisp.setCheckable(True)

        self.actionDataOut = QAction(
            QIcon(resource_path("imag_kml_export.png")), "Export KML", self
        )
        self.actionDataOut.setStatusTip("Export KML FILE")

        toolbar.addAction(self.actionOpenFileBrowser)
        toolbar.addAction(self.actionDataConfig)
        toolbar.addAction(self.actionDataCutDisp)
        toolbar.addAction(self.actionDataJoinDisp)
        toolbar.addAction(self.actionDataOut)

        # Add the toolbar above the main content area.
        layout.addWidget(toolbar)

        # Main layout
        vbox_layout = QVBoxLayout()
        vbox_layout.addWidget(
            self.createFileList(), alignment=Qt.AlignmentFlag.AlignLeft
        )
        vbox_layout.addWidget(
            self.createMapTypeSelector(), alignment=Qt.AlignmentFlag.AlignLeft
        )
        vbox_layout.addWidget(
            self.createLogoLabel(), alignment=Qt.AlignmentFlag.AlignHCenter
        )

        ctrl_panel = QFrame()
        ctrl_panel.setLineWidth(3)
        ctrl_panel.setLayout(vbox_layout)
        ctrl_panel.setMaximumWidth(300)

        canvas_layout = QHBoxLayout()
        canvas_layout.addWidget(self.createPlotTabs(), 1)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.addWidget(ctrl_panel)
        main_layout.addLayout(canvas_layout)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        self.polygonDrawer = OrthogonalPolygonDrawer(self.ax)
        self.polygonDrawer.polygonFinished.connect(self.modify)

        # Disable actions until a project is opened.
        self.actionOpenFileBrowser.setEnabled(False)
        self.actionDataCutDisp.setEnabled(False)
        self.actionDataConfig.setEnabled(False)
        self.actionDataJoinDisp.setEnabled(False)
        self.actionDataOut.setEnabled(False)

        self.connectSignals()
        self._line_undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._line_undo_shortcut.activated.connect(self._undo_line_edit)
        self._line_redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._line_redo_shortcut.activated.connect(self._redo_line_edit)

    def connectSignals(self):
        self.actionOpenFileBrowser.triggered.connect(self.openFileBrowser)
        self.actionDataConfig.triggered.connect(
            lambda checked=False: DataSettingsDialog(parent=self).exec()
        )
        self.actionDataCutDisp.toggled.connect(self._on_linecut_toggled)
        self.actionDataJoinDisp.toggled.connect(self._on_lineappend_toggled)
        self.actionDataOut.triggered.connect(self.exportKML)

    def actionEnable(self, action=True):
        self._actions_enabled = action
        self.actionOpenFileBrowser.setEnabled(action)
        self.actionDataCutDisp.setEnabled(action)   
        self.actionDataConfig.setEnabled(action)
        self.actionDataJoinDisp.setEnabled(action)
        self.actionDataOut.setEnabled(action)
        if hasattr(self, "plotTabs"):
            is_line_tab = self.plotTabs.tabText(self.plotTabs.currentIndex()) == "Line"
            self._update_line_tab_controls(is_line_tab)

    def _on_linecut_toggled(self, checked):
        if checked and self.actionDataJoinDisp.isChecked():
            self.actionDataJoinDisp.setChecked(False)
        if not checked:
            self._linecut_preview = None
        self._update_cursor_for_mode()

    def _on_lineappend_toggled(self, checked):
        if checked and self.actionDataCutDisp.isChecked():
            self.actionDataCutDisp.setChecked(False)
        if not checked:
            self._clear_line_append_selection()
        self._update_cursor_for_mode()

    def _update_cursor_for_mode(self):
        cursor = (
            Qt.CrossCursor
            if self.actionDataCutDisp.isChecked() or self.actionDataJoinDisp.isChecked()
            else Qt.ArrowCursor
        )
        if hasattr(self, "canvas") and self.canvas is not None:
            self.canvas.setCursor(cursor)
        if hasattr(self, "line_canvas") and self.line_canvas is not None:
            self.line_canvas.setCursor(cursor)
        
    def createLogoLabel(self):
        lbl_logo = QLabel("")
        lbl_logo.setPixmap(
            QPixmap(resource_path("kigam_geolux_logo.png")).scaledToWidth(210)
        )
        lbl_logo.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        lbl_logo.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        lbl_logo.setStyleSheet("padding: 30px;")
        return lbl_logo

    def createFileList(self):
        """Create the list widget that shows the loaded file names."""
        self.fileListWidget = QListWidget()
        self.fileListWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        self.fileListWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fileListWidget.setMaximumWidth(200)
        self.fileListWidget.itemSelectionChanged.connect(
            self.on_file_selection_changed
        )
        self.fileListWidget.customContextMenuRequested.connect(
            self.show_file_list_context_menu
        )
        return self.fileListWidget

    def createMapTypeSelector(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(4)

        label = QLabel("Background Map")
        self.mapTypeCombo = QComboBox()
        self.mapTypeCombo.setMaximumWidth(200)
        for label_text, value in MAP_TYPE_OPTIONS:
            self.mapTypeCombo.addItem(label_text, value)
        current = self.map_type or "none"
        current_index = self.mapTypeCombo.findData(current)
        if current_index != -1:
            self.mapTypeCombo.setCurrentIndex(current_index)
        self.mapTypeCombo.currentIndexChanged.connect(self._on_map_type_changed)

        layout.addWidget(label)
        layout.addWidget(self.mapTypeCombo)
        return container

    def createPlotTabs(self):
        self.plotTabs = QTabWidget()
        self.plotTabs.addTab(self.createCanvasPlot(), "Flight")

        line_tab = QWidget()
        line_layout = QVBoxLayout(line_tab)
        line_layout.setContentsMargins(0, 0, 0, 0)
        line_layout.addWidget(self.createLineCanvasPlot())
        self.plotTabs.addTab(line_tab, "Line")
        self.plotTabs.currentChanged.connect(self._on_plot_tab_changed)
        return self.plotTabs

    def _on_plot_tab_changed(self, index):
        is_line_tab = self.plotTabs.tabText(index) == "Line"
        try:
            config.set("flightplot_last_tab", self.plotTabs.tabText(index), save=True)
        except Exception as e:
            logger.warning(f"Failed to persist last tab: {e}")
        self._update_line_tab_controls(is_line_tab)
        if is_line_tab:
            if not self._plot_df_by_file:
                self.updatePlot()
            needs_regen = (
                self._line_plot_state_hash is not None
                and self._line_base_state_hash != self._line_plot_state_hash
            )
            if needs_regen:
                regen = QMessageBox.question(
                    self,
                    "Line Data",
                    "Regenerate Line tab data?\n(This will be a separate copy from the Flight tab.)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if regen == QMessageBox.StandardButton.Yes:
                    if not self._regenerate_line_tab_data():
                        QMessageBox.information(
                            self,
                            "Line Data",
                            "No data available to regenerate.",
                        )
            self.updateLinePlot()
        else:
            # Ensure line tools off when returning to Flight
            if self.actionDataCutDisp.isChecked():
                self.actionDataCutDisp.setChecked(False)
            if self.actionDataJoinDisp.isChecked():
                self.actionDataJoinDisp.setChecked(False)

    def _reset_line_edit_state(self, clear_undo: bool = True) -> None:
        self._line_cut_points = {}
        self._line_delete_points = {}
        self._line_append_links = {}
        self._line_append_cross_links = []
        self._line_append_groups_by_file = {}
        self._line_append_cross_groups = []
        self._clear_line_append_selection()
        self._linecut_preview = None
        self._linecut_point = None
        if clear_undo:
            self._line_undo_stack = []
            self._line_redo_stack = []

    def _snapshot_line_edit_state(self) -> dict:
        return self._serialize_line_edit_state()

    def _push_line_undo_state(self) -> None:
        self._line_undo_stack.append(self._snapshot_line_edit_state())
        self._line_redo_stack = []

    def _restore_line_edit_state(self, state: dict) -> None:
        valid_files = set(self._line_base_df_by_file)
        if not valid_files:
            valid_files = self._current_file_names()

        self._reset_line_edit_state(clear_undo=False)

        for fname, points in (state.get("cut_points") or {}).items():
            if not valid_files or fname in valid_files:
                self._line_cut_points[fname] = {int(p) for p in points}

        for fname, points in (state.get("delete_points") or {}).items():
            if not valid_files or fname in valid_files:
                self._line_delete_points[fname] = {int(p) for p in points}

        for fname, links in (state.get("append_links") or {}).items():
            if not valid_files or fname in valid_files:
                cleaned = []
                for a, b in links:
                    cleaned.append((int(a), int(b)))
                self._line_append_links[fname] = cleaned

        for link in state.get("append_cross_links") or []:
            try:
                (fa, ida), (fb, idb) = link
            except Exception:
                continue
            if (not valid_files) or (fa in valid_files and fb in valid_files):
                self._line_append_cross_links.append(
                    ((fa, int(ida)), (fb, int(idb)))
                )

    def _undo_line_edit(self) -> None:
        if not (
            hasattr(self, "plotTabs")
            and self.plotTabs.tabText(self.plotTabs.currentIndex()) == "Line"
        ):
            return
        if not self._line_undo_stack:
            return
        current_state = self._snapshot_line_edit_state()
        state = self._line_undo_stack.pop()
        self._line_redo_stack.append(current_state)
        self._restore_line_edit_state(state)
        self._refresh_line_tab_data()
        self._save_line_edit_state()
        self.updateLinePlot()

    def _redo_line_edit(self) -> None:
        if not (
            hasattr(self, "plotTabs")
            and self.plotTabs.tabText(self.plotTabs.currentIndex()) == "Line"
        ):
            return
        if not self._line_redo_stack:
            return
        current_state = self._snapshot_line_edit_state()
        state = self._line_redo_stack.pop()
        self._line_undo_stack.append(current_state)
        self._restore_line_edit_state(state)
        self._refresh_line_tab_data()
        self._save_line_edit_state()
        self.updateLinePlot()

    def _refresh_line_tab_data(self) -> None:
        if not self._line_base_df_by_file:
            self._line_plot_df_by_file = {}
            self._line_intervals_by_file = {}
            self._line_append_groups_by_file = {}
            self._line_append_cross_groups = []
            self.db.update_scanline_state()
            return

        self._line_plot_df_by_file = {}
        self._line_intervals_by_file = {}
        for filename, base_df in self._line_base_df_by_file.items():
            base_intervals = self._line_base_intervals_by_file.get(filename)
            if base_intervals is None:
                base_intervals = self.db.df_to_intervals(base_df)
                self._line_base_intervals_by_file[filename] = base_intervals
            edited_df, intervals, _ = self._apply_line_edits(
                filename, base_df, base_intervals
            )
            self._line_intervals_by_file[filename] = intervals
            if edited_df is None or edited_df.empty or not intervals:
                continue
            self._line_plot_df_by_file[filename] = edited_df

        self._line_append_groups_by_file = {}
        for filename, intervals in self._line_intervals_by_file.items():
            links = self._line_append_links.get(filename, [])
            self._line_append_groups_by_file[filename] = (
                self._build_line_append_groups(intervals, links)
            )
        self._validate_line_append_selection()
        self._line_append_cross_groups = self._build_cross_file_append_groups()
        self.db.update_scanline_state(
            df_by_file=self._line_plot_df_by_file,
            groups_by_file=self._line_append_groups_by_file,
            intervals_by_file=self._line_intervals_by_file,
            cross_groups=self._line_append_cross_groups,
        )

    def _regenerate_line_tab_data(self, reset_state: bool = True) -> bool:
        if not self._plot_df_by_file:
            return False

        self._line_base_df_by_file = {}
        self._line_base_intervals_by_file = {}
        for filename, df in self._plot_df_by_file.items():
            if df is None or df.empty:
                continue
            base_df = df.copy(deep=True)
            if "record_id" not in base_df.columns:
                base_df["record_id"] = np.arange(len(base_df))
            self._line_base_df_by_file[filename] = base_df
            self._line_base_intervals_by_file[filename] = self.db.df_to_intervals(
                base_df
            )

        if reset_state:
            self._reset_line_edit_state()
        self._refresh_line_tab_data()
        if reset_state:
            self._save_line_edit_state()
        self._line_base_state_hash = self._line_plot_state_hash
        return True

    def _update_line_tab_controls(self, is_line_tab):
        if not hasattr(self, "fileListWidget"):
            return
        base_enabled = getattr(self, "_actions_enabled", False)
        self.fileListWidget.setEnabled(base_enabled and not is_line_tab)
        self.actionOpenFileBrowser.setEnabled(base_enabled and not is_line_tab)
        self.actionDataConfig.setEnabled(base_enabled and not is_line_tab)
        if not is_line_tab:
            if self.actionDataCutDisp.isChecked():
                self.actionDataCutDisp.setChecked(False)
            if self.actionDataJoinDisp.isChecked():
                self.actionDataJoinDisp.setChecked(False)
        self.actionDataCutDisp.setEnabled(base_enabled and is_line_tab)
        self.actionDataJoinDisp.setEnabled(base_enabled and is_line_tab)

    def createCanvasPlot(self):
        """Create a canvas plot using matplotlib"""
        # Configure the matplotlib plot.
        self.fig, self.ax = plt.subplots(figsize=(10, 8), dpi=100)

        self.ax.set_title("Mag Plot")
        self.ax.set_xlabel("Easting (m)")
        self.ax.set_ylabel("Northing (m)")
        self.ax.grid(True)
        self.ax.set_aspect("equal")

        plt.tight_layout(pad=1.0, w_pad=1.5, h_pad=1)
        # Wrap the matplotlib canvas as a PyQt6 widget.
        self.canvas = FigureCanvas(self.fig)

        self.canvas.mpl_connect("scroll_event", self.scroll)
        self.canvas.mpl_connect("button_press_event", self.on_press)
        self.canvas.mpl_connect("button_release_event", self.on_release)
        self.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.canvas.mpl_connect("resize_event", self.on_resize)
        return self.canvas

    def createLineCanvasPlot(self):
        self.line_fig, self.line_ax = plt.subplots(figsize=(10, 8), dpi=100)
        self.line_ax.set_title("Line Plot")
        self.line_ax.set_xlabel("Easting (m)")
        self.line_ax.set_ylabel("Northing (m)")
        self.line_ax.grid(True)
        self.line_ax.set_aspect("equal", "box")
        self.line_fig.tight_layout()
        self.line_canvas = FigureCanvas(self.line_fig)
        self.line_canvas.mpl_connect("scroll_event", self._line_scroll)
        self.line_canvas.mpl_connect("button_press_event", self._line_on_press)
        self.line_canvas.mpl_connect("button_release_event", self._line_on_release)
        self.line_canvas.mpl_connect("motion_notify_event", self._line_on_motion)
        self.line_canvas.mpl_connect("resize_event", self._line_on_resize)
        return self.line_canvas

    def _line_on_resize(self, event):
        self._fit_bounds_to_canvas_equal_on(
            self.line_ax, self.line_canvas, margin_ratio=0.05
        )

    def _line_on_press(self, event):
        if (
            event.button == 3
            and self.actionDataJoinDisp.isChecked()
            and self._line_append_selected
        ):
            self._clear_line_append_selection()
            self.updateLinePlot()
            return
        if event.button == 1 and self._handle_line_marker(event):
            return
        if event.button == 1 and event.inaxes == self.line_ax:
            if event.xdata is None or event.ydata is None:
                return
            self._line_is_panning = True
            self._line_last_mouse_pos = (event.xdata, event.ydata)

    def _line_on_release(self, event):
        if event.button == 1:
            self._line_is_panning = False
            self._line_last_mouse_pos = None

    def _line_on_motion(self, event):
        if not self._line_is_panning or event.inaxes != self.line_ax:
            return

        if (
            self._line_last_mouse_pos is None
            or event.xdata is None
            or event.ydata is None
        ):
            return

        dx = self._line_last_mouse_pos[0] - event.xdata
        dy = self._line_last_mouse_pos[1] - event.ydata

        xlim = self.line_ax.get_xlim()
        ylim = self.line_ax.get_ylim()

        self.line_ax.set_xlim(xlim[0] + dx, xlim[1] + dx)
        self.line_ax.set_ylim(ylim[0] + dy, ylim[1] + dy)

        self._line_last_mouse_pos = (event.xdata, event.ydata)
        self.line_canvas.draw_idle()

    def _line_scroll(self, event):
        if event.inaxes != self.line_ax:
            return
        if event.xdata is None or event.ydata is None:
            return

        scale_factor = 1.2 if event.button == "up" else 1 / 1.2
        xlim = self.line_ax.get_xlim()
        ylim = self.line_ax.get_ylim()

        xdata, ydata = event.xdata, event.ydata
        new_xlim = [
            xdata - (xdata - xlim[0]) * scale_factor,
            xdata + (xlim[1] - xdata) * scale_factor,
        ]
        new_ylim = [
            ydata - (ydata - ylim[0]) * scale_factor,
            ydata + (ylim[1] - ydata) * scale_factor,
        ]

        self.line_ax.set_xlim(new_xlim)
        self.line_ax.set_ylim(new_ylim)
        self.line_canvas.draw_idle()

    def on_resize(self, event):
        self._fit_bounds_to_canvas_equal(margin_ratio=0.05)

    def on_press(self, event):
        if event.button == 1 and self._handle_line_marker(event):
            return
        if event.button == 1 and event.inaxes == self.ax:
            self._is_panning = True
            self._last_mouse_pos = (event.xdata, event.ydata)
        self.on_canvas_click(event)

    def _handle_line_marker(self, event):
        if not (
            hasattr(self, "plotTabs")
            and self.plotTabs.tabText(self.plotTabs.currentIndex()) == "Line"
        ):
            return False
        if event.inaxes != self.line_ax:
            return False
        if not (
            self.actionDataCutDisp.isChecked()
            or self.actionDataJoinDisp.isChecked()
        ):
            return False
        if event.xdata is None or event.ydata is None:
            return False

        if self.actionDataCutDisp.isChecked():
            return self._handle_linecut_click(event, temporary=True)
        if self.actionDataJoinDisp.isChecked():
            return self._handle_lineappend_click(event)
        return False

    def _handle_lineappend_click(self, event):
        nearest = self._find_nearest_plot_point(event.xdata, event.ydata)
        if not nearest:
            QMessageBox.information(self, "Line Append", "No data points available.")
            return True

        filename, record_id, px, py = nearest
        groups = self._line_append_groups_by_file.get(filename)
        if groups is None:
            intervals = self._line_intervals_by_file.get(filename, [])
            links = self._line_append_links.get(filename, [])
            groups = self._build_line_append_groups(intervals, links)
            self._line_append_groups_by_file[filename] = groups

        group = self._line_append_group_for_record(groups, record_id)
        if group is None:
            QMessageBox.information(
                self,
                "Line Append",
                "Selected point does not belong to an active line.",
            )
            return True

        if self._line_append_selected:
            first = self._line_append_selected[0]
            if filename == first[0]:
                first_groups = self._line_append_groups_by_file.get(first[0])
                if first_groups is None:
                    first_intervals = self._line_intervals_by_file.get(first[0], [])
                    first_links = self._line_append_links.get(first[0], [])
                    first_groups = self._build_line_append_groups(
                        first_intervals, first_links
                    )
                    self._line_append_groups_by_file[first[0]] = first_groups
                first_group = self._line_append_group_for_record(
                    first_groups, first[1]
                )
                if self._line_append_group_key(first_group) == self._line_append_group_key(
                    group
                ):
                    QMessageBox.information(
                        self,
                        "Line Append",
                        "The same line is already selected.",
                    )
                    return True

        self._line_append_selected.append((filename, int(record_id), px, py))

        if len(self._line_append_selected) < 2:
            self.updateLinePlot()
            return True

        self.updateLinePlot()
        action = self._prompt_lineappend_action()
        if action == "done":
            self._push_line_undo_state()
            first = self._line_append_selected[0]
            second = self._line_append_selected[1]
            if first[0] == second[0]:
                self._line_append_links.setdefault(first[0], []).append(
                    (first[1], second[1])
                )
            else:
                self._line_append_cross_links.append(
                    ((first[0], first[1]), (second[0], second[1]))
                )

        self._clear_line_append_selection()
        if action == "done":
            self._refresh_line_tab_data()
            self.actionDataJoinDisp.setChecked(False)
            self._save_line_edit_state()
        self.updateLinePlot()
        return True

    def _prompt_lineappend_action(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Line Append")
        dlg.setText("Append the selected lines?")
        done_btn = dlg.addButton("DONE", QMessageBox.AcceptRole)
        dlg.addButton("Cancel", QMessageBox.RejectRole)
        dlg.exec()

        if dlg.clickedButton() == done_btn:
            return "done"
        return "cancel"

    def _line_append_group_for_record(self, groups, record_id):
        if not groups:
            return None
        for group in groups:
            for start, end in group:
                if start <= record_id < end:
                    return group
        return None

    def _line_append_group_key(self, group):
        if not group:
            return None
        return tuple(group)

    def _build_line_append_groups(self, intervals, links):
        if not intervals:
            return []
        parent = list(range(len(intervals)))

        def find(idx):
            while parent[idx] != idx:
                parent[idx] = parent[parent[idx]]
                idx = parent[idx]
            return idx

        def union(a, b):
            ra = find(a)
            rb = find(b)
            if ra != rb:
                parent[rb] = ra

        for a_id, b_id in links:
            a_idx = self._find_interval_index(intervals, a_id)
            if a_idx is None:
                a_idx = self._find_closest_interval_index(intervals, a_id)
            b_idx = self._find_interval_index(intervals, b_id)
            if b_idx is None:
                b_idx = self._find_closest_interval_index(intervals, b_id)
            if a_idx is None or b_idx is None:
                continue
            union(a_idx, b_idx)

        grouped = {}
        for idx, interval in enumerate(intervals):
            root = find(idx)
            grouped.setdefault(root, []).append(interval)

        return list(grouped.values())

    def _build_cross_file_append_groups(self):
        if not self._line_append_cross_links:
            return []

        def find(parent, node):
            parent.setdefault(node, node)
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        def union(parent, a, b):
            ra = find(parent, a)
            rb = find(parent, b)
            if ra != rb:
                parent[rb] = ra

        def node_for_record(filename, record_id):
            groups = self._line_append_groups_by_file.get(filename, [])
            group = self._line_append_group_for_record(groups, record_id)
            if group is None:
                return None
            return (filename, self._line_append_group_key(group))

        parent = {}
        for (file_a, id_a), (file_b, id_b) in self._line_append_cross_links:
            node_a = node_for_record(file_a, id_a)
            node_b = node_for_record(file_b, id_b)
            if node_a is None or node_b is None:
                continue
            union(parent, node_a, node_b)

        if not parent:
            return []

        group_map = {}
        for filename, groups in self._line_append_groups_by_file.items():
            for group in groups:
                group_map[(filename, self._line_append_group_key(group))] = list(group)

        components = {}
        for node in parent:
            root = find(parent, node)
            components.setdefault(root, []).append(node)

        cross_groups = []
        for nodes in components.values():
            entries = []
            for filename, key in nodes:
                group = group_map.get((filename, key))
                if group:
                    entries.append((filename, group))
            if len(entries) >= 2:
                cross_groups.append(entries)

        return cross_groups

    def _find_interval_index(self, intervals, record_id):
        for idx, (start, end) in enumerate(intervals):
            if start <= record_id < end:
                return idx
        return None

    def _find_closest_interval_index(self, intervals, record_id):
        if not intervals:
            return None
        best_idx = None
        best_dist = None
        for idx, (start, end) in enumerate(intervals):
            if start <= record_id < end:
                return idx
            if record_id < start:
                dist = start - record_id
            else:
                dist = record_id - (end - 1)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def _clear_line_append_selection(self):
        self._line_append_selected.clear()

    def _validate_line_append_selection(self):
        if not self._line_append_selected:
            return
        for sel in self._line_append_selected:
            filename, record_id, _, _ = sel
            groups = self._line_append_groups_by_file.get(filename, [])
            if self._line_append_group_for_record(groups, record_id) is None:
                self._clear_line_append_selection()
                return

    def _handle_linecut_click(self, event, temporary=False):
        nearest = self._find_nearest_plot_point(event.xdata, event.ydata)
        if not nearest:
            QMessageBox.information(self, "Line Cut", "No data points available.")
            return True

        filename, record_id, px, py = nearest
        if temporary:
            self._linecut_preview = (filename, int(record_id))
            self._linecut_point = (px, py)
            self.updateLinePlot()
        action = self._prompt_linecut_action(filename, record_id)
        if action is None:
            if temporary:
                self._linecut_point = None
                self._linecut_preview = None
                self.updateLinePlot()
            else:
                self._linecut_point = None
            return True

        if not temporary:
            self._linecut_point = (px, py)
        record_id = int(record_id)
        changed = False
        if action == "cut":
            self._push_line_undo_state()
            self._line_cut_points.setdefault(filename, set()).add(record_id)
            changed = True
        elif action == "delete":
            intervals = self._line_intervals_by_file.get(filename, [])
            if not any(start <= record_id < end for start, end in intervals):
                QMessageBox.information(
                    self,
                    "Line Cut",
                    "Selected point does not belong to an active line.",
                )
                if temporary:
                    self._linecut_point = None
                    self._linecut_preview = None
                    self.updateLinePlot()
                return True
            self._push_line_undo_state()
            self._line_delete_points.setdefault(filename, set()).add(record_id)
            changed = True
        if temporary:
            self._linecut_point = None
            self._linecut_preview = None
        if changed:
            self._refresh_line_tab_data()
            self.actionDataCutDisp.setChecked(False)
            self._save_line_edit_state()
        self.updateLinePlot()
        return True

    def _find_nearest_plot_point(self, x, y):
        if not self._line_plot_df_by_file:
            return None

        best = None
        best_dist = None
        for filename, df in self._line_plot_df_by_file.items():
            if df is None or df.empty:
                continue
            if not {"X", "Y"}.issubset(df.columns):
                continue
            xs = df["X"].to_numpy()
            ys = df["Y"].to_numpy()
            if xs.size == 0:
                continue

            dx = xs - x
            dy = ys - y
            dist2 = dx * dx + dy * dy
            idx = int(np.argmin(dist2))
            dist = float(dist2[idx])
            if best_dist is None or dist < best_dist:
                row = df.iloc[idx]
                record_id = row["record_id"] if "record_id" in row else row.name
                try:
                    record_id = int(record_id)
                except Exception:
                    record_id = int(row.name)
                best = (filename, record_id, float(row["X"]), float(row["Y"]))
                best_dist = dist

        return best

    def _prompt_linecut_action(self, filename, record_id):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Line Cut")
        dlg.setText(f"{filename}\nrecord_id: {record_id}\nSelect action:")
        cut_btn = dlg.addButton("CUT", QMessageBox.AcceptRole)
        del_btn = dlg.addButton("DELETE", QMessageBox.DestructiveRole)
        dlg.addButton(QMessageBox.Cancel)
        dlg.exec()

        if dlg.clickedButton() == cut_btn:
            return "cut"
        if dlg.clickedButton() == del_btn:
            return "delete"
        return None

    def on_release(self, event):
        if event.button == 1:
            self._is_panning = False
            self._last_mouse_pos = None

    def on_motion(self, event):
        if not self._is_panning or event.inaxes != self.ax:
            return

        if self._last_mouse_pos is None:
            return

        dx = self._last_mouse_pos[0] - event.xdata
        dy = self._last_mouse_pos[1] - event.ydata

        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        self.ax.set_xlim(xlim[0] + dx, xlim[1] + dx)
        self.ax.set_ylim(ylim[0] + dy, ylim[1] + dy)

        self._last_mouse_pos = (event.xdata, event.ydata)
        self.canvas.draw_idle()

    def scroll(self, event):
        if event.inaxes != self.ax:
            return

        scale_factor = 1.2 if event.button == "up" else 1 / 1.2
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        xdata, ydata = event.xdata, event.ydata
        new_xlim = [
            xdata - (xdata - xlim[0]) * scale_factor,
            xdata + (xlim[1] - xdata) * scale_factor,
        ]
        new_ylim = [
            ydata - (ydata - ylim[0]) * scale_factor,
            ydata + (ylim[1] - ydata) * scale_factor,
        ]

        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)
        self.canvas.draw_idle()

    def on_item_clicked(self, item):
        file_name = item.text()
        self.updatePlot()

    def on_file_selection_changed(self):
        selected = [item.text() for item in self.fileListWidget.selectedItems()]
        if not selected:
            self._clear_plot_for_empty_selection("No files selected  to plot.")
            return
        self.updatePlot()

    def calc_XYlimit_listAll(self):
        all_x, all_y = [], []
        combined_df = getattr(self.db, "combined_df", None)
        if (
            combined_df is not None
            and not combined_df.empty
            and {"X", "Y"}.issubset(combined_df.columns)
        ):
            all_x = combined_df["X"].to_numpy()
            all_y = combined_df["Y"].to_numpy()
        else:
            listAll = [
                self.fileListWidget.item(i).text()
                for i in range(self.fileListWidget.count())
            ]
            for filename in listAll:
                df = self.db.get_FlightData(filename)
                if df is None or df.empty:
                    continue
                xdata, ydata, vals = self.db.get_XYMagData(df)
                all_x.extend(xdata)
                all_y.extend(ydata)
        if len(all_x) == 0 or len(all_y) == 0:
            return 0, 1, 0, 1
        pad = 100
        self.minx, self.maxx = int(np.min(all_x) - pad), int(np.max(all_x) + pad)
        self.miny, self.maxy = int(np.min(all_y) - pad), int(np.max(all_y) + pad)
        self.data_width = self.maxx - self.minx
        self.data_height = self.maxy - self.miny
        data_ratio = self.data_width / self.data_height

        w, h = self.canvas.get_width_height()
        if h <= 0:
            h = 1
        canvas_ratio = w / h

        if data_ratio < canvas_ratio:
            width = canvas_ratio * self.data_height
            minx = (self.minx + self.maxx) / 2 - width / 2
            maxx = (self.minx + self.maxx) / 2 + width / 2
            miny = self.miny
            maxy = self.maxy
        else:
            height = self.data_width / canvas_ratio
            miny = (self.miny + self.maxy) / 2 - height / 2
            maxy = (self.miny + self.maxy) / 2 + height / 2
            minx = self.minx
            maxx = self.maxx

        return minx, maxx, miny, maxy

    def _apply_line_edits(self, filename, df, base_intervals=None):
        if df is None or df.empty:
            return df, [], []

        work = df
        if "record_id" not in work.columns:
            work = work.copy()
            work["record_id"] = np.arange(len(work))

        if base_intervals is None:
            base_intervals = self.db.df_to_intervals(work)

        intervals = list(base_intervals)
        cut_points = self._line_cut_points.get(filename, set())
        if cut_points and intervals:
            cut_intervals = [(int(p), int(p) + 1) for p in cut_points]
            intervals = subtract_intervals(intervals, cut_intervals)

        delete_points = self._line_delete_points.get(filename, set())
        if delete_points and intervals:
            intervals = [
                (start, end)
                for start, end in intervals
                if not any(start <= p < end for p in delete_points)
            ]

        if intervals:
            work = self._filter_df_by_intervals(work, intervals)
        else:
            work = work.iloc[0:0]

        return work, intervals, base_intervals

    def _filter_df_by_intervals(self, df, intervals):
        if df is None or df.empty or not intervals:
            return df.iloc[0:0]
        record_ids = pd.to_numeric(df["record_id"], errors="coerce").to_numpy()
        keep = np.zeros(len(df), dtype=bool)
        for start, end in intervals:
            keep |= (record_ids >= start) & (record_ids < end)
        return df.loc[keep].copy()

    def _clear_overlay_artists(self):
        if not self._overlay_artists:
            return
        for artist in self._overlay_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._overlay_artists = []

    def _clear_legend(self):
        if self._legend is None:
            return
        try:
            self._legend.remove()
        except Exception:
            pass
        self._legend = None

    def _current_file_names(self):
        return {
            self.fileListWidget.item(i).text()
            for i in range(self.fileListWidget.count())
        }

    def _serialize_line_edit_state(self) -> dict:
        return {
            "cut_points": {
                fname: sorted(int(p) for p in points)
                for fname, points in self._line_cut_points.items()
            },
            "delete_points": {
                fname: sorted(int(p) for p in points)
                for fname, points in self._line_delete_points.items()
            },
            "append_links": {
                fname: [[int(a), int(b)] for a, b in links]
                for fname, links in self._line_append_links.items()
            },
            "append_cross_links": [
                [[fa, int(ida)], [fb, int(idb)]]
                for (fa, ida), (fb, idb) in self._line_append_cross_links
            ],
        }

    def _extract_latlon_alt(self, df):
        lat_series = df.get("Latitude")
        lon_series = df.get("Longitude")
        if lat_series is not None and lon_series is not None:
            lats = pd.to_numeric(lat_series, errors="coerce").to_numpy()
            lons = pd.to_numeric(lon_series, errors="coerce").to_numpy()
        else:
            if not {"X", "Y"}.issubset(df.columns):
                return None, None, None
            epsg = None
            if "CRS_EPSG" in df.columns:
                try:
                    epsg = int(df["CRS_EPSG"].iloc[0])
                except Exception:
                    epsg = None
            if epsg is None and self._last_epsg:
                try:
                    epsg = int(self._last_epsg)
                except Exception:
                    epsg = None
            if epsg is None:
                return None, None, None
            transformer = Transformer.from_crs(
                f"EPSG:{int(epsg)}", "EPSG:4326", always_xy=True
            )
            xs = pd.to_numeric(df["X"], errors="coerce").to_numpy()
            ys = pd.to_numeric(df["Y"], errors="coerce").to_numpy()
            lons, lats = transformer.transform(xs, ys)

        alt = None
        if "Altitude" in df.columns:
            alt = pd.to_numeric(df["Altitude"], errors="coerce").to_numpy()
        return lats, lons, alt

    def exportKML(self):
        if not self._plot_df_by_file:
            self.updatePlot()
        if not self._plot_df_by_file:
            QMessageBox.information(self, "Export KML", "No data to export.")
            return

        proj_path = Path(config.get("project_path", ""))
        if proj_path:
            default_path = proj_path / "flight_plot.kml"
        else:
            default_path = Path.cwd() / "flight_plot.kml"

        file_path, _ = QFileDialog.getSaveFileName(
            parent=self,
            caption="Export KML",
            dir=str(default_path),
            filter="KML files (*.kml);;All files (*)",
        )
        if not file_path:
            return

        try:
            total_points = 0
            with open(file_path, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
                f.write("  <Document>\n")
                f.write("    <name>Flight Plot</name>\n")
                # Line style
                f.write(
                    "    <Style id=\"lineStyle\">"
                    "<LineStyle><color>ff0000ff</color><width>3</width></LineStyle>"
                    "</Style>\n"
                )
                # Point style
                f.write(
                    "    <Style id=\"ptStyle\">"
                    "<IconStyle><scale>0.7</scale>"
                    "<Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>"
                    "</IconStyle>"
                    "</Style>\n"
                )

                # Choose the data source based on the active tab.
                use_line_tab = (
                    hasattr(self, "plotTabs")
                    and self.plotTabs.tabText(self.plotTabs.currentIndex()) == "Line"
                    and bool(self._line_plot_df_by_file)
                )
                if use_line_tab:
                    line_entries = self._build_line_plot_entries()
                    for df in line_entries:
                        if df is None or df.empty:
                            continue
                        lats, lons, alts = self._extract_latlon_alt(df)
                        if lats is None or lons is None:
                            continue
                        coords = []
                        for lat, lon, alt_val in zip(
                            np.asarray(lats),
                            np.asarray(lons),
                            np.asarray(alts) if alts is not None else np.zeros(len(lats)),
                        ):
                            if np.isnan(lat) or np.isnan(lon):
                                continue
                            alt = 0.0 if np.isnan(alt_val) else float(alt_val)
                            coords.append(f"{float(lon)},{float(lat)},{alt}")
                        if coords:
                            f.write("      <Placemark>\n")
                            f.write("        <styleUrl>#lineStyle</styleUrl>\n")
                            f.write("        <tessellate>1</tessellate>\n")
                            f.write("        <LineString>\n")
                            f.write("          <tessellate>1</tessellate>\n")
                            f.write("          <coordinates>\n")
                            f.write("            " + " ".join(coords) + "\n")
                            f.write("          </coordinates>\n")
                            f.write("        </LineString>\n")
                            f.write("      </Placemark>\n")
                            total_points += len(coords)
                else:
                    df_by_file = self._plot_df_by_file
                    for fname, df in df_by_file.items():
                        if df is None or df.empty:
                            continue
                        lats, lons, alts = self._extract_latlon_alt(df)
                        if lats is None or lons is None:
                            logger.warning(
                                f"Export KML: missing lat/lon for {fname}, skipping."
                            )
                            continue

                        work = df
                        if "record_id" not in work.columns:
                            work = work.copy()
                            work["record_id"] = np.arange(len(work))
                        record_ids = pd.to_numeric(
                            work["record_id"], errors="coerce"
                        ).to_numpy()
                        intervals = self.db.df_to_intervals(work)

                        arr_lats = np.asarray(lats)
                        arr_lons = np.asarray(lons)
                        arr_alts = np.asarray(alts) if alts is not None else None

                        for start, end in intervals:
                            mask = (record_ids >= start) & (record_ids < end)
                            if not mask.any():
                                continue
                            coords = []
                            for lat, lon, alt_val in zip(
                                arr_lats[mask],
                                arr_lons[mask],
                                arr_alts[mask] if arr_alts is not None else np.zeros(mask.sum()),
                            ):
                                if np.isnan(lat) or np.isnan(lon):
                                    continue
                                alt = 0.0
                                if not np.isnan(alt_val):
                                    alt = float(alt_val)
                                coords.append(f"{float(lon)},{float(lat)},{alt}")
                            if coords:
                                f.write("      <Placemark>\n")
                                f.write("        <styleUrl>#lineStyle</styleUrl>\n")
                                f.write("        <tessellate>1</tessellate>\n")
                                f.write("        <LineString>\n")
                                f.write("          <tessellate>1</tessellate>\n")
                                f.write("          <coordinates>\n")
                                f.write("            " + " ".join(coords) + "\n")
                                f.write("          </coordinates>\n")
                                f.write("        </LineString>\n")
                                f.write("      </Placemark>\n")
                                total_points += len(coords)

                f.write("  </Document>\n")
                f.write("</kml>\n")

            if total_points == 0:
                QMessageBox.warning(
                    self,
                    "Export KML",
                    "No valid coordinates to export.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Export KML",
                    f"Saved {total_points} points to:\n{file_path}",
                )
        except Exception as err:
            logger.error(f"Export KML failed: {err}")
            QMessageBox.critical(
                self,
                "Export KML",
                f"Failed to export KML:\n{err}",
            )

    def _save_line_edit_state(self) -> None:
        if config.file_path is None:
            return
        try:
            config.set(
                "flight_line_edit_state",
                self._serialize_line_edit_state(),
                save=True,
            )
        except Exception as err:
            logger.warning(f"Failed to save line edit state: {err}")

    def _load_line_edit_state(self) -> None:
        state = config.get("flight_line_edit_state", {}) or {}
        valid_files = self._current_file_names()

        self._line_cut_points = {}
        self._line_delete_points = {}
        self._line_append_links = {}
        self._line_append_cross_links = []
        self._line_append_groups_by_file = {}
        self._line_append_cross_groups = []
        self._clear_line_append_selection()
        self._linecut_preview = None
        self._linecut_point = None

        for fname, points in (state.get("cut_points") or {}).items():
            if fname in valid_files:
                self._line_cut_points[fname] = {int(p) for p in points}

        for fname, points in (state.get("delete_points") or {}).items():
            if fname in valid_files:
                self._line_delete_points[fname] = {int(p) for p in points}

        for fname, links in (state.get("append_links") or {}).items():
            if fname in valid_files:
                cleaned = []
                for a, b in links:
                    cleaned.append((int(a), int(b)))
                self._line_append_links[fname] = cleaned

        for link in state.get("append_cross_links") or []:
            try:
                (fa, ida), (fb, idb) = link
            except Exception:
                continue
            if fa in valid_files and fb in valid_files:
                self._line_append_cross_links.append(
                    ((fa, int(ida)), (fb, int(idb)))
                )
        self._line_undo_stack = []
        self._line_redo_stack = []

    def _ensure_line_tab_state_restored(self) -> None:
        if not self._plot_df_by_file:
            return
        if self._line_plot_state_hash is None:
            return
        if self._line_base_state_hash == self._line_plot_state_hash:
            return
        if self._regenerate_line_tab_data(reset_state=False):
            self.updateLinePlot()

    def _restore_last_tab(self) -> None:
        """Select Line tab on project load if it was last used and data exists."""
        if not hasattr(self, "plotTabs"):
            return
        last_tab = str(config.get("flightplot_last_tab", "Flight")).strip()
        if not last_tab:
            return
        # Do not switch to Line unless data is ready
        if last_tab.lower() == "line":
            has_line_data = bool(self._line_plot_df_by_file or self._line_base_df_by_file)
            if not has_line_data:
                return
        for idx in range(self.plotTabs.count()):
            if self.plotTabs.tabText(idx).lower() == last_tab.lower():
                if self.plotTabs.currentIndex() != idx:
                    self.plotTabs.setCurrentIndex(idx)
                return

    def _clear_plot_for_empty_selection(self, title: str) -> None:
        self._clear_overlay_artists()
        self._clear_legend()
        for scatter in self._scatter_by_file.values():
            scatter.set_visible(False)
        if self._color_scatter is not None:
            self._color_scatter.set_visible(False)
        if self._map_artist is not None:
            self._map_artist.set_visible(False)
        if hasattr(self, "colorbar"):
            self.colorbar.remove()
            del self.colorbar
        if hasattr(self, "sm"):
            del self.sm
        self.ax.set_title(title)
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1)
        self.ax.grid(True)
        self.canvas.draw_idle()

    def _draw_line_append_overlays(self, palette, ax=None):
        artists = []
        if ax is None:
            ax = self.ax
        if not self._line_append_selected:
            return artists
        drawn = set()
        for idx, (filename, record_id, _, _) in enumerate(self._line_append_selected):
            groups = self._line_append_groups_by_file.get(filename, [])
            group = self._line_append_group_for_record(groups, record_id)
            if not group:
                continue
            group_key = (filename, self._line_append_group_key(group))
            if group_key in drawn:
                continue
            drawn.add(group_key)
            df = self._line_plot_df_by_file.get(filename)
            if df is None or df.empty:
                continue
            if not {"X", "Y", "record_id"}.issubset(df.columns):
                continue
            record_ids = pd.to_numeric(df["record_id"], errors="coerce").to_numpy()
            for start, end in group:
                mask = (record_ids >= start) & (record_ids < end)
                seg = df.loc[mask]
                if seg.empty:
                    continue
                line = ax.plot(
                    seg["X"].values,
                    seg["Y"].values,
                    linewidth=3,
                    marker="o",
                    c="yellow",
                    zorder=6,
                )[0]
                artists.append(line)
        return artists

    def _draw_linecut_preview(self, ax=None):
        if not self._linecut_preview:
            return []
        if ax is None:
            ax = self.ax
        filename, record_id = self._linecut_preview
        intervals = self._line_intervals_by_file.get(filename, [])
        interval = None
        for start, end in intervals:
            if start <= record_id < end:
                interval = (start, end)
                break
        if interval is None:
            return []

        df = self._line_plot_df_by_file.get(filename)
        if df is None or df.empty:
            return []
        if not {"X", "Y", "record_id"}.issubset(df.columns):
            return []
        record_ids = pd.to_numeric(df["record_id"], errors="coerce").to_numpy()
        start, end = interval
        mask = (record_ids >= start) & (record_ids < end)
        seg = df.loc[mask]
        if seg.empty:
            return []
        line = ax.plot(
            seg["X"].values,
            seg["Y"].values,
            linewidth=3,
            marker="o",
            c="yellow",
            zorder=6,
        )[0]
        return [line]

    def _line_plot_start_x(self, df):
        if df is None or df.empty or "X" not in df.columns:
            return float("inf")
        series = pd.to_numeric(df["X"], errors="coerce")
        if series.empty:
            return float("inf")
        first = series.iloc[0]
        if pd.isna(first):
            return float("inf")
        return float(first)

    def _build_line_plot_entries(self):
        df_by_file = self._line_plot_df_by_file or getattr(
            self.db, "scanline_df_by_file", {}
        )
        if not df_by_file:
            return []

        groups_by_file = self._line_append_groups_by_file or getattr(
            self.db, "scanline_groups_by_file", {}
        )
        intervals_by_file = self._line_intervals_by_file or getattr(
            self.db, "scanline_intervals_by_file", {}
        )
        cross_groups = self._line_append_cross_groups or getattr(
            self.db, "scanline_cross_groups", []
        )

        entries = []
        skip_groups = set()

        def group_key(group):
            return tuple((int(start), int(end)) for start, end in group)

        if cross_groups:
            for group in cross_groups:
                for fname, intervals in group:
                    skip_groups.add((fname, group_key(intervals)))
            for group in cross_groups:
                parts = []
                for fname, intervals in group:
                    df = df_by_file.get(fname)
                    if df is None or df.empty:
                        continue
                    work = df
                    if "record_id" not in work.columns:
                        work = work.copy()
                        work["record_id"] = np.arange(len(work))
                    record_ids = pd.to_numeric(
                        work["record_id"], errors="coerce"
                    ).to_numpy()
                    if record_ids.size == 0:
                        continue
                    mask = np.zeros(len(work), dtype=bool)
                    for start, end in intervals:
                        mask |= (record_ids >= start) & (record_ids < end)
                    g = work.loc[mask].copy()
                    if g.empty:
                        continue
                    g["record_id"] = pd.to_numeric(
                        g["record_id"], errors="coerce"
                    )
                    g = g.sort_values("record_id").reset_index(drop=True)
                    parts.append(g)
                if parts:
                    merged = pd.concat(parts, ignore_index=True)
                    merged = merged.sort_values("record_id").reset_index(drop=True)
                    entries.append(merged)

        for filename, df in df_by_file.items():
            if df is None or df.empty:
                continue
            work = df
            if "record_id" not in work.columns:
                work = work.copy()
                work["record_id"] = np.arange(len(work))
            record_ids = pd.to_numeric(
                work["record_id"], errors="coerce"
            ).to_numpy()
            if record_ids.size == 0:
                continue
            groups = groups_by_file.get(filename)
            if not groups:
                intervals = intervals_by_file.get(filename, [])
                groups = [[interval] for interval in intervals]
            for group in groups:
                if not group:
                    continue
                if (filename, group_key(group)) in skip_groups:
                    continue
                mask = np.zeros(len(work), dtype=bool)
                for start, end in group:
                    mask |= (record_ids >= start) & (record_ids < end)
                g = work.loc[mask].copy()
                if g.empty:
                    continue
                g["record_id"] = pd.to_numeric(
                    g["record_id"], errors="coerce"
                )
                g = g.sort_values("record_id").reset_index(drop=True)
                entries.append(g)

        entries.sort(key=self._line_plot_start_x)
        return entries

    def updateLinePlot(self):
        if self.line_ax is None or self.line_canvas is None:
            return

        self.line_ax.clear()

        # Reuse the background map from the Flight tab in the Line tab.
        self._line_map_artist = None
        if (
            self.map_type
            and self.map_type != "none"
            and self._map_image is not None
            and self._map_extent is not None
        ):
            try:
                self._line_map_artist = self.line_ax.imshow(
                    self._map_image,
                    extent=self._map_extent,
                    origin="upper",
                    zorder=0,
                    aspect="equal",
                )
            except Exception as e:
                logger.warning(f"Line map draw failed: {e}")

        line_entries = self._build_line_plot_entries()
        if not line_entries:
            self.line_ax.set_title("No line data to plot")
        else:
            colors = ("#1f77b4", "#ff7f0e")
            for idx, df in enumerate(line_entries):
                if not {"X", "Y"}.issubset(df.columns):
                    continue
                x = pd.to_numeric(df["X"], errors="coerce").to_numpy()
                y = pd.to_numeric(df["Y"], errors="coerce").to_numpy()
                mask = np.isfinite(x) & np.isfinite(y)
                if not mask.any():
                    continue
                xs = x[mask]
                ys = y[mask]
                color = colors[idx % 2]
                self.line_ax.scatter(xs, ys, s=4, color=color, zorder=3)
                if xs.size > 1:
                    dx = np.diff(xs)
                    dy = np.diff(ys)
                    valid = np.isfinite(dx) & np.isfinite(dy)
                    if valid.any():
                        self.line_ax.quiver(
                            xs[:-1][valid],
                            ys[:-1][valid],
                            dx[valid],
                            dy[valid],
                            angles="xy",
                            scale_units="xy",
                            scale=1,
                            pivot="tail",
                            color=color,
                            width=0.0025,
                            headwidth=3,
                            headlength=4,
                            headaxislength=3.5,
                            zorder=2,
                        )

        palette = plt.get_cmap("tab10").colors
        self._draw_linecut_preview(ax=self.line_ax)
        self._draw_line_append_overlays(palette, ax=self.line_ax)
        if self.actionDataCutDisp.isChecked() and self._linecut_point:
            x, y = self._linecut_point
            self.line_ax.scatter([x], [y], s=40, marker="x", color="red", zorder=10)

        self.line_ax.ticklabel_format(useOffset=False, style="plain", axis="x")
        self.line_ax.ticklabel_format(useOffset=False, style="plain", axis="y")
        self.line_ax.set_title("Line Plot")
        self.line_ax.set_xlabel("Easting (m)")
        self.line_ax.set_ylabel("Northing (m)")
        self.line_ax.grid(True)
        self.line_ax.set_aspect("equal", "box")
        self.line_fig.tight_layout()
        self.line_canvas.draw()

    def updatePlot(self):
        cfg = config.get("filters")
        direction_degree = config.get("direction")

        try:
            # --- 1) Collect the selected file list ---
            selected = [item.text() for item in self.fileListWidget.selectedItems()]
            if not selected:
                self._clear_plot_for_empty_selection(
                    "No files selected  to plot."
                )
                return

            # --- 2) Extract X, Y, and values for each file ---
            all_x, all_y, all_vals = [], [], []
            all_lat, all_lon = [], []
            file_data_list = []
            self._plot_df_by_file = {}
            self.db.clear_combined_df()
            timeline = None
            timeline_id = "flight:plot"
            source_offsets = {}
            try:
                timeline = self.db.reset_timeline(timeline_id, selected)
                source_offsets = {
                    sid: timeline.offsets[idx]
                    for idx, sid in enumerate(timeline.source_ids)
                }
            except Exception as e:
                logger.exception("Failed to create plot timeline")
            data_epsg = None
            for filename in selected:
                src_df = self.db.get_FlightData(filename)
                if src_df is None or src_df.empty:
                    continue
                filtered_df = self.db.get_filtered_data(
                    src_df, cfg, direction_degree
                )
                if filtered_df is None or filtered_df.empty:
                    continue

                base_df = filtered_df
                if "record_id" not in base_df.columns:
                    base_df = base_df.copy()
                    base_df["record_id"] = np.arange(len(base_df))
                intervals = self.db.df_to_intervals(base_df)
                if not intervals:
                    continue

                xdata = ydata = vals = None
                seg_df = None
                if timeline is not None and filename in source_offsets:
                    offset = source_offsets[filename]
                    global_intervals = [
                        (offset + s, offset + e) for s, e in intervals
                    ]
                    segment_id = f"{timeline_id}:{filename}"
                    try:
                        self.db.create_segment(
                            segment_id,
                            timeline_id,
                            global_intervals,
                            meta={"source": filename},
                        )
                        xdata, ydata, vals = self.db.get_scatter_arrays(
                            segment_id, "X", "Y", "Mag", stride=1
                        )
                        seg_df = self.db.materialize_segment_df(segment_id)
                    except Exception as e:
                        logger.exception(
                            f"Failed to build scatter segment for flight file '{filename}'"
                        )

                if seg_df is None or seg_df.empty:
                    seg_df = base_df

                if xdata is None or ydata is None or vals is None:
                    xdata, ydata, vals = self.db.get_XYMagData(seg_df)

                if len(xdata) == 0:
                    continue

                self._plot_df_by_file[filename] = seg_df
                self.db.put_combined_df(seg_df)

                lat_series = seg_df.get("Latitude")
                lon_series = seg_df.get("Longitude")
                if "CRS_EPSG" in seg_df.columns and data_epsg is None:
                    try:
                        data_epsg = int(seg_df["CRS_EPSG"].iloc[0])
                    except Exception:
                        data_epsg = None

                if lat_series is not None and lon_series is not None:
                    all_lat.extend(
                        pd.to_numeric(lat_series, errors="coerce").dropna()
                    )
                    all_lon.extend(
                        pd.to_numeric(lon_series, errors="coerce").dropna()
                    )
                file_data_list.append((filename, xdata, ydata, vals))
                all_x.extend(xdata)
                all_y.extend(ydata)
                all_vals.extend(vals)

            self.df = self.db.combined_df
            hash_items = [
                (fname, len(df) if df is not None else 0)
                for fname, df in self._plot_df_by_file.items()
            ]
            new_hash = tuple(sorted(hash_items)) if hash_items else None
            previous_hash = self._line_plot_state_hash
            if new_hash != previous_hash:
                self._line_plot_state_hash = new_hash
                self._line_base_state_hash = None
            else:
                self._line_plot_state_hash = new_hash
            if len(all_x) == 0:
                self._clear_plot_for_empty_selection("No data to plot.")
                return

            vmin = np.min(all_vals)
            vmax = np.max(all_vals)
            self.values_colorbar = (vmin, vmax)

            map_drawn = False
            if self.map_type and self.map_type != "none":
                map_drawn = self._update_background_map(
                    all_lat, all_lon, data_epsg=data_epsg
                )

            data_minx, data_maxx, data_miny, data_maxy = self.calc_XYlimit_listAll()
            # Always start the axes at the data bounds, matching the no-background view.
            # Even if the image is larger, the imshow extent still covers the full map during pan/zoom.
            self.ax.set_xlim(data_minx, data_maxx)
            self.ax.set_ylim(data_miny, data_maxy)
            if map_drawn and self._map_image is not None and self._map_extent:
                try:
                    # Draw the fetched background image using the original map extent.
                    display_extent = self._map_extent
                    if self._map_artist is None:
                        self._map_artist = self.ax.imshow(
                            self._map_image,
                            extent=display_extent,
                            origin="upper",
                            zorder=0,
                            aspect="equal",
                        )
                    else:
                        self._map_artist.set_data(self._map_image)
                        self._map_artist.set_extent(display_extent)
                        self._map_artist.set_visible(True)
                except Exception as e:
                    logger.exception("Failed to draw background map")
                    map_drawn = False
                    self._map_image = None
                    self._map_extent = None
            else:
                if self._map_artist is not None:
                    self._map_artist.set_visible(False)


            # # --- 5) Configure the colormap ---
            show_cb = cfg.get("show_colorbar", False)
            palette = plt.get_cmap("tab10").colors
            self._clear_legend()
            if show_cb:
                cmap = plt.cm.get_cmap("jet")
                norm = plt.Normalize(vmin=vmin, vmax=vmax)
                for scatter in self._scatter_by_file.values():
                    scatter.set_visible(False)
                all_x_arr = np.asarray(all_x)
                all_y_arr = np.asarray(all_y)
                all_vals_arr = np.asarray(all_vals)
                if self._color_scatter is None:
                    self._color_scatter = self.ax.scatter(
                        all_x_arr,
                        all_y_arr,
                        c=all_vals_arr,
                        cmap=cmap,
                        norm=norm,
                        s=1,
                        alpha=0.8,
                        zorder=5,
                    )
                else:
                    if all_x_arr.size:
                        offsets = np.column_stack((all_x_arr, all_y_arr))
                    else:
                        offsets = np.empty((0, 2))
                    self._color_scatter.set_offsets(offsets)
                    self._color_scatter.set_array(all_vals_arr)
                    self._color_scatter.set_cmap(cmap)
                    self._color_scatter.set_norm(norm)
                    self._color_scatter.set_visible(True)
                self.sm = self._color_scatter
                if not hasattr(self, "colorbar"):
                    self.colorbar = self.fig.colorbar(
                        self._color_scatter,
                        ax=self.ax,
                        label="Value",
                        shrink=0.5,
                        pad=0.04,
                        fraction=0.05,
                    )
                else:
                    self.colorbar.update_normal(self._color_scatter)
                    self.colorbar.ax.ticklabel_format(useOffset=False, style="plain")
            else:
                if self._color_scatter is not None:
                    self._color_scatter.set_visible(False)
                if hasattr(self, "colorbar"):
                    self.colorbar.remove()
                    del self.colorbar
                if hasattr(self, "sm"):
                    del self.sm
                active_files = set()
                for idx, (fname, x, y, vals) in enumerate(file_data_list):
                    color = palette[idx % len(palette)]
                    active_files.add(fname)
                    scatter = self._scatter_by_file.get(fname)
                    if scatter is None:
                        scatter = self.ax.scatter(
                            x,
                            y,
                            color=color,
                            s=1,
                            alpha=0.8,
                            zorder=5,
                            label=fname,
                        )
                        self._scatter_by_file[fname] = scatter
                    else:
                        offsets = np.column_stack((x, y)) if len(x) else np.empty((0, 2))
                        scatter.set_offsets(offsets)
                        scatter.set_color(color)
                        scatter.set_visible(True)
                        scatter.set_label(fname)
                for fname, scatter in self._scatter_by_file.items():
                    if fname not in active_files:
                        scatter.set_visible(False)
                if active_files:
                    self._legend = self.ax.legend(
                        loc="best", fontsize=8, frameon=True
                    )
            # ployline
            self._clear_overlay_artists()
            overlay_artists = []

            is_line_tab = (
                hasattr(self, "plotTabs")
                and self.plotTabs.tabText(self.plotTabs.currentIndex()) == "Line"
            )
            if is_line_tab:
                overlay_artists.extend(self._draw_linecut_preview())
                overlay_artists.extend(self._draw_line_append_overlays(palette))

                if self.actionDataCutDisp.isChecked() and self._linecut_point:
                    x, y = self._linecut_point
                    point = self.ax.scatter(
                        [x], [y], s=40, marker="x", color="red", zorder=10
                    )
                    overlay_artists.append(point)
            self._overlay_artists = overlay_artists
            # Disable offset notation so absolute values remain visible.
            self.ax.ticklabel_format(useOffset=False, style="plain", axis="x")
            self.ax.ticklabel_format(useOffset=False, style="plain", axis="y")

            # --- 8) Styling ---
            self.ax.set_title("Mag Plot")
            self.ax.set_xlabel("Easting (m)")
            self.ax.set_ylabel("Northing (m)")
            self.ax.grid(True)
            self.ax.set_aspect("equal")

        except Exception as err:
            logger.exception("Flight plot update failed")

        self.fig.tight_layout()
        self.canvas.draw()
        if (
            hasattr(self, "plotTabs")
            and self.plotTabs.tabText(self.plotTabs.currentIndex()) == "Line"
        ):
            self.updateLinePlot()

    def _fit_bounds_to_canvas_equal(self, margin_ratio=0.05):
        """Expand x/y limits to fit the canvas while keeping aspect=equal (1:1)."""
        ax = self.ax
        # Current data bounds
        x1, x2 = ax.get_xlim()
        y1, y2 = ax.get_ylim()

        # Compute the data range
        rx = max(x2 - x1, 1e-12)
        ry = max(y2 - y1, 1e-12)

        # # Apply a 5% margin if extra padding has not already been added.
        cx = (x1 + x2) * 0.5
        cy = (y1 + y2) * 0.5

        # Canvas pixel aspect ratio
        w, h = self.canvas.get_width_height()
        if h <= 0:
            h = 1
        canvas_ratio = w / h  # (width/height)

        # Match the data rx/ry ratio to the canvas ratio to preserve aspect=equal.
        data_ratio = rx / ry
        if data_ratio < canvas_ratio:
            # Increase rx when the width is too small.
            rx = canvas_ratio * ry
        else:
            # Increase ry when the height is too small.
            ry = rx / canvas_ratio

        # Apply the new bounds while keeping the center fixed.
        new_x1, new_x2 = cx - rx * 0.5, cx + rx * 0.5
        new_y1, new_y2 = cy - ry * 0.5, cy + ry * 0.5

        ax.set_xlim(new_x1, new_x2)
        ax.set_ylim(new_y1, new_y2)
        self.ax.set_aspect("equal")
        self.canvas.draw_idle()

    def _fit_bounds_to_canvas_equal_on(self, ax, canvas, margin_ratio=0.05):
        if ax is None or canvas is None:
            return
        x1, x2 = ax.get_xlim()
        y1, y2 = ax.get_ylim()

        rx = max(x2 - x1, 1e-12)
        ry = max(y2 - y1, 1e-12)

        cx = (x1 + x2) * 0.5
        cy = (y1 + y2) * 0.5

        w, h = canvas.get_width_height()
        if h <= 0:
            h = 1
        canvas_ratio = w / h

        data_ratio = rx / ry
        if data_ratio < canvas_ratio:
            rx = canvas_ratio * ry
        else:
            ry = rx / canvas_ratio

        new_x1, new_x2 = cx - rx * 0.5, cx + rx * 0.5
        new_y1, new_y2 = cy - ry * 0.5, cy + ry * 0.5

        ax.set_xlim(new_x1, new_x2)
        ax.set_ylim(new_y1, new_y2)
        ax.set_aspect("equal")
        canvas.draw_idle()

    def updateFileList(self, files):
        """Update the list widget with files from the selected folder."""
        blocker = QSignalBlocker(self.fileListWidget)
        self.fileListWidget.clear()

        for file_name in files:
            item = QListWidgetItem(file_name)
            self.fileListWidget.addItem(item)
            item.setSelected(True)
            self.fileListWidget.setFocus()
        del blocker

        proj_path = Path(config.get("project_path", ""))
        self.db.clear_FlightData()

        for file_name in files:
            file_path = proj_path / "Measure Flight Folder" / (file_name + ".csv")
            self.db.load_FlightData(file_path)
        self.updatePlot()

    def modify(self, points):
        user_response = QMessageBox.question(
            self,
            "Confirm Region Selection",
            "Do you want to select data within the drawn region?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        apply_area = user_response == QMessageBox.StandardButton.Yes
        if apply_area:
            logger.info(f"Applied area selection with {len(points)} polygon point(s)")
            config.set("bound_area_points", points, save=True)
        self.polygonDrawer.clear()
        self.polygonDrawer.enable(False)
        self._is_panning = False
        self._last_mouse_pos = None

        filters = config.get("filters", {}) or {}
        filters.setdefault("enable_area_bound", False)
        filters.setdefault("show_area_bound", False)
        filters["enable_area_bound"] = False
        if apply_area:
            filters["show_area_bound"] = True
        config.set("filters", filters, save=True)

        if apply_area:
            self.updatePlot()

    def load_bound_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Assume the first line is a count/header and skip it.
            vertex_points = []
            for line in lines[1:]:  # Skip the first line
                parts = line.strip().split()
                if len(parts) != 2:
                    logger.warning(f"Invalid line: {line.strip()}")
                    continue
                x, y = map(float, parts)
                vertex_points.append((x, y))

            # Close the polygon if the first and last vertices are different.
            if vertex_points and vertex_points[0] != vertex_points[-1]:
                vertex_points.append(vertex_points[0])

            config.set("bound_area_points", vertex_points, save=True)
            logger.info(f"Vertex load complete: {len(vertex_points)} points")
            self.updatePlot()

        except Exception as e:
            logger.exception(f"Failed to load boundary file: {file_path}")
            QMessageBox.critical(
                self,
                "File Error",
                f"An error occurred while opening or processing the file: {repr(e)}",
            )

    def openFileBrowser(self):
        proj_path = Path(config.get("project_path", ""))
        if not proj_path:
            QMessageBox.warning(self, "ERROR", "Open a project folder first.")
            return
        open_path = proj_path / "Measure Flight Folder"
        files, _ = QFileDialog.getOpenFileNames(
            parent=self,
            caption="Select Mag data files",
            dir=str(open_path),
            filter="Flight data (*.csv);;All files (*)",
        )
        if not files:
            return

        list_files = config.get("Flight_File_List", [])
        for file in files:
            p = Path(file)
            name_wo_ext = p.stem
            if name_wo_ext not in list_files:
                list_files.append(name_wo_ext)

        list_files = list(set(list_files))
        config.set("Flight_File_List", list_files, save=True)
        logger.info(f"Added {len(files)} flight data file(s) from {open_path}")
        self.updateFileList(list_files)

    def initialize(self):
        filters_defaults = {
            "direction_filter": {"enabled": False, "threshold": 5},
            "continuity_filter": {"enabled": False, "num_points": 10},
            "speed_filter": {"enabled": False, "target_speed": 5, "tolerance": 1},
            "show_colorbar": False,
            "show_backgroundmap": False,
            "enable_area_bound": False,
            "show_area_bound": False,
        }

        filters = config.get("filters", {})
        if not filters:
            filters = filters_defaults.copy()
        else:
            for key, value in filters_defaults.items():
                filters.setdefault(key, value)

        # Do not persist background map selection; always start from `none`.
        if "background_map_type" in filters:
            filters.pop("background_map_type", None)
        config.set("filters", filters, save=True)
        self._set_map_type("none", update_plot=False, log_source="initialize")

        flightData_path = os.path.join(
            config.get("project_path", ""), "Measure Flight Folder"
        )
        if not os.path.exists(flightData_path):
            os.makedirs(flightData_path)

        list_files = config.get("Flight_File_List", [])
        self.updateFileList(list_files)
        logger.info(
            f"Flight plot initialized with {len(list_files)} project flight file(s)"
        )

    def show_file_list_context_menu(self, position):
        item = self.fileListWidget.itemAt(position)
        if not item:
            return

        menu = QMenu()
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.fileListWidget.mapToGlobal(position))

        if action == delete_action:
            self.delete_selected_items(item)

    def delete_selected_items(self, item_to_delete):
        name = item_to_delete.text()

        reply = QMessageBox.question(
            self,
            "Delete Item",
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.fileListWidget.takeItem(self.fileListWidget.row(item_to_delete))

            list_files = config.get("Flight_File_List", [])
            if name in list_files:
                list_files.remove(name)
            config.set("Flight_File_List", list_files, save=True)

            self._line_cut_points.pop(name, None)
            self._line_delete_points.pop(name, None)
            self._line_append_links.pop(name, None)
            self._line_append_groups_by_file.pop(name, None)
            if self._line_append_cross_links:
                self._line_append_cross_links = [
                    link
                    for link in self._line_append_cross_links
                    if name not in (link[0][0], link[1][0])
                ]
            self._save_line_edit_state()
            self.updatePlot()

    def delete_all_items(self):
        self.fileListWidget.clear()
        self.db.clear_FlightData()
        self._plot_df_by_file.clear()
        self._line_base_df_by_file.clear()
        self._line_base_intervals_by_file.clear()
        self._line_plot_df_by_file.clear()
        self._line_intervals_by_file.clear()
        self._line_plot_state_hash = None
        self._line_base_state_hash = None
        self._reset_line_edit_state()
        self._refresh_line_tab_data()
        self._save_line_edit_state()
        self.updatePlot()
        self.updateLinePlot()

    def on_canvas_click(self, event):
        """Handle clicks on the canvas, specifically on the colorbar."""
        if not (hasattr(self, "colorbar") and self.colorbar):
            return
        if event is None or event.inaxes is None:
            return
        if event.inaxes is not self.colorbar.ax:
            return

        current_min, current_max = self.sm.get_clim()

        dlg = ColorbarRangeDialog(self, current_min, current_max, self.values_colorbar)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_min, new_max = dlg.get_values()
            if new_min is not None and new_max is not None:
                self.sm.set_clim(vmin=new_min, vmax=new_max)
                self.canvas.draw()

    @Slot(str)
    def on_project_opened(self, project_path: str):
        self.initialize()
        self._load_line_edit_state()
        self.updatePlot()
        self._ensure_line_tab_state_restored()
        self._restore_last_tab()

    @Slot()
    def on_project_reset(self):
        self.delete_all_items()

    def _sync_map_type_selector(self, map_type: str) -> None:
        if not hasattr(self, "mapTypeCombo"):
            return
        index = self.mapTypeCombo.findData(map_type)
        if index == -1:
            return
        if self.mapTypeCombo.currentIndex() == index:
            return
        blocker = QSignalBlocker(self.mapTypeCombo)
        self.mapTypeCombo.setCurrentIndex(index)

    def _set_map_type(
        self, map_type: str, update_plot: bool = True, log_source: str = "selector"
    ) -> None:
        chosen = map_type or "none"
        current = self.map_type or "none"
        if chosen == current:
            return
        self.map_type = chosen
        self._sync_map_type_selector(chosen)
        logger.info(f"Background map type changed to '{chosen}'")
        if update_plot:
            self.updatePlot()

    def _on_map_type_changed(self, index: int) -> None:
        if index < 0:
            return
        chosen = self.mapTypeCombo.itemData(index)
        self._set_map_type(str(chosen), log_source="selector")

    def show_map_context_menu(self):
        menu = QMenu(self)
        actions = {
            "None": "none",
            "roadmap": "roadmap",
            "satellite": "satellite",
            "hybrid": "hybrid",
            "terrain": "terrain",
        }
        current = self.map_type or "none"
        for label, value in actions.items():
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(current == value)
            act.setData(value)

        selected_action = menu.exec(QCursor.pos())
        if not selected_action:
            return

        chosen = selected_action.data()
        self._set_map_type(str(chosen), log_source="context_menu")

    def _get_api_key(self) -> Optional[str]:
        # Prefer environment/user settings; embedded key is a last resort and may be blocked.
        key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if key:
            return key.strip()
        settings = QSettings("Geolux", "KLuxMap")
        stored_key = settings.value("google_maps_api_key", "", type=str)
        if stored_key:
            return stored_key.strip()
        cfg_key = config.get("google_maps_api_key")
        if cfg_key:
            return str(cfg_key).strip()
        if GOOGLE_MAPS_API_KEY_HARDCODED:
            logger.warning(
                "Falling back to embedded Google Maps API key; set GOOGLE_MAPS_API_KEY for reliable access."
            )
            return GOOGLE_MAPS_API_KEY_HARDCODED
        logger.warning("Google Maps API key not configured; skipping background.")
        return None

    def _estimate_zoom(
        self, center_lat: float, lat_span: float, lon_span: float, px_w: int, px_h: int
    ) -> int:
        if px_w <= 0 or px_h <= 0:
            return 15
        meters_lat = max(lat_span, 1e-6) * 111_000
        meters_lon = max(lon_span, 1e-6) * 111_000 * math.cos(
            math.radians(center_lat)
        )
        meters_per_px = max(meters_lat / max(px_h, 1e-6), meters_lon / max(px_w, 1e-6))
        if meters_per_px <= 0:
            return 15
        raw_zoom = math.log2(
            156543.03392 * math.cos(math.radians(center_lat)) / meters_per_px
        )
        return max(0, min(21, int(raw_zoom)))

    def _latlon_bounds(self, latitudes, longitudes):
        if not latitudes or not longitudes:
            return None
        lat_min, lat_max = np.min(latitudes), np.max(latitudes)
        lon_min, lon_max = np.min(longitudes), np.max(longitudes)
        lat_range = lat_max - lat_min
        lon_range = lon_max - lon_min
        min_span = 0.0005
        lat_range = max(lat_range, min_span) * 2
        lon_range = max(lon_range, min_span) * 2
        # Keep a 1:1 ratio for the square image canvas (1280x1280).
        square_span = max(lat_range, lon_range)
        lat_range = square_span
        lon_range = square_span
        center_lat = (lat_max + lat_min) / 2
        center_lon = (lon_max + lon_min) / 2
        return {
            "center": (center_lat, center_lon),
            "lat_span": lat_range,
            "lon_span": lon_range,
            "lat_min": center_lat - lat_range / 2,
            "lat_max": center_lat + lat_range / 2,
            "lon_min": center_lon - lon_range / 2,
            "lon_max": center_lon + lon_range / 2,
        }

    def _qt_image_to_array(self, image: QImage):
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        ptr = image.bits()
        expected_size = image.height() * image.bytesPerLine()
        # PyQt returns a sip.voidptr (needs setsize), PySide6 returns a memoryview (no setsize)
        if hasattr(ptr, "setsize"):
            ptr.setsize(expected_size)
            buffer = ptr
        else:
            buffer = memoryview(ptr)

        arr = np.frombuffer(buffer, np.uint8, count=expected_size).reshape(
            (image.height(), image.bytesPerLine() // 4, 4)
        )
        # Use copy() so the array remains valid after QImage is released.
        return arr.copy()

    def _latlon_to_utm_extent(self, bounds: dict, data_epsg: Optional[int]):
        try:
            epsg = data_epsg
            if not epsg:
                epsg = self.db._latlon_to_utm_epsg(
                    bounds["center"][0], bounds["center"][1]
                )
            transformer = Transformer.from_crs(
                "EPSG:4326", f"EPSG:{int(epsg)}", always_xy=True
            )
            x1, y1 = transformer.transform(bounds["lon_min"], bounds["lat_min"])
            x2, y2 = transformer.transform(bounds["lon_max"], bounds["lat_max"])
            xmin, xmax = sorted([x1, x2])
            ymin, ymax = sorted([y1, y2])
            self._last_epsg = epsg
            return xmin, xmax, ymin, ymax
        except Exception as e:
            logger.error(f"Failed to project bounds to UTM: {e}")
            return None

    def _update_background_map(self, latitudes, longitudes, data_epsg=None):
        try:
            bounds = self._latlon_bounds(latitudes, longitudes)
            if not bounds:
                return False

            api_key = self._get_api_key()
            if not api_key:
                logger.warning("Google Maps API key not configured; skipping background.")
                return False

            w, h = self.canvas.get_width_height()
            size_w = max(256, min(640, int(w)))
            size_h = max(256, min(640, int(h)))
            scale = 2

            zoom = self._estimate_zoom(
                bounds["center"][0],
                bounds["lat_span"],
                bounds["lon_span"],
                size_w * scale,
                size_h * scale,
            )

            # Cache key based on map type, center, span, zoom, and EPSG (excluding size/scale).
            cache_key = (
                self.map_type,
                round(bounds["center"][0], 7),
                round(bounds["center"][1], 7),
                round(bounds["lat_span"], 7),
                round(bounds["lon_span"], 7),
                zoom,
                data_epsg,
            )
            if cache_key in self._map_cache:
                cached_img, cached_extent = self._map_cache[cache_key]
                if cached_img is not None and cached_extent is not None:
                    self._map_image = cached_img
                    self._map_extent = cached_extent
                    return True

            # Cache miss: reset the previous map state.
            self._map_image = None
            self._map_extent = None

            url = (
                "https://maps.googleapis.com/maps/api/staticmap"
                f"?center={bounds['center'][0]},{bounds['center'][1]}"
                f"&zoom={zoom}&size={size_w}x{size_h}&scale={scale}"
                f"&maptype={self.map_type}&key={api_key}"
            )

            resp = None
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
            except requests.HTTPError as e:
                status = getattr(resp, "status_code", None)
                if status == 403:
                    logger.error(
                        "Failed to fetch Static Map (403 Forbidden). "
                        "Verify GOOGLE_MAPS_API_KEY, billing status, and Static Maps API enablement."
                    )
                else:
                    logger.error(
                        f"Failed to fetch Static Map (HTTP {status}, map_type={self.map_type}, zoom={zoom}): {e}"
                    )
                return False
            except Exception as e:
                logger.exception("Failed to fetch Static Map")
                return False

            pix = QPixmap()
            if not pix.loadFromData(resp.content):
                logger.error("Failed to load map image from response content.")
                return False
            self._map_pixmap = pix
            image = pix.toImage()
            self._map_image = self._qt_image_to_array(image)

            extent = self._latlon_to_utm_extent(bounds, data_epsg)
            if not extent:
                logger.error("map fetch: failed to compute UTM extent from bounds")
                return False
            self._map_extent = extent
            self._map_cache[cache_key] = (self._map_image, self._map_extent)
            return True
        except Exception as e:
            logger.exception(f"_update_background_map unexpected failure: {e}")
            return False
