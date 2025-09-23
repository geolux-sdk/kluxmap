import os

import matplotlib.pyplot as plt
import numpy as np
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

# 파일 상단에 추가
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from myResource import resource_path
from mySettings import config
from myWidgets import ColorbarRangeDialog, DataSettingsDialog, OrthogonalPolygonDrawer


class FlightPlotWidget(QWidget):

    def __init__(self, settings, db, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.settings = settings
        self.db = db

        self._selected_lines = []

        self._is_panning = False
        self._last_mouse_pos = None

        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        # Toolbar
        toolbar = QToolBar(self)

        self.actionOpenFileBrower = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon),
            "&Open File Browser",
            self,
        )
        self.actionOpenFileBrower.setStatusTip("Open Project Browser")

        self.actionDataConfiDisp = QAction(
            QIcon(resource_path("filter.png")), "Trim Filters", self
        )
        self.actionDataConfiDisp.setStatusTip("Trim Filters Settings")

        toolbar.addAction(self.actionOpenFileBrower)
        toolbar.addAction(self.actionDataConfiDisp)

        # 레이아웃에 툴바와 실제 콘텐츠(MainWidget)를 추가
        layout.addWidget(toolbar)

        # 메인 레이아웃 설정
        vbox_layout = QVBoxLayout()
        # vbox_layout.addWidget(
        #     self.createProjectLabel(), alignment=Qt.AlignmentFlag.AlignLeft
        # )
        vbox_layout.addWidget(
            self.createFileList(), alignment=Qt.AlignmentFlag.AlignLeft
        )
        vbox_layout.addWidget(
            self.createLogoLabel(), alignment=Qt.AlignmentFlag.AlignHCenter
        )

        ctrl_panel = QFrame()
        ctrl_panel.setLineWidth(3)
        ctrl_panel.setLayout(vbox_layout)
        ctrl_panel.setMaximumWidth(300)
        # ctrl_panel.setFrameShape(QFrame.Shape.StyledPanel)

        canvas_layout = QHBoxLayout()

        # canvas_layout.addWidget(
        #     self.createCanvasPlot(), alignment=Qt.AlignmentFlag.AlignHCenter
        # )
        canvas_layout.addWidget(self.createCanvasPlot(), 1)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.addWidget(ctrl_panel)
        main_layout.addLayout(canvas_layout)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        self.polygonDrawer = OrthogonalPolygonDrawer(self.ax)
        self.polygonDrawer.polygonFinished.connect(self.modify)

        # 초기 비활성화
        self.actionOpenFileBrower.setEnabled(False)
        self.actionDataConfiDisp.setEnabled(False)

        self.connectSingnal()

    def connectSingnal(self):
        self.actionOpenFileBrower.triggered.connect(self.openFIleBrowser)
        self.actionDataConfiDisp.triggered.connect(
            lambda checked=False: DataSettingsDialog(parent=self).exec()
        )

    def actionEnable(self, action=True):
        self.actionOpenFileBrower.setEnabled(action)
        self.actionDataConfiDisp.setEnabled(action)

    def createProjectLabel(self):
        # "프로젝트:" 텍스트를 위한 QLabel
        lbl_project_text = QLabel("Project:")
        lbl_project_text.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        # 폴더 경로를 표시하는 QLabel
        self.lbl_folder_path = QLabel("")
        self.lbl_folder_path.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        # self.lbl_folder_path.setMinimumWidth(200)
        # self.lbl_folder_path.setMaximumWidth(300)

        # QLabel들을 레이아웃에 배치
        layout = QHBoxLayout()
        layout.addWidget(lbl_project_text)
        layout.addWidget(self.lbl_folder_path)

        # 위젯에 레이아웃 설정
        widget = QWidget()
        widget.setLayout(layout)

        return widget

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
        """파일 목록을 보여주는 리스트 위젯을 생성하는 메서드"""
        self.fileListWidget = QListWidget()
        self.fileListWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        self.fileListWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fileListWidget.setMaximumWidth(200)
        self.fileListWidget.itemClicked.connect(self.on_item_clicked)
        self.fileListWidget.customContextMenuRequested.connect(
            self.show_file_list_context_menu
        )
        return self.fileListWidget

    def createCanvasPlot(self):
        """Create a canvas plot using matplotlib"""
        # matplotlib plot 설정
        self.fig, self.ax = plt.subplots(figsize=(10, 8), dpi=100)

        self.ax.set_title("Mag Plot")
        self.ax.set_xlabel("Easting (m)")
        self.ax.set_ylabel("Northing (m)")
        self.ax.grid(True)
        self.ax.set_aspect("equal")

        plt.tight_layout(pad=1.0, w_pad=1.5, h_pad=1)
        # matplotlib canvas를 PyQt6 위젯으로 변환하여 반환
        self.canvas = FigureCanvas(self.fig)

        self.canvas.mpl_connect("scroll_event", self.scroll)
        self.canvas.mpl_connect("button_press_event", self.on_press)
        self.canvas.mpl_connect("button_release_event", self.on_release)
        self.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.canvas.mpl_connect("resize_event", self.on_resize)
        return self.canvas

    def on_resize(self, event):
        # self.updatePlot()
        self._fit_bounds_to_canvas_equal(margin_ratio=0.05)

    def on_press(self, event):
        if event.button == 1 and event.inaxes == self.ax:
            self._is_panning = True
            self._last_mouse_pos = (event.xdata, event.ydata)
        self.on_canvas_click(event)

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
        logger.debug(f"Item clicked: {file_name}")
        self.updatePlot()

    def clac_XYlimit_listAll(self):
        all_x, all_y = [], []
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

    def updatePlot(self):
        logger.debug("updatePlot")
        cfg = config.get("filters")

        try:
            # --- 1) 선택된 파일 목록 확보 ---
            selected = [item.text() for item in self.fileListWidget.selectedItems()]
            if not selected:
                self.ax.clear()
                self.ax.set_title("No files selected  to plot.")
                self.ax.set_xticks([])
                self.ax.set_yticks([])
                self.canvas.draw()
                return

            # --- 2) 파일별 X, Y, 값 추출 ---
            all_x, all_y, all_vals = [], [], []
            file_data_list = []
            self.db.clear_combined_df()
            for filename in selected:
                df = self.db.get_filtered_data(self.db.get_FlightData(filename), cfg)
                if df is None or df.empty:
                    continue
                self.db.put_combined_df(df)

                xdata, ydata, vals = self.db.get_XYMagData(df)

                if len(xdata) == 0:
                    continue
                file_data_list.append((filename, xdata, ydata, vals))
                all_x.extend(xdata)
                all_y.extend(ydata)
                all_vals.extend(vals)

            if len(all_x) == 0:
                self.ax.clear()
                self.ax.set_title("No data to plot.")
                self.ax.set_xticks([])
                self.ax.set_yticks([])
                self.canvas.draw()
                return

            # # --- 3) 전체 경계 계산 ---
            # minx, maxx = np.min(all_x), np.max(all_x)
            # miny, maxy = np.min(all_y), np.max(all_y)
            # pad = 100
            vmin = np.min(all_vals)
            vmax = np.max(all_vals)
            self.values_colorbar = (vmin, vmax)

            self.ax.clear()
            minx, maxx, miny, maxy = self.clac_XYlimit_listAll()
            self.ax.set_xlim(minx, maxx)
            self.ax.set_ylim(miny, maxy)

            # # --- 5) 컬러맵 설정 ---
            show_cb = cfg.get("show_colorbar", False)

            # --- 6) 산점도 표시 ---
            for idx, (fname, x, y, vals) in enumerate(file_data_list):
                if show_cb:
                    cmap = plt.cm.get_cmap("jet")
                    norm = plt.Normalize(vmin=vmin, vmax=vmax)

                    self.ax.scatter(
                        x,
                        y,
                        c=vals,
                        cmap=cmap,
                        norm=norm,
                        s=1,
                        alpha=0.8,
                        zorder=5,
                    )
                else:
                    palette = plt.get_cmap("tab10").colors

                    color = palette[idx % len(palette)]
                    self.ax.scatter(
                        x,
                        y,
                        color=color,
                        s=1,
                        alpha=0.8,
                        zorder=5,
                        label=fname,
                    )

            # --- 7) 컬러바 표시 여부 ---
            if show_cb:
                if not hasattr(self, "sm"):
                    self.sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
                    self.sm.set_clim(vmin, vmax)
                    self.sm.set_array(all_vals)
                    self.colorbar = self.fig.colorbar(
                        self.sm,
                        ax=self.ax,
                        label="Value",
                        shrink=0.5,
                        pad=0.04,
                        fraction=0.05,
                    )
                else:
                    self.sm.set_clim(vmin, vmax)
                    self.sm.set_array(all_vals)
                    self.colorbar.update_normal(self.sm)
                    self.colorbar.ax.ticklabel_format(useOffset=False, style="plain")
            else:
                if hasattr(self, "colorbar"):
                    self.colorbar.remove()
                    del self.colorbar
                if hasattr(self, "sm"):
                    del self.sm
            # ployline
            if self._selected_lines:
                for i, line in enumerate(self._selected_lines):
                    start, end = line
                    color = palette[i % len(palette)]
                    xs = self.df["X"].iloc[start : end + 1].values
                    ys = self.df["Y"].iloc[start : end + 1].values
                    self.ax.plot(xs, ys, linewidth=3, c="black", zorder=5)

            # 오프셋 모드 끄기 → 절대값 그대로 표시
            self.ax.ticklabel_format(useOffset=False, style="plain", axis="x")
            self.ax.ticklabel_format(useOffset=False, style="plain", axis="y")

            # --- 8) 스타일 ---
            self.ax.set_title("Mag Plot")
            self.ax.set_xlabel("Easting (m)")
            self.ax.set_ylabel("Northing (m)")
            self.ax.grid(True)
            self.ax.set_aspect("equal")

        except Exception as err:
            logger.error(f"Update Plot : {repr(err)}")

        # self._fit_bounds_to_canvas_equal(margin_ratio=0.05)
        self.fig.tight_layout()
        self.canvas.draw()

    def _fit_bounds_to_canvas_equal(self, margin_ratio=0.05):
        logger.debug("_fit_bounds_to_canvas_equal")
        """aspect=equal(1:1) 유지하면서 캔버스 비율에 맞게 x/y 범위를 확장해 꽉 채우기."""
        ax = self.ax
        # 현재 데이터 경계
        x1, x2 = ax.get_xlim()
        y1, y2 = ax.get_ylim()

        # 데이터 범위 계산
        rx = max(x2 - x1, 1e-12)
        ry = max(y2 - y1, 1e-12)

        # # 5% 여백 적용 (이미 여백을 넣어 설정했다면 생략 가능)
        cx = (x1 + x2) * 0.5
        cy = (y1 + y2) * 0.5

        # 캔버스 픽셀 비율
        w, h = self.canvas.get_width_height()
        if h <= 0:
            h = 1
        canvas_ratio = w / h  # (가로/세로)

        # aspect=equal(1:1)을 유지하려면 데이터의 (rx/ry)도 canvas_ratio로 맞춰야 함
        data_ratio = rx / ry
        if data_ratio < canvas_ratio:
            # 가로가 부족 → rx를 늘림
            rx = canvas_ratio * ry
        else:
            # 세로가 부족 → ry를 늘림
            ry = rx / canvas_ratio

        # 새 경계 설정(센터 고정)
        new_x1, new_x2 = cx - rx * 0.5, cx + rx * 0.5
        new_y1, new_y2 = cy - ry * 0.5, cy + ry * 0.5

        ax.set_xlim(new_x1, new_x2)
        ax.set_ylim(new_y1, new_y2)
        logger.debug(
            f"new_x1: {new_x1}, new_x2: {new_x2}, new_y1: {new_y1}, new_y2: {new_y2}"
        )
        self.ax.set_aspect("equal")
        self.canvas.draw_idle()

    def updateFileList(self, files):
        """선택된 폴더의 파일 목록을 리스트 위젯에 업데이트"""
        self.fileListWidget.clear()

        for file_name in files:
            basename = os.path.basename(file_name)
            item = QListWidgetItem(basename)
            self.fileListWidget.addItem(item)
            item.setSelected(True)
            self.fileListWidget.setFocus()

        self.db.clear_FlightData()
        for file_name in files:
            self.db.load_FlightData(file_name)
        self.updatePlot()

    def modify(self, points):
        user_response = QMessageBox.question(
            self,
            "Confirm Region Selection",
            "Do you want to select data within the drawn region?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        # 사용자가 Yes를 선택한 경우
        if user_response == QMessageBox.StandardButton.Yes:
            # 버텍스 출력
            for idx, (x, y) in enumerate(points):
                logger.debug(f"Vertex {idx}: {x:.6f}, {y:.6f}")
            # self.polygonDrawer.disconnect()
            self.polygonDrawer.clear()
            config.set("bound_area_points", points, save=True)
            self.updatePlot()
        else:
            self.polygonDrawer.clear()

    def load_bound_file(self, file_path):
        logger.debug(f"load_bound_file {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # 첫 줄은 점의 개수 또는 무시해도 되는 숫자라고 가정
            vertex_points = []
            for line in lines[1:]:  # 첫 줄은 건너뜀
                parts = line.strip().split()
                if len(parts) != 2:
                    logger.warning(f"Invalid line: {line.strip()}")
                    continue
                x, y = map(float, parts)
                vertex_points.append((x, y))

            # 닫혀 있지 않으면 시작점 추가해서 닫기
            if vertex_points and vertex_points[0] != vertex_points[-1]:
                vertex_points.append(vertex_points[0])

            config.set("bound_area_points", vertex_points, save=True)
            logger.info(f"Vertex load complete: {len(vertex_points)} points")
            self.updatePlot()

        except Exception as e:
            logger.error(f"load_bound_file 오류: {repr(e)}")
            QMessageBox.critical(
                self,
                "File Error",
                f"An error occurred while opening or processing the file: {repr(e)}",
            )

    def openFIleBrowser(self):
        logger.debug("openFIleBrowser")
        proj_path = config.get("project_path", "")
        if not proj_path:
            QMessageBox.warning(self, "ERROR", "Open a project folder first.")
            return
        path = os.path.join(proj_path, "Measure Flight Folder")
        files, _ = QFileDialog.getOpenFileNames(
            parent=self,
            caption="Select Mag data files",
            dir=path,
            filter="Flight data (*.csv);;All files (*)",
        )
        logger.debug(f"Selected files: {files}")
        if not files:
            return

        list_files = config.get("Flight_File_List", [])
        list_files.extend(files)
        list_files = list(set(list_files))
        config.set("Flight_File_List", list_files, save=True)

        self.updateFileList(list_files)

    def initialize(self):
        logger.debug("initialize")

        filters_defaults = {
            "direction_filter": {"enabled": False, "threshold": 5},
            "continuity_filter": {"enabled": False, "num_points": 10},
            "speed_filter": {"enabled": False, "target_speed": 5, "tolerance": 1},
            "show_colorbar": False,
            "show_backgroundmap": False,
            "enable_area_bound": False,
            "show_area_bound": False,
        }

        config.set("filters", config.get("filters", filters_defaults), save=True)

        # self.lbl_folder_path.setText(config.get("project_path", ""))
        flightData_path = os.path.join(
            config.get("project_path", ""), "Measure Flight Folder"
        )
        if not os.path.exists(flightData_path):
            os.makedirs(flightData_path)

        list_files = config.get("Flight_File_List", [])
        self.updateFileList(list_files)

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
            f"Are you sure you want to delete '{name}' and its associated file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.fileListWidget.takeItem(self.fileListWidget.row(item_to_delete))

            # self.delete_FlightFolderFile(name)
            list_files = config.get("Flight_File_List", [])
            filename = os.path.join(
                config.get("project_path", ""), "Measure Flight Folder", name
            )
            if filename in list_files:
                list_files.remove(filename)
            config.set("Flight_File_List", list_files, save=True)
            self.updatePlot()

    def delete_FlightFolderFile(self, name: str):
        logger.debug(f"delete_FlightFolderFile {name}")
        proj_path = config.get("project_path", "")
        if not proj_path:
            QMessageBox.warning(self, "Warning", "Project path is not set.")
            return

        filename = os.path.join(proj_path, "Measure Flight Folder", name)

        if os.path.exists(filename):
            try:
                os.remove(filename)
                logger.info(f"Deleted file: {filename}")
                QMessageBox.information(
                    self, "Delete Complete", f"File '{name}' has been deleted."
                )
            except Exception as e:
                logger.error(f"Failed to delete {filename}: {e}")
                QMessageBox.critical(self, "Error", f"Failed to delete file:\n{e}")
        else:
            logger.warning(f"File not found: {filename}")
            QMessageBox.warning(self, "Warning", f"File does not exist:\n{filename}")

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
            new_min, new_max = dlg.getValues()
            if new_min is not None and new_max is not None:
                self.sm.set_clim(vmin=new_min, vmax=new_max)
                self.canvas.draw()

    @Slot(str)
    def on_project_opened(self, project_path: str):
        self.initialize()

    @Slot()
    def on_project_reset(self):
        self.initialize()
