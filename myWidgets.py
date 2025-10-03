import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from pykrige.ok import OrdinaryKriging
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from mySettings import config


class ColorbarRangeDialog(QDialog):
    """A dialog to set the min/max range for a colorbar."""

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
    # 거리 스케일
    xs = np.asarray(x)
    ys = np.asarray(y)
    zs = np.asarray(z, float)
    xmin, xmax = xs.min(), xs.max()
    ymin, ymax = ys.min(), ys.max()
    h_max = np.hypot(xmax - xmin, ymax - ymin)  # 영역 대각선 길이 근사
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

        # --- 유효한 DataFrame만 필터링해서 병합 ---
        valid_dfs = []
        for name, df in df_dict.items():
            if {"X", "Y", col_name}.issubset(df.columns):
                valid_dfs.append(df[["X", "Y", col_name]])
            else:
                print(
                    f"[경고] '{name}' 파일에는 '{col_name}' 또는 X/Y 컬럼이 없음 → 건너뜀"
                )

        if not valid_dfs:
            QMessageBox.critical(
                self,
                "Error",
                f"No valid data found with 'X', 'Y', and '{col_name}' columns.",
            )
            self.reject()
            return

        # --- 병합 ---
        merged_df = pd.concat(valid_dfs, ignore_index=True)

        # --- NumPy 배열로 변환 ---
        self.x = merged_df["X"].to_numpy()
        self.y = merged_df["Y"].to_numpy()
        self.z = merged_df[col_name].to_numpy()

        self.initUI()
        # Kriging을 바로 실행하면 UI가 표시되기 전에 멈출 수 있으므로,
        # QTimer를 사용해 잠시 후 실행되도록 스케줄링합니다.
        QTimer.singleShot(100, self.run_kriging)

    def initUI(self):
        layout = QVBoxLayout(self)

        # --- Controls ---
        ctrl_layout = QHBoxLayout()

        # Variogram 선택
        self.variogram_cb = QComboBox()
        self.variogram_cb.addItems(
            ["linear", "power", "gaussian", "spherical", "exponential"]
        )
        ctrl_layout.addWidget(QLabel("Variogram:"))
        ctrl_layout.addWidget(self.variogram_cb)

        # 필터에 저장된 variogram 값으로 콤보박스 초기화, 없으면 'linear' 사용
        current_variogram = self.filters.get("variogram", "linear")
        index = self.variogram_cb.findText(
            current_variogram, Qt.MatchFlag.MatchFixedString
        )
        self.variogram_cb.setCurrentIndex(index if index >= 0 else 0)

        # --- X 축 설정 ---
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

        # --- Y 축 설정 ---
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

        # 컨트롤 그룹과 버튼 사이에 신축성 있는 공간을 추가하여 간격을 조절합니다.
        ctrl_layout.addStretch(1)

        # Run 버튼
        run_btn = QPushButton("Run Kriging")
        run_btn.setFixedWidth(100)
        run_btn.clicked.connect(self.run_kriging)
        ctrl_layout.addWidget(run_btn)

        # Save 버튼 추가
        save_btn = QPushButton("Save Plot")
        save_btn.setFixedWidth(100)
        save_btn.clicked.connect(self.save_plot)
        ctrl_layout.addWidget(save_btn)

        layout.addLayout(ctrl_layout)

        # --- Plot area ---
        self.fig, self.ax = plt.subplots()
        self.canvas = FigureCanvas(self.fig)
        self.canvas.mpl_connect("button_press_event", self.on_canvas_click)
        layout.addWidget(self.canvas)

        # Set initial values for range inputs, using saved filters if available
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
            default_path,  # Default filename
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

            # Save range values to filters
            self.filters["grid_min_x"] = grid_min_x
            self.filters["grid_max_x"] = grid_max_x
            self.filters["grid_min_y"] = grid_min_y
            self.filters["grid_max_y"] = grid_max_y

            gridx = np.linspace(grid_min_x, grid_max_x, grid_size_x)
            gridy = np.linspace(grid_min_y, grid_max_y, grid_size_y)

            z_interp, _ = OK.execute("grid", gridx, gridy)
            # logger.info(f"---- griding variance {max(ss)}")
            if hasattr(self, "colorbar"):
                self.colorbar.remove()
                del self.colorbar
            if hasattr(self, "sm"):
                del self.sm

            # Update plot
            self.ax.clear()
            gx, gy = np.meshgrid(gridx, gridy)
            self.im = self.ax.pcolormesh(gx, gy, z_interp, shading="auto", cmap="jet")
            self.ax.set_title(f"{self.title} DATA")

            self.colorbar = self.fig.colorbar(
                self.im, ax=self.ax, label="Interpolated Value"
            )
            # 오프셋 모드 끄기 → 절대값 그대로 표시
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
        if self.colorbar and event.inaxes == self.colorbar.ax:
            current_min, current_max = self.im.get_clim()

            dlg = ColorbarRangeDialog(self, current_min, current_max)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_min, new_max = dlg.getValues()
                if new_min is not None and new_max is not None:
                    self.im.set_clim(vmin=new_min, vmax=new_max)
                    self.canvas.draw_idle()

    def closeEvent(self, event):
        # 부모가 참조 리스트에서 제거
        if hasattr(self.parent(), "_open_kriging_dialogs"):
            try:
                self.parent()._open_kriging_dialogs.remove(self)
            except ValueError:
                pass
        event.accept()
        config.set("kriging", self.filters, save=True)


class DataFilterDialog(QDialog):
    def __init__(self, parent=None):
        logger.debug("DataFilterDialog __init__ called")
        super().__init__(parent)
        self.parentWidget = parent
        self.setWindowTitle("Filter Settings")
        self.filters = config.get("filters_line", {})
        self.fs = 1

        form = QFormLayout(self)
        self.diurnal_cb = QCheckBox("Diurnal Correction")
        diurnal_cfg = self.filters.get("Diurnal_Correction", {})
        self.diurnal_cb.setChecked(diurnal_cfg.get("enabled", False))
        self.diurnal_cb.stateChanged.connect(self.update_diurnal_cb_state)
        form.addRow(self.diurnal_cb)

        self.load_diurnal_btn = QPushButton("Load Diurnal Data")
        self.load_diurnal_btn.clicked.connect(self.load_diurnal_data)
        form.addRow(self.load_diurnal_btn)

        # --- Median Filter ---
        self.median_cb = QCheckBox("Median Filter")
        med_cfg = self.filters.get("median_filter", {})
        self.median_cb.setChecked(med_cfg.get("enabled", False))
        form.addRow(self.median_cb)

        self.median_size = QLineEdit(str(med_cfg.get("kernel_size", 3)))
        form.addRow("Median Kernel Size:", self.median_size)

        # --- Low-pass Filter ---
        self.low_cb = QCheckBox("Low-pass Filter")
        low_cfg = self.filters.get("lowpass_filter", {})
        self.low_cb.setChecked(low_cfg.get("enabled", False))
        form.addRow(self.low_cb)

        self.low_cutoff = QLineEdit(str(low_cfg.get("cutoff_freq", 0.1)))
        form.addRow("Low-pass Cutoff (Hz):", self.low_cutoff)

        self.cal_cb = QCheckBox("Directional Correction")
        cali_cfg = self.filters.get("cali_filter", {})
        self.cal_cb.setChecked(cali_cfg.get("enabled", False))
        self.cal_cb.stateChanged.connect(self.update_load_button_state)
        form.addRow(self.cal_cb)

        # --- Load Calibration Button ---
        self.load_cal_btn = QPushButton("Load Flight Calibration")
        self.load_cal_btn.clicked.connect(self.load_calibration_data)
        form.addRow(self.load_cal_btn)

        self.calc_cal_btn = QPushButton("Calculate Optimal Values")
        self.calc_cal_btn.clicked.connect(self.calc_calibration_data)
        form.addRow(self.calc_cal_btn)

        grid = QGridLayout()
        grid.setColumnStretch(
            0, 1
        )  # 첫 번째 열에 신축성을 부여하여 오른쪽으로 밀어냅니다.
        # Row 1
        self.ew_input = QLineEdit("0")
        grid.addWidget(QLabel("E → W"), 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.ew_input, 1, 2)

        # Row 2
        self.we_input = QLineEdit("0")
        grid.addWidget(QLabel("W → E"), 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.we_input, 2, 2)

        # Row 3
        self.ns_input = QLineEdit("0")
        grid.addWidget(QLabel("N → S"), 3, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.ns_input, 3, 2)

        # Row 4
        self.sn_input = QLineEdit("0")
        grid.addWidget(QLabel("S → N"), 4, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.sn_input, 4, 2)
        form.addRow(grid)

        # Set initial state of the button
        self.update_load_button_state(self.cal_cb.checkState())
        self.update_diurnal_cb_state(self.diurnal_cb.checkState())

        # --- OK button ---
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

    def update_diurnal_cb_state(self, state):
        is_checked = (state == Qt.CheckState.Checked.value) or (
            state == Qt.CheckState.Checked
        )
        self.load_diurnal_btn.setEnabled(is_checked)

    def load_diurnal_data(self):
        logger.debug("DataFilterDialog load_diurnal_data called")
        # 이전에 선택한 경로가 있으면 그 경로에서 시작
        # diurnal_cfg = self.filters.get("Diurnal_Correction", {})
        start_path = os.path.join(config.get("project_path"), "Diurnal_Data Folder")

        files, _ = QFileDialog.getOpenFileNames(
            parent=self,
            caption="Select Mag data files",
            dir=start_path,
            filter="Flight data (*.csv);;All files (*)",
        )
        durinal_cfg = self.filters.setdefault("Diurnal_Correction", {})
        durinal_cfg["files"] = files

    def update_load_button_state(self, state):
        """Enable/disable the load button based on the checkbox state."""
        is_checked = (state == Qt.CheckState.Checked.value) or (
            state == Qt.CheckState.Checked
        )
        self.load_cal_btn.setEnabled(is_checked)
        self.calc_cal_btn.setEnabled(is_checked)
        self.ew_input.setEnabled(is_checked)
        self.we_input.setEnabled(is_checked)
        self.ns_input.setEnabled(is_checked)
        self.sn_input.setEnabled(is_checked)

    def calc_calibration_data(self):
        logger.debug("DataFilterDialog calc_calibration_data called")
        self.parentWidget.calculate_directional_avg_from_df()
        cali_cfg = self.filters.get("cali_filter", {})
        self.sn_input.setText(str(cali_cfg.get("offset_S_N", 0.0)))
        self.ns_input.setText(str(cali_cfg.get("offset_N_S", 0.0)))
        self.we_input.setText(str(cali_cfg.get("offset_W_E", 0.0)))
        self.ew_input.setText(str(cali_cfg.get("offset_E_W", 0.0)))

    def load_calibration_data(self):
        """Load calibration data from calibration.txt in the project folder."""
        try:
            file_path = os.path.join(config.get("project_path"), "calibration.txt")

            if not os.path.exists(file_path):
                QMessageBox.warning(
                    self,
                    "File Not Found",
                    f"calibration.txt not found in the project folder:\n{file_path}",
                )
                return

            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            cal_values = {}
            for line in lines:
                parts = line.strip().split()
                if len(parts) == 2:
                    direction, value = parts
                    cal_values[direction.upper()] = value

            self.ew_input.setText(cal_values.get("EW", "0"))
            self.we_input.setText(cal_values.get("WE", "0"))
            self.ns_input.setText(cal_values.get("NS", "0"))
            self.sn_input.setText(cal_values.get("SN", "0"))

            logger.info("Calibration data loaded from file.")
        except Exception as e:
            logger.error(f"Failed to load or parse calibration file: {e}")
            QMessageBox.critical(
                self, "Load Error", f"Could not load calibration file:\n{e}"
            )

    def accept(self):
        # validate numeric inputs
        try:
            ksize = int(self.median_size.text())
            low_f = float(self.low_cutoff.text())

            cali_offsets = {}
            # Also validate calibration inputs if the filter is enabled
            cali_offsets["offset_E_W"] = float(self.ew_input.text() or 0)
            cali_offsets["offset_W_E"] = float(self.we_input.text() or 0)
            cali_offsets["offset_N_S"] = float(self.ns_input.text() or 0)
            cali_offsets["offset_S_N"] = float(self.sn_input.text() or 0)
        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Median size, cutoff frequencies, and calibration offsets must be valid numbers.",
            )
            return
        # 2) Validate range
        nyquist = 0.5 * self.fs
        if low_f <= 0 or low_f >= nyquist:
            QMessageBox.warning(
                self,
                "Low-pass Cutoff Error",
                f"Low-pass cutoff frequency must be 0 < f < {nyquist:.2f} Hz.",
            )
            return

        if ksize <= 0:
            QMessageBox.warning(
                self,
                "Median Kernel Error",
                "Median kernel size must be an integer greater than or equal to 1.",
            )
            return
        # write back into filters dict

        self.filters["median_filter"] = {
            "enabled": self.median_cb.isChecked(),
            "kernel_size": ksize,
        }
        self.filters["lowpass_filter"] = {
            "enabled": self.low_cb.isChecked(),
            "cutoff_freq": low_f,
        }
        self.filters["cali_filter"] = {
            "enabled": self.cal_cb.isChecked(),
            "offset_E_W": cali_offsets.get("offset_E_W", 0),
            "offset_W_E": cali_offsets.get("offset_W_E", 0),
            "offset_N_S": cali_offsets.get("offset_N_S", 0),
            "offset_S_N": cali_offsets.get("offset_S_N", 0),
        }
        diurnal_cfg = self.filters.setdefault("Diurnal_Correction", {})
        diurnal_cfg["enabled"] = self.diurnal_cb.isChecked()
        config.set("filters_line", self.filters, save=True)

        self.parentWidget.filtering(self.filters.copy())
        logger.debug("DataFilterDialog accept called")
        super().accept()


class DataSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.MainWindow = parent
        self.setWindowTitle("Trim Settings")
        self.fcfg = config.get("filters")
        form = QFormLayout(self)

        # Direction filter
        self.dir_cb = QCheckBox("NS/EW Filter")
        self.dir_cb.setChecked(self.fcfg["direction_filter"].get("enabled", False))
        self.dir_thr = QLineEdit(str(self.fcfg["direction_filter"].get("threshold", 5)))
        form.addRow(self.dir_cb)
        form.addRow("Direction Threshold:", self.dir_thr)

        # Continuity filter
        self.cont_cb = QCheckBox("Continuity Filter")
        self.cont_cb.setChecked(self.fcfg["continuity_filter"].get("enabled", False))
        self.cont_num = QLineEdit(
            str(self.fcfg["continuity_filter"].get("num_points", 10))
        )
        form.addRow(self.cont_cb)
        form.addRow("Number of Points:", self.cont_num)

        # Speed filter
        self.speed_cb = QCheckBox("Speed Filter")
        self.speed_cb.setChecked(self.fcfg["speed_filter"].get("enabled", False))
        self.sp_speed = QLineEdit(str(self.fcfg["speed_filter"].get("target_speed", 5)))
        self.sp_tol = QLineEdit(str(self.fcfg["speed_filter"].get("tolerance", 1)))
        form.addRow(self.speed_cb)
        form.addRow("Target Speed (m/s):", self.sp_speed)
        form.addRow("Tolerance (m/s):", self.sp_tol)

        # Colorbar toggle
        self.color_cb = QCheckBox("Show Colorbar")
        self.color_cb.setChecked(self.fcfg["show_colorbar"])
        form.addRow(self.color_cb)

        # Background Map toggle
        self.map_cb = QCheckBox("Show Background Map")
        self.map_cb.setChecked(self.fcfg["show_backgroundmap"])
        form.addRow(self.map_cb)
        self.map_cb.setEnabled(False)

        # area bound toggle
        self.show_area_bound_cb = QCheckBox("Apply Area Bound")
        self.show_area_bound_cb.setChecked(self.fcfg["show_area_bound"])
        self.show_area_bound_cb.stateChanged.connect(self.update_area_bound_state)
        form.addRow(self.show_area_bound_cb)

        self.load_bound_btn = QPushButton("Load Boundary Data")
        self.load_bound_btn.clicked.connect(self.load_bound_data)
        form.addRow(self.load_bound_btn)

        self.area_bound_cb = QCheckBox("Enable Area Bound")
        self.area_bound_cb.setChecked(self.fcfg["enable_area_bound"])
        form.addRow(self.area_bound_cb)

        self.update_area_bound_state(self.show_area_bound_cb.checkState())
        # OK Button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

    def accept(self):
        # Validate checkbox-related inputs before closing
        if self.speed_cb.isChecked():
            try:
                float(self.sp_speed.text())
                float(self.sp_tol.text())
            except ValueError:
                QMessageBox.warning(
                    self, "Input Error", "Target Speed and Tolerance must be numbers."
                )
                return
        if self.dir_cb.isChecked():
            try:
                float(self.dir_thr.text())
            except ValueError:
                QMessageBox.warning(
                    self, "Input Error", "Direction Threshold must be a number."
                )
                return

        self.fcfg["speed_filter"]["enabled"] = self.speed_cb.isChecked()
        self.fcfg["speed_filter"]["target_speed"] = float(self.sp_speed.text())
        self.fcfg["speed_filter"]["tolerance"] = float(self.sp_tol.text())
        self.fcfg["direction_filter"]["enabled"] = self.dir_cb.isChecked()
        self.fcfg["direction_filter"]["threshold"] = float(self.dir_thr.text())
        self.fcfg["continuity_filter"]["enabled"] = self.cont_cb.isChecked()
        self.fcfg["continuity_filter"]["num_points"] = int(self.cont_num.text())
        self.fcfg["enable_area_bound"] = self.area_bound_cb.isChecked()
        self.fcfg["show_area_bound"] = self.show_area_bound_cb.isChecked()
        self.fcfg["show_colorbar"] = self.color_cb.isChecked()
        self.fcfg["show_backgroundmap"] = self.map_cb.isChecked()

        if self.fcfg["enable_area_bound"]:
            self.MainWindow.polygonDrawer.enable(True)
        else:
            self.MainWindow.polygonDrawer.enable(False)

        self.MainWindow.updatePlot()
        config.set("filters", self.fcfg, save=True)
        super().accept()

    def update_area_bound_state(self, state):
        is_checked = (state == Qt.CheckState.Checked.value) or (
            state == Qt.CheckState.Checked
        )
        self.load_bound_btn.setEnabled(is_checked)

    def load_bound_data(self):
        logger.debug("DataFilterDialog load_bound_data called")

        # 1) 파일 다이얼로그로 boundary 파일(.txt/.csv) 선택
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Boundary File",
            "",  # 기본 열릴 디렉터리 (빈 문자열이면 마지막 디렉터리)
            "Text Files (*.bln);;CSV Files (*.csv)",
        )

        # 사용자가 취소 클릭했으면 종료
        if not file_path:
            logger.debug("Boundary file selection canceled")
            return

        self.MainWindow.load_bound_file(file_path)


class OrthogonalPolygonDrawer(QObject):
    polygonFinished = Signal(list)

    def __init__(self, ax, close_threshold_px=10):
        super().__init__()
        self.ax = ax
        self.canvas = ax.figure.canvas
        self.points = []  # 확정된 버텍스 리스트
        self.lines = []  # 그려진 선 목록
        self.preview_line = None  # 마우스 무브 시 보여줄 예비 선
        self.close_threshold = close_threshold_px  # 픽셀 단위

    def on_press(self, event):
        # 축 영역 내 클릭만 처리
        if event.inaxes != self.ax:
            return
        x, y = event.xdata, event.ydata

        # 첫 점 없으면 무조건 추가
        if not self.points and event.button == 1:
            self.points.append((x, y))
            self.canvas.draw_idle()
            return

        # 클릭이 시작점 근처인지 확인 (픽셀 기준)
        start_x, start_y = self.points[0]
        disp_click = self.ax.transData.transform((x, y))
        disp_start = self.ax.transData.transform((start_x, start_y))
        dist_px = np.hypot(disp_click[0] - disp_start[0], disp_click[1] - disp_start[1])
        if dist_px < self.close_threshold and len(self.points) > 2:
            # 자동 마감
            self._finalize()
            return

        # 일반 클릭: 수평/수직 스냅 후 추가
        if event.button == 1:
            prev_x, prev_y = self.points[-1]
            dx, dy = x - prev_x, y - prev_y
            if abs(dx) > abs(dy):
                new_pt = (x, prev_y)
            else:
                new_pt = (prev_x, y)
            # 선 그리기
            (line,) = self.ax.plot(
                [prev_x, new_pt[0]], [prev_y, new_pt[1]], color="blue", linewidth=2
            )
            self.lines.append(line)
            self.points.append(new_pt)
            self.canvas.draw_idle()

    def on_move(self, event):
        # 마우스 이동 예비 선 표시
        if event.inaxes != self.ax or not self.points:
            return
        x, y = event.xdata, event.ydata
        prev_x, prev_y = self.points[-1]
        dx, dy = x - prev_x, y - prev_y
        if abs(dx) > abs(dy):
            snap = (x, prev_y)
        else:
            snap = (prev_x, y)
        if self.preview_line:
            self.preview_line.set_data([prev_x, snap[0]], [prev_y, snap[1]])
        else:
            (self.preview_line,) = self.ax.plot(
                [prev_x, snap[0]], [prev_y, snap[1]], color="red", linestyle="--"
            )
        self.canvas.draw_idle()

    def on_key(self, event):
        # 키로 마감: 엔터 or return
        if event.key in ("enter", "return") and len(self.points) > 2:
            self._finalize()

    def _finalize(self):
        # 마지막 점과 시작점을 연결
        first_x, first_y = self.points[0]
        last_x, last_y = self.points[-1]
        (line,) = self.ax.plot(
            [last_x, first_x], [last_y, first_y], color="blue", linewidth=2
        )
        self.lines.append(line)

        # 예비 선 제거
        if self.preview_line:
            self.preview_line.remove()
            self.preview_line = None
        self.canvas.draw_idle()

        self.polygonFinished.emit(self.points)

    def disconnect(self):
        # 이벤트 연결 해제
        self.canvas.mpl_disconnect(self.cid_press)
        self.canvas.mpl_disconnect(self.cid_move)
        self.canvas.mpl_disconnect(self.cid_key)

    def clear(self):
        """
        기존에 그려진 모든 선과 예비선을 제거하고,
        points와 lines 리스트를 초기 상태로 되돌립니다.
        """
        # 1) 화면에서 그려진 선들 제거
        for line in self.lines:
            try:
                line.remove()
            except Exception:
                pass
        self.lines.clear()

        # 2) 예비선 제거
        if self.preview_line:
            try:
                self.preview_line.remove()
            except Exception:
                pass
            self.preview_line = None

        # 3) 점 리스트 초기화
        self.points.clear()

        # 4) 캔버스 갱신
        self.canvas.draw_idle()

    def enable(self, flag):
        if flag:
            # 이벤트 연결
            self.cid_press = self.canvas.mpl_connect(
                "button_press_event", self.on_press
            )
            self.cid_move = self.canvas.mpl_connect("motion_notify_event", self.on_move)
            self.cid_key = self.canvas.mpl_connect("key_press_event", self.on_key)
        else:
            if hasattr(self, "cid_press"):
                self.disconnect()


class ConfigDataSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Data Settings")

        main_layout = QVBoxLayout(self)

        # --- Bound Area Group ---
        bound_group = QGroupBox("Bound Area [Easting (m), Northing (m)]")
        bound_layout = QFormLayout()

        self.bound_text = QPlainTextEdit()
        self.bound_text.setPlaceholderText(
            "Example:\n14346651.44 4458000.72\n14348205.20 4458000.72"
        )
        self.bound_text.setMinimumHeight(80)
        points = config.get("bound_area_points", [])
        if points:
            lines = [f"{x:.6f} {y:.6f}" for (x, y) in points]
            self.bound_text.setPlainText("\n".join(lines))

        bound_group.setLayout(bound_layout)
        # Clear 버튼 추가
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_bound_area)

        # 버튼을 오른쪽에 정렬
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(clear_button)

        bound_layout.addRow("Vertex List", self.bound_text)
        bound_layout.addRow(button_layout)
        bound_group.setLayout(bound_layout)

        # --- Add Groups to Main Layout ---
        main_layout.addWidget(bound_group)

        # --- OK/Cancel Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def accept(self):
        # Parse Bound Area coordinates
        lines = self.bound_text.toPlainText().strip().splitlines()
        try:
            vertexdata = [
                tuple(map(float, line.split())) for line in lines if line.strip()
            ]
            config.set("bound_area_points", vertexdata, save=True)

        except ValueError:
            QMessageBox.warning(
                self,
                "Input Error",
                "Each line in the Bound Area must contain two valid numeric values (easting and northing).",
            )
            return
        super().accept()

    def clear_bound_area(self):
        self.bound_text.clear()


class CreateProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Project Settings")

        main_layout = QVBoxLayout(self)

        # --- Bound Area Group ---
        folder_group = QGroupBox("Project Folder Select:")

        self.project_name = QLineEdit()
        self.project_name.setMinimumWidth(300)
        self.project_path = QLineEdit()
        self.project_fullpath = QLabel()
        open_button = QPushButton("Path")
        open_button.clicked.connect(self.open_folder)

        projfolder_layout = QFormLayout()
        projfolder_layout.addRow("Name:", self.project_name)
        projfolder_layout.addRow(open_button, self.project_path)
        projfolder_layout.addRow("Full Path:", self.project_fullpath)

        folder_group.setLayout(projfolder_layout)

        direction_group = QGroupBox("Flight Direction:")
        self.radio_nw = QRadioButton("NS")
        radio_ew = QRadioButton("EW")
        radio_degree = QRadioButton("Degree")
        self.degree_edit = QLineEdit()
        self.degree_edit.setText("0")
        self.degree_edit.setToolTip(
            "Enter the angle relative to North (0° = North, 90° = East, range -90~90."
        )
        self.degree_edit.setFixedWidth(60)
        self.degree_edit.setEnabled(False)
        self.radio_nw.setChecked(True)

        dir_button_group = QButtonGroup(direction_group)
        dir_button_group.addButton(self.radio_nw)
        dir_button_group.addButton(radio_ew)
        dir_button_group.addButton(radio_degree)
        dir_button_group.setExclusive(True)

        hbox = QHBoxLayout()
        hbox.addWidget(self.radio_nw)
        hbox.addStretch()
        hbox.addWidget(radio_ew)
        hbox.addStretch()

        degree_layout = QHBoxLayout()
        degree_layout.addWidget(radio_degree)
        degree_layout.addWidget(self.degree_edit)
        degree_layout.addStretch()

        hbox.addLayout(degree_layout)

        direction_group.setLayout(hbox)

        # --- Add Groups to Main Layout ---
        main_layout.addWidget(folder_group)
        main_layout.addWidget(direction_group)

        # --- OK/Cancel Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        radio_degree.toggled.connect(
            lambda checked: self.degree_edit.setEnabled(checked)
        )

    def accept(self):
        logger.debug("CreateProjectDialog accept called")
        if not hasattr(self, "fullpath"):
            return
        self.selection = {"project_path": str(self.fullpath)}

        if self.degree_edit.isEnabled():  # Degree radio selected
            degree_str = self.degree_edit.text().strip()
            try:
                value = int(degree_str)
                if not (-90 <= value <= 90):
                    raise ValueError("Out of range")
                self.selection["direction"] = value
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Invalid Input",
                    "Please enter a valid numeric angle between -90 and 90 degrees.",
                )
                logger.warning(f"Invalid Range Input {degree_str}")
                return
        elif self.radio_nw.isChecked():
            self.selection["direction"] = 0
        else:
            self.selection["direction"] = 90
        logger.info(f"selection: {self.selection}")
        super().accept()

    def open_folder(self):
        folder_path = browse_directory(self)
        proj_folder_path = Path(folder_path)
        if folder_path:
            self.project_path.setText(str(proj_folder_path))
            self.fullpath = proj_folder_path / self.project_name.text().strip()
            self.project_fullpath.setText(str(self.fullpath))


def browse_files(
    parent=None,
    initial_dir: str = "",
    filter_str: str = "All Files (*)",
    caption: str = "Select Files",
) -> list[str]:
    """여러 파일을 선택하도록 QFileDialog 실행"""
    start_dir = (
        initial_dir if (initial_dir and os.path.exists(initial_dir)) else os.getcwd()
    )
    try:
        files, _ = QFileDialog.getOpenFileNames(
            parent=parent,
            caption=caption,
            dir=start_dir,
            filter=filter_str,
        )
        return files or []
    except Exception as e:
        logger.error(f"browse_files error: {e}")
        return []


def browse_directory(
    parent=None,
    initial_dir: str = "",
    caption: str = "Select Directory",
) -> str:
    """디렉토리를 선택하도록 QFileDialog 실행"""
    start_dir = (
        initial_dir if (initial_dir and os.path.exists(initial_dir)) else os.getcwd()
    )
    try:
        folder = QFileDialog.getExistingDirectory(
            parent=parent,
            caption=caption,
            dir=start_dir,
        )
        return folder or ""
    except Exception as e:
        logger.error(f"browse_directory error: {e}")
        return ""
