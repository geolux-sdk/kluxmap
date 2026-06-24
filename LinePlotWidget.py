import os
import math
import shutil
from typing import Optional

import numpy as np

import matplotlib.pyplot as plt
import pandas as pd
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import ppigrf

# Widget imports
from PySide6.QtCore import Qt, QSize, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import butter, filtfilt

from DataManager import DataManager, Source
from direction_utils import classify_points

from myResource import resource_path
from mySettings import config
from kriging_dialog import KrigingPlotDialog
from myWidgets import DataFilterDialog

from micro_levelling_medain_filter import run_micro_level

class LinePlotWidget(QWidget):
    def __init__(
        self, db: DataManager, main_window: Optional[QWidget] = None
    ) -> None:
        super().__init__()
       
        self.db: DataManager = db
        self.main_window: Optional[QWidget] = main_window

        self.selected_df = pd.DataFrame()
        self.scanline_df = {}
        self.scanline_filepaths = {}
        self.scatter_colorbar = None
        self.plot_list = []
        self.selected_col_name = "Mag"
        self.calibration_data = {}
        self._active_scanline_name = None
        self._active_timeline_id = None
        self._active_segment_id = None
        self._segment_overlay = None
        self._segment_counter = 0
        self._line_select_start = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        # Page toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(32, 32))

        self.actionDataConfig = QAction(
            QIcon(resource_path("filter.png")), "Filter", self
        )
        self.actionDataConfig.setStatusTip("Data filter settings")
        self.actionDataConfig.triggered.connect(self._open_data_filter_dialog)

        self.actionPlotKriging = QAction(
            QIcon(resource_path("griding.png")), "Gridding", self
        )
        self.actionPlotKriging.triggered.connect(self._open_kriging_dialog)

        # Add the save action to the toolbar.
        self.actionSaveData = QAction(QIcon(resource_path("save.png")), "SAVE", self)
        self.actionSaveData.setStatusTip("Save processed data")
        self.actionSaveData.triggered.connect(self.save_data)

        toolbar.addAction(self.actionDataConfig)
        toolbar.addAction(self.actionPlotKriging)
        toolbar.addAction(self.actionSaveData)

        layout.addWidget(toolbar)

        # Main layout
        vbox_layout = QVBoxLayout()
        vbox_layout.addWidget(
            self._create_file_list(), alignment=Qt.AlignmentFlag.AlignLeft
        )
        ctrl_panel = QFrame()
        ctrl_panel.setLineWidth(3)
        ctrl_panel.setLayout(vbox_layout)

        data_layout = QHBoxLayout()
        table_widget = self._create_table_widget()
        data_layout.addWidget(table_widget, 1)

        # Container for the scatter plot and its controls
        scatter_container = QWidget()
        scatter_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        scatter_vbox = QVBoxLayout(scatter_container)
        scatter_vbox.setContentsMargins(0, 0, 0, 0)

        # Add the colorbar toggle above the scatter plot
        self.scatter_colorbar_cb = QCheckBox("COLOR BAR")
        self.scatter_colorbar_cb.stateChanged.connect(self.update_scatterplot)
        scatter_vbox.addWidget(
            self.scatter_colorbar_cb, alignment=Qt.AlignmentFlag.AlignRight
        )
        scatter_vbox.addWidget(
            self._create_scatter_plot()
        )  # Place the scatter plot below the checkbox

        data_layout.addWidget(scatter_container, 12)
        # Make the scatter panel slightly wider than the table
        data_layout.setStretch(0, 10)
        data_layout.setStretch(1, 12)

        dataV_layout = QVBoxLayout()
        # Keep the lower plot shorter than the upper data area
        dataV_layout.addLayout(data_layout, 2)
        dataV_layout.addWidget(self._create_canvas_plot(), 1)

        data_panel = QFrame()
        data_panel.setLayout(dataV_layout)
        data_panel.setLineWidth(3)
        data_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.addWidget(ctrl_panel)
        main_layout.addWidget(data_panel)
        main_layout.setStretch(0, 0)
        main_layout.setStretch(1, 1)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        self.actionDataConfig.setEnabled(False)
        self.actionPlotKriging.setEnabled(False)
        self.actionSaveData.setEnabled(False)

    def set_actions_enabled(self, action=True):
        self.actionDataConfig.setEnabled(action)
        self.actionPlotKriging.setEnabled(action)
        self.actionSaveData.setEnabled(action)

    def _open_data_filter_dialog(self):
        DataFilterDialog(self).exec()

    def _create_scatter_plot(self):
        # Increase the default scatter plot size for dense scanline data
        self.scatter_fig = Figure(figsize=(8, 4), dpi=100)
        self.scatter_ax = self.scatter_fig.add_subplot(111)
        self.scatter_ax.set_title("Mag Value (Sensor_Total)")
        self.scatter_ax.set_xlabel("Index")
        self.scatter_ax.set_ylabel("Sensor_Total")
        self.scatter_ax.grid(True)
        self.scatter_canvas = FigureCanvas(self.scatter_fig)
        self.scatter_canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.scatter_canvas.setMinimumHeight(300)
        return self.scatter_canvas

    def _create_canvas_plot(self):
        self.fig = Figure(figsize=(12, 2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.canvas.mpl_connect("button_press_event", self._on_lineplot_press)
        self.canvas.mpl_connect("button_release_event", self._on_lineplot_release)
        return self.canvas

    def _create_file_list(self):
        """Create the list widget that shows scanline files."""
        self.fileListWidget = QListWidget()
        self.fileListWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.fileListWidget.setFixedWidth(100)
        self.fileListWidget.itemClicked.connect(self.on_item_clicked)
        self.fileListWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fileListWidget.customContextMenuRequested.connect(
            self.show_file_list_context_menu
        )
        return self.fileListWidget

    def _create_table_widget(self):
        self.tableWidget = QTableWidget()
        self.tableWidget.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectColumns  # Select whole columns
        )
        self.tableWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tableWidget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.tableWidget.cellClicked.connect(self.on_table_cell_clicked)

        self.tableWidget.horizontalHeader().sectionClicked.connect(
            self.on_header_clicked
        )

        header = self.tableWidget.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.on_header_right_click)

        return self.tableWidget

    def on_header_right_click(self, pos):  # pos: QPoint in header coordinates
        header = self.tableWidget.horizontalHeader()
        logical_index = header.logicalIndexAt(pos)
        if logical_index < 0:
            return

        if logical_index not in self.plot_list:
            self.plot_list.append(logical_index)
        else:
            if len(self.plot_list) > 1:
                self.plot_list.remove(logical_index)
        self.plot_column_by_index(self.plot_list)

    def calculate_directional_avg_from_df(self):
        """
        Calculate average magnetic offsets by scanline direction.

        Parameters:
            scanline_df (dict[str, pd.DataFrame]): key=name, value=DataFrame

        Returns:
            dict: directional offsets for TD/BU/LR/RL
        """

        cali = config.get(
            "cali_filter",
            {
                "enabled": False,
                "offset_RL": 0.0,
                "offset_LR": 0.0,
                "offset_TD": 0.0,
                "offset_BU": 0.0,
            },
        )

        if not self.scanline_df:
            logger.warning("No scanline data to calculate calibration.")
            # Save the default configuration and exit safely.
            config.set_subvalue("filters_line", "cali_filter", cali)
            return None, None, None

        # Average Mag values by direction (TD/BU/LR/RL).
        sums = {"TD": 0.0, "BU": 0.0, "LR": 0.0, "RL": 0.0}
        counts = {"TD": 0, "BU": 0, "LR": 0, "RL": 0}
        main_direction_degree = config.get("direction", 0)

        for name, df in self.scanline_df.items():
            if df.empty or not {"Mag", "X", "Y"}.issubset(df.columns):
                continue

            mag_avg = float(df["Mag"].mean())
            direction = classify_points(
                float(df["X"].iloc[0]),
                float(df["Y"].iloc[0]),
                float(df["X"].iloc[-1]),
                float(df["Y"].iloc[-1]),
                main_direction_degree,
            )
            if direction is None:
                continue

            sums[direction] += mag_avg
            counts[direction] += 1

        offsets = {"offset_TD": 0.0, "offset_BU": 0.0, "offset_LR": 0.0, "offset_RL": 0.0}

        if counts["TD"] > 0 and counts["BU"] > 0:
            td_avg = sums["TD"] / counts["TD"]
            bu_avg = sums["BU"] / counts["BU"]
            diff_v = td_avg - bu_avg
            offsets["offset_TD"] = -diff_v / 2.0
            offsets["offset_BU"] = diff_v / 2.0

        if counts["LR"] > 0 and counts["RL"] > 0:
            lr_avg = sums["LR"] / counts["LR"]
            rl_avg = sums["RL"] / counts["RL"]
            diff_h = lr_avg - rl_avg
            offsets["offset_LR"] = -diff_h / 2.0
            offsets["offset_RL"] = diff_h / 2.0

        cali.update(offsets)
        config.set_subvalue("filters_line", "cali_filter", cali)
        logger.info(
            "Calculated scanline calibration offsets: "
            f"TD={offsets['offset_TD']:.3f}, "
            f"BU={offsets['offset_BU']:.3f}, "
            f"LR={offsets['offset_LR']:.3f}, "
            f"RL={offsets['offset_RL']:.3f}"
        )
        return offsets

    def update_file_list(self, file_paths):
        """Refresh the list widget with selected scanline files."""
        self.fileListWidget.clear()
        self.scanline_df.clear()
        self.scanline_filepaths.clear()

        if file_paths:
            filtered_paths = [
                fp for fp in file_paths if os.path.basename(fp).lower().startswith("line")
            ]

            for file_path in sorted(filtered_paths):
                base = os.path.basename(file_path)  # Extract the filename only.
                name_wo_ext = os.path.splitext(base)[0]  # Remove the extension.
                item = QListWidgetItem(name_wo_ext)
                self.fileListWidget.addItem(item)
                df = pd.read_csv(file_path)
                self.scanline_df[name_wo_ext] = df
                self.scanline_filepaths[name_wo_ext] = file_path

        if self.scanline_df:
            logger.info(
                f"Loaded {len(self.scanline_df)} scanline file(s) into the line plot"
            )

        # Automatically select and load the first item.
        if self.fileListWidget.count() > 0:
            first_item = self.fileListWidget.item(0)
            first_item.setSelected(True)
            self.fileListWidget.setFocus()
            self.selected_col_name = "Mag"
            self.on_item_clicked(first_item)
            self.first_item = first_item

    def update_scatterplot(self):
        self._reset_scatter_axes()

        if not self.scanline_df:
            self.scatter_ax.set_title("No Scanline Data")
            self.scatter_canvas.draw()
            return

        val_col = self.selected_col_name
        colorbar_mode = self.scatter_colorbar_cb.isChecked()

        if colorbar_mode:
            val_col = self._draw_colorbar_mode(val_col)
        else:
            self._draw_polyline_mode()

        self._draw_selected_scanline()
        self._apply_segment_overlay()

        self._format_scatter_axes(val_col)
        self.scatter_canvas.draw()

    # --- Scatter plot helpers ---------------------------------------------
    def _reset_scatter_axes(self):
        self.scatter_fig.clear()
        self.scatter_ax = self.scatter_fig.add_subplot(111)

    def _draw_colorbar_mode(self, val_col):
        allowed_cols = [
            "Mag",
            "Mag_diurnal",
            "Mag_median",
            "Mag_lowpass",
            "Mag_calibrated",
            "Mag_igrf",
            "IGRF",
            "Mag_Level",
        ]

        # Fall back to "Mag" if the last dataframe column is not in the allowed list.
        if not self.selected_df.empty:
            last_col = self.selected_df.columns[-1]
            val_col = last_col if last_col in allowed_cols else "Mag"

        if val_col not in allowed_cols:
            val_col = "Mag"

        cmap = plt.get_cmap("jet")
        all_x, all_y, all_vals = [], [], []
        for df in self.scanline_df.values():
            if {"X", "Y", val_col}.issubset(df.columns):
                all_x.extend(df["X"])
                all_y.extend(df["Y"])
                all_vals.extend(df[val_col])

        if all_x:
            sc = self.scatter_ax.scatter(all_x, all_y, c=all_vals, cmap=cmap, s=10)
            self.scatter_colorbar = self.scatter_fig.colorbar(
                sc, ax=self.scatter_ax, label="Value"
            )
            self.scatter_colorbar.ax.ticklabel_format(useOffset=False, style="plain")
        return val_col

    def _draw_polyline_mode(self):
        for key, df in self.scanline_df.items():
            if "X" in df.columns and "Y" in df.columns:
                self.scatter_ax.plot(df["X"], df["Y"], color="blue", linewidth=1)
                start_x, start_y = df["X"].iloc[0], df["Y"].iloc[0]
                self.scatter_ax.annotate(
                    str(key),
                    (start_x, start_y),
                    textcoords="offset points",
                    xytext=(1, 1),
                    fontsize=7,
                    color="black",
                )

    def _draw_selected_scanline(self):
        if self.selected_df.empty or "X" not in self.selected_df.columns:
            return
        x, y = self.selected_df["X"], self.selected_df["Y"]
        self.scatter_ax.scatter(x, y, color="black", s=3)

        # Draw direction arrow using the local direction around the midpoint
        if len(self.selected_df) >= 2:
            mid_idx = len(self.selected_df) // 2
            prev_idx = max(mid_idx - 1, 0)
            next_idx = min(mid_idx + 1, len(self.selected_df) - 1)

            x0 = float(self.selected_df["X"].iloc[prev_idx])
            y0 = float(self.selected_df["Y"].iloc[prev_idx])
            x1 = float(self.selected_df["X"].iloc[next_idx])
            y1 = float(self.selected_df["Y"].iloc[next_idx])

            dx = x1 - x0
            dy = y1 - y0
            seg_len = math.hypot(dx, dy)

            if seg_len > 0:
                mid_x = (x0 + x1) / 2.0
                mid_y = (y0 + y1) / 2.0

                arrow_len = max(np.ptp(x.to_numpy()), np.ptp(y.to_numpy())) * 0.05
                if arrow_len == 0:
                    arrow_len = 1.0

                ux = dx / seg_len
                uy = dy / seg_len

                self.scatter_ax.annotate(
                    "",
                    xy=(mid_x + ux * arrow_len, mid_y + uy * arrow_len),
                    xytext=(mid_x, mid_y),
                    arrowprops=dict(arrowstyle="-|>", color="red", lw=5,mutation_scale=20,),
                    zorder=6,
                )

    def _format_scatter_axes(self, val_col: str):
        """Apply common scatter-axis formatting."""
        self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="x")
        self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="y")
        self.scatter_ax.set_title(f"{val_col}")
        self.scatter_ax.set_xlabel("X (Easting)")
        self.scatter_ax.set_ylabel("Y (Northing)")
        self.scatter_ax.set_aspect("equal", "box")
        self.scatter_ax.grid(True)
        self.scatter_fig.tight_layout()

    def on_item_clicked(self, item):
        name = item.text()
        df = self.scanline_df.get(name, pd.DataFrame())
        self.selected_df = df
        self._active_scanline_name = name
        self._active_timeline_id = None
        self._active_segment_id = None
        self._segment_overlay = None
        self._line_select_start = None
        self.populate_table(df)

        if df.empty or self.selected_col_name not in df.columns:
            return

        col_index = df.columns.get_loc(self.selected_col_name)
        self.tableWidget.setCurrentCell(0, col_index)
        self.plot_list = [col_index]
        self.plot_column_by_index(self.plot_list)

        self.update_scatterplot()

    def populate_table(self, df):
        self.tableWidget.clear()
        self.tableWidget.setRowCount(len(df))
        self.tableWidget.setColumnCount(len(df.columns))
        self.tableWidget.setHorizontalHeaderLabels(df.columns.tolist())

        for i, row in df.iterrows():
            for j, value in enumerate(row):
                if isinstance(value, (float, np.floating)):
                    # Show floats in fixed-point (no scientific notation)
                    val_str = f"{value:.6f}"
                else:
                    val_str = str(value)
                item = QTableWidgetItem(val_str)
                self.tableWidget.setItem(i, j, item)

    def on_table_cell_clicked(self, row, column_index):
        self.on_header_clicked(column_index)

    def on_header_clicked(self, column_index):
        self.plot_list = [column_index]
        self.plot_column_by_index(self.plot_list)
        self.selected_col_name = self.tableWidget.horizontalHeaderItem(
            column_index
        ).text()
        self.update_scatterplot()

    def plot_column_by_index(self, column_list):
        if self.selected_df.empty:
            return

        x_values = self.selected_df.index.values

        self.ax.clear()
        for column in column_list:
            col_name = self.selected_df.columns[column]
            y_values = self.selected_df[col_name].values

            self.ax.plot(
                x_values,
                y_values,
                marker="o",
                linewidth=0.8,
                markersize=1,
                label=str(col_name),
            )
        self.ax.legend(loc="best", fontsize=8, frameon=True)
        self.ax.set_xlabel("Index")
        self.ax.set_ylabel(col_name)
        self.ax.grid(True)
        self.fig.tight_layout()
        self.canvas.draw()

    def _on_lineplot_press(self, event):
        if event.button != 1:
            return
        if event.inaxes != self.ax:
            return
        if self.selected_df.empty:
            return
        if event.xdata is None:
            return
        self._line_select_start = float(event.xdata)

    def _on_lineplot_release(self, event):
        if event.button != 1:
            return
        if self._line_select_start is None:
            return
        if event.inaxes != self.ax:
            self._line_select_start = None
            return
        if event.xdata is None:
            self._line_select_start = None
            return
        x0 = self._line_select_start
        x1 = float(event.xdata)
        self._line_select_start = None
        g0, g1 = self._xrange_to_global_indices(x0, x1, len(self.selected_df))
        if g0 is None:
            return
        try:
            timeline_id = self._ensure_segment_timeline()
            segment_id = f"{timeline_id}:seg{self._segment_counter}"
            self._segment_counter += 1
            self.db.create_segment_from_range(
                segment_id,
                timeline_id,
                g0,
                g1,
                meta={"source": self._active_scanline_name},
            )
        except Exception as e:
            logger.exception("Failed to create line plot segment")
            return
        self.set_segment(segment_id)

    def _xrange_to_global_indices(self, x0: float, x1: float, length: int):
        if length <= 0:
            return None, None
        start = min(x0, x1)
        end = max(x0, x1)
        g0 = int(math.floor(start))
        g1 = int(math.floor(end)) + 1
        if g0 < 0:
            g0 = 0
        if g1 > length:
            g1 = length
        if g0 >= g1:
            return None, None
        return g0, g1

    def _ensure_segment_timeline(self) -> str:
        if not self._active_scanline_name:
            raise ValueError("No scanline selected.")
        source_id = f"scanline:{self._active_scanline_name}"
        timeline_id = f"scanline:{self._active_scanline_name}"
        src_path = self.scanline_filepaths.get(self._active_scanline_name, "")
        if self.selected_df.empty:
            raise ValueError("Selected DataFrame is empty.")
        # Store a snapshot to avoid in-place mutation.
        self.db.sources[source_id] = Source(
            source_id=source_id,
            path=str(src_path),
            df=self.selected_df.copy(),
        )
        self.db.create_timeline(timeline_id, [source_id])
        self._active_timeline_id = timeline_id
        return timeline_id

    def set_segment(self, segment_id: str) -> None:
        self._active_segment_id = segment_id
        self._draw_segment_overlay(segment_id, draw=True)

    def _draw_segment_overlay(self, segment_id: str, draw: bool) -> None:
        if not hasattr(self, "scatter_ax") or self.scatter_ax is None:
            return
        if self._segment_overlay is not None:
            try:
                self._segment_overlay.remove()
            except Exception:
                pass
            self._segment_overlay = None
        if self.selected_df.empty:
            return
        if not {"X", "Y"}.issubset(self.selected_df.columns):
            logger.warning("Segment overlay skipped: missing X/Y.")
            return
        c_col = None
        if self.selected_col_name in self.selected_df.columns:
            c_col = self.selected_col_name
        elif "Mag" in self.selected_df.columns:
            c_col = "Mag"

        try:
            if c_col is None:
                x_arr, y_arr = self.db.get_scatter_arrays(
                    segment_id, "X", "Y", None, stride=1
                )
            else:
                x_arr, y_arr, _ = self.db.get_scatter_arrays(
                    segment_id, "X", "Y", c_col, stride=1
                )
        except Exception as e:
            logger.error(f"Segment overlay failed: {e}")
            return

        if len(x_arr) == 0:
            return
        self._segment_overlay = self.scatter_ax.scatter(
            x_arr,
            y_arr,
            s=12,
            color="orange",
            alpha=0.9,
            zorder=7,
        )
        if draw:
            self.scatter_canvas.draw_idle()

    def _apply_segment_overlay(self) -> None:
        if self._active_segment_id:
            self._draw_segment_overlay(self._active_segment_id, draw=False)

    def show_file_list_context_menu(self, position):
        item = self.fileListWidget.itemAt(position)
        if item is None:
            return

        menu = QMenu(self)
        delete_action = menu.addAction("Delete")
        selected_action = menu.exec(self.fileListWidget.mapToGlobal(position))
        if selected_action == delete_action:
            self.delete_scanline_item(item)

    def delete_scanline_item(self, item_to_delete):
        name = item_to_delete.text()

        reply = QMessageBox.question(
            self,
            "Delete Item",
            f"Are you sure you want to delete '{name}' and its associated file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            is_current = self.fileListWidget.currentItem() == item_to_delete

            if name in self.scanline_df:
                del self.scanline_df[name]
                logger.info(f"Deleted scanline data for '{name}'")

            file_to_delete = self.scanline_filepaths.pop(name, None)
            if file_to_delete and os.path.exists(file_to_delete):
                try:
                    os.remove(file_to_delete)
                    logger.info(f"Deleted file: {file_to_delete}")
                except OSError as e:
                    logger.error(f"Error deleting file {file_to_delete}: {e}")
                    QMessageBox.critical(
                        self, "File Deletion Error", f"Could not delete file:\n{e}"
                    )
            elif file_to_delete:
                logger.warning(f"File to delete not found on disk: {file_to_delete}")

            self.fileListWidget.takeItem(self.fileListWidget.row(item_to_delete))

            if is_current:
                if self.fileListWidget.count() > 0:
                    new_item = self.fileListWidget.item(0)
                    self.fileListWidget.setCurrentItem(new_item)
                    self.on_item_clicked(new_item)
                else:
                    self.selected_df = pd.DataFrame()
                    self.populate_table(self.selected_df)
                    self.ax.clear()
                    self.canvas.draw()
                    self.update_scatterplot()
            else:
                self.update_scatterplot()

    def _butter_coeffs(self, cutoff, fs, order=4, btype="low"):
        """
        Helper to compute Butterworth filter coefficients.
        """
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = butter(order, normal_cutoff, btype=btype, analog=False)
        return b, a

    def filtering(self, settings):
        """
        For each scanline DataFrame in self.scanline_df, apply enabled filters and
        write outputs to new columns (diurnal, median, lowpass, calibrated).
        """
        current_item = self.fileListWidget.currentItem()
        if not current_item and self.fileListWidget.count() > 0:
            current_item = self.fileListWidget.item(0)
        if not current_item:
            logger.info("Line filtering skipped because no scanline data is loaded.")
            return

        enabled_filters = []
        if settings.get("Diurnal_Correction", {}).get("enabled", False):
            enabled_filters.append("diurnal")
        if settings.get("igrf_correction", {}).get("enabled", False):
            enabled_filters.append("igrf")
        if settings.get("median_filter", {}).get("enabled", False):
            enabled_filters.append("median")
        if settings.get("lowpass_filter", {}).get("enabled", False):
            enabled_filters.append("lowpass")
        if settings.get("cali_filter", {}).get("enabled", False):
            enabled_filters.append("calibration")
        if settings.get("micro_levelling", {}).get("enabled", False):
            enabled_filters.append("micro")
        logger.info(
            f"Applying line filters to {len(self.scanline_df)} scanline(s): "
            f"{', '.join(enabled_filters) if enabled_filters else 'none'}"
        )
        diurnal_df = self._load_diurnal_df(settings)

        if not self.scanline_df:
            logger.info("Line filtering skipped because no scanline data is loaded.")
            return

        for key, df in self.scanline_df.items():
            self._reset_filter_columns(df)
            filtered_mag = df["Mag"].astype(float)

            filtered_mag = self._apply_diurnal(df, filtered_mag, settings, diurnal_df, key)
            filtered_mag = self._apply_igrf(df, filtered_mag, settings, key)
            filtered_mag = self._apply_median(df, filtered_mag, settings, key)
            filtered_mag = self._apply_lowpass(df, filtered_mag, settings, key)
            filtered_mag = self._apply_calibration(df, filtered_mag, settings, key)

        # 적용 순서상 마지막으로 실제 생성된 필터 컬럼을 결정적으로 선택
        filter_to_col = {
            "diurnal": "Mag_diurnal",
            "igrf": "Mag_igrf",
            "median": "Mag_median",
            "lowpass": "Mag_lowpass",
            "calibration": "Mag_calibrated",
        }
        col_name = "Mag"
        for f in ["diurnal", "igrf", "median", "lowpass", "calibration"]:
            col = filter_to_col[f]
            if f in enabled_filters and any(
                col in d.columns for d in self.scanline_df.values()
            ):
                col_name = col
        filtered_mag = self._apply_micro_levelling(self.scanline_df, settings, col_name)

        logger.info(
            f"Line filtering complete for {len(self.scanline_df)} scanline(s); "
            f"active plot column={col_name}"
        )
        self.on_item_clicked(current_item)
        return

    # --- Filtering helpers -------------------------------------------------
    def _load_diurnal_df(self, settings):
        diurnal_cfg = settings.get("Diurnal_Correction", {})
        if not diurnal_cfg.get("enabled", False):
            return pd.DataFrame()

        csv_files = diurnal_cfg.get("files", [])
        if not csv_files:
            logger.warning("Diurnal correction is enabled but no diurnal files are selected.")
            return pd.DataFrame()
        df_list = []
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file)
                df_list.append(df)
            except Exception as e:
                logger.error(f"Failed to load diurnal file '{csv_file}': {e}")
        if not df_list:
            logger.warning("No valid diurnal files could be loaded.")
            QMessageBox.warning(
                self,
                "Diurnal Data Error",
                "No valid diurnal files could be loaded.\n\n"
                "Diurnal correction was skipped.",
            )
            return pd.DataFrame()

        diurnal_df = pd.concat(df_list, ignore_index=True)
        try:
            diurnal_df["Mag"] = pd.to_numeric(diurnal_df["Mag"], errors="coerce")
            # Drop sentinel values (e.g., missing data coded as 99999.00)
            drop_mask = diurnal_df["Mag"] == 99999.0
            if drop_mask.any():
                removed = int(drop_mask.sum())
                diurnal_df = diurnal_df.loc[~drop_mask].copy()
                logger.warning(f"Removed {removed} diurnal rows with Mag=99999.00")
            if diurnal_df.empty:
                logger.warning("All diurnal rows were filtered out; diurnal correction was skipped.")
                QMessageBox.warning(
                    self,
                    "Diurnal Data Error",
                    "All diurnal rows were filtered out.\n\n"
                    "Diurnal correction was skipped.",
                )
                return pd.DataFrame()

            mag_mean = diurnal_df["Mag"].mean()
            diurnal_df["Mag"] = diurnal_df["Mag"] - mag_mean
            logger.info(
                f"Loaded diurnal reference data: files={len(df_list)}, rows={len(diurnal_df)}, "
                f"mean_offset={mag_mean:.3f}"
            )

            # Check overlapping timestamps across merged files (Date + Time)
            if {"Date", "Time"}.issubset(diurnal_df.columns):
                dt_series = pd.to_datetime(
                    diurnal_df["Date"].astype(str) + " " + diurnal_df["Time"].astype(str),
                    errors="coerce",
                )
                dup_mask = dt_series.duplicated(keep=False)
                dup_count = int(dup_mask.sum())
                if dup_count:
                    logger.warning(
                        f"Diurnal data contains {dup_count} overlapping timestamps"
                    )
        except Exception as e:
            logger.exception("Failed to prepare diurnal reference data")
            # If any error occurs, zero out Mag values to allow downstream processing.
            QMessageBox.warning(
                self,
                "Diurnal Data Error",
                f"An error occurred while processing diurnal data:\n{e}\n\n"
                "Mag values were zeroed so filtering can continue.",
            )
            return pd.DataFrame()
        return diurnal_df

    def _reset_filter_columns(self, df: pd.DataFrame):
        cols_to_drop = [
            "Mag_diurnal",
            "Mag_median",
            "Mag_level",
            "Mag_lowpass",
            "Mag_calibrated",
            "IGRF",
            "Mag_igrf",
        ]
        df.drop(columns=cols_to_drop, inplace=True, errors="ignore")

    def _apply_diurnal(self, df, filtered_mag, settings, diurnal_df, key):
        diurnal_cfg = settings.get("Diurnal_Correction", {})
        # diurnal_df can be 0 if _load_diurnal_df failed
        if not diurnal_cfg.get("enabled", False) or not isinstance(diurnal_df, pd.DataFrame) or diurnal_df.empty:
            return filtered_mag
        try:
            merged = pd.merge(
                df,
                diurnal_df[["Date", "Time", "Mag"]],
                on=["Date", "Time"],
                how="left",
                suffixes=("", "_diurnal"),
            )
            merged["Mag_corrected"] = (
                merged["Mag"].astype(float)
                - merged["Mag_diurnal"].astype(float)
                # + reference_value
            )
            df["Diurnal"] = merged["Mag_diurnal"]
            df["Mag_diurnal"] = merged["Mag_corrected"]
            return df["Mag_diurnal"]
        except Exception as err:
            logger.exception(f"Diurnal correction failed for scanline '{key}'")
            QMessageBox.warning(
                self,
                "Filter Error",
                f"Diurnal correction failed for scanline '{key}':\n{err}",
            )
            return filtered_mag

    def _apply_igrf(self, df, filtered_mag, settings, key):
        """
        Apply IGRF correction using the available coordinates and timestamps.
        - df["IGRF"] stores the modeled total field in nT.
        - df["Mag_igrf"] stores filtered_mag - IGRF.
        """
        igrf_cfg = settings.get("igrf_correction", {})
        if not igrf_cfg.get("enabled", False):
            return filtered_mag

        required_cols = {"Latitude", "Longitude"}
        if not required_cols.issubset(df.columns):
            logger.warning(f"{key}: IGRF skipped (Latitude/Longitude missing)")
            return filtered_mag

        try:
            lats = pd.to_numeric(df["Latitude"], errors="coerce").to_numpy()
            lons = pd.to_numeric(df["Longitude"], errors="coerce").to_numpy()
            flight_altitude_m = float(igrf_cfg.get("flight_altitude", 0) or 0)

            if flight_altitude_m != 0:
                # Use a constant user-specified altitude for all samples.
                alt_km = np.full(len(lats), flight_altitude_m / 1000.0, dtype=float)
            elif "Altitude" in df.columns:
                alt_km = (
                    pd.to_numeric(df["Altitude"], errors="coerce").to_numpy() / 1000.0
                )
            else:
                alt_km = np.zeros_like(lats, dtype=float)
            alt_km = np.nan_to_num(alt_km, nan=0.0)

            coord_valid = (~np.isnan(lats)) & (~np.isnan(lons))
            if not coord_valid.any():
                logger.warning(f"{key}: IGRF skipped (no valid lat/lon)")
                return filtered_mag

            # Use Date+Time when available; otherwise fall back to Date or the current UTC time.
            if {"Date", "Time"}.issubset(df.columns):
                timestamps = pd.to_datetime(
                    df["Date"].astype(str) + " " + df["Time"].astype(str),
                    errors="coerce",
                )
            elif "Date" in df.columns:
                timestamps = pd.to_datetime(df["Date"].astype(str), errors="coerce")
            else:
                timestamps = pd.Series(
                    [pd.Timestamp.now(tz="UTC").tz_localize(None)] * len(df)
                )

            igrf_vals = np.full(len(df), np.nan, dtype=float)

            # Compute IGRF values in one batch and keep the diagonal entries
            # so each row uses its own timestamp.
            valid_idx = ~timestamps.isna()
            if not valid_idx.any():
                logger.warning(f"{key}: IGRF skipped (no valid timestamps)")
                return filtered_mag

            mask = valid_idx & coord_valid
            valid_lons = lons[mask]
            valid_lats = lats[mask]
            valid_alt_km = alt_km[mask]
            valid_datetimes = np.array(
                [ts.to_pydatetime() for ts in timestamps[mask]],
                dtype=object,
            )

            Be, Bn, Bu = ppigrf.igrf(
                valid_lons,
                valid_lats,
                valid_alt_km,
                valid_datetimes,
            )
            igrf_vals[mask] = np.linalg.norm(
                np.column_stack(
                    [
                        np.diagonal(Be),
                        np.diagonal(Bn),
                        np.diagonal(Bu),
                    ]
                ),
                axis=1,
            )

            df["IGRF"] = igrf_vals
            df["Mag_igrf"] = filtered_mag.values - df["IGRF"].values
            return df["Mag_igrf"]
        except Exception as err:
            logger.exception(f"IGRF correction failed for scanline '{key}'")
            QMessageBox.warning(
                self,
                "Filter Error",
                f"IGRF correction failed for scanline '{key}':\n{err}",
            )
            return filtered_mag

    def _apply_median(self, df, filtered_mag, settings, key):
        med_cfg = settings.get("median_filter", {})
        if not med_cfg.get("enabled", False):
            return filtered_mag
        try:
            ksize = med_cfg.get("kernel_size", 3)
            df["Mag_median"] = filtered_mag.rolling(
                window=ksize, center=True, min_periods=1
            ).median()
            return df["Mag_median"]
        except Exception as err:
            logger.exception(f"Median filter failed for scanline '{key}'")
            QMessageBox.warning(
                self,
                "Filter Error",
                f"Median filter failed for scanline '{key}':\n{err}",
            )
            return filtered_mag

    def _apply_micro_levelling(self, scanline_df, settings, col_name):
        """
        Placeholder for the micro-levelling pipeline.

        Expected to:
        - use short/long filters (or window lengths) from config
        - optionally apply 2D median smoothing with search radius / neighbor count
        - write output to df['Mag_micro'] and return that series

        Currently this keeps the existing dataframe order and updates matching keys.
        """
        micro_cfg = settings.get("micro_levelling", {})
        if not micro_cfg.get("enabled", False):
            return
        try:
            short_len = micro_cfg.get("short_filter_size", micro_cfg.get("window_size", 5))
            long_len = micro_cfg.get("long_filter_size", micro_cfg.get("poly_order", 2))
            search_radius = micro_cfg.get("search_radius", 5.0)
            min_neighbors = micro_cfg.get("min_neighbor_count", 5)

            filtered = run_micro_level(
                scanline_df,
                short_len,
                long_len,
                search_radius,
                min_neighbors,
                col_name,
            )
            # Preserve the current order and append only new keys at the end.
            for k, v in filtered.items():
                if k in self.scanline_df:
                    self.scanline_df[k] = v  # Keep the current position and update values only.
                else:
                    self.scanline_df[k] = v  # Append new items to the end.
            return

        except Exception as err:
            logger.exception("Micro levelling failed")
            QMessageBox.warning(
                self,
                "Filter Error",
                f"Micro levelling failed for scanline \n{err}",
            )
        return

    def _apply_lowpass(self, df, filtered_mag, settings, key):
        low_cfg = settings.get("lowpass_filter", {})
        if not low_cfg.get("enabled", False):
            return filtered_mag
        try:
            cutoff = low_cfg.get("cutoff_freq", 0.1)
            b, a = self._butter_coeffs(cutoff, 1, order=4, btype="low")
            df["Mag_lowpass"] = filtfilt(b, a, filtered_mag.values)
            return df["Mag_lowpass"]
        except Exception as err:
            logger.exception(f"Low-pass filter failed for scanline '{key}'")
            QMessageBox.warning(
                self,
                "Filter Error",
                f"Low-pass filter failed for scanline '{key}':\n{err}",
            )
            return filtered_mag

    def _apply_calibration(self, df, filtered_mag, settings, key):
        cal_cfg = settings.get("cali_filter", {})
        if not cal_cfg.get("enabled", False):
            return filtered_mag
        if not {"X", "Y"}.issubset(df.columns):
            logger.warning(f"{key}: Calibration skipped (missing X/Y columns)")
            return filtered_mag

        start_x, end_x = df["X"].iloc[0], df["X"].iloc[-1]
        start_y, end_y = df["Y"].iloc[0], df["Y"].iloc[-1]
        main_direction_degree = config.get("direction", 0)
        direction = classify_points(
            float(start_x),
            float(start_y),
            float(end_x),
            float(end_y),
            main_direction_degree,
        )
        if direction is None:
            logger.warning(f"{key}: Calibration skipped (zero-length direction vector)")
            return filtered_mag

        offset_key = f"offset_{direction}"
        offset = cal_cfg.get(offset_key, 0.0)

        df["Mag_calibrated"] = filtered_mag + offset
        return df["Mag_calibrated"]

    # --- Minimal self-test helpers (manual) -------------------------------
    def _selftest_filters(self):
        """
        간단한 샘플 데이터로 필터 헬퍼를 검증할 때 수동 호출.
        실행하지 않고 참조용으로만 둠.
        """
        import numpy as np

        df = pd.DataFrame(
            {
                "Date": ["2025-01-01"] * 5,
                "Time": ["00:00:0" + str(i) for i in range(5)],
                "Mag": [10, 12, 11, 13, 12],
                "X": np.arange(5),
                "Y": np.arange(5),
            }
        )
        settings = {
            "Diurnal_Correction": {"enabled": False, "files": []},
            "median_filter": {"enabled": True, "kernel_size": 3},
            "lowpass_filter": {"enabled": False},
            "cali_filter": {"enabled": True, "offset_LR": 1, "offset_RL": -1, "offset_TD": 0, "offset_BU": 0},
        }
        self._reset_filter_columns(df)
        mag = df["Mag"].astype(float)
        mag = self._apply_median(df, mag, settings, "selftest")
        self._apply_calibration(df, mag, settings, "selftest")
        return df

    def _open_kriging_dialog(self):
        if self.selected_df.empty or self.tableWidget.columnCount() == 0:
            QMessageBox.warning(
                self,
                "Gridding",
                "No scanline data is available for gridding.",
            )
            return

        column_index = self.tableWidget.currentColumn()
        if column_index < 0:
            QMessageBox.warning(
                self,
                "Gridding",
                "Please select a data column before running gridding.",
            )
            return

        col_name = self.selected_df.columns[column_index]
        parent_window = self.main_window or self.window()
        dlg = KrigingPlotDialog(
            parent_window,
            self.scanline_df,
            col_name,
        )
        dlg.setParent(parent_window)
        dlg.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        self._open_kriging_dialogs = getattr(self, "_open_kriging_dialogs", [])
        self._open_kriging_dialogs.append(dlg)

    def save_data(self):
        """
        Save the processed scanline data.
        1. Save each scanline back to its original CSV file.
        2. Save one merged CSV file that combines all scanlines.
        """
        if not self.scanline_df:
            QMessageBox.warning(self, "No Data", "There is no data to save.")
            return

        # 1. Save each scanline to its original file.
        for key, df in self.scanline_df.items():
            try:
                df.to_csv(self.scanline_filepaths[key], index=False)
            except Exception as e:
                logger.exception(
                    f"Failed to save individual scanline file: {self.scanline_filepaths[key]}"
                )
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Could not save file for scanline '{key}':\n{e}",
                )
                return  # Stop if saving an individual file fails.

        # 2. Merge all scanlines and save the combined file.
        try:
            # Merge every dataframe in the current scanline set.
            all_dfs = list(self.scanline_df.values())
            # keep column order aligned with the first dataframe
            combined_df = pd.concat(all_dfs, ignore_index=True, sort=False)
            combined_df = combined_df.reindex(columns=all_dfs[0].columns)

            # Determine the output path.
            if not self.scanline_filepaths:
                logger.error(
                    "Cannot determine save path as scanline_filepaths is empty."
                )
                QMessageBox.critical(
                    self,
                    "Save Error",
                    "Could not determine the directory to save the combined file.",
                )
                return

            first_path = next(iter(self.scanline_filepaths.values()))
            results_dir = os.path.dirname(first_path)

            # Save the merged file in the same results folder.
            output_path = os.path.join(results_dir, "combined_processed_scanlines.csv")

            # Write the merged dataframe to disk.
            combined_df.to_csv(output_path, index=False)
            logger.info(f"Saved combined file to: {output_path}")

            QMessageBox.information(
                self,
                "Save Complete",
                f"Individual and combined scanline files were saved successfully.\n\nCombined file location:\n{output_path}",
            )

        except Exception as e:
            logger.exception("Failed to save combined scanline file")
            QMessageBox.critical(
                self,
                "Save Error",
                f"An error occurred while saving the combined file:\n{e}",
            )

    def _list_files_in_folder(self, folder: str, exts=".csv") -> list[str]:
        files = []
        for name in sorted(os.listdir(folder)):
            f = os.path.join(folder, name)
            if os.path.isfile(f) and (exts is None or name.lower().endswith(exts)):
                files.append(f)
        return files

    def initialize(self):
        proj_path = config.get("project_path", "")
        outfolder_path = os.path.join(proj_path, "results")
        if not os.path.exists(outfolder_path):
            os.makedirs(outfolder_path)

        existing_files = self._list_files_in_folder(outfolder_path)
        if len(existing_files) != 0:
            reply = QMessageBox.question(
                self,
                "Generate Scan Lines",
                "Do you want to generate scan line data from the drone data?\nThis will overwrite any existing scan line data.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                if os.path.exists(outfolder_path):
                    shutil.rmtree(outfolder_path)

                ScanLineFiles = self.db.merge_and_save_scanlines_by_direction(
                    outfolder_path
                )
                self.update_file_list(ScanLineFiles)
                logger.info(
                    f"Generated {len(ScanLineFiles)} scanline file(s) in {outfolder_path}"
                )
                QApplication.restoreOverrideCursor()
            else:
                self.update_file_list(existing_files)
                logger.info(
                    f"Loaded {len(existing_files)} existing scanline file(s) from {outfolder_path}"
                )
            return
        else:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            ScanLineFiles = self.db.merge_and_save_scanlines_by_direction(
                outfolder_path
            )
            self.update_file_list(ScanLineFiles)
            logger.info(
                f"Generated {len(ScanLineFiles)} scanline file(s) in {outfolder_path}"
            )
            QApplication.restoreOverrideCursor()

    def delete_all_items(self):
        self.fileListWidget.clear()
        self.scanline_df.clear()
        self.scanline_filepaths.clear()
        self.selected_df = pd.DataFrame()
        self.populate_table(self.selected_df)
        self.scatter_fig.clear()
        self.ax.clear()
        self.canvas.draw()
        self.update_scatterplot()

    @Slot(str)
    def on_project_opened(self, project_path: str):
        pass

    @Slot()
    def on_project_reset(self):
        self.delete_all_items()
