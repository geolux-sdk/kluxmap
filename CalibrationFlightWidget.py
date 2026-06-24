import os
from typing import Optional
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QSize, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QMenu,
    QListWidget,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QButtonGroup,
)

from DataManager import DataManager
from direction_utils import classify_points
from myResource import resource_path
from mySettings import config


class CalibrationFlightWidget(QWidget):
    def __init__(
        self, db: DataManager, main_window: Optional[QWidget] = None
    ) -> None:
        super().__init__()
        self.db: DataManager = db
        self.main_window: Optional[QWidget] = main_window

        self.df = pd.DataFrame()
        # Remember picked scatter positions for the current interaction.
        self._sel_positions = []
        self._selected_lines = []
        self._selected_files = []
        self._temp_line = None
        self._palette = plt.get_cmap("tab10").colors
        self._init_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _init_ui(self):
        layout = QVBoxLayout()

        # Toolbar
        toolbar = QToolBar(self)
        toolbar.setIconSize(QSize(32, 32))
        self.actionOpenCaliFolder = QAction(
            QIcon(resource_path("imag_data_import.png")),
            "Open Calibration Flight Folder..",
            self,
        )
        self.actionOpenCaliFolder.setStatusTip("Open Calibration Flight Folder")
        self.actionOpenCaliFolder.triggered.connect(
            self._open_calibration_flight_folder
        )
        toolbar.addAction(self.actionOpenCaliFolder)

        layout.addWidget(toolbar)

        # Main plot widget
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)

        # Scatter + controls
        data_layout = QHBoxLayout()
        data_layout.addWidget(
            self._create_scatter_plot(), 0, Qt.AlignmentFlag.AlignHCenter
        )
        data_layout.addWidget(
            self._create_data_widgets(), 0, Qt.AlignmentFlag.AlignHCenter
        )

        dataV_layout = QVBoxLayout()
        dataV_layout.addLayout(data_layout)
        dataV_layout.addWidget(
            self._create_canvas_plot(), 0, Qt.AlignmentFlag.AlignHCenter
        )

        panel = QFrame()
        panel.setLayout(dataV_layout)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel.setLineWidth(2)

        self.file_list_widget = self._create_file_list_widget()
        main_layout.addWidget(self.file_list_widget, 0)
        main_layout.addWidget(panel)
        main_layout.setStretch(0, 0)
        main_layout.setStretch(1, 1)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        self.actionOpenCaliFolder.setEnabled(False)

    def set_actions_enabled(self, action=True):
        self.actionOpenCaliFolder.setEnabled(action)

    def _open_calibration_flight_folder(self):
        project_path = config.get("project_path", "")
        if not project_path:
            QMessageBox.warning(self, "ERROR", "Open a project folder first.")
            return
        path = os.path.join(project_path, "Calibration Flight Folder")
        if not os.path.isdir(path):
            QMessageBox.warning(
                self,
                "Folder Missing",
                f'"Calibration Flight Folder" not found under:\n{project_path}',
            )
            return
        files, _ = QFileDialog.getOpenFileNames(
            parent=self,
            caption="Select Mag data files",
            dir=path,
            filter="Flight data (*.csv);;All files (*)",
        )

        if not files:
            return

        self._selected_files = files
        logger.info(
            f"Loaded {len(files)} calibration flight file(s) from {path}"
        )
        self.update_file_list(files)
        self.df = self.db.merge_csv_to_df(files)
        self.update_plots(self.df)

    def _create_scatter_plot(self):
        # Slightly enlarge the mag scatter plot (~additional 10% bigger than before)
        self.scatter_fig = Figure(figsize=(7.3, 2.4), dpi=100)
        self.scatter_ax = self.scatter_fig.add_subplot(111)
        self.scatter_ax.set_title("Total Magnetic Field (Mag)")
        self.scatter_ax.set_xlabel("Index")
        self.scatter_ax.set_ylabel("Mag")
        self.scatter_ax.grid(True)

        self.scatter_canvas = FigureCanvas(self.scatter_fig)
        # Connect mouse interaction handlers.
        self.scatter_canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.scatter_canvas.mpl_connect("button_press_event", self._on_scatter_select)
        self.scatter_canvas.mpl_connect("scroll_event", self._on_scroll_zoom)
        return self.scatter_canvas

    def _create_canvas_plot(self):
        # Make the figure a bit wider so both plots can fill the space
        self.fig = Figure(figsize=(13.2, 8), dpi=100)

        # Top plot (row 1 of 2)
        self.ax_mag = self.fig.add_subplot(2, 1, 1)
        self.ax_mag.set_title("Mag Plot")
        # Keep the default axis formatting for ax_mag.

        # Bottom plot (row 2 of 2)
        self.ax_speed = self.fig.add_subplot(2, 1, 2)
        self.ax_speed.set_title("Speed Plot")
        # Keep the default axis formatting for ax_speed.

        # Create the canvas and return it
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return self.canvas

    def _create_data_widgets(self):
        box = QGroupBox("Directional Calibration Data")

        # Use a vertical layout on the group box.
        vbox = QVBoxLayout(box)

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_calibration_flight_data)
        vbox.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._cancel_calibration_flight_data)
        vbox.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Grid of calibration inputs
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)  # let the QLineEdits expand

        # Header
        grid.addWidget(
            QLabel("Direction"), 0, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(QLabel("Value"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(
            QLabel("Main Direction"), 0, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )

        # Row 1 (vertical up/down) + shared main selector for vertical pair
        self.TD_input = QLineEdit()
        self.main_dir_group = QButtonGroup(box)
        self.main_dir_group.setExclusive(True)

        self.cb_vertical_main = QCheckBox()
        self.cb_vertical_main.setToolTip("Checked: Top -> Down is main. Unchecked: Bottom -> Up is main.")
        self.main_dir_group.addButton(self.cb_vertical_main)
        grid.addWidget(QLabel("Top -> Down"), 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.TD_input, 1, 1)
        grid.addWidget(self.cb_vertical_main, 1, 2, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        # Row 2 (vertical counterpart)
        self.BU_input = QLineEdit()
        grid.addWidget(QLabel("Bottom -> Up"), 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.BU_input, 2, 1)

        # Row 3 (horizontal left/right) + shared main selector for horizontal pair
        self.LR_input = QLineEdit()
        self.cb_horizontal_main = QCheckBox()
        self.cb_horizontal_main.setToolTip("Checked: Left -> Right is main. Unchecked: Right -> Left is main.")
        self.main_dir_group.addButton(self.cb_horizontal_main)
        grid.addWidget(QLabel("Left -> Right"), 3, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.LR_input, 3, 1)
        grid.addWidget(self.cb_horizontal_main, 3, 2, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        # Row 4 (horizontal counterpart)
        self.RL_input = QLineEdit()
        grid.addWidget(QLabel("Right -> Left"), 4, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.RL_input, 4, 1)

        vbox.addLayout(grid)

        # Default reference direction: vertical (Top -> Down). Only one can be checked.
        self.cb_vertical_main.setChecked(True)
        self.cb_horizontal_main.setChecked(False)

        vbox.addStretch()
        # Save button
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_calibration_flight_data)
        vbox.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return box

    def _create_file_list_widget(self):
        box = QGroupBox("Selected Files")
        layout = QVBoxLayout(box)
        self.file_list = QListWidget()
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(
            self._show_file_context_menu
        )
        layout.addWidget(self.file_list)
        box.setMinimumWidth(220)
        box.setFixedWidth(240)
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        return box

    def update_file_list(self, files):
        """Show selected calibration files on the left list."""
        self.file_list.clear()
        self.file_list.addItems([os.path.basename(path) for path in files])

    def _show_file_context_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        remove_action = menu.addAction("Remove")
        chosen = menu.exec(self.file_list.mapToGlobal(pos))
        if chosen == remove_action:
            row = self.file_list.row(item)
            self._confirm_and_remove_file(row)

    def _confirm_and_remove_file(self, row):
        """Confirm and remove a file from the selection and data."""
        if row < 0 or row >= len(self._selected_files):
            return
        file_path = self._selected_files[row]
        reply = QMessageBox.question(
            self,
            "Remove File",
            f"Delete '{os.path.basename(file_path)}' from the selection?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._selected_files.pop(row)
        self.update_file_list(self._selected_files)

        if self._selected_files:
            self.df = self.db.merge_csv_to_df(self._selected_files)
        else:
            self.df = pd.DataFrame()
        self.update_plots(self.df)

    def _cancel_calibration_flight_data(self):
        self._selected_lines.clear()
        self._sel_positions.clear()
        self.TD_input.setText("")
        self.BU_input.setText("")
        self.LR_input.setText("")
        self.RL_input.setText("")
        self._set_input_color(self.TD_input, None)
        self._set_input_color(self.BU_input, None)
        self._set_input_color(self.LR_input, None)
        self._set_input_color(self.RL_input, None)
        self.update_plots(self.df)

    def _apply_calibration_flight_data(self):
        if not self._selected_lines:
            logger.warning("_apply_calibration_flight_data: No lines selected.")
            QMessageBox.warning(
                self,
                "No Selection",
                "Please select one or more flight lines from the plot first.",
            )
            return

        # Store average magnetic values grouped by direction.
        directional_mags = {"TD": [], "BU": [], "LR": [], "RL": []}
        direction_colors = {"TD": [], "BU": [], "LR": [], "RL": []}

        for idx, line in enumerate(self._selected_lines):
            start, end = line
            segment_df = self.df.iloc[start : end + 1]
            color = self._palette[idx % len(self._palette)]

            # Average the selected segment and classify its direction.
            avg_mag = segment_df["Mag"].mean()

            # Compare the segment heading against the chosen reference axis.
            start_x, end_x = segment_df["X"].iloc[0], segment_df["X"].iloc[-1]
            start_y, end_y = segment_df["Y"].iloc[0], segment_df["Y"].iloc[-1]

            main_deg = getattr(self, "_main_direction_degree", 0) or 0
            direction = classify_points(
                start_x, start_y, end_x, end_y, main_deg
            )
            if direction is None:
                continue

            directional_mags[direction].append(avg_mag)
            direction_colors[direction].append(color)

        # Apply averaged values to the inputs and highlight the source color.
        self._apply_direction_result("TD", self.TD_input, directional_mags, direction_colors)
        self._apply_direction_result("BU", self.BU_input, directional_mags, direction_colors)
        self._apply_direction_result("LR", self.LR_input, directional_mags, direction_colors)
        self._apply_direction_result("RL", self.RL_input, directional_mags, direction_colors)

        QMessageBox.information(
            self,
            "Applied",
            "The average magnetic field values have been calculated and applied to the input fields.",
        )
        logger.info(
            f"Applied calibration guidance from {len(self._selected_lines)} selected line(s)"
        )

        # Clear the temporary selection and refresh the plots.
        self._sel_positions.clear()
        self.update_plots(self.df)

    def _save_calibration_flight_data(self):
        project_path = config.get("project_path")
        if not project_path:
            QMessageBox.warning(
                self, "Project Path Missing", "Open a project folder before saving."
            )
            return

        # Read the directional offset values from the input fields.
        try:
            values = {
                "TD": float(self.TD_input.text()),
                "BU": float(self.BU_input.text()),
                "LR": float(self.LR_input.text()),
                "RL": float(self.RL_input.text()),
            }
        except ValueError:
            QMessageBox.warning(
                self, "Input Error", "All input values must be valid numbers."
            )
            return

        # Choose main directions per axis (two selectors)
        if self.cb_vertical_main.isChecked():
            reference = "TD"
        else:
            reference = "LR"

        reference_value = values[reference]

        # Calculate differences and store them (use axis-specific mains)
        offsets = {
            "offset_TD": reference_value - values["TD"],
            "offset_BU": reference_value - values["BU"],
            "offset_LR": reference_value - values["LR"],
            "offset_RL": reference_value - values["RL"],
        }

        # Persist current widget state
        self.save_state_to_config()

        QMessageBox.information(
            self,
            "Saved",
            "Calibration offsets saved.\n"
        )

        # --- Save to file ---
        file_path = os.path.join(project_path, "calibration.txt")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # New labels aligned with the UI.
                f.write(f"TD {offsets['offset_TD']:.2f}\n")
                f.write(f"BU {offsets['offset_BU']:.2f}\n")
                f.write(f"LR {offsets['offset_LR']:.2f}\n")
                f.write(f"RL {offsets['offset_RL']:.2f}\n")

            logger.info(f"Calibration data saved to {file_path}")
        except IOError as e:
            logger.exception(f"Failed to save calibration file: {file_path}")
            QMessageBox.critical(
                self, "File Save Error", f"Could not save calibration file:\n{e}"
            )

    def update_plots(self, df):
        if df is None or df.empty:
            self._temp_line = None
            return

        # Reset the temporary line reference before redrawing the axes.
        self._temp_line = None

        # --- Scatter plot update ---
        # Use cumulative distance on the x-axis when X and Y are available.
        distance = None
        step_dist = None
        if {"X", "Y"}.issubset(df.columns):
            dx = df["X"].diff()
            dy = df["Y"].diff()
            step_dist = np.sqrt(dx**2 + dy**2)
            distance = step_dist.cumsum().fillna(0)
            df["Distance"] = distance

        self.scatter_ax.clear()
        if {"X", "Y", "Mag"}.issubset(df.columns):
            x, y = df["X"], df["Y"]
            self.scatter_ax.scatter(x, y, color="black", s=1, alpha=0.7)
            # Expand the horizontal range for easier interaction.
            x_min, x_max = x.min(), x.max()
            x_margin = x_max - x_min
            self.scatter_ax.set_xlim(x_min - x_margin, x_max + x_margin)

            # Disable axis offset notation so absolute coordinates stay visible.
            self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="x")
            self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="y")

            self.scatter_ax.set_title("Flight Path")
            self.scatter_ax.set_xlabel("X (Easting)")
            self.scatter_ax.set_ylabel("Y (Northing)")
            self.scatter_ax.set_aspect("equal", "box")
            self.scatter_ax.grid(True)
        else:
            self.scatter_ax.set_title("X, Y, or Mag data not available")

        palette = self._palette
        if self._selected_lines:
            for i, line in enumerate(self._selected_lines):
                start, end = line
                color = palette[i % len(palette)]
                xs = df["X"].iloc[start : end + 1].values
                ys = df["Y"].iloc[start : end + 1].values

                # draw the polyline
                self.scatter_ax.plot(xs, ys, linewidth=3, c=color, zorder=5)

                # single arrow from near-start to near-end
                dx = 5
                dy = 5
                self.scatter_ax.annotate(
                    "",
                    xy=(xs[-1] + dx, ys[-1] + dy),
                    xytext=(xs[0] + dx, ys[0] + dy),
                    arrowprops=dict(arrowstyle="->", color=color, lw=1.5),
                    zorder=6,
                )

        self.scatter_fig.tight_layout()
        self.scatter_canvas.draw()

        # --- Line plot update ---
        self.ax_mag.clear()
        self.ax_speed.clear()

        # --- Mag Plot ---
        if "Mag" in df.columns:
            x_axis = distance if distance is not None else df.index
            self.ax_mag.plot(x_axis, df["Mag"], label="Mag", linewidth=0.8)
            self.ax_mag.set_title("Magnetic Field")
            self.ax_mag.set_xlabel("Distance (m)" if distance is not None else "Index")
            self.ax_mag.set_ylabel("Total Magnetic Intensity (nT)")
            self.ax_mag.legend()
            self.ax_mag.grid(True)
        else:
            self.ax_mag.set_title("Mag data not available")

        # --- Speed Plot ---
        speed_available = False
        if {"X", "Y", "Counter"}.issubset(df.columns):
            dt = df["Counter"].diff() / 1000.0
            if step_dist is None:
                dx = df["X"].diff()
                dy = df["Y"].diff()
                step_dist = np.sqrt(dx**2 + dy**2)
            speed = step_dist / dt.replace(0, np.nan)
            df["Speed"] = speed
            speed_available = True

            x_axis = distance if distance is not None else df.index
            self.ax_speed.plot(
                x_axis, df["Speed"], label="Speed (m/s)", linewidth=0.8
            )
            self.ax_speed.set_title("Flight Speed")
            self.ax_speed.set_xlabel("Distance (m)" if distance is not None else "Index")
            self.ax_speed.set_ylabel("Speed (m/s)")
            self.ax_speed.legend()
            self.ax_speed.grid(True)
        else:
            self.ax_speed.set_title(
                "Speed data not available (missing X, Y, or Counter)"
            )

        # --- Plot selected lines on both plots ---
        if self._selected_lines:
            for i, line in enumerate(self._selected_lines):
                start, end = line
                color = palette[i % len(palette)]
                idxs = (
                    df["Distance"].values[start : end + 1]
                    if distance is not None
                    else df.index.values[start : end + 1]
                )

                if "Mag" in df.columns:
                    mags = df["Mag"].iloc[start : end + 1].values
                    self.ax_mag.plot(idxs, mags, linewidth=2, c=color, zorder=5)

                if speed_available:
                    speeds = df["Speed"].iloc[start : end + 1].values
                    self.ax_speed.plot(idxs, speeds, linewidth=2, c=color, zorder=5)

        # Keep extra left margin so y-labels stay visible
        self.fig.tight_layout(rect=[0.05, 0.05, 0.98, 0.95], h_pad=2.0)
        self.canvas.draw()

    def _on_scatter_select(self, event):
        # Right click cancels the current selection immediately.
        if event.button == 3:
            # Remove the active selection and temporary line.
            self._sel_positions.clear()
            if hasattr(self, "_temp_line") and self._temp_line:
                try:
                    self._temp_line.remove()
                except NotImplementedError:
                    pass
                self._temp_line = None
            self.update_plots(self.df)
            return

        if event.inaxes is not self.scatter_ax or self.df.empty:
            return

        # Left click selects the starting point.
        if event.button == 1 and not self._sel_positions:
            if len(self._selected_lines) >= 4:
                QMessageBox.information(
                    self,
                    "Selection Limit",
                    "You can select up to 4 flight lines.",
                )
                return
            x0, y0 = event.xdata, event.ydata
            dx = self.df["X"].values - x0
            dy = self.df["Y"].values - y0
            pos = int((dx * dx + dy * dy).argmin())
            self._sel_positions = [pos]
            self.scatter_ax.scatter(
                self.df["X"].iloc[pos],
                self.df["Y"].iloc[pos],
                marker="o",
                s=5,
                c="yellow",
                zorder=10,
            )
            self.scatter_ax.figure.canvas.draw_idle()
            return
        if event.button == 1 and self._sel_positions:
            x0, y0 = event.xdata, event.ydata
            dx = self.df["X"].values - x0
            dy = self.df["Y"].values - y0
            pos = int((dx * dx + dy * dy).argmin())

            self._sel_positions.append(pos)
            if self._sel_positions[0] != self._sel_positions[1]:
                self._selected_lines.append(sorted(self._sel_positions))
            self._sel_positions.clear()
            self.update_plots(self.df)
            return

    def _on_mouse_move(self, event):
        """Draw a temporary rubber-band line while selecting a segment."""
        if not self._sel_positions or event.inaxes is not self.scatter_ax:
            return
        x0 = self.df["X"].iloc[self._sel_positions[0]]
        y0 = self.df["Y"].iloc[self._sel_positions[0]]
        x1, y1 = event.xdata, event.ydata
        # Remove the previous preview line.
        if hasattr(self, "_temp_line") and self._temp_line:
            try:
                self._temp_line.remove()
            except NotImplementedError:
                # Ignore the case where the artist has already been removed.
                pass
            self._temp_line = None
        # Draw the updated preview line.
        self._temp_line = self.scatter_ax.plot(
            [x0, x1], [y0, y1], "--", color="blue", zorder=4
        )[0]
        self.scatter_ax.figure.canvas.draw_idle()

    def _on_scroll_zoom(self, event):
        """Zoom the scatter plot around the mouse cursor."""
        if event.inaxes is not self.scatter_ax:
            return
        if event.xdata is None or event.ydata is None:
            return

        scale = 1.2 if event.button == "up" else 1 / 1.2
        xlim = self.scatter_ax.get_xlim()
        ylim = self.scatter_ax.get_ylim()
        xdata, ydata = event.xdata, event.ydata

        new_xlim = [
            xdata - (xdata - xlim[0]) * scale,
            xdata + (xlim[1] - xdata) * scale,
        ]
        new_ylim = [
            ydata - (ydata - ylim[0]) * scale,
            ydata + (ylim[1] - ydata) * scale,
        ]

        self.scatter_ax.set_xlim(new_xlim)
        self.scatter_ax.set_ylim(new_ylim)
        self.scatter_canvas.draw_idle()

    def _set_input_color(self, line_edit, color=None):
        """Apply the selected line color to the input background."""
        if color is None:
            line_edit.setStyleSheet("")
            return
        r, g, b = [int(c * 255) for c in color[:3]]
        alpha = 64  # 0-255, roughly 25% opacity
        line_edit.setStyleSheet(
            f"background-color: rgba({r}, {g}, {b}, {alpha});"
        )

    def _apply_direction_result(self, direction, line_edit, directional_mags, direction_colors):
        """Write the averaged value and reflect the selected line color."""
        if directional_mags[direction]:
            avg = sum(directional_mags[direction]) / len(directional_mags[direction])
            line_edit.setText(f"{avg:.2f}")
            color = direction_colors[direction][0] if direction_colors[direction] else None
            self._set_input_color(line_edit, color)
        else:
            self._set_input_color(line_edit, None)

    @Slot(str)
    def on_project_opened(self, project_path: str):
        self._main_direction_str = config.get('direction_str', '')
        self._main_direction_degree = config.get("direction", 0)
        self.load_state_from_config()

    @Slot()
    def on_project_reset(self):
        self.TD_input.clear()
        self.BU_input.clear()
        self.LR_input.clear()
        self.RL_input.clear()
        self.cb_vertical_main.setChecked(True)
        self.cb_horizontal_main.setChecked(False)
        self._selected_files.clear()
        self.update_file_list(self._selected_files)
        self.df = pd.DataFrame()

        # Clear all plots
        if hasattr(self, "scatter_ax"):
            self.scatter_ax.clear()
            self.scatter_ax.set_title("No data loaded.")
            if hasattr(self, "scatter_canvas"):
                self.scatter_canvas.draw_idle()
        if hasattr(self, "ax_mag"):
            self.ax_mag.clear()
        if hasattr(self, "ax_speed"):
            self.ax_speed.clear()
        if hasattr(self, "canvas"):
            self.canvas.draw_idle()

        self.save_state_to_config()

    def save_state_to_config(self):
        """Save current calibration widget state to project config."""
        if config.file_path is None:
            return
        # Reload existing config from disk if in-memory store is empty to avoid overwriting other keys.
        if not config.config:
            try:
                config.load()
            except Exception as e:
                logger.warning(f"Failed to reload config before saving calibration state: {e}")
        state = {
            "FileList": self._selected_files,
            "TD": self.TD_input.text(),
            "BU": self.BU_input.text(),
            "LR": self.LR_input.text(),
            "RL": self.RL_input.text(),
            "vertical_main": self.cb_vertical_main.isChecked(),
            "horizontal_main": self.cb_horizontal_main.isChecked(),
        }
        try:
            config.set("calibration_widget", state, save=True)
        except Exception as e:
            logger.warning(f"Failed to save calibration widget state: {e}")

    def load_state_from_config(self):
        """Restore calibration widget state from project config."""
        state = config.get("calibration_widget", {}) or {}
        self._selected_files = state.get("FileList", [])
        self.TD_input.setText(str(state.get("TD", "")))
        self.BU_input.setText(str(state.get("BU", "")))
        self.LR_input.setText(str(state.get("LR", "")))
        self.RL_input.setText(str(state.get("RL", "")))

        vert = state.get("vertical_main")
        horiz = state.get("horizontal_main")
        if vert is None and horiz is None:
            self.cb_vertical_main.setChecked(True)
            self.cb_horizontal_main.setChecked(False)
        else:
            if bool(vert) and not bool(horiz):
                self.cb_vertical_main.setChecked(True)
                self.cb_horizontal_main.setChecked(False)
            elif bool(horiz) and not bool(vert):
                self.cb_vertical_main.setChecked(False)
                self.cb_horizontal_main.setChecked(True)
            else:
                self.cb_vertical_main.setChecked(True)
                self.cb_horizontal_main.setChecked(False)
        
        self.update_file_list(self._selected_files)
        if self._selected_files:
            self.df = self.db.merge_csv_to_df(self._selected_files)
            self.update_plots(self.df)
