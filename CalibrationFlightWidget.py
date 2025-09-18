import os
from io import StringIO

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from mySettings import config


class CalibrationFlightWidget(QWidget):
    def __init__(self, settings, db, main_window=None):
        super().__init__()
        self.settings = settings
        self.db = db
        self.main_window = main_window

        self.df = pd.DataFrame()
        # 선택한 두 지점을 기억할 리스트
        self._sel_positions = []
        self._selected_lines = []
        self.initUI()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def initUI(self):
        layout = QVBoxLayout()

        # Toolbar
        toolbar = QToolBar(self)
        self.actionOpenCaliFolder = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon),
            "Open Calibration Flight Folder..",
            self,
        )
        self.actionOpenCaliFolder.setStatusTip("Open Calibration Flight Folder")
        self.actionOpenCaliFolder.triggered.connect(self.openCalibrationFlightFolder)
        toolbar.addAction(self.actionOpenCaliFolder)

        self.actionImportCaliFile = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "Open Calibration Flight Folder..",
            self,
        )
        self.actionImportCaliFile.setStatusTip("file Calibration Flight File")
        self.actionImportCaliFile.triggered.connect(self.importCaliFile)
        toolbar.addAction(self.actionImportCaliFile)
        layout.addWidget(toolbar)

        # Main plot widget
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)

        # Scatter + controls
        data_layout = QHBoxLayout()
        data_layout.addWidget(
            self.createScatterPlot(), 0, Qt.AlignmentFlag.AlignHCenter
        )
        data_layout.addWidget(
            self.createDataWidgets(), 0, Qt.AlignmentFlag.AlignHCenter
        )

        dataV_layout = QVBoxLayout()
        dataV_layout.addLayout(data_layout)
        dataV_layout.addWidget(
            self.createCanvasPlot(), 0, Qt.AlignmentFlag.AlignHCenter
        )

        panel = QFrame()
        panel.setLayout(dataV_layout)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel.setLineWidth(2)

        main_layout.addWidget(panel)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        self.actionOpenCaliFolder.setEnabled(False)
        self.actionImportCaliFile.setEnabled(False)

    def actionEnable(self, action=True):
        self.actionOpenCaliFolder.setEnabled(action)
        self.actionImportCaliFile.setEnabled(action)

    def importCaliFile(self):
        logger.debug("importCaliFile")

        # 1) 파일 다이얼로그로 CSV 파일 선택
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV File to Import",
            "",  # 기본 열릴 디렉터리 (빈 문자열이면 마지막 디렉터리)
            "CSV Files (*.csv)",
        )

        # 사용자가 취소 클릭했으면 종료
        if not file_path:
            logger.debug("Import CSV file selection canceled")
            return

        # 2) 선택된 파일을 results 폴더에 복사
        try:
            try:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                rows_buf = StringIO()
                with open(file_path, "r", encoding="utf-8", errors="replace") as fr:
                    for line in fr:
                        parts = line.rstrip("\n").split(",")
                        kept = parts[:6]  # 앞 6개 필드만
                        rows_buf.write(",".join(kept) + "\n")
                rows_buf.seek(0)
                df = pd.read_csv(rows_buf)
                df = df[df["Time"].astype(str).str.endswith(".000")]

                QApplication.restoreOverrideCursor()

                logger.debug(f"Imported CSV from {file_path} (first 5 columns only)")
            except Exception as e:
                logger.error(f"Error importing and truncating CSV: {e}")
                QMessageBox.critical(
                    self, "Import Error", f"Failed to import and truncate CSV:\n{e}"
                )
                return
            self.db.insert_data(df, "imported_cali_file")
            self.df = self.db.get_dataframe("imported_cali_file")
            # 3) 파일 목록 및 플롯 갱신
            self.update_plots(self.df)

        except Exception as e:
            logger.error(f"Failed to import CSV file: {repr(e)}")
            QMessageBox.critical(
                self,
                "Import Error",
                f"An error occurred while importing the file:\n{repr(e)}",
            )

    def openCalibrationFlightFolder(self):
        logger.debug("openCalibrationFlightFolder")
        project_path = config.get("project_path", "")
        if not project_path:
            QMessageBox.warning(self, "ERROR", "Open a project folder first.")
            return
        path = os.path.join(project_path, "Calibration Flight Folder")
        files, _ = QFileDialog.getOpenFileNames(
            parent=self,
            caption="Select Mag data files",
            dir=path,
            filter="Flight data (*.csv);;All files (*)",
        )
        logger.debug(f"Selected files: {files}")

        self.df = self.db.merge_CSVtodf(files)
        self.update_plots(self.df)

    def createScatterPlot(self):
        self.scatter_fig = Figure(figsize=(6, 2), dpi=100)
        self.scatter_ax = self.scatter_fig.add_subplot(111)
        self.scatter_ax.set_title("Total Magnetic Field (Mag)")
        self.scatter_ax.set_xlabel("Index")
        self.scatter_ax.set_ylabel("Mag")
        self.scatter_ax.grid(True)

        self.scatter_canvas = FigureCanvas(self.scatter_fig)
        # 마우스 클릭 이벤트 연결
        self.scatter_canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.scatter_canvas.mpl_connect("button_press_event", self._on_scatter_select)
        return self.scatter_canvas

    def createCanvasPlot(self):
        # Make the figure taller so both plots have room
        self.fig = Figure(figsize=(12, 8), dpi=100)

        # Top plot (row 1 of 2)
        self.ax_mag = self.fig.add_subplot(2, 1, 1)
        self.ax_mag.set_title("Mag Plot")
        # … any default formatting for ax_mag …

        # Bottom plot (row 2 of 2)
        self.ax_speed = self.fig.add_subplot(2, 1, 2)
        self.ax_speed.set_title("Speed Plot")
        # … any default formatting for ax_speed …

        # Create the canvas and return it
        self.canvas = FigureCanvas(self.fig)
        return self.canvas

    def createDataWidgets(self):
        box = QGroupBox("Directional Calibration Data")

        # Use a vertical layout on the group box
        vbox = QVBoxLayout(box)

        # — Apply button —
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.applyCalibrationFlightData)
        vbox.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        # — Cancel button —
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancelCalibrationFlightData)
        vbox.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # — Grid of inputs —
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)  # let the QLineEdits expand

        # Header
        grid.addWidget(
            QLabel("Direction"), 0, 0, alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(QLabel("Value"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(
            QLabel("Reference"), 0, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )

        # Row 1
        self.ew_input = QLineEdit()
        self.cb_ew = QCheckBox()
        grid.addWidget(QLabel("E → W"), 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.ew_input, 1, 1)
        grid.addWidget(self.cb_ew, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        # Row 2
        self.we_input = QLineEdit()
        self.cb_we = QCheckBox()
        grid.addWidget(QLabel("W → E"), 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.we_input, 2, 1)
        grid.addWidget(self.cb_we, 2, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        # Row 3
        self.ns_input = QLineEdit()
        self.cb_ns = QCheckBox()
        grid.addWidget(QLabel("N → S"), 3, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.ns_input, 3, 1)
        grid.addWidget(self.cb_ns, 3, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        # Row 4
        self.sn_input = QLineEdit()
        self.cb_sn = QCheckBox()
        grid.addWidget(QLabel("S → N"), 4, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.sn_input, 4, 1)
        grid.addWidget(self.cb_sn, 4, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        vbox.addLayout(grid)

        # — Enforce single-selection among the four checkboxes —
        btn_group = QButtonGroup(box)
        for cb in (self.cb_ew, self.cb_we, self.cb_ns, self.cb_sn):
            btn_group.addButton(cb)
        btn_group.setExclusive(True)
        self.cb_ew.setChecked(True)  # Set the first checkbox as default

        vbox.addStretch()
        # — Save button —
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.saveCalibrationFlightData)
        vbox.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return box

    def cancelCalibrationFlightData(self):
        self._selected_lines.clear()
        self._sel_positions.clear()
        self.ew_input.setText("")
        self.we_input.setText("")
        self.ns_input.setText("")
        self.sn_input.setText("")
        self.update_plots(self.df)

    def applyCalibrationFlightData(self):
        if not self._selected_lines:
            logger.warning("applyCalibrationFlightData: No lines selected.")
            QMessageBox.warning(
                self,
                "No Selection",
                "Please select one or more flight lines from the plot first.",
            )
            return

        # 각 방향별 평균 자기장 값을 저장할 딕셔너리
        directional_mags = {"E_W": [], "W_E": [], "N_S": [], "S_N": []}

        for line in self._selected_lines:
            start, end = line
            segment_df = self.df.iloc[start : end + 1]

            # mag의 평균값을 구하고 방향을 확인한후 그 값을 ew_input등에 방향에 맞추어 넣는다
            avg_mag = segment_df["Mag"].mean()

            # 방향을 확인
            start_x, end_x = segment_df["X"].iloc[0], segment_df["X"].iloc[-1]
            start_y, end_y = segment_df["Y"].iloc[0], segment_df["Y"].iloc[-1]

            dx = end_x - start_x
            dy = end_y - start_y

            direction = None
            # X축(동서) 변화가 Y축(남북) 변화보다 클 경우
            if abs(dx) > abs(dy):
                if dx > 0:
                    direction = "W_E"  # West to East
                else:
                    direction = "E_W"  # East to West
            # Y축(남북) 변화가 더 클 경우
            else:
                if dy > 0:
                    direction = "S_N"  # South to North
                else:
                    direction = "N_S"  # North to South

            if direction:
                directional_mags[direction].append(avg_mag)
                logger.debug(
                    f"Line ({start}-{end}) is {direction} with avg mag {avg_mag:.2f}"
                )

        # 각 방향별로 계산된 평균값들을 다시 평균내어 입력 필드에 설정
        if directional_mags["E_W"]:
            self.ew_input.setText(
                f"{sum(directional_mags['E_W']) / len(directional_mags['E_W']):.2f}"
            )
        if directional_mags["W_E"]:
            self.we_input.setText(
                f"{sum(directional_mags['W_E']) / len(directional_mags['W_E']):.2f}"
            )
        if directional_mags["N_S"]:
            self.ns_input.setText(
                f"{sum(directional_mags['N_S']) / len(directional_mags['N_S']):.2f}"
            )
        if directional_mags["S_N"]:
            self.sn_input.setText(
                f"{sum(directional_mags['S_N']) / len(directional_mags['S_N']):.2f}"
            )

        QMessageBox.information(
            self,
            "Applied",
            "The average magnetic field values have been calculated and applied to the input fields.",
        )

        # 적용 후 선택 초기화 및 플롯 업데이트

        self._sel_positions.clear()
        self.update_plots(self.df)

    def saveCalibrationFlightData(self):
        # 레퍼런스용 check 박스를 확인하고 그값을 기준으로 차이를 저장
        try:
            values = {
                "E_W": float(self.ew_input.text()),
                "W_E": float(self.we_input.text()),
                "N_S": float(self.ns_input.text()),
                "S_N": float(self.sn_input.text()),
            }
        except ValueError:
            QMessageBox.warning(
                self, "Input Error", "All input values must be valid numbers."
            )
            return

        # Find the reference value from the checked checkbox
        reference_direction = None
        if self.cb_ew.isChecked():
            reference_direction = "E_W"
        elif self.cb_we.isChecked():
            reference_direction = "W_E"
        elif self.cb_ns.isChecked():
            reference_direction = "N_S"
        elif self.cb_sn.isChecked():
            reference_direction = "S_N"

        if not reference_direction:
            QMessageBox.warning(
                self,
                "Reference Not Set",
                "Please select a reference direction by checking one of the boxes.",
            )
            return

        reference_value = values[reference_direction]

        # Calculate differences and store them
        offsets = {
            "offset_E_W": reference_value - values["E_W"],
            "offset_W_E": reference_value - values["W_E"],
            "offset_N_S": reference_value - values["N_S"],
            "offset_S_N": reference_value - values["S_N"],
        }

        QMessageBox.information(
            self,
            "Saved",
            f"Calibration offsets saved with reference '{reference_direction}'.",
        )

        # --- Save to file ---
        file_path = os.path.join(config.get("project_path"), "calibration.txt")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"EW {offsets['offset_E_W']:.2f}\n")
                f.write(f"WE {offsets['offset_W_E']:.2f}\n")
                f.write(f"NS {offsets['offset_N_S']:.2f}\n")
                f.write(f"SN {offsets['offset_S_N']:.2f}\n")
            logger.info(f"Calibration data saved to {file_path}")
        except IOError as e:
            logger.error(f"Failed to save calibration file: {e}")
            QMessageBox.critical(
                self, "File Save Error", f"Could not save calibration file:\n{e}"
            )

    def update_plots(self, df):
        if df is None or df.empty:
            logger.warning("Calibration data is empty. Cannot update plots.")
            return

        # --- Scatter Plot 업데이트 ---
        self.scatter_ax.clear()
        if {"X", "Y", "Mag"}.issubset(df.columns):
            x, y = df["X"], df["Y"]
            self.scatter_ax.scatter(x, y, color="black", s=1, alpha=0.7)
            # 가로축 범위 확대
            x_min, x_max = x.min(), x.max()
            x_margin = x_max - x_min
            self.scatter_ax.set_xlim(x_min - x_margin, x_max + x_margin)
            # y_min, y_max = y.min(), y.max()
            # y_margin = y_max - y_min
            # self.scatter_ax.set_ylim(y_min - y_margin, y_max + y_margin)

            # 오프셋 모드 끄기 → 절대값 그대로 표시
            self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="x")
            self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="y")

            self.scatter_ax.set_title("Flight Path")
            self.scatter_ax.set_xlabel("X (Easting)")
            self.scatter_ax.set_ylabel("Y (Northing)")
            self.scatter_ax.set_aspect("equal", "box")
            self.scatter_ax.grid(True)
        else:
            self.scatter_ax.set_title("X, Y, or Mag data not available")

        palette = plt.get_cmap("tab10").colors
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
                    xy=(xs[-1] + dx, ys[-1] + dy),  # arrowhead just before the real end
                    xytext=(xs[0] + dx, ys[0] + dy),  # tail just after the real start
                    arrowprops=dict(arrowstyle="->", color=color, lw=1.5),
                    zorder=6,
                )

        self.scatter_fig.tight_layout()
        self.scatter_canvas.draw()

        # --- Line Plot 업데이트 ---
        self.ax_mag.clear()
        self.ax_speed.clear()

        # --- Mag Plot ---
        if "Mag" in df.columns:
            self.ax_mag.plot(df.index, df["Mag"], label="Mag", linewidth=0.8)
            self.ax_mag.set_title("Magnetic Field")
            self.ax_mag.set_xlabel("Index")
            self.ax_mag.set_ylabel("Mag Value")
            self.ax_mag.legend()
            self.ax_mag.grid(True)
        else:
            self.ax_mag.set_title("Mag data not available")

        # --- Speed Plot ---
        speed_available = False
        if {"X", "Y", "Counter"}.issubset(df.columns):
            dt = df["Counter"].diff() / 1000.0  # ms to s
            dx = df["X"].diff()
            dy = df["Y"].diff()
            dist = np.sqrt(dx**2 + dy**2)
            speed = dist / dt.replace(0, np.nan)
            df["Speed"] = speed
            speed_available = True

            self.ax_speed.plot(
                df.index, df["Speed"], label="Speed (m/s)", linewidth=0.8
            )
            self.ax_speed.set_title("Flight Speed")
            self.ax_speed.set_xlabel("Index")
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
                idxs = df.index.values[start : end + 1]

                if "Mag" in df.columns:
                    mags = df["Mag"].iloc[start : end + 1].values
                    self.ax_mag.plot(idxs, mags, linewidth=2, c=color, zorder=5)

                if speed_available:
                    speeds = df["Speed"].iloc[start : end + 1].values
                    self.ax_speed.plot(idxs, speeds, linewidth=2, c=color, zorder=5)

        self.fig.tight_layout()
        self.canvas.draw()

    def _on_scatter_select(self, event):
        # 오른쪽 클릭: 즉시 취소
        if event.button == 3:
            # 현재 선택 및 임시 선 제거
            self._sel_positions.clear()
            if hasattr(self, "_temp_line") and self._temp_line:
                self._temp_line.remove()
                self._temp_line = None
            self.update_plots(self.df)
            return

        if event.inaxes is not self.scatter_ax or self.df.empty:
            return

        # 왼쪽 클릭 싱글: 시작점 마킹
        if event.button == 1 and not self._sel_positions:
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
        """첫 점 선택 후 마우스 이동 시 임시 라인(rubber-band) 그리기"""
        if not self._sel_positions or event.inaxes is not self.scatter_ax:
            return
        x0 = self.df["X"].iloc[self._sel_positions[0]]
        y0 = self.df["Y"].iloc[self._sel_positions[0]]
        x1, y1 = event.xdata, event.ydata
        # 이전 임시 라인 제거
        if hasattr(self, "_temp_line") and self._temp_line:
            self._temp_line.remove()
        # 새로운 임시 라인 그리기
        self._temp_line = self.scatter_ax.plot(
            [x0, x1], [y0, y1], "--", color="blue", zorder=4
        )[0]
        self.scatter_ax.figure.canvas.draw_idle()

    @Slot(str)
    def on_project_opened(self, project_path: str):
        pass

    @Slot()
    def on_project_reset(self):
        pass
