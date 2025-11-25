import os
import shutil

import matplotlib.pyplot as plt
import pandas as pd
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

# 파일 상단에 추가
from PySide6.QtCore import Qt, Slot
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
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import butter, filtfilt

from myResource import resource_path
from mySettings import config
from myWidgets import DataFilterDialog, KrigingPlotDialog_withHead


class LinePlotWidget(QWidget):
    def __init__(self, db, main_window=None):
        super().__init__()
       
        self.db = db
        self.main_window = main_window

        self.selected_df = pd.DataFrame()
        self.scanline_df = {}
        self.scanline_filepaths = {}
        self.scatter_colorbar = None
        self.plot_list = []
        self.selected_col_name = "Mag"
        self.calibration_data = {}

        logger.debug("LinePlotWidget")
        self.initUI()
        logger.debug("MainWIdget end")

    def initUI(self):
        layout = QVBoxLayout()
        # 페이지 전용 툴바
        toolbar = QToolBar()

        self.actionDataConfiDisp = QAction(
            QIcon(resource_path("filter.png")), "Filter", self
        )
        self.actionDataConfiDisp.setStatusTip("Data Filter Settings")
        self.actionDataConfiDisp.triggered.connect(self.openDataFilterDialog)

        self.actionPlotKriging = QAction(
            QIcon(resource_path("griding.png")), "Griding", self
        )
        self.actionPlotKriging.triggered.connect(self.openKrigingDialog)

        # Save를 툴바에 추가하고 LinePlotWidget.saveData로 연결
        self.actionSaveData = QAction(QIcon(resource_path("save.png")), "SAVE", self)
        self.actionSaveData.setStatusTip("Save Proecessed Data")
        self.actionSaveData.triggered.connect(self.saveData)

        toolbar.addAction(self.actionDataConfiDisp)
        toolbar.addAction(self.actionPlotKriging)
        toolbar.addAction(self.actionSaveData)

        layout.addWidget(toolbar)

        # 메인 레이아웃 설정
        vbox_layout = QVBoxLayout()
        vbox_layout.addWidget(
            self.createFileList(), alignment=Qt.AlignmentFlag.AlignLeft
        )
        ctrl_panel = QFrame()
        ctrl_panel.setLineWidth(3)
        ctrl_panel.setLayout(vbox_layout)

        data_layout = QHBoxLayout()
        data_layout.addWidget(
            self.createTableWidget(),
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        # 스캐터 플롯과 컨트롤(체크박스)을 담을 컨테이너 위젯 생성
        scatter_container = QWidget()
        scatter_vbox = QVBoxLayout(scatter_container)
        scatter_vbox.setContentsMargins(0, 0, 0, 0)

        # "COLORBAR" 체크박스를 생성하고 레이아웃의 오른쪽에 추가
        self.scatter_colorbar_cb = QCheckBox("COLOR BAR")
        self.scatter_colorbar_cb.stateChanged.connect(self.update_scatterplot)
        scatter_vbox.addWidget(
            self.scatter_colorbar_cb, alignment=Qt.AlignmentFlag.AlignRight
        )
        scatter_vbox.addWidget(
            self.createScatterPlot()
        )  # 체크박스 아래에 스캐터 플롯 추가

        data_layout.addWidget(scatter_container)

        dataV_layout = QVBoxLayout()
        dataV_layout.addLayout(data_layout)
        dataV_layout.addWidget(
            self.createCanvasPlot(), alignment=Qt.AlignmentFlag.AlignHCenter
        )

        data_panel = QFrame()
        data_panel.setLayout(dataV_layout)
        data_panel.setLineWidth(3)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.addWidget(ctrl_panel)
        main_layout.addWidget(data_panel)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        self.actionDataConfiDisp.setEnabled(False)
        self.actionPlotKriging.setEnabled(False)
        self.actionSaveData.setEnabled(False)

    def actionEnable(self, action=True):
        self.actionDataConfiDisp.setEnabled(action)
        self.actionPlotKriging.setEnabled(action)
        self.actionSaveData.setEnabled(action)

    def openDataFilterDialog(self):
        DataFilterDialog(self).exec()

    def createScatterPlot(self):
        self.scatter_fig, self.scatter_ax = plt.subplots(figsize=(6, 2), dpi=100)
        self.scatter_ax.set_title("Mag Value (Sensor_Total)")
        self.scatter_ax.set_xlabel("Index")
        self.scatter_ax.set_ylabel("Sensor_Total")
        self.scatter_ax.grid(True)
        self.scatter_canvas = FigureCanvas(self.scatter_fig)
        return self.scatter_canvas

    def createCanvasPlot(self):
        self.fig, self.ax = plt.subplots(figsize=(12, 2), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        return self.canvas

    def createFileList(self):
        logger.debug("createFileList")
        """파일 목록을 보여주는 리스트 위젯을 생성하는 메서드"""
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

    def createTableWidget(self):
        self.tableWidget = QTableWidget()
        self.tableWidget.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectColumns  # ← 행 단위에서 셀 단위로 변경
        )
        self.tableWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tableWidget.setMinimumSize(500, 500)
        self.tableWidget.cellClicked.connect(self.on_table_cell_clicked)

        self.tableWidget.horizontalHeader().sectionClicked.connect(
            self.on_header_clicked
        )

        header = self.tableWidget.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.on_header_right_click)

        return self.tableWidget

    def on_header_right_click(self, pos):  # pos: QPoint (헤더 기준 좌표)
        header = self.tableWidget.horizontalHeader()
        logical_index = header.logicalIndexAt(pos)
        if logical_index < 0:
            return

        logger.debug(f"Header RIGHT click: {logical_index}")
        if logical_index not in self.plot_list:
            self.plot_list.append(logical_index)
        else:
            if len(self.plot_list) > 1:
                self.plot_list.remove(logical_index)
        logger.debug(f"on_header_clicked {logical_index} {self.plot_list}")
        self.plot_column_by_index(self.plot_list)

    def calculate_directional_avg_from_df(self):
        logger.debug("calculate_directional_avg_from_df")
        """
        로드된 DataFrame 딕셔너리에서 방향별 평균 계산

        Parameters:
            scanline_df (dict[str, pd.DataFrame]): key=이름, value=DataFrame

        Returns:
            tuple: (ns_avg, sn_avg, diff)
        """

        cali = config.get(
            "cali_filter",
            {
                "enabled": False,
                "offset_E_W": 0.0,
                "offset_W_E": 0.0,
                "offset_N_S": 0.0,
                "offset_S_N": 0.0,
            },
        )

        if not self.scanline_df:
            logger.warning("No scanline data to calculate calibration.")
            # 안전 기본값으로 저장 후 리턴
            config.set_subvalue("filters_line", "cali_filter", cali)
            return None, None, None

        # candidate_fields = ["Sensor_X", "Sensor_Y", "Sensor_Z", "Mag"]
        candidate_fields = ["Mag"]
        result_diff = {}
        ns_avg = sn_avg = diff = None  # ← 미리 정의해 UnboundLocalError 방지

        for field in candidate_fields:
            ns_sum = ns_count = 0
            sn_sum = sn_count = 0
            for name, df in self.scanline_df.items():
                if df.empty:
                    continue

                if field not in df.columns:  # 필드가 없으면 건너뛰기
                    continue

                mag_avg = float(df[field].mean())

                # Y 증가 → S_N, Y 감소 → N_S
                if df["Y"].iloc[-1] > df["Y"].iloc[0]:
                    sn_sum += mag_avg
                    sn_count += 1
                else:
                    ns_sum += mag_avg
                    ns_count += 1

            # 각 필드별 평균 차이 계산
            if ns_count > 0 and sn_count > 0:
                ns_avg = ns_sum / ns_count
                sn_avg = sn_sum / sn_count
                diff = round(ns_avg - sn_avg, 2)
                result_diff[field] = diff
            else:
                logger.debug(f"Field {field} skipped (not enough data)")

        cali["offset_S_N"] = result_diff["Mag"]
        cali["offset_N_S"] = 0.0
        cali["offset_E_W"] = 0.0
        cali["offset_W_E"] = 0.0

        # if "Sensor_X" in result_diff:
        #     self.calibration_data["offset_Sensor_X"] = result_diff["Sensor_X"]
        #     self.calibration_data["offset_Sensor_Y"] = result_diff["Sensor_Y"]
        #     self.calibration_data["offset_Sensor_Z"] = result_diff["Sensor_Z"]

        config.set_subvalue("filters_line", "cali_filter", cali)
        logger.debug(f"save calibration data {self.calibration_data}")
        return ns_avg, sn_avg, diff

    def updateFileList(self, file_paths):
        logger.debug("updateFileList")
        """선택된 폴더의 파일 목록을 리스트 위젯에 업데이트"""
        self.fileListWidget.clear()
        self.scanline_df.clear()
        self.scanline_filepaths.clear()

        if file_paths:
            for file_path in file_paths:
                base = os.path.basename(file_path)  # 파일명만 추출
                name_wo_ext = os.path.splitext(base)[0]  # 확장자 제거
                item = QListWidgetItem(name_wo_ext)
                self.fileListWidget.addItem(item)
                logger.debug(f"list update {file_path}")
                df = pd.read_csv(file_path)
                self.scanline_df[name_wo_ext] = df
                self.scanline_filepaths[name_wo_ext] = file_path

        # 🔵 첫 번째 항목 자동 선택 및 로드
        if self.fileListWidget.count() > 0:
            first_item = self.fileListWidget.item(0)
            first_item.setSelected(True)
            self.fileListWidget.setFocus()
            self.selected_col_name = "Mag"
            self.on_item_clicked(first_item)
            self.first_item = first_item

    def update_scatterplot(self):
        logger.debug("update_scatterplot")
        self.scatter_fig.clear()  # 전체 Figure를 클리어하여 레이아웃 문제를 근본적으로 해결
        self.scatter_ax = self.scatter_fig.add_subplot(111)  # 서브플롯을 다시 추가

        if not self.scanline_df:
            self.scatter_ax.set_title("No Scanline Data")

        val_col = self.selected_col_name
        if self.scatter_colorbar_cb.isChecked():
            if self.selected_col_name not in [
                "Mag",
                "Mag_median",
                "Mag_lowpass",
                "Mag_calibrated",
            ]:
                val_col = "Mag"

            # --- COLORBAR MODE ---
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
                self.scatter_colorbar.ax.ticklabel_format(
                    useOffset=False, style="plain"
                )
        else:
            for idx, (key, df) in enumerate(self.scanline_df.items()):
                if "X" in df.columns and "Y" in df.columns:
                    # 라인 그리기
                    self.scatter_ax.plot(df["X"], df["Y"], color="blue", linewidth=1)

                    # 시작점 좌표
                    start_x, start_y = df["X"].iloc[0], df["Y"].iloc[0]

                    # 시작점 옆에 scanline_df의 key 표시
                    self.scatter_ax.annotate(
                        str(key),  # 딕셔너리 key를 텍스트로
                        (start_x, start_y),  # 시작점 좌표
                        textcoords="offset points",
                        xytext=(1, 1),  # 점에서 약간 오른쪽 위
                        fontsize=7,
                        color="black",
                    )

        # Plot the selected scanline on top, in red
        if not self.selected_df.empty and "X" in self.selected_df.columns:
            x, y = (
                self.selected_df["X"],
                self.selected_df["Y"],
            )
            self.scatter_ax.scatter(x, y, color="black", s=3)

            # 라인 중간 지점 옆에 방향을 나타내는 화살표와 텍스트를 그립니다.
            if len(self.selected_df) >= 2:
                # 1. 스캔라인의 시작과 끝 Y좌표를 비교하여 남-북 방향을 결정합니다.
                y_start = self.selected_df["Y"].iloc[0]
                y_end = self.selected_df["Y"].iloc[-1]

                # 2. 라인의 중간 지점 좌표를 찾습니다.
                mid_idx = len(self.selected_df) // 2
                start_x = self.selected_df["X"].iloc[mid_idx]
                start_y = self.selected_df["Y"].iloc[mid_idx]
                if y_end > y_start:
                    end_y = start_y + 5
                else:
                    end_y = start_y - 5

                # 3. 중간 지점 옆에 방향 텍스트와 화살표를 그립니다.
                self.scatter_ax.annotate(
                    "",
                    xy=(start_x + 5, end_y + 5),  # 화살표가 가리키는 지점
                    xytext=(start_x + 5, start_y + 5),  # 텍스트 위치 오프셋 (픽셀 단위)
                    arrowprops=dict(
                        arrowstyle="->",
                        color="green",
                        lw=3,
                    ),
                    zorder=6,
                )
        # 오프셋 모드 끄기 → 절대값 그대로 표시
        self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="x")
        self.scatter_ax.ticklabel_format(useOffset=False, style="plain", axis="y")

        self.scatter_ax.set_title(f"{val_col}")
        self.scatter_ax.set_xlabel("X (Easting)")
        self.scatter_ax.set_ylabel("Y (Northing)")
        self.scatter_ax.set_aspect("equal", "box")
        self.scatter_ax.grid(True)
        self.scatter_fig.tight_layout()
        self.scatter_canvas.draw()

    def on_item_clicked(self, item):
        name = item.text()
        df = self.scanline_df.get(name, pd.DataFrame())
        self.selected_df = df
        self.populate_table(df)

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
                item = QTableWidgetItem(str(value))
                self.tableWidget.setItem(i, j, item)

    def on_table_cell_clicked(self, row, column_index):
        logger.debug(f"on_table_cell_clicked {row} {column_index}")
        self.on_header_clicked(column_index)

    def on_header_clicked(self, column_index):
        logger.debug(f"on_header_clicked {column_index}")
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
        # self.ax.set_title(f"Plot of '{col_name}'")
        self.ax.set_xlabel("Index")
        self.ax.set_ylabel(col_name)
        self.ax.grid(True)
        self.fig.tight_layout()
        self.canvas.draw()

    def show_file_list_context_menu(self, position):
        item = self.fileListWidget.itemAt(position)
        if not item:
            return

        menu = QMenu()
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.fileListWidget.mapToGlobal(position))

        if action == delete_action:
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
        For each scanline DataFrame in self.scanline_df, read the 'Mag' column,
        apply the enabled filters, and write the outputs to new columns.
        """
        # 현재 선택된 항목을 기억하여 필터링 후 뷰를 업데이트합니다.
        current_item = self.fileListWidget.currentItem()
        if not current_item:
            # 선택된 항목이 없으면 첫 번째 항목을 사용합니다.
            if self.fileListWidget.count() > 0:
                current_item = self.fileListWidget.item(0)
            else:
                logger.warning("Filtering called, but no items to process.")
                return

        logger.debug(f"LinePlotWidget filtering {settings}")

        # 일보정 ---------------------
        diurnal_cfg = settings.get("Diurnal_Correction", {})
        if diurnal_cfg.get("enabled", False):
            csv_files = diurnal_cfg.get("files", [])
            diurnal_df = pd.DataFrame()

            if not csv_files:
                diurnal_df = pd.DataFrame()  # 빈 DataFrame
            else:
                df_list = []
                for csv_file in csv_files:
                    try:
                        df = pd.read_csv(csv_file)
                        df_list.append(df)
                        logger.debug(f"Loaded {csv_file}")
                    except Exception as e:
                        logger.error(f"Error loading {csv_file}: {e}")

                diurnal_df = (
                    pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
                )
        else:
            diurnal_df = pd.DataFrame()

        for key, df in self.scanline_df.items():
            # 필터링을 다시 적용하기 전에 이전에 생성된 필터 컬럼들을 삭제합니다.
            cols_to_drop = [
                "Mag_diurnal",
                "Mag_median",
                "Mag_lowpass",
                "Mag_calibrated",
            ]
            df.drop(columns=cols_to_drop, inplace=True, errors="ignore")

            # ensure we don’t overwrite original
            filtered_mag = df["Mag"].astype(float)

            # 일보정 ---------------------
            try:
                if diurnal_cfg.get("enabled", False) and not diurnal_df.empty:
                    reference_value = diurnal_df["Mag"][0].astype(float)
                    # df 와 diurnal_df 를 Date + Time 기준으로 merge
                    merged = pd.merge(
                        df,
                        diurnal_df[["Date", "Time", "Mag"]],
                        on=["Date", "Time"],
                        how="left",
                        suffixes=("", "_diurnal"),
                    )

                    # filter_mag - diurnal_mag
                    merged["Mag_corrected"] = (
                        merged["Mag"].astype(float)
                        - merged["Mag_diurnal"].astype(float)
                        + reference_value
                    )

                    df["Diurnal"] = merged["Mag_diurnal"]

                    # filtered_mag 업데이트
                    filtered_mag = merged["Mag_corrected"]
                    df["Mag_diurnal"] = filtered_mag

            except Exception as err:
                logger.error(f"Median filter failed for {key}: {err}")
                QMessageBox.warning(
                    self,
                    "Filter Error",
                    f"Median filter failed for scanline '{key}':\n{err}",
                )

            # --- Median filter ---
            try:
                med_cfg = settings.get("median_filter", {})
                if med_cfg.get("enabled", False):
                    ksize = med_cfg.get("kernel_size", 3)
                    df["Mag_median"] = filtered_mag.rolling(
                        window=ksize, center=True, min_periods=1
                    ).median()
                    logger.debug(f"{key}: applied Median (ksize={ksize})")
                    filtered_mag = df["Mag_median"]
            except Exception as err:
                logger.error(f"Median filter failed for {key}: {err}")
                QMessageBox.warning(
                    self,
                    "Filter Error",
                    f"Median filter failed for scanline '{key}':\n{err}",
                )

            # --- Low-pass filter ---
            try:
                low_cfg = settings.get("lowpass_filter", {})
                if low_cfg.get("enabled", False):
                    cutoff = low_cfg.get("cutoff_freq", 0.1)
                    b, a = self._butter_coeffs(cutoff, 1, order=4, btype="low")
                    df["Mag_lowpass"] = filtfilt(b, a, filtered_mag.values)
                    logger.debug(f"{key}: applied Low-pass (cutoff={cutoff} Hz)")
                    filtered_mag = df["Mag_lowpass"]
            except Exception as err:
                logger.error(f"Low-pass filter failed for {key}: {err}")
                QMessageBox.warning(
                    self,
                    "Filter Error",
                    f"Low-pass filter failed for scanline '{key}':\n{err}",
                )

            # --- Calibration filter ---
            cal_cfg = settings.get("cali_filter", {})

            if cal_cfg.get("enabled", False):
                # 1. 스캔라인의 방향 결정
                start_x, end_x = df["X"].iloc[0], df["X"].iloc[-1]
                start_y, end_y = df["Y"].iloc[0], df["Y"].iloc[-1]
                dx = end_x - start_x
                dy = end_y - start_y

                direction = None
                if abs(dx) > abs(dy):
                    direction = "W_E" if dx > 0 else "E_W"
                else:
                    direction = "S_N" if dy > 0 else "N_S"

                # 2. 해당 방향의 오프셋 값 가져오기

                offset_key = f"offset_{direction}"
                offset = cal_cfg.get(offset_key, 0.0)

                # 3. 오프셋을 빼서 값을 보정하고 새 컬럼에 저장
                df["Mag_calibrated"] = filtered_mag + offset
                logger.debug(
                    f"{key}: applied Calibration (dir={direction}, offset={offset:.2f})"
                )

                # if "Sensor_X" in df.columns:
                #     if direction == "S_N":
                #         logger.debug(f"Make Cali_Sensor Data {self.calibration_data}")
                #         df["Cal_Sensor_X"] = (
                #             df["Sensor_X"] + self.calibration_data["offset_Sensor_X"]
                #         )
                #         df["Cal_Sensor_Y"] = (
                #             df["Sensor_Y"] + self.calibration_data["offset_Sensor_Y"]
                #         )
                #         df["Cal_Sensor_Z"] = (
                #             df["Sensor_Z"] + self.calibration_data["offset_Sensor_Z"]
                #         )
                #     else:
                #         df["Cal_Sensor_X"] = df["Sensor_X"]
                #         df["Cal_Sensor_Y"] = df["Sensor_Y"]
                #         df["Cal_Sensor_Z"] = df["Sensor_Z"]

        # 필터링이 적용된 후, 이전에 선택된 항목의 뷰를 새로고침합니다.
        self.on_item_clicked(current_item)
        return

    def openKrigingDialog(self):
        column_index = self.tableWidget.currentColumn()
        col_name = self.selected_df.columns[column_index]
        dlg = KrigingPlotDialog_withHead(
            self.main_window,
            self.scanline_df,
            col_name,
        )
        dlg.setParent(self.main_window)
        dlg.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        self._open_kriging_dialogs = getattr(self, "_open_kriging_dialogs", [])
        self._open_kriging_dialogs.append(dlg)

    def saveData(self):
        """
        처리된 스캔라인 데이터를 저장합니다.
        1. 각 스캔라인을 개별 CSV 파일로 덮어씁니다.
        2. 모든 스캔라인을 병합하여 하나의 CSV 파일로 저장합니다.
        """
        if not self.scanline_df:
            QMessageBox.warning(self, "No Data", "There is no data to save.")
            return

        # 1. 각 스캔라인을 개별 파일로 저장
        for key, df in self.scanline_df.items():
            try:
                df.to_csv(self.scanline_filepaths[key], index=False)
                logger.debug(f"Saved individual file: {self.scanline_filepaths[key]}")
            except Exception as e:
                logger.error(f"Failed to save individual file for {key}: {e}")
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Could not save file for scanline '{key}':\n{e}",
                )
                return  # 개별 파일 저장 실패 시 중단

        # 2. 모든 스캔라인을 하나의 파일로 병합하여 저장
        try:
            # 모든 데이터프레임 병합
            all_dfs = list(self.scanline_df.values())
            combined_df = pd.concat(all_dfs, ignore_index=True)

            # 저장 경로 결정
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

            # 병합 파일 저장 위치: .processed 폴더 안
            output_path = os.path.join(results_dir, "combined_processed_scanlines.csv")

            # 병합된 데이터프레임 저장
            combined_df.to_csv(output_path, index=False)
            logger.info(f"Saved combined file to: {output_path}")

            QMessageBox.information(
                self,
                "Save Complete",
                f"Individual and combined scanline files were saved successfully.\n\nCombined file location:\n{output_path}",
            )

        except Exception as e:
            logger.error(f"Failed to save combined file: {e}")
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
        logger.debug("initialize")
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
                    logger.debug(
                        f"Removed existing scanlines directory: {outfolder_path}"
                    )

                # ScanLineFiles = self.db.save_all_continuous_record_groups(
                #     outfolder_path, "1Hz"
                # )
                ScanLineFiles = self.db.merge_and_save_scanlines_by_direction(
                    outfolder_path
                )
                self.updateFileList(ScanLineFiles)
                QApplication.restoreOverrideCursor()
            else:
                self.updateFileList(existing_files)
            return
        else:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            # ScanLineFiles = self.db.save_all_continuous_record_groups(outfolder_path, "1Hz")
            ScanLineFiles = self.db.merge_and_save_scanlines_by_direction(
                outfolder_path
            )
            self.updateFileList(ScanLineFiles)
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
