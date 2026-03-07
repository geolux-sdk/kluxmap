import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import LightSource
from pykrige.ok import OrdinaryKriging
from PySide6.QtCore import Qt, QTimer
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
    QVBoxLayout,
)

from mySettings import config

__all__ = ["ColorbarRangeDialog", "KrigingPlotDialog_withHead", "suggest_params"]


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

    def getValues(self):
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


class KrigingPlotDialog_withHead(QDialog):
    def __init__(self, parent, df_dict, col_name):
        super().__init__(parent)
        self.title = col_name
        self.parentWindow = parent
        self.setWindowTitle(f"Kriging: {self.title}")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(800, 600)
        self.filters = config.get("kriging", {})
        self.contour_set = None
        self.shade_im = None
        self.colorbar = None
        self.scatter_plot = None

        valid_dfs = []
        for name, df in df_dict.items():
            if {"X", "Y", col_name}.issubset(df.columns):
                valid_dfs.append(df[["X", "Y", col_name]])
            else:
                print(
                    f"[경고] '{name}' 파일에는 '{col_name}' 또는 X/Y 컬럼이 없음 혹은 건너뜀"
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

        self.x = merged_df["X"].to_numpy()
        self.y = merged_df["Y"].to_numpy()
        self.z = merged_df[col_name].to_numpy()

        self.initUI()
        QTimer.singleShot(100, self.run_kriging)

    def initUI(self):
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

        self.scatter_cb = QCheckBox("Scatter")
        self.scatter_cb.setChecked(False)
        ctrl_layout.addWidget(self.scatter_cb)

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

        run_btn = QPushButton("Run Kriging")
        run_btn.setFixedWidth(100)
        run_btn.clicked.connect(self.run_kriging)
        ctrl_layout.addWidget(run_btn)

        save_btn = QPushButton("Save Plot")
        save_btn.setFixedWidth(100)
        save_btn.clicked.connect(self.save_plot)
        ctrl_layout.addWidget(save_btn)

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

    def run_kriging(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
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

            grid_size_x = int(self.grid_size_x_input.text())
            grid_size_y = int(self.grid_size_y_input.text())
            self.filters["grid_size_x"] = grid_size_x
            self.filters["grid_size_y"] = grid_size_y

            grid_min_x = float(self.grid_size_x_min.text())
            grid_max_x = float(self.grid_size_x_max.text())
            grid_min_y = float(self.grid_size_y_min.text())
            grid_max_y = float(self.grid_size_y_max.text())

            self.filters["grid_min_x"] = grid_min_x
            self.filters["grid_max_x"] = grid_max_x
            self.filters["grid_min_y"] = grid_min_y
            self.filters["grid_max_y"] = grid_max_y

            gridx = np.linspace(grid_min_x, grid_max_x, grid_size_x)
            gridy = np.linspace(grid_min_y, grid_max_y, grid_size_y)

            z_interp, _ = OK.execute("grid", gridx, gridy)
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
            gx, gy = np.meshgrid(gridx, gridy)
            self.im = self.ax.pcolormesh(gx, gy, z_interp, shading="auto", cmap="jet")
            self.ax.set_title(f"{self.title} DATA")

            if self.shade_cb.isChecked():
                # LightSource로 음영을 추가해 가독성을 높인다.
                ls = LightSource(azdeg=225, altdeg=25)
                shade = ls.hillshade(
                    z_interp,
                    vert_exag=6.0,
                    fraction=1.5,
                )
                shadow_alpha = np.clip((1.0 - shade) * 0.3, 0.0, 0.3)
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
                # 기본 10개 등고선
                levels = np.linspace(np.nanmin(z_interp), np.nanmax(z_interp), 10)
                levels = np.linspace(np.nanmin(z_interp), np.nanmax(z_interp), 10)
                self.contour_set = self.ax.contour(
                    gx,
                    gy,
                    z_interp,
                    levels=levels,
                    colors="black",
                    linewidths=0.6,
                    alpha=0.8,
                )
                self.ax.clabel(self.contour_set, fmt="%.1f", fontsize=7, inline=True)

            if self.scatter_cb.isChecked():
                # 원본 측정 위치를 겹쳐서 표시
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

    def on_canvas_click(self, event):
        """Handle clicks on the canvas, specifically on the colorbar."""
        if hasattr(self, "colorbar") and event.inaxes == getattr(self.colorbar, "ax", None):
            current_min, current_max = self.im.get_clim()

            dlg = ColorbarRangeDialog(self, current_min, current_max)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_min, new_max = dlg.getValues()
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
