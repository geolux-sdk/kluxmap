import os
from io import StringIO
import math
from pathlib import Path
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
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QButtonGroup,
)

from mySettings import config


class CalibrationFlightWidget(QWidget):
    def __init__(self, db, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window

        self.df = pd.DataFrame()
        # 선택한 두 지점을 기억할 리스트
        self._sel_positions = []
        self._selected_lines = []
        self._selected_files = []
        self._temp_line = None
        self._palette = plt.get_cmap("tab10").colors
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

        self.file_list_widget = self.createFileListWidget()
        main_layout.addWidget(self.file_list_widget, 0)
        main_layout.addWidget(panel)
        main_layout.setStretch(0, 0)
        main_layout.setStretch(1, 1)
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
        logger.debug(f"Selected files: {files}")

        if not files:
            return

        self._selected_files = files
        self.updateFileList(files)
        self.df = self.db.merge_CSVtodf(files)
        self.update_plots(self.df)

    def createScatterPlot(self):
        # Slightly enlarge the mag scatter plot (~additional 10% bigger than before)
        self.scatter_fig = Figure(figsize=(7.3, 2.4), dpi=100)
        self.scatter_ax = self.scatter_fig.add_subplot(111)
        self.scatter_ax.set_title("Total Magnetic Field (Mag)")
        self.scatter_ax.set_xlabel("Index")
        self.scatter_ax.set_ylabel("Mag")
        self.scatter_ax.grid(True)

        self.scatter_canvas = FigureCanvas(self.scatter_fig)
        # 마우스 클릭 이벤트 연결
        self.scatter_canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.scatter_canvas.mpl_connect("button_press_event", self._on_scatter_select)
        self.scatter_canvas.mpl_connect("scroll_event", self._on_scroll_zoom)
        return self.scatter_canvas

    def createCanvasPlot(self):
        # Make the figure a bit wider so both plots can fill the space
        self.fig = Figure(figsize=(13.2, 8), dpi=100)

        # Top plot (row 1 of 2)
        self.ax_mag = self.fig.add_subplot(2, 1, 1)
        self.ax_mag.set_title("Mag Plot")
        # … any default formatting for ax_mag …

        # Bottom plot (row 2 of 2)
        self.ax_speed = self.fig.add_subplot(2, 1, 2)
        self.ax_speed.set_title("Speed Plot")
        # … any default formatting for ax_speed …

        # Reduce side margins so plots fill the horizontal space better
        self.fig.subplots_adjust(left=0.07, right=0.98)

        # Create the canvas and return it
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
            QLabel("Main Direction"), 0, 2, alignment=Qt.AlignmentFlag.AlignCenter
        )

        # Row 1 (vertical up/down)
        # Row 1 (vertical up/down) + shared main selector for vertical pair
        self.TD_input = QLineEdit()
        self.main_dir_group = QButtonGroup(box)
        self.main_dir_group.setExclusive(True)

        self.cb_vertical_main = QCheckBox()
        self.cb_vertical_main.setToolTip("Checked: Top → Down is main. Unchecked: Bottom → Up is main.")
        self.main_dir_group.addButton(self.cb_vertical_main)
        grid.addWidget(QLabel("Top → Down"), 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.TD_input, 1, 1)
        grid.addWidget(self.cb_vertical_main, 1, 2, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        # Row 2 (vertical counterpart)
        self.BU_input = QLineEdit()
        grid.addWidget(QLabel("Bottom → Up"), 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.BU_input, 2, 1)

        # Row 3 (horizontal left/right) + shared main selector for horizontal pair
        self.LR_input = QLineEdit()
        self.cb_horizontal_main = QCheckBox()
        self.cb_horizontal_main.setToolTip("Checked: Left → Right is main. Unchecked: Right → Left is main.")
        self.main_dir_group.addButton(self.cb_horizontal_main)
        grid.addWidget(QLabel("Left → Right"), 3, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.LR_input, 3, 1)
        grid.addWidget(self.cb_horizontal_main, 3, 2, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        # Row 4 (horizontal counterpart)
        self.RL_input = QLineEdit()
        grid.addWidget(QLabel("Right → Left"), 4, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.RL_input, 4, 1)

        vbox.addLayout(grid)

        # Default reference direction: vertical (Top → Down). Only one can be checked.
        self.cb_vertical_main.setChecked(True)
        self.cb_horizontal_main.setChecked(False)

        vbox.addStretch()
        # — Save button —
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.saveCalibrationFlightData)
        vbox.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return box

    def createFileListWidget(self):
        box = QGroupBox("Selected Files")
        layout = QVBoxLayout(box)
        self.file_list = QListWidget()
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._showFileContextMenu)
        layout.addWidget(self.file_list)
        box.setMinimumWidth(220)
        box.setFixedWidth(240)
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        return box

    def updateFileList(self, files):
        """Show selected calibration files on the left list."""
        self.file_list.clear()
        self.file_list.addItems([os.path.basename(path) for path in files])

    def _showFileContextMenu(self, pos):
        item = self.file_list.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        remove_action = menu.addAction("Remove")
        chosen = menu.exec(self.file_list.mapToGlobal(pos))
        if chosen == remove_action:
            row = self.file_list.row(item)
            self._confirmAndRemoveFile(row)

    def _confirmAndRemoveFile(self, row):
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
        self.updateFileList(self._selected_files)

        if self._selected_files:
            self.df = self.db.merge_CSVtodf(self._selected_files)
        else:
            self.df = pd.DataFrame()
        self.update_plots(self.df)

    def cancelCalibrationFlightData(self):
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

    def applyCalibrationFlightData(self):
        if not self._selected_lines:
            logger.warning("applyCalibrationFlightData: No lines selected.")
            QMessageBox.warning(
                self,
                "No Selection",
                "Please select one or more flight lines from the plot first.",
            )
            return

        # 각 방향별 평균 자기장 값을 저장할 딕셔너리 (Top-Down / Bottom-Up / Left-Right / Right-Left)
        directional_mags = {"TD": [], "BU": [], "LR": [], "RL": []}
        direction_colors = {"TD": [], "BU": [], "LR": [], "RL": []}

        for idx, line in enumerate(self._selected_lines):
            start, end = line
            segment_df = self.df.iloc[start : end + 1]
            color = self._palette[idx % len(self._palette)]

            # mag의 평균값을 구하고 방향을 확인한후 그 값을 TD_input등에 방향에 맞추어 넣는다
            avg_mag = segment_df["Mag"].mean()

            # 방향을 확인 (북을 기준으로 한 각도와 비교)
            start_x, end_x = segment_df["X"].iloc[0], segment_df["X"].iloc[-1]
            start_y, end_y = segment_df["Y"].iloc[0], segment_df["Y"].iloc[-1]

            dx = end_x - start_x
            dy = end_y - start_y

            # heading_deg: 북을 0°, 시계방향 증가 (atan2(dx, dy) 사용)
            heading_deg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
            main_deg = getattr(self, "_main_direction_degree", 0) or 0
            diff = (heading_deg - main_deg + 360) % 360

            # main 방향을 기준으로 4분면으로 분류
            if diff <= 45 or diff > 315:
                direction = "TD"  # along main direction
            elif diff <= 135:
                direction = "LR"  # 90° clockwise from main
            elif diff <= 225:
                direction = "BU"  # opposite to main
            else:
                direction = "RL"  # 270° from main (counter-clockwise)

            directional_mags[direction].append(avg_mag)
            direction_colors[direction].append(color)
            logger.debug(
                f"Line ({start}-{end}) heading {heading_deg:.1f}°, diff {diff:.1f}° -> {direction} with avg mag {avg_mag:.2f}"
            )

        # 각 방향별로 계산된 평균값들을 다시 평균내어 입력 필드에 설정 + 색상 강조
        self._apply_direction_result("TD", self.TD_input, directional_mags, direction_colors)
        self._apply_direction_result("BU", self.BU_input, directional_mags, direction_colors)
        self._apply_direction_result("LR", self.LR_input, directional_mags, direction_colors)
        self._apply_direction_result("RL", self.RL_input, directional_mags, direction_colors)

        QMessageBox.information(
            self,
            "Applied",
            "The average magnetic field values have been calculated and applied to the input fields.",
        )

        # 적용 후 선택 초기화 및 플롯 업데이트

        self._sel_positions.clear()
        self.update_plots(self.df)

    def saveCalibrationFlightData(self):
        project_path = config.get("project_path")
        if not project_path:
            QMessageBox.warning(
                self, "Project Path Missing", "Open a project folder before saving."
            )
            return
    
        # 레퍼런스용 check 박스를 확인하고 그값을 기준으로 차이를 저장
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
                # New labels (aligned with UI)
                f.write(f"TD {offsets['offset_TD']:.2f}\n")
                f.write(f"BU {offsets['offset_BU']:.2f}\n")
                f.write(f"LR {offsets['offset_LR']:.2f}\n")
                f.write(f"RL {offsets['offset_RL']:.2f}\n")

            logger.info(f"Calibration data saved to {file_path}")
        except IOError as e:
            logger.error(f"Failed to save calibration file: {e}")
            QMessageBox.critical(
                self, "File Save Error", f"Could not save calibration file:\n{e}"
            )

    def update_plots(self, df):
        if df is None or df.empty:
            logger.warning("Calibration data is empty. Cannot update plots.")
            self._temp_line = None
            return

        # 임시 라인 초기화 (Axes가 갱신되면 제거할 수 없으므로 참조만 해제)
        self._temp_line = None

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
                try:
                    self._temp_line.remove()
                except NotImplementedError:
                    pass
                self._temp_line = None
            self.update_plots(self.df)
            return

        if event.inaxes is not self.scatter_ax or self.df.empty:
            return

        # 왼쪽 클릭 싱글: 시작점 마킹
        if event.button == 1 and not self._sel_positions:
            if len(self._selected_lines) >= 4:
                QMessageBox.information(
                    self,
                    "선택 제한",
                    "비행 라인은 최대 4개까지만 선택할 수 있습니다.",
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
        """첫 점 선택 후 마우스 이동 시 임시 라인(rubber-band) 그리기"""
        if not self._sel_positions or event.inaxes is not self.scatter_ax:
            return
        x0 = self.df["X"].iloc[self._sel_positions[0]]
        y0 = self.df["Y"].iloc[self._sel_positions[0]]
        x1, y1 = event.xdata, event.ydata
        # 이전 임시 라인 제거
        if hasattr(self, "_temp_line") and self._temp_line:
            try:
                self._temp_line.remove()
            except NotImplementedError:
                # 이미 축에서 제거된 경우 무시
                pass
            self._temp_line = None
        # 새로운 임시 라인 그리기
        self._temp_line = self.scatter_ax.plot(
            [x0, x1], [y0, y1], "--", color="blue", zorder=4
        )[0]
        self.scatter_ax.figure.canvas.draw_idle()

    def _on_scroll_zoom(self, event):
        """마우스 휠로 스캐터 영역 확대/축소."""
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
        """입력창 배경에 선택된 라인 색상을 반영."""
        if color is None:
            line_edit.setStyleSheet("")
            return
        r, g, b = [int(c * 255) for c in color[:3]]
        alpha = 64  # 0~255 (약 25% 투명)
        line_edit.setStyleSheet(
            f"background-color: rgba({r}, {g}, {b}, {alpha});"
        )

    def _apply_direction_result(self, direction, line_edit, directional_mags, direction_colors):
        """평균값을 입력창에 설정하고 선택 라인 색상으로 배경 표시."""
        if directional_mags[direction]:
            avg = sum(directional_mags[direction]) / len(directional_mags[direction])
            line_edit.setText(f"{avg:.2f}")
            color = direction_colors[direction][0] if direction_colors[direction] else None
            self._set_input_color(line_edit, color)
        else:
            self._set_input_color(line_edit, None)

    @Slot(str)
    def on_project_opened(self, project_path: str):
        logger.debug(f"CalibrationFlightWidget: Project opened at {project_path}")
        self._main_direiion_str = config.get('direction_str', '')
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
        self.updateFileList(self._selected_files)
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
        logger.debug("Saving calibration widget state to config")
        if config.file_path is None:
            return
        # Reload existing config from disk if in-memory store is empty to avoid overwriting other keys.
        if not config.config:
            try:
                config.load()
            except Exception as e:
                logger.warning(f"Failed to reload config before saving calibration state: {e}")
        # file_names = [Path(p).name for p in self._selected_files] if getattr(self, "_selected_files", None) else []
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
        
        self.updateFileList(self._selected_files)
        if self._selected_files:
            self.df = self.db.merge_CSVtodf(self._selected_files)
            self.update_plots(self.df)
