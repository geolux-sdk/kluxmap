import os
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PySide6.QtCore import QObject, Qt, QTimer, Signal, QSize
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDial,
    QFileDialog,
    QAbstractItemView,
    QListView,
    QTreeView,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
    QVBoxLayout,
)

from mySettings import config
from kriging_dialog import (
    ColorbarRangeDialog,
    KrigingPlotDialog_withHead,
    suggest_params,
)




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
        # Row 1 (match Calibration Flight order: vertical first)
        self.td_input = QLineEdit("0")  # Top -> Down
        grid.addWidget(
            QLabel("Top -> Down"), 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(self.td_input, 1, 2)

        # Row 2
        self.bu_input = QLineEdit("0")  # Bottom -> Up
        grid.addWidget(
            QLabel("Down -> Top"), 2, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(self.bu_input, 2, 2)

        # Row 3
        self.lr_input = QLineEdit("0")  # Left -> Right
        grid.addWidget(
            QLabel("Left -> Right"), 3, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(self.lr_input, 3, 2)

        # Row 4
        self.rl_input = QLineEdit("0")  # Right -> Left
        grid.addWidget(
            QLabel("Right -> Left"), 4, 1, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(self.rl_input, 4, 2)
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
        self.rl_input.setEnabled(is_checked)
        self.lr_input.setEnabled(is_checked)
        self.td_input.setEnabled(is_checked)
        self.bu_input.setEnabled(is_checked)

    def calc_calibration_data(self):
        logger.debug("DataFilterDialog calc_calibration_data called")
        self.parentWidget.calculate_directional_avg_from_df()
        # 최신 계산값을 config에서 다시 불러와 UI에 반영
        filters_line = config.get("filters_line", {})
        cali_cfg = filters_line.get("cali_filter", self.filters.get("cali_filter", {}))
        self.bu_input.setText(str(cali_cfg.get("offset_BU", 0.0)))
        self.td_input.setText(str(cali_cfg.get("offset_TD", 0.0)))
        self.lr_input.setText(str(cali_cfg.get("offset_LR", 0.0)))
        self.rl_input.setText(str(cali_cfg.get("offset_RL", 0.0)))

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

            # Support both legacy labels (EW/WE/NS/SN) and new labels (RL/LR/TD/BU).
            self.rl_input.setText(
                cal_values.get("RL", cal_values.get("EW", "0"))
            )
            self.lr_input.setText(
                cal_values.get("LR", cal_values.get("WE", "0"))
            )
            self.td_input.setText(
                cal_values.get("TD", cal_values.get("NS", "0"))
            )
            self.bu_input.setText(
                cal_values.get("BU", cal_values.get("SN", "0"))
            )

            QMessageBox.information(
                self,
                "Flight Calibration Loaded",
                (
                    "Loaded calibration.txt\n"
                    f"Top->Down: {self.td_input.text()}\n"
                    f"Down->Top: {self.bu_input.text()}\n"
                    f"Left->Right: {self.lr_input.text()}\n"
                    f"Right->Left: {self.rl_input.text()}"
                ),
            )

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
            cali_offsets["offset_RL"] = float(self.rl_input.text() or 0)  # Right -> Left
            cali_offsets["offset_LR"] = float(self.lr_input.text() or 0)  # Left -> Right
            cali_offsets["offset_TD"] = float(self.td_input.text() or 0)  # Top -> Down
            cali_offsets["offset_BU"] = float(self.bu_input.text() or 0)  # Down -> Top
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
            "offset_RL": cali_offsets.get("offset_RL", 0),
            "offset_LR": cali_offsets.get("offset_LR", 0),
            "offset_TD": cali_offsets.get("offset_TD", 0),
            "offset_BU": cali_offsets.get("offset_BU", 0),
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
        self.dir_cb = QCheckBox("Filter by Angle")
        self.dir_cb.setChecked(self.fcfg["direction_filter"].get("enabled", False))
        self.dir_thr = QLineEdit(str(self.fcfg["direction_filter"].get("threshold", 5)))
        form.addRow(self.dir_cb)
        form.addRow("Tolerance:", self.dir_thr)

        # Continuity filter
        self.cont_cb = QCheckBox("Mininum Consecutive Data")
        self.cont_cb.setChecked(self.fcfg["continuity_filter"].get("enabled", False))
        self.cont_num = QLineEdit(
            str(self.fcfg["continuity_filter"].get("num_points", 10))
        )
        form.addRow(self.cont_cb)
        form.addRow("Number of Points:", self.cont_num)

        # Speed filter
        self.speed_cb = QCheckBox("Filter by Speed")
        self.speed_cb.setChecked(self.fcfg["speed_filter"].get("enabled", False))
        self.sp_speed = QLineEdit(str(self.fcfg["speed_filter"].get("target_speed", 5)))
        self.sp_tol = QLineEdit(str(self.fcfg["speed_filter"].get("tolerance", 1)))
        form.addRow(self.speed_cb)
        form.addRow("Target Speed (m/s):", self.sp_speed)
        form.addRow("Tolerance (m/s):", self.sp_tol)

        # # Colorbar toggle
        # self.color_cb = QCheckBox("Show Colorbar")
        # self.color_cb.setChecked(self.fcfg["show_colorbar"])
        # form.addRow(self.color_cb)

        # # Background Map toggle
        # self.map_cb = QCheckBox("Show Background Map")
        # self.map_cb.setChecked(self.fcfg["show_backgroundmap"])
        # form.addRow(self.map_cb)
        # self.map_cb.setEnabled(False)

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
        # self.fcfg["show_colorbar"] = self.color_cb.isChecked()
        # self.fcfg["show_backgroundmap"] = self.map_cb.isChecked()

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
        self.project_name.setText(self._generate_default_name())
        self.project_path = QLineEdit()
        self.project_fullpath = QLabel()
        open_button = QPushButton("Path")
        open_button.clicked.connect(self.open_folder)
        self.project_name.textChanged.connect(self.update_fullpath)
        self.project_path.textChanged.connect(self.update_fullpath)

        projfolder_layout = QFormLayout()
        projfolder_layout.addRow("Name:", self.project_name)
        projfolder_layout.addRow(open_button, self.project_path)
        projfolder_layout.addRow("Full Path:", self.project_fullpath)

        folder_group.setLayout(projfolder_layout)

        direction_group = QGroupBox("Flight Azimuth:")
        self.azimuth_label = QLabel(self._format_quadrant_bearing(0))
        self.azimuth_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.azimuth_dial = QDial()
        self.azimuth_dial.setRange(0, 359)
        self.azimuth_dial.setWrapping(True)
        self.azimuth_dial.setNotchesVisible(True)
        self.azimuth_dial.setFixedSize(QSize(140, 140))
        # Qt draws 0° at the bottom by default; shift by 180° so 0° appears at the top.
        self._dial_offset = 180
        self.azimuth_dial.setValue(self._dial_offset)

        self.azimuth_spin = QSpinBox()
        self.azimuth_spin.setRange(0, 359)
        self.azimuth_spin.setWrapping(True)
        self.azimuth_spin.setSuffix("°")
        self.azimuth_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)

        direction_layout = QHBoxLayout()
        direction_layout.addWidget(self.azimuth_label)
        direction_layout.addStretch()

        dial_grid = QGridLayout()
        cardinal_style = "font-weight: bold; color: #d9534f;"
        dial_grid.addWidget(
            QLabel("N", alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
            0,
            1,
        )
        dial_grid.itemAtPosition(0, 1).widget().setStyleSheet(cardinal_style)
        dial_grid.addWidget(
            QLabel("W", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            1,
            0,
        )
        dial_grid.itemAtPosition(1, 0).widget().setStyleSheet(cardinal_style)

        dial_box = QVBoxLayout()
        dial_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dial_box.setContentsMargins(0, 0, 0, 0)
        dial_box.addWidget(self.azimuth_dial, alignment=Qt.AlignmentFlag.AlignCenter)
        south_label = QLabel("S", alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        south_label.setStyleSheet(cardinal_style)
        dial_box.addWidget(south_label, alignment=Qt.AlignmentFlag.AlignCenter)
        dial_container = QWidget()
        dial_container.setLayout(dial_box)
        dial_grid.addWidget(
            dial_container,
            1,
            1,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        dial_grid.addWidget(
            QLabel("E", alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            1,
            2,
        )
        dial_grid.itemAtPosition(1, 2).widget().setStyleSheet(cardinal_style)
        dial_grid.addWidget(
            self.azimuth_spin,
            2,
            1,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        dial_grid.setRowStretch(0, 1)
        dial_grid.setRowStretch(1, 0)
        dial_grid.setRowStretch(2, 1)
        dial_grid.setColumnStretch(0, 1)
        dial_grid.setColumnStretch(1, 0)
        dial_grid.setColumnStretch(2, 1)

        direction_layout.addLayout(dial_grid)
        direction_group.setLayout(direction_layout)

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

        self.azimuth_dial.valueChanged.connect(self._update_azimuth_label)
        self.azimuth_spin.valueChanged.connect(self._update_dial_from_spin)
        self._update_azimuth_label(self.azimuth_dial.value())

    def accept(self):
        logger.debug("CreateProjectDialog accept called")
        if not hasattr(self, "fullpath"):
            QMessageBox.warning(
                self,
                "Project Path Missing",
                "Please select a project folder and name before continuing.",
            )
            return
        self.selection = {"project_path": str(self.fullpath)}

        self.selection["direction"] = self._dial_to_azimuth(self.azimuth_dial.value())
        self.selection["direction_str"] = self._format_quadrant_bearing(
            self.selection["direction"]
        )
        logger.info(f"selection: {self.selection}")
        super().accept()

    def open_folder(self):
        folder_path = browse_directory(self)
        if not folder_path:
            logger.debug("CreateProjectDialog open_folder canceled")
            return
        proj_folder_path = Path(folder_path)
        project_name = self.project_name.text().strip()
        if not project_name:
            project_name = self._generate_default_name(proj_folder_path)
            self.project_name.setText(project_name)
        self.project_path.setText(str(proj_folder_path))
        self.fullpath = proj_folder_path / project_name
        self.project_fullpath.setText(str(self.fullpath))
        logger.debug(f"CreateProjectDialog open_folder called: {self.fullpath}")

    def update_fullpath(self):
        base_path = self.project_path.text().strip()
        project_name = self.project_name.text().strip()
        if not base_path or not project_name:
            self.project_fullpath.clear()
            if hasattr(self, "fullpath"):
                del self.fullpath
            return
        self.fullpath = Path(base_path) / project_name
        self.project_fullpath.setText(str(self.fullpath))

    def _generate_default_name(self, base_path=None):
        """Return Proj_YYYYMMDD, adding a counter if the folder already exists."""
        base_name = datetime.now().strftime("Proj_%Y%m%d")
        if base_path is None:
            return base_name
        candidate = base_name
        counter = 1
        while (Path(base_path) / candidate).exists():
            candidate = f"{base_name}_{counter:02d}"
            counter += 1
        return candidate

    def _dial_to_azimuth(self, dial_value: int) -> int:
        """Convert dial value to azimuth with 0° at the top."""
        return (dial_value + self._dial_offset) % 360

    def _azimuth_to_dial(self, azimuth: int) -> int:
        """Convert azimuth back to dial value honoring the offset."""
        return (azimuth - self._dial_offset) % 360

    def _update_azimuth_label(self, value):
        """Update label to show the current azimuth selection."""
        azimuth = self._dial_to_azimuth(int(value))
        bearing_text = self._format_quadrant_bearing(azimuth)
        try:
            self.azimuth_spin.blockSignals(True)
            self.azimuth_spin.setValue(azimuth)
        finally:
            self.azimuth_spin.blockSignals(False)
        self.azimuth_label.setText(f"{bearing_text}")

    def _update_dial_from_spin(self, value: int):
        """Sync dial when spinbox changes for precise angle entry."""
        dial_value = self._azimuth_to_dial(int(value))
        try:
            self.azimuth_dial.blockSignals(True)
            self.azimuth_dial.setValue(dial_value)
        finally:
            self.azimuth_dial.blockSignals(False)
        self._update_azimuth_label(dial_value)

    def _format_quadrant_bearing(self, angle: int) -> str:
        """Return a quadrant bearing like 'N 30° E' using 45° spans around NESW."""
        angle = angle % 360
        if angle <= 45 or angle > 315:
            offset = angle if angle <= 45 else 360 - angle
            # if offset == 0:
            #     return "N"
            secondary = "E" if angle <= 45 else "W"
            return f"N {offset}° {secondary}"
        if angle <= 135:
            offset = 90 - angle if angle <= 90 else angle - 90
            # if offset == 0:
            #     return "E"
            secondary = "N" if angle < 90 else "S"
            return f"E {offset}° {secondary}"
        if angle <= 225:
            offset = 180 - angle if angle <= 180 else angle - 180
            # if offset == 0:
            #     return "S"
            secondary = "E" if angle < 180 else "W"
            return f"S {offset}° {secondary}"
        offset = 270 - angle if angle <= 270 else angle - 270
        # if offset == 0:
        #     return "W"
        secondary = "S" if angle < 270 else "N"
        return f"W {offset}° {secondary}"


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


def browse_multidirectiorys(
    parent=None,
    initial_dir: str = "",
    caption: str = "Select Directories",
) -> list[str]:
    # Select multiple directories using a non-native QFileDialog.
    start_dir = (
        initial_dir if (initial_dir and os.path.exists(initial_dir)) else os.getcwd()
    )
    try:
        dialog = QFileDialog(parent, caption, start_dir)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)

        for view in dialog.findChildren(QListView):
            view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for view in dialog.findChildren(QTreeView):
            view.setSelectionMode(QAbstractItemView.ExtendedSelection)

        if dialog.exec():
            return dialog.selectedFiles()
        return []
    except Exception as e:
        logger.error(f"browse_multidirectiorys error: {e}")
        return []

