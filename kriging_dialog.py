import os
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import LightSource
from matplotlib.path import Path as MplPath
from loguru import logger
from pykrige.ok import OrdinaryKriging
from pyproj import Transformer
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolBar,
    QVBoxLayout,
)
from scipy.spatial import ConvexHull, QhullError

from myResource import resource_path
from mySettings import config

__all__ = [
    "ColorbarRangeDialog",
    "KrigingPlotDialog",
    "KrigingPlotDialog_withHead",
    "suggest_params",
]


def _icon_from_candidates(*names: str) -> QIcon:
    for name in names:
        path = resource_path(name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()


DEFAULT_SHADE_PARAMS = {
    "azdeg": 225.0,
    "altdeg": 25.0,
    "vert_exag": 6.0,
    "fraction": 1.5,
    "alpha_scale": 0.3,
    "alpha_max": 0.3,
}

DEFAULT_CONTOUR_PARAMS = {
    "scale": "linear",
    "levels": 10,
    "linewidth": 0.6,
    "alpha": 0.8,
    "label_fontsize": 7,
}

KMZ_COLORBAR_GAP_FRACTION = 0.06
KMZ_COLORBAR_WIDTH_FRACTION = 0.16
KMZ_COLORBAR_HEIGHT_FRACTION = 0.78
MIN_GRID_SIZE = 2
MAX_GRID_SIZE = 500
MAX_GRID_CELLS = 250000


class ColorbarRangeDialog(QDialog):
    """Dialog to set or restore the colorbar range."""

    def __init__(self, parent=None, current_min=0, current_max=1, restore=(0, 1)):
        super().__init__(parent)
        self.setWindowTitle("Set Colorbar Range")
        self.restore = restore

        layout = QFormLayout(self)

        self.min_input = QLineEdit(f"{current_min:.2f}")
        self.max_input = QLineEdit(f"{current_max:.2f}")

        layout.addRow("Minimum:", self.min_input)
        layout.addRow("Maximum:", self.max_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        restore_button = QPushButton("Restore")
        buttons.addButton(restore_button, QDialogButtonBox.ButtonRole.ActionRole)
        restore_button.clicked.connect(self.restore_values)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        """Returns the new min and max values, or (None, None) if invalid."""
        try:
            min_val = float(self.min_input.text())
            max_val = float(self.max_input.text())
            if min_val >= max_val:
                QMessageBox.warning(
                    self,
                    "Input Error",
                    "Minimum value must be less than maximum value.",
                )
                return None, None
            return min_val, max_val
        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Please enter valid numbers for minimum and maximum.",
            )
            return None, None

    def restore_values(self):
        min_val, max_val = self.restore
        self.min_input.setText(f"{min_val:.2f}")
        self.max_input.setText(f"{max_val:.2f}")

class ShadeSettingsDialog(QDialog):
    """Dialog to edit shade rendering parameters."""

    def __init__(self, parent=None, current_values=None):
        super().__init__(parent)
        self.setWindowTitle("Shade Settings")
        self.restore = dict(DEFAULT_SHADE_PARAMS)
        self.current_values = dict(self.restore)
        if current_values:
            self.current_values.update(current_values)

        layout = QFormLayout(self)

        self.azdeg_input = QLineEdit(str(self.current_values["azdeg"]))
        self.altdeg_input = QLineEdit(str(self.current_values["altdeg"]))
        self.vert_exag_input = QLineEdit(str(self.current_values["vert_exag"]))
        self.fraction_input = QLineEdit(str(self.current_values["fraction"]))
        self.alpha_scale_input = QLineEdit(str(self.current_values["alpha_scale"]))
        self.alpha_max_input = QLineEdit(str(self.current_values["alpha_max"]))

        layout.addRow("Azimuth:", self.azdeg_input)
        layout.addRow("Altitude:", self.altdeg_input)
        layout.addRow("Vert Exag:", self.vert_exag_input)
        layout.addRow("Fraction:", self.fraction_input)
        layout.addRow("Alpha Scale:", self.alpha_scale_input)
        layout.addRow("Alpha Max:", self.alpha_max_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        restore_button = QPushButton("Restore")
        buttons.addButton(restore_button, QDialogButtonBox.ButtonRole.ActionRole)
        restore_button.clicked.connect(self.restore_values)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def restore_values(self):
        self.azdeg_input.setText(str(self.restore["azdeg"]))
        self.altdeg_input.setText(str(self.restore["altdeg"]))
        self.vert_exag_input.setText(str(self.restore["vert_exag"]))
        self.fraction_input.setText(str(self.restore["fraction"]))
        self.alpha_scale_input.setText(str(self.restore["alpha_scale"]))
        self.alpha_max_input.setText(str(self.restore["alpha_max"]))

    def get_values(self):
        try:
            values = {
                "azdeg": float(self.azdeg_input.text()),
                "altdeg": float(self.altdeg_input.text()),
                "vert_exag": float(self.vert_exag_input.text()),
                "fraction": float(self.fraction_input.text()),
                "alpha_scale": float(self.alpha_scale_input.text()),
                "alpha_max": float(self.alpha_max_input.text()),
            }
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter valid numeric values.")
            return None

        if not (0.0 <= values["altdeg"] <= 90.0):
            QMessageBox.warning(self, "Input Error", "Altitude must be between 0 and 90.")
            return None
        if values["vert_exag"] <= 0 or values["fraction"] <= 0:
            QMessageBox.warning(
                self,
                "Input Error",
                "Vert Exag and Fraction must be greater than 0.",
            )
            return None
        if values["alpha_scale"] < 0 or values["alpha_max"] < 0:
            QMessageBox.warning(
                self,
                "Input Error",
                "Alpha Scale and Alpha Max must be 0 or greater.",
            )
            return None
        return values


class ContourSettingsDialog(QDialog):
    """Dialog to edit contour rendering parameters."""

    def __init__(self, parent=None, current_values=None):
        super().__init__(parent)
        self.setWindowTitle("Contour Settings")
        self.restore = dict(DEFAULT_CONTOUR_PARAMS)
        self.current_values = dict(self.restore)
        if current_values:
            self.current_values.update(current_values)

        layout = QFormLayout(self)

        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["linear", "log"])
        self.scale_combo.setCurrentText(str(self.current_values["scale"]).lower())
        self.levels_input = QLineEdit(str(self.current_values["levels"]))
        self.linewidth_input = QLineEdit(str(self.current_values["linewidth"]))
        self.alpha_input = QLineEdit(str(self.current_values["alpha"]))
        self.label_fontsize_input = QLineEdit(str(self.current_values["label_fontsize"]))

        layout.addRow("Scale:", self.scale_combo)
        layout.addRow("Levels:", self.levels_input)
        layout.addRow("Line Width:", self.linewidth_input)
        layout.addRow("Alpha:", self.alpha_input)
        layout.addRow("Label Font:", self.label_fontsize_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        restore_button = QPushButton("Restore")
        buttons.addButton(restore_button, QDialogButtonBox.ButtonRole.ActionRole)
        restore_button.clicked.connect(self.restore_values)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def restore_values(self):
        self.scale_combo.setCurrentText(str(self.restore["scale"]).lower())
        self.levels_input.setText(str(self.restore["levels"]))
        self.linewidth_input.setText(str(self.restore["linewidth"]))
        self.alpha_input.setText(str(self.restore["alpha"]))
        self.label_fontsize_input.setText(str(self.restore["label_fontsize"]))

    def get_values(self):
        try:
            values = {
                "scale": self.scale_combo.currentText().lower(),
                "levels": int(self.levels_input.text()),
                "linewidth": float(self.linewidth_input.text()),
                "alpha": float(self.alpha_input.text()),
                "label_fontsize": float(self.label_fontsize_input.text()),
            }
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter valid contour values.")
            return None

        if values["levels"] < 2:
            QMessageBox.warning(self, "Input Error", "Levels must be 2 or greater.")
            return None
        if values["linewidth"] <= 0:
            QMessageBox.warning(self, "Input Error", "Line Width must be greater than 0.")
            return None
        if not (0.0 <= values["alpha"] <= 1.0):
            QMessageBox.warning(self, "Input Error", "Alpha must be between 0 and 1.")
            return None
        if values["label_fontsize"] <= 0:
            QMessageBox.warning(
                self,
                "Input Error",
                "Label Font must be greater than 0.",
            )
            return None
        return values


def suggest_params(x, y, z, model: str):
    xs = np.asarray(x)
    ys = np.asarray(y)
    zs = np.asarray(z, float)
    xmin, xmax = xs.min(), xs.max()
    ymin, ymax = ys.min(), ys.max()
    h_max = np.hypot(xmax - xmin, ymax - ymin)
    sill = float(np.var(zs, ddof=1)) if zs.size > 1 else 1.0

    if model == "linear":
        slope = sill / max(h_max, 1e-9)
        nugget = 0.1 * sill
        return [slope, nugget]

    if model == "power":
        exponent = 1.5
        scale = sill / (max(h_max, 1e-9) ** exponent)
        nugget = 0.1 * sill
        return [scale, exponent, nugget]

    if model == "spherical":
        range_ = 0.3 * h_max
        nugget = 0.1 * sill
        return [sill, range_, nugget]

    if model == "exponential":
        range_ = 0.2 * h_max
        nugget = 0.1 * sill
        return [sill, range_, nugget]

    if model == "gaussian":
        range_ = 0.4 * h_max
        nugget = 0.05 * sill
        return [sill, range_, nugget]

    raise ValueError("unknown model")


class KrigingPlotDialog(QDialog):
    def __init__(self, parent, df_dict, col_name):
        super().__init__(parent)
        self.title = col_name
        self.parentWindow = parent
        self.setWindowTitle(f"Kriging: {self.title}")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(800, 600)
        self.filters = config.get("kriging", {})
        self.filters.setdefault("shade_params", dict(DEFAULT_SHADE_PARAMS))
        self.filters.setdefault("contour_params", dict(DEFAULT_CONTOUR_PARAMS))
        self.filters.setdefault("clip_to_hull", True)
        self.contour_set = None
        self.shade_im = None
        self.colorbar = None
        self.scatter_plot = None
        self._last_kriging_grid = None
        self._source_epsg = None
        self._source_latlon_bounds = None
        self._kriging_running = False

        valid_dfs = []
        for name, df in df_dict.items():
            if {"X", "Y", col_name}.issubset(df.columns):
                base_cols = ["X", "Y", col_name]
                optional_cols = [
                    col
                    for col in ("Latitude", "Longitude", "CRS_EPSG")
                    if col in df.columns and col not in base_cols
                ]
                work = df[base_cols + optional_cols].copy()
                for col in base_cols:
                    work[col] = pd.to_numeric(work[col], errors="coerce")
                valid_mask = np.isfinite(work[base_cols].to_numpy(dtype=float)).all(
                    axis=1
                )
                removed_count = int((~valid_mask).sum())
                if removed_count:
                    logger.warning(
                        f"'{name}' skipped {removed_count} non-numeric kriging row(s)."
                    )
                work = work.loc[valid_mask]
                if work.empty:
                    logger.warning(
                        f"'{name}' has no numeric X/Y/'{col_name}' rows and will be skipped."
                    )
                    continue
                valid_dfs.append(work)
            else:
                logger.warning(
                    f"[Warning] '{name}' is missing '{col_name}' or X/Y columns and will be skipped."
                )

        if not valid_dfs:
            QMessageBox.critical(
                self,
                "Error",
                f"No valid data found with 'X', 'Y', and '{col_name}' columns.",
            )
            self.reject()
            return

        merged_df = pd.concat(valid_dfs, ignore_index=True)
        if len(merged_df) < 3:
            QMessageBox.critical(
                self,
                "Error",
                "Kriging requires at least 3 numeric rows with X, Y, "
                f"and '{col_name}' values.",
            )
            self.reject()
            return

        self._source_epsg = self._extract_source_epsg(merged_df)
        self._source_latlon_bounds = self._extract_source_latlon_bounds(merged_df)

        self.x = merged_df["X"].to_numpy(dtype=float)
        self.y = merged_df["Y"].to_numpy(dtype=float)
        self.z = merged_df[col_name].to_numpy(dtype=float)

        self._init_ui()
        QTimer.singleShot(100, self.run_kriging)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        ctrl_layout = QHBoxLayout()

        self.variogram_cb = QComboBox()
        self.variogram_cb.addItems(
            ["linear", "power", "gaussian", "spherical", "exponential"]
        )
        ctrl_layout.addWidget(QLabel("Variogram:"))
        ctrl_layout.addWidget(self.variogram_cb)

        self.shade_cb = QCheckBox("Shade")
        self.shade_cb.setChecked(False)
        ctrl_layout.addWidget(self.shade_cb)

        self.contour_cb = QCheckBox("Contour")
        self.contour_cb.setChecked(False)
        ctrl_layout.addWidget(self.contour_cb)

        self.scatter_cb = QCheckBox("Flight Path")
        self.scatter_cb.setChecked(False)
        ctrl_layout.addWidget(self.scatter_cb)

        self.clip_to_hull_cb = QCheckBox("Clip Outside Data")
        self.clip_to_hull_cb.setChecked(bool(self.filters.get("clip_to_hull", True)))
        ctrl_layout.addWidget(self.clip_to_hull_cb)

        current_variogram = self.filters.get("variogram", "linear")
        index = self.variogram_cb.findText(
            current_variogram, Qt.MatchFlag.MatchFixedString
        )
        self.variogram_cb.setCurrentIndex(index if index >= 0 else 0)

        x_layout = QHBoxLayout()
        x_layout.addWidget(QLabel("X Range:"))

        x_layout.addWidget(QLabel("Min:"))
        self.grid_size_x_min = QLineEdit()
        self.grid_size_x_min.setFixedWidth(80)
        x_layout.addWidget(self.grid_size_x_min)

        x_layout.addWidget(QLabel("Max:"))
        self.grid_size_x_max = QLineEdit()
        self.grid_size_x_max.setFixedWidth(80)
        x_layout.addWidget(self.grid_size_x_max)

        x_layout.addWidget(QLabel("GridNum:"))
        self.grid_size_x_input = QLineEdit(str(self.filters.get("grid_size_x", 50)))
        self.grid_size_x_input.setFixedWidth(50)
        x_layout.addWidget(self.grid_size_x_input)

        y_layout = QHBoxLayout()
        y_layout.addWidget(QLabel("Y Range:"))

        y_layout.addWidget(QLabel("Min:"))
        self.grid_size_y_min = QLineEdit()
        self.grid_size_y_min.setFixedWidth(80)
        y_layout.addWidget(self.grid_size_y_min)

        y_layout.addWidget(QLabel("Max:"))
        self.grid_size_y_max = QLineEdit()
        self.grid_size_y_max.setFixedWidth(80)
        y_layout.addWidget(self.grid_size_y_max)

        y_layout.addWidget(QLabel("GridNum:"))
        self.grid_size_y_input = QLineEdit(str(self.filters.get("grid_size_y", 50)))
        self.grid_size_y_input.setFixedWidth(50)
        y_layout.addWidget(self.grid_size_y_input)

        xy_layout = QVBoxLayout()
        xy_layout.addLayout(x_layout)
        xy_layout.addLayout(y_layout)

        ctrl_layout.addLayout(xy_layout)

        ctrl_layout.addStretch(1)

        self.run_btn = QPushButton("Run Kriging")
        self.run_btn.setFixedWidth(100)
        self.run_btn.clicked.connect(self.run_kriging)
        ctrl_layout.addWidget(self.run_btn)

        self.save_btn = QPushButton("Save Plot")
        self.save_btn.setFixedWidth(100)
        self.save_btn.clicked.connect(self.save_plot)
        ctrl_layout.addWidget(self.save_btn)

        layout.addWidget(self.create_toolbar())
        layout.addLayout(ctrl_layout)

        self.fig, self.ax = plt.subplots()
        self.canvas = FigureCanvas(self.fig)
        self.canvas.mpl_connect("button_press_event", self.on_canvas_click)
        layout.addWidget(self.canvas)

        default_min_x = f"{np.min(self.x):.2f}"
        default_max_x = f"{np.max(self.x):.2f}"
        default_min_y = f"{np.min(self.y):.2f}"
        default_max_y = f"{np.max(self.y):.2f}"
        self.grid_size_x_min.setText(str(self.filters.get("grid_min_x", default_min_x)))
        self.grid_size_x_max.setText(str(self.filters.get("grid_max_x", default_max_x)))
        self.grid_size_y_min.setText(str(self.filters.get("grid_min_y", default_min_y)))
        self.grid_size_y_max.setText(str(self.filters.get("grid_max_y", default_max_y)))

    def create_toolbar(self):
        self.toolbar = QToolBar(self)
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)

        self.actionShade = QAction(
            _icon_from_candidates("imag_shdow.png", "imag_Shadow.png", "imag_Shadow_2.png"),
            "Shade",
            self,
        )
        self.actionContour = QAction(
            _icon_from_candidates("imag_countour.png", "imag_contour.png"),
            "Contour",
            self,
        )
        self.actionKmlExport = QAction(
            _icon_from_candidates("imag_kml_export.png"),
            "KMZ Export",
            self,
        )
        self.toolbar.actionTriggered.connect(self.on_toolbar_action_triggered)

        self.toolbar.addAction(self.actionShade)
        self.toolbar.addAction(self.actionContour)
        self.toolbar.addAction(self.actionKmlExport)
        return self.toolbar

    def on_toolbar_action_triggered(self, action):
        if action == self.actionShade:
            self.open_shade_settings()
        elif action == self.actionContour:
            self.open_contour_settings()
        elif action == self.actionKmlExport:
            self.export_kml()

    def _set_kriging_controls_enabled(self, enabled):
        widgets = [
            "run_btn",
            "save_btn",
            "variogram_cb",
            "shade_cb",
            "contour_cb",
            "scatter_cb",
            "clip_to_hull_cb",
            "grid_size_x_min",
            "grid_size_x_max",
            "grid_size_x_input",
            "grid_size_y_min",
            "grid_size_y_max",
            "grid_size_y_input",
        ]
        for attr in widgets:
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(enabled)

        for action in ("actionShade", "actionContour", "actionKmlExport"):
            toolbar_action = getattr(self, action, None)
            if toolbar_action is not None:
                toolbar_action.setEnabled(enabled)

    def open_shade_settings(self):
        dlg = ShadeSettingsDialog(
            self,
            current_values=self.filters.get("shade_params", DEFAULT_SHADE_PARAMS),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if values is None:
            return

        self.filters["shade_params"] = values
        self.shade_cb.setChecked(True)
        self.run_kriging()

    def open_contour_settings(self):
        dlg = ContourSettingsDialog(
            self,
            current_values=self.filters.get("contour_params", DEFAULT_CONTOUR_PARAMS),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if values is None:
            return

        self.filters["contour_params"] = values
        self.contour_cb.setChecked(True)
        self.run_kriging()

    def save_plot(self):
        if not hasattr(self, "fig"):
            QMessageBox.warning(self, "Warning", "No plot to save.")
            return

        default_path = os.path.join(
            config.get("project_path"), f"{self.title}_kriging.png"
        )

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot",
            default_path,
            "PNG Image (*.png);;JPEG Image (*.jpg);;All Files (*)",
        )

        if file_path:
            try:
                self.fig.savefig(file_path, dpi=300, bbox_inches="tight")
                QMessageBox.information(
                    self, "Success", f"Plot saved successfully to:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save plot:\n{e}")

    @staticmethod
    def _extract_source_epsg(df):
        if "CRS_EPSG" not in df.columns:
            return None

        epsg_values = pd.to_numeric(df["CRS_EPSG"], errors="coerce").dropna()
        if epsg_values.empty:
            return None

        try:
            return int(epsg_values.iloc[0])
        except Exception:
            return None

    @staticmethod
    def _extract_source_latlon_bounds(df):
        if not {"Latitude", "Longitude"}.issubset(df.columns):
            return None

        lats = pd.to_numeric(df["Latitude"], errors="coerce").to_numpy()
        lons = pd.to_numeric(df["Longitude"], errors="coerce").to_numpy()
        valid = np.isfinite(lats) & np.isfinite(lons)
        if not valid.any():
            return None

        return {
            "north": float(np.max(lats[valid])),
            "south": float(np.min(lats[valid])),
            "east": float(np.max(lons[valid])),
            "west": float(np.min(lons[valid])),
        }

    @staticmethod
    def _safe_filename_stem(text):
        stem = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_"
            for ch in str(text)
        ).strip("_")
        return stem or "kriging"

    @staticmethod
    def _latlon_bounds_from_xy_bounds(min_x, max_x, min_y, max_y):
        return {
            "north": max_y,
            "south": min_y,
            "east": max_x,
            "west": min_x,
        }

    def _project_bounds_to_overlay_coordinates(self, min_x, max_x, min_y, max_y):
        if self._source_epsg is not None:
            try:
                transformer = Transformer.from_crs(
                    f"EPSG:{int(self._source_epsg)}",
                    "EPSG:4326",
                    always_xy=True,
                )
                xs = [min_x, max_x, max_x, min_x]
                ys = [min_y, min_y, max_y, max_y]
                lons, lats = transformer.transform(xs, ys)
                coords = [
                    (float(lon), float(lat))
                    for lon, lat in zip(lons, lats)
                    if np.isfinite(lon) and np.isfinite(lat)
                ]
                if len(coords) == 4:
                    return {"type": "quad", "coords": coords}
            except Exception as err:
                logger.warning(f"Kriging KML coordinate transform failed: {err}")
        return None

    @staticmethod
    def _is_latlon_bounds(min_x, max_x, min_y, max_y):
        return -180.0 <= min_x <= max_x <= 180.0 and -90.0 <= min_y <= max_y <= 90.0

    def _build_overlay_coordinates(self):
        if not self._last_kriging_grid:
            return None

        grid_min_x, grid_max_x, grid_min_y, grid_max_y = self._last_kriging_grid[
            "bounds"
        ]

        projected = self._project_bounds_to_overlay_coordinates(
            grid_min_x,
            grid_max_x,
            grid_min_y,
            grid_max_y,
        )
        if projected is not None:
            return projected

        if self._source_latlon_bounds is not None:
            return {"type": "box", "bounds": dict(self._source_latlon_bounds)}

        if self._is_latlon_bounds(grid_min_x, grid_max_x, grid_min_y, grid_max_y):
            return {
                "type": "box",
                "bounds": self._latlon_bounds_from_xy_bounds(
                    grid_min_x,
                    grid_max_x,
                    grid_min_y,
                    grid_max_y,
                ),
            }

        return None

    def _build_colorbar_coordinates(self):
        if not self._last_kriging_grid:
            return None

        grid_min_x, grid_max_x, grid_min_y, grid_max_y = self._last_kriging_grid[
            "bounds"
        ]
        grid_width = grid_max_x - grid_min_x
        grid_height = grid_max_y - grid_min_y
        if grid_width <= 0 or grid_height <= 0:
            return None

        if self._source_epsg is not None:
            gap = grid_width * KMZ_COLORBAR_GAP_FRACTION
            bar_width = grid_width * KMZ_COLORBAR_WIDTH_FRACTION
            bar_height = grid_height * KMZ_COLORBAR_HEIGHT_FRACTION
            center_y = (grid_min_y + grid_max_y) / 2.0
            return self._project_bounds_to_overlay_coordinates(
                grid_max_x + gap,
                grid_max_x + gap + bar_width,
                center_y - bar_height / 2.0,
                center_y + bar_height / 2.0,
            )

        if self._source_latlon_bounds is not None:
            bounds = dict(self._source_latlon_bounds)
        elif self._is_latlon_bounds(grid_min_x, grid_max_x, grid_min_y, grid_max_y):
            bounds = self._latlon_bounds_from_xy_bounds(
                grid_min_x,
                grid_max_x,
                grid_min_y,
                grid_max_y,
            )
        else:
            return None

        lon_width = bounds["east"] - bounds["west"]
        lat_height = bounds["north"] - bounds["south"]
        if lon_width <= 0 or lat_height <= 0:
            return None

        gap = lon_width * KMZ_COLORBAR_GAP_FRACTION
        bar_width = lon_width * KMZ_COLORBAR_WIDTH_FRACTION
        bar_height = lat_height * KMZ_COLORBAR_HEIGHT_FRACTION
        center_lat = (bounds["north"] + bounds["south"]) / 2.0
        return {
            "type": "box",
            "bounds": {
                "north": center_lat + bar_height / 2.0,
                "south": center_lat - bar_height / 2.0,
                "east": bounds["east"] + gap + bar_width,
                "west": bounds["east"] + gap,
            },
        }

    def _render_overlay_png(self, grid):
        grid_min_x, grid_max_x, grid_min_y, grid_max_y = grid["bounds"]
        z_interp = np.ma.array(grid["z"], copy=True)
        valid_values = np.ma.compressed(z_interp)

        fig = plt.figure(figsize=(8, 8), dpi=200)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()

        cmap = plt.get_cmap("jet").copy()
        cmap.set_bad((0.0, 0.0, 0.0, 0.0))
        vmin, vmax = self.im.get_clim() if hasattr(self, "im") else (None, None)
        im = ax.pcolormesh(
            grid["gx"],
            grid["gy"],
            z_interp,
            shading="auto",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )

        if self.shade_cb.isChecked() and valid_values.size:
            shade_params = dict(DEFAULT_SHADE_PARAMS)
            shade_params.update(self.filters.get("shade_params", {}))
            ls = LightSource(
                azdeg=shade_params["azdeg"],
                altdeg=shade_params["altdeg"],
            )
            shade = ls.hillshade(
                np.ma.filled(z_interp, float(np.mean(valid_values))),
                vert_exag=shade_params["vert_exag"],
                fraction=shade_params["fraction"],
            )
            shadow_alpha = np.clip(
                (1.0 - shade) * shade_params["alpha_scale"],
                0.0,
                shade_params["alpha_max"],
            )
            hull_mask = grid.get("hull_mask")
            if hull_mask is not None:
                shadow_alpha = np.where(hull_mask, 0.0, shadow_alpha)
            shadow_rgba = np.zeros(shade.shape + (4,), dtype=float)
            shadow_rgba[..., 3] = shadow_alpha
            ax.imshow(
                shadow_rgba,
                extent=[grid_min_x, grid_max_x, grid_min_y, grid_max_y],
                origin="lower",
                aspect="auto",
                zorder=im.get_zorder() + 1,
            )

        if self.contour_cb.isChecked() and valid_values.size:
            contour_params = dict(DEFAULT_CONTOUR_PARAMS)
            contour_params.update(self.filters.get("contour_params", {}))
            z_min = float(np.min(valid_values))
            z_max = float(np.max(valid_values))
            levels = None
            if z_min < z_max:
                if contour_params["scale"] == "log" and z_min > 0 and z_max > 0:
                    levels = np.geomspace(
                        z_min,
                        z_max,
                        int(contour_params["levels"]),
                    )
                elif contour_params["scale"] != "log":
                    levels = np.linspace(
                        z_min,
                        z_max,
                        int(contour_params["levels"]),
                    )
            if levels is not None:
                contours = ax.contour(
                    grid["gx"],
                    grid["gy"],
                    z_interp,
                    levels=levels,
                    colors="black",
                    linewidths=contour_params["linewidth"],
                    alpha=contour_params["alpha"],
                )
                ax.clabel(
                    contours,
                    fmt="%.1f",
                    fontsize=contour_params["label_fontsize"],
                    inline=True,
                )

        if self.scatter_cb.isChecked():
            ax.scatter(
                self.x,
                self.y,
                s=8,
                c="k",
                marker="o",
                edgecolors="white",
                linewidths=0.3,
                alpha=0.8,
                zorder=im.get_zorder() + 2,
            )

        ax.set_xlim(grid_min_x, grid_max_x)
        ax.set_ylim(grid_min_y, grid_max_y)
        ax.set_aspect("auto")

        image_buffer = BytesIO()
        try:
            fig.savefig(
                image_buffer,
                format="png",
                transparent=True,
                pad_inches=0,
            )
            return image_buffer.getvalue()
        finally:
            plt.close(fig)

    def _render_colorbar_png(self):
        fig = plt.figure(figsize=(1.55, 4.8), dpi=220)
        fig.patch.set_facecolor("white")
        colorbar_ax = fig.add_axes([0.20, 0.10, 0.25, 0.78])
        vmin, vmax = self.im.get_clim() if hasattr(self, "im") else (0.0, 1.0)
        cmap = plt.get_cmap("jet")
        mappable = plt.cm.ScalarMappable(cmap=cmap)
        mappable.set_clim(vmin, vmax)
        colorbar = fig.colorbar(mappable, cax=colorbar_ax)
        colorbar.ax.ticklabel_format(useOffset=False, style="plain")
        colorbar.ax.tick_params(labelsize=9, colors="black", width=0.8)
        colorbar.ax.set_title(str(self.title), fontsize=10, pad=8, color="black")
        colorbar.outline.set_edgecolor("black")
        colorbar.outline.set_linewidth(0.8)

        image_buffer = BytesIO()
        try:
            fig.savefig(
                image_buffer,
                format="png",
                facecolor="white",
                edgecolor="white",
                bbox_inches="tight",
                pad_inches=0.08,
            )
            return image_buffer.getvalue()
        finally:
            plt.close(fig)

    def _build_ground_overlay_lines(
        self,
        name,
        image_href,
        overlay_coordinates,
        draw_order,
    ):
        name = escape(str(name))
        image_href = escape(str(image_href))
        lines = [
            "    <GroundOverlay>",
            f"      <name>{name}</name>",
            "      <Icon>",
            f"        <href>{image_href}</href>",
            "      </Icon>",
            f"      <drawOrder>{draw_order}</drawOrder>",
        ]

        if overlay_coordinates["type"] == "quad":
            coord_text = " ".join(
                f"{lon:.10f},{lat:.10f},0"
                for lon, lat in overlay_coordinates["coords"]
            )
            lines.extend(
                [
                    "      <gx:LatLonQuad>",
                    f"        <coordinates>{coord_text}</coordinates>",
                    "      </gx:LatLonQuad>",
                ]
            )
        else:
            bounds = overlay_coordinates["bounds"]
            lines.extend(
                [
                    "      <LatLonBox>",
                    f"        <north>{bounds['north']:.10f}</north>",
                    f"        <south>{bounds['south']:.10f}</south>",
                    f"        <east>{bounds['east']:.10f}</east>",
                    f"        <west>{bounds['west']:.10f}</west>",
                    "        <rotation>0</rotation>",
                    "      </LatLonBox>",
                ]
            )

        lines.append("    </GroundOverlay>")
        return lines

    def _build_overlay_kml(self, overlays):
        title = escape(f"{self.title} Kriging")
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2" '
            'xmlns:gx="http://www.google.com/kml/ext/2.2">',
            "  <Document>",
            f"    <name>{title}</name>",
        ]
        for overlay in overlays:
            lines.extend(
                self._build_ground_overlay_lines(
                    overlay["name"],
                    overlay["href"],
                    overlay["coordinates"],
                    overlay["draw_order"],
                )
            )

        lines.extend(
            [
                "  </Document>",
                "</kml>",
                "",
            ]
        )
        return "\n".join(lines)

    def export_kml(self):
        if self._last_kriging_grid is None or not hasattr(self, "im"):
            QMessageBox.information(
                self,
                "KMZ Export",
                "No kriging image to export. Please run kriging first.",
            )
            return

        overlay_coordinates = self._build_overlay_coordinates()
        colorbar_coordinates = self._build_colorbar_coordinates()
        if overlay_coordinates is None:
            QMessageBox.warning(
                self,
                "KMZ Export",
                "KMZ export requires Latitude/Longitude or CRS_EPSG information.",
            )
            return
        if colorbar_coordinates is None:
            QMessageBox.warning(
                self,
                "KMZ Export",
                "Could not determine a valid colorbar location.",
            )
            return

        project_path = config.get("project_path", "") or ""
        default_dir = Path(project_path) / "results" if project_path else Path.cwd()
        default_dir.mkdir(parents=True, exist_ok=True)
        default_path = default_dir / f"{self._safe_filename_stem(self.title)}_kriging.kmz"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export KMZ",
            str(default_path),
            "KMZ files (*.kmz);;All files (*)",
        )
        if not file_path:
            return

        kmz_path = Path(file_path)
        if kmz_path.suffix.lower() != ".kmz":
            kmz_path = kmz_path.with_suffix(".kmz")

        try:
            overlay_png = self._render_overlay_png(self._last_kriging_grid)
            colorbar_png = self._render_colorbar_png()
            overlay_kml = self._build_overlay_kml(
                [
                    {
                        "name": f"{self.title} Kriging",
                        "href": "kriging.png",
                        "coordinates": overlay_coordinates,
                        "draw_order": 1,
                    },
                    {
                        "name": f"{self.title} Colorbar",
                        "href": "colorbar.png",
                        "coordinates": colorbar_coordinates,
                        "draw_order": 2,
                    },
                ]
            )
            with zipfile.ZipFile(
                kmz_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as kmz:
                kmz.writestr("doc.kml", overlay_kml)
                kmz.writestr("kriging.png", overlay_png)
                kmz.writestr("colorbar.png", colorbar_png)
            QMessageBox.information(
                self,
                "KMZ Export",
                "KMZ export completed.\n\n"
                f"KMZ file:\n{kmz_path}",
            )
        except Exception as err:
            logger.exception("Kriging KMZ export failed")
            QMessageBox.critical(
                self,
                "KMZ Export",
                f"Failed to export KMZ:\n{err}",
            )

    def _build_hull_mask(self, gx, gy):
        points = np.column_stack([self.x, self.y])
        points = points[np.isfinite(points).all(axis=1)]
        if len(points) < 3:
            return None

        unique_points = np.unique(points, axis=0)
        if len(unique_points) < 3:
            return None

        try:
            hull = ConvexHull(unique_points)
        except QhullError:
            return None

        hull_points = unique_points[hull.vertices]
        hull_path = MplPath(np.vstack([hull_points, hull_points[0]]))
        grid_points = np.column_stack([gx.ravel(), gy.ravel()])
        outside = ~hull_path.contains_points(grid_points, radius=1e-9)
        return outside.reshape(gx.shape)

    def _read_grid_inputs(self):
        try:
            grid_size_x = int(self.grid_size_x_input.text())
            grid_size_y = int(self.grid_size_y_input.text())
            grid_min_x = float(self.grid_size_x_min.text())
            grid_max_x = float(self.grid_size_x_max.text())
            grid_min_y = float(self.grid_size_y_min.text())
            grid_max_y = float(self.grid_size_y_max.text())
        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Please enter numeric values for range and grid number inputs.",
            )
            return None

        if not (MIN_GRID_SIZE <= grid_size_x <= MAX_GRID_SIZE):
            QMessageBox.warning(
                self,
                "Input Error",
                f"X GridNum must be between {MIN_GRID_SIZE} and {MAX_GRID_SIZE}.",
            )
            return None

        if not (MIN_GRID_SIZE <= grid_size_y <= MAX_GRID_SIZE):
            QMessageBox.warning(
                self,
                "Input Error",
                f"Y GridNum must be between {MIN_GRID_SIZE} and {MAX_GRID_SIZE}.",
            )
            return None

        if grid_size_x * grid_size_y > MAX_GRID_CELLS:
            QMessageBox.warning(
                self,
                "Input Error",
                "Grid size is too large. Please keep "
                f"X GridNum * Y GridNum <= {MAX_GRID_CELLS}.",
            )
            return None

        range_values = [grid_min_x, grid_max_x, grid_min_y, grid_max_y]
        if not all(np.isfinite(range_values)):
            QMessageBox.warning(
                self,
                "Input Error",
                "Range values must be finite numbers.",
            )
            return None

        if grid_min_x >= grid_max_x:
            QMessageBox.warning(
                self,
                "Input Error",
                "X Range minimum must be less than maximum.",
            )
            return None

        if grid_min_y >= grid_max_y:
            QMessageBox.warning(
                self,
                "Input Error",
                "Y Range minimum must be less than maximum.",
            )
            return None

        return grid_size_x, grid_size_y, grid_min_x, grid_max_x, grid_min_y, grid_max_y

    def run_kriging(self):
        if self._kriging_running:
            return
        self._kriging_running = True
        self._set_kriging_controls_enabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            variogram = self.variogram_cb.currentText()
            self.filters["variogram"] = variogram
            variogram_parameters = suggest_params(self.x, self.y, self.z, variogram)
            OK = OrdinaryKriging(
                self.x,
                self.y,
                self.z,
                variogram_model=variogram,
                variogram_parameters=variogram_parameters,
                verbose=False,
                enable_plotting=False,
                anisotropy_scaling=1.0,
                anisotropy_angle=0.0,
            )

            grid_inputs = self._read_grid_inputs()
            if grid_inputs is None:
                return

            (
                grid_size_x,
                grid_size_y,
                grid_min_x,
                grid_max_x,
                grid_min_y,
                grid_max_y,
            ) = grid_inputs

            self.filters["grid_size_x"] = grid_size_x
            self.filters["grid_size_y"] = grid_size_y

            self.filters["grid_min_x"] = grid_min_x
            self.filters["grid_max_x"] = grid_max_x
            self.filters["grid_min_y"] = grid_min_y
            self.filters["grid_max_y"] = grid_max_y

            gridx = np.linspace(grid_min_x, grid_max_x, grid_size_x)
            gridy = np.linspace(grid_min_y, grid_max_y, grid_size_y)
            gx, gy = np.meshgrid(gridx, gridy)

            z_interp, _ = OK.execute("grid", gridx, gridy)
            z_interp = np.ma.array(z_interp, copy=False)
            clip_to_hull = self.clip_to_hull_cb.isChecked()
            self.filters["clip_to_hull"] = clip_to_hull
            hull_mask = None
            if clip_to_hull:
                hull_mask = self._build_hull_mask(gx, gy)
                if hull_mask is not None:
                    z_interp = np.ma.array(
                        z_interp,
                        mask=np.ma.getmaskarray(z_interp) | hull_mask,
                        copy=False,
                    )
            valid_values = np.ma.compressed(z_interp)
            if self.colorbar:
                self.colorbar.remove()
                self.colorbar = None
            if hasattr(self, "sm"):
                del self.sm
            if self.shade_im is not None:
                try:
                    self.shade_im.remove()
                except Exception:
                    pass
                self.shade_im = None
            if self.contour_set is not None and hasattr(self.contour_set, "collections"):
                for coll in self.contour_set.collections:
                    try:
                        coll.remove()
                    except Exception:
                        pass
                self.contour_set = None
            if self.scatter_plot is not None:
                try:
                    self.scatter_plot.remove()
                except Exception:
                    pass
                self.scatter_plot = None

            self.ax.clear()
            self.im = self.ax.pcolormesh(gx, gy, z_interp, shading="auto", cmap="jet")
            self.ax.set_title(f"{self.title} DATA")

            if self.shade_cb.isChecked():
                # Add LightSource shading to improve terrain readability.
                shade_params = dict(DEFAULT_SHADE_PARAMS)
                shade_params.update(self.filters.get("shade_params", {}))
                ls = LightSource(
                    azdeg=shade_params["azdeg"],
                    altdeg=shade_params["altdeg"],
                )
                if valid_values.size:
                    shade = ls.hillshade(
                        np.ma.filled(z_interp, float(np.mean(valid_values))),
                        vert_exag=shade_params["vert_exag"],
                        fraction=shade_params["fraction"],
                    )
                    shadow_alpha = np.clip(
                        (1.0 - shade) * shade_params["alpha_scale"],
                        0.0,
                        shade_params["alpha_max"],
                    )
                    if hull_mask is not None:
                        shadow_alpha = np.where(hull_mask, 0.0, shadow_alpha)
                    shadow_rgba = np.zeros(shade.shape + (4,), dtype=float)
                    shadow_rgba[..., 3] = shadow_alpha
                    self.shade_im = self.ax.imshow(
                        shadow_rgba,
                        extent=[grid_min_x, grid_max_x, grid_min_y, grid_max_y],
                        origin="lower",
                        aspect="equal",
                        zorder=self.im.get_zorder() + 1,
                    )

            if self.contour_cb.isChecked():
                contour_params = dict(DEFAULT_CONTOUR_PARAMS)
                contour_params.update(self.filters.get("contour_params", {}))
                if valid_values.size == 0:
                    levels = None
                else:
                    z_min = float(np.min(valid_values))
                    z_max = float(np.max(valid_values))

                    if contour_params["scale"] == "log":
                        if z_min <= 0 or z_max <= 0:
                            QMessageBox.warning(
                                self,
                                "Contour Warning",
                                "Log Scale contour requires positive interpolated values.",
                            )
                            levels = None
                        else:
                            levels = np.geomspace(
                                z_min,
                                z_max,
                                int(contour_params["levels"]),
                            )
                    else:
                        levels = np.linspace(
                            z_min,
                            z_max,
                            int(contour_params["levels"]),
                        )

                if levels is not None:
                    self.contour_set = self.ax.contour(
                        gx,
                        gy,
                        z_interp,
                        levels=levels,
                        colors="black",
                        linewidths=contour_params["linewidth"],
                        alpha=contour_params["alpha"],
                    )
                    self.ax.clabel(
                        self.contour_set,
                        fmt="%.1f",
                        fontsize=contour_params["label_fontsize"],
                        inline=True,
                    )

            if self.scatter_cb.isChecked():
                # Overlay the original measurement locations.
                self.scatter_plot = self.ax.scatter(
                    self.x,
                    self.y,
                    s=8,
                    c="k",
                    marker="o",
                    edgecolors="white",
                    linewidths=0.3,
                    alpha=0.8,
                    zorder=self.im.get_zorder() + 2,
                )

            self.colorbar = self.fig.colorbar(
                self.im, ax=self.ax, label="Interpolated Value"
            )
            self.colorbar.ax.ticklabel_format(useOffset=False, style="plain")
            self.ax.ticklabel_format(useOffset=False, style="plain", axis="x")
            self.ax.ticklabel_format(useOffset=False, style="plain", axis="y")
            self.ax.set_aspect("equal", adjustable="box")
            self._last_kriging_grid = {
                "gx": gx.copy(),
                "gy": gy.copy(),
                "z": np.ma.array(z_interp, copy=True),
                "bounds": (grid_min_x, grid_max_x, grid_min_y, grid_max_y),
                "hull_mask": hull_mask.copy() if hull_mask is not None else None,
            }
            self.canvas.draw()
        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Please ensure all range and grid number inputs are valid numbers.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Kriging failed:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()
            self._set_kriging_controls_enabled(True)
            self._kriging_running = False

    def on_canvas_click(self, event):
        """Handle clicks on the canvas, specifically on the colorbar."""
        if hasattr(self, "colorbar") and event.inaxes == getattr(self.colorbar, "ax", None):
            current_min, current_max = self.im.get_clim()

            dlg = ColorbarRangeDialog(self, current_min, current_max)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_min, new_max = dlg.get_values()
                if new_min is not None and new_max is not None:
                    self.im.set_clim(vmin=new_min, vmax=new_max)
                    self.canvas.draw_idle()

    def closeEvent(self, event):
        if hasattr(self.parent(), "_open_kriging_dialogs"):
            try:
                self.parent()._open_kriging_dialogs.remove(self)
            except ValueError:
                pass
        event.accept()
        config.set("kriging", self.filters, save=True)


# Backward-compatible alias for older imports.
KrigingPlotDialog_withHead = KrigingPlotDialog
