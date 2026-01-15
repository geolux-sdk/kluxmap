import math
import os
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from loguru import logger
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from pyproj import Transformer

GOOGLE_MAPS_API_KEY_HARDCODED = "AIzaSyD1zF_979D6PEvhKJvI9ZvSf27UZ-MtqYw"

# 파일 상단에 추가
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QCursor, QIcon, QImage, QPixmap
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
from segment_utils import subtract_intervals


class FlightPlotWidget(QWidget):

    def __init__(self, db, main_window=None):
        super().__init__()
        self.main_window = main_window
        
        self.db = db

        self._selected_lines = []
        self._linecut_point = None
        self._lineappend_points = []
        self._plot_df_by_file = {}
        self._base_intervals_by_file = {}
        self._line_intervals_by_file = {}
        self._line_cut_points = {}
        self._line_delete_points = {}
        self._line_append_links = {}
        self._line_append_groups_by_file = {}
        self._line_append_selected = []
        self._linecut_preview = None
        self.df = pd.DataFrame()

        self._is_panning = False
        self._last_mouse_pos = None

        config.get("filters", {})
        # 배경 지도는 항상 none으로 시작하며 설정을 저장하지 않는다.
        self.map_type = "none"
        self._map_pixmap: Optional[QPixmap] = None
        self._map_image = None
        self._map_extent = None
        self._last_epsg = None
        self._map_cache: dict = {}

        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        # Toolbar
        toolbar = QToolBar(self)

        self.actionOpenFileBrower = QAction(
            QIcon(resource_path("imag_data_import.png")),
            "&Open File Browser",
            self,
        )
        self.actionOpenFileBrower.setStatusTip("Open Project Browser")

        self.actionDataCutDisp = QAction(
            QIcon(resource_path("imag_cut.png")), "Line Cut", self
        )
        self.actionDataCutDisp.setStatusTip("Line Cut")
        self.actionDataCutDisp.setCheckable(True)

        self.actionDataConfiDisp = QAction(
            QIcon(resource_path("filter.png")), "Trim Filters", self
        )
        self.actionDataConfiDisp.setStatusTip("Trim Filters Settings")

        self.actionDataXXXDisp = QAction(
            QIcon(resource_path("imag_sum.png")), "Line Append", self
        )
        self.actionDataXXXDisp.setStatusTip("Line Append")
        self.actionDataXXXDisp.setCheckable(True)

        self.actionDataOut = QAction(
            QIcon(resource_path("imag_kml_export.png")), "Export KML", self
        )
        self.actionDataOut.setStatusTip("Export KML FILE")

        toolbar.addAction(self.actionOpenFileBrower)
        toolbar.addAction(self.actionDataCutDisp)
        toolbar.addAction(self.actionDataConfiDisp)
        toolbar.addAction(self.actionDataXXXDisp)
        toolbar.addAction(self.actionDataOut)

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
        self.actionDataCutDisp.setEnabled(False)
        self.actionDataConfiDisp.setEnabled(False)
        self.actionDataXXXDisp.setEnabled(False)
        self.actionDataOut.setEnabled(False)

        self.connectSingnal()

    def connectSingnal(self):
        self.actionOpenFileBrower.triggered.connect(self.openFIleBrowser)
        self.actionDataConfiDisp.triggered.connect(
            lambda checked=False: DataSettingsDialog(parent=self).exec()
        )
        self.actionDataCutDisp.toggled.connect(self._on_linecut_toggled)
        self.actionDataXXXDisp.toggled.connect(self._on_lineappend_toggled)

    def actionEnable(self, action=True):
        self.actionOpenFileBrower.setEnabled(action)
        self.actionDataCutDisp.setEnabled(action)   
        self.actionDataConfiDisp.setEnabled(action)
        self.actionDataXXXDisp.setEnabled(action)
        self.actionDataOut.setEnabled(action)

    def _on_linecut_toggled(self, checked):
        if checked and self.actionDataXXXDisp.isChecked():
            self.actionDataXXXDisp.setChecked(False)
        if not checked:
            self._linecut_preview = None
        self._update_cursor_for_mode()

    def _on_lineappend_toggled(self, checked):
        if checked and self.actionDataCutDisp.isChecked():
            self.actionDataCutDisp.setChecked(False)
        if not checked:
            self._clear_line_append_selection()
        self._update_cursor_for_mode()

    def _update_cursor_for_mode(self):
        if self.actionDataCutDisp.isChecked() or self.actionDataXXXDisp.isChecked():
            self.canvas.setCursor(Qt.CrossCursor)
        else:
            self.canvas.setCursor(Qt.ArrowCursor)
        
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
        if event.button == 1 and self._handle_line_marker(event):
            return
        if event.button == 3:
            self.show_map_context_menu()
            return
        if event.button == 1 and event.inaxes == self.ax:
            self._is_panning = True
            self._last_mouse_pos = (event.xdata, event.ydata)
        self.on_canvas_click(event)

    def _handle_line_marker(self, event):
        if event.inaxes != self.ax:
            return False
        if not (
            self.actionDataCutDisp.isChecked()
            or self.actionDataXXXDisp.isChecked()
        ):
            return False
        if event.xdata is None or event.ydata is None:
            return False

        if self.actionDataCutDisp.isChecked():
            return self._handle_linecut_click(event, temporary=True)
        if self.actionDataXXXDisp.isChecked():
            return self._handle_lineappend_click(event)
        return False

    def _handle_lineappend_click(self, event):
        nearest = self._find_nearest_plot_point(event.xdata, event.ydata)
        if not nearest:
            QMessageBox.information(self, "Line Append", "No data points available.")
            return True

        filename, record_id, px, py = nearest
        groups = self._line_append_groups_by_file.get(filename)
        if groups is None:
            intervals = self._line_intervals_by_file.get(filename, [])
            links = self._line_append_links.get(filename, [])
            groups = self._build_line_append_groups(intervals, links)
            self._line_append_groups_by_file[filename] = groups

        group = self._line_append_group_for_record(groups, record_id)
        if group is None:
            QMessageBox.information(
                self,
                "Line Append",
                "Selected point does not belong to an active line.",
            )
            return True

        if self._line_append_selected:
            first = self._line_append_selected[0]
            if filename != first[0]:
                QMessageBox.information(
                    self,
                    "Line Append",
                    "Select a line from the same file.",
                )
                return True
            first_group = self._line_append_group_for_record(groups, first[1])
            if self._line_append_group_key(first_group) == self._line_append_group_key(
                group
            ):
                QMessageBox.information(
                    self,
                    "Line Append",
                    "The same line is already selected.",
                )
                return True

        self._line_append_selected.append((filename, int(record_id), px, py))

        if len(self._line_append_selected) < 2:
            self.updatePlot()
            return True

        self.updatePlot()
        action = self._prompt_lineappend_action()
        if action == "done":
            first = self._line_append_selected[0]
            second = self._line_append_selected[1]
            self._line_append_links.setdefault(filename, []).append(
                (first[1], second[1])
            )

        self._clear_line_append_selection()
        self.updatePlot()
        return True

    def _prompt_lineappend_action(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Line Append")
        dlg.setText("Append the selected lines?")
        done_btn = dlg.addButton("DONE", QMessageBox.AcceptRole)
        dlg.addButton("Cancel", QMessageBox.RejectRole)
        dlg.exec()

        if dlg.clickedButton() == done_btn:
            return "done"
        return "cancel"

    def _line_append_group_for_record(self, groups, record_id):
        if not groups:
            return None
        for group in groups:
            for start, end in group:
                if start <= record_id < end:
                    return group
        return None

    def _line_append_group_key(self, group):
        if not group:
            return None
        return tuple(group)

    def _build_line_append_groups(self, intervals, links):
        if not intervals:
            return []
        parent = list(range(len(intervals)))

        def find(idx):
            while parent[idx] != idx:
                parent[idx] = parent[parent[idx]]
                idx = parent[idx]
            return idx

        def union(a, b):
            ra = find(a)
            rb = find(b)
            if ra != rb:
                parent[rb] = ra

        for a_id, b_id in links:
            a_idx = self._find_interval_index(intervals, a_id)
            if a_idx is None:
                a_idx = self._find_closest_interval_index(intervals, a_id)
            b_idx = self._find_interval_index(intervals, b_id)
            if b_idx is None:
                b_idx = self._find_closest_interval_index(intervals, b_id)
            if a_idx is None or b_idx is None:
                continue
            union(a_idx, b_idx)

        grouped = {}
        for idx, interval in enumerate(intervals):
            root = find(idx)
            grouped.setdefault(root, []).append(interval)

        return list(grouped.values())

    def _find_interval_index(self, intervals, record_id):
        for idx, (start, end) in enumerate(intervals):
            if start <= record_id < end:
                return idx
        return None

    def _find_closest_interval_index(self, intervals, record_id):
        if not intervals:
            return None
        best_idx = None
        best_dist = None
        for idx, (start, end) in enumerate(intervals):
            if start <= record_id < end:
                return idx
            if record_id < start:
                dist = start - record_id
            else:
                dist = record_id - (end - 1)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def _clear_line_append_selection(self):
        self._line_append_selected.clear()
        self._lineappend_points = []

    def _validate_line_append_selection(self):
        if not self._line_append_selected:
            return
        for sel in self._line_append_selected:
            filename, record_id, _, _ = sel
            groups = self._line_append_groups_by_file.get(filename, [])
            if self._line_append_group_for_record(groups, record_id) is None:
                self._clear_line_append_selection()
                return

    def _handle_linecut_click(self, event, temporary=False):
        nearest = self._find_nearest_plot_point(event.xdata, event.ydata)
        if not nearest:
            QMessageBox.information(self, "Line Cut", "No data points available.")
            return True

        filename, record_id, px, py = nearest
        if temporary:
            self._linecut_preview = (filename, int(record_id))
            self._linecut_point = (px, py)
            self.updatePlot()
        action = self._prompt_linecut_action(filename, record_id)
        if action is None:
            if temporary:
                self._linecut_point = None
                self._linecut_preview = None
                self.updatePlot()
            else:
                self._linecut_point = None
            return True

        if not temporary:
            self._linecut_point = (px, py)
        record_id = int(record_id)
        if action == "cut":
            self._line_cut_points.setdefault(filename, set()).add(record_id)
        elif action == "delete":
            intervals = self._line_intervals_by_file.get(filename, [])
            if not any(start <= record_id < end for start, end in intervals):
                QMessageBox.information(
                    self,
                    "Line Cut",
                    "Selected point does not belong to an active line.",
                )
                if temporary:
                    self._linecut_point = None
                    self._linecut_preview = None
                    self.updatePlot()
                return True
            self._line_delete_points.setdefault(filename, set()).add(record_id)
        if temporary:
            self._linecut_point = None
            self._linecut_preview = None
        self.updatePlot()
        return True

    def _find_nearest_plot_point(self, x, y):
        if not self._plot_df_by_file:
            return None

        best = None
        best_dist = None
        for filename, df in self._plot_df_by_file.items():
            if df is None or df.empty:
                continue
            if not {"X", "Y"}.issubset(df.columns):
                continue
            xs = df["X"].to_numpy()
            ys = df["Y"].to_numpy()
            if xs.size == 0:
                continue

            dx = xs - x
            dy = ys - y
            dist2 = dx * dx + dy * dy
            idx = int(np.argmin(dist2))
            dist = float(dist2[idx])
            if best_dist is None or dist < best_dist:
                row = df.iloc[idx]
                record_id = row["record_id"] if "record_id" in row else row.name
                try:
                    record_id = int(record_id)
                except Exception:
                    record_id = int(row.name)
                best = (filename, record_id, float(row["X"]), float(row["Y"]))
                best_dist = dist

        return best

    def _prompt_linecut_action(self, filename, record_id):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Line Cut")
        dlg.setText(f"{filename}\nrecord_id: {record_id}\nSelect action:")
        cut_btn = dlg.addButton("CUT", QMessageBox.AcceptRole)
        del_btn = dlg.addButton("DELETE", QMessageBox.DestructiveRole)
        dlg.addButton(QMessageBox.Cancel)
        dlg.exec()

        if dlg.clickedButton() == cut_btn:
            return "cut"
        if dlg.clickedButton() == del_btn:
            return "delete"
        return None

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
        combined_df = getattr(self.db, "combined_df", None)
        if (
            combined_df is not None
            and not combined_df.empty
            and {"X", "Y"}.issubset(combined_df.columns)
        ):
            all_x = combined_df["X"].to_numpy()
            all_y = combined_df["Y"].to_numpy()
        else:
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
        if len(all_x) == 0 or len(all_y) == 0:
            return 0, 1, 0, 1
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

    def _apply_line_edits(self, filename, df, base_intervals=None):
        if df is None or df.empty:
            return df, [], []

        work = df
        if "record_id" not in work.columns:
            work = work.copy()
            work["record_id"] = np.arange(len(work))

        if base_intervals is None:
            base_intervals = self.db.df_to_intervals(work)

        intervals = list(base_intervals)
        cut_points = self._line_cut_points.get(filename, set())
        if cut_points and intervals:
            cut_intervals = [(int(p), int(p) + 1) for p in cut_points]
            intervals = subtract_intervals(intervals, cut_intervals)

        delete_points = self._line_delete_points.get(filename, set())
        if delete_points and intervals:
            intervals = [
                (start, end)
                for start, end in intervals
                if not any(start <= p < end for p in delete_points)
            ]

        if intervals:
            work = self._filter_df_by_intervals(work, intervals)
        else:
            work = work.iloc[0:0]

        return work, intervals, base_intervals

    def _filter_df_by_intervals(self, df, intervals):
        if df is None or df.empty or not intervals:
            return df.iloc[0:0]
        record_ids = pd.to_numeric(df["record_id"], errors="coerce").to_numpy()
        keep = np.zeros(len(df), dtype=bool)
        for start, end in intervals:
            keep |= (record_ids >= start) & (record_ids < end)
        return df.loc[keep].copy()

    def _draw_line_append_overlays(self, palette):
        if not self._line_append_selected:
            return
        drawn = set()
        for idx, (filename, record_id, _, _) in enumerate(self._line_append_selected):
            groups = self._line_append_groups_by_file.get(filename, [])
            group = self._line_append_group_for_record(groups, record_id)
            if not group:
                continue
            group_key = (filename, self._line_append_group_key(group))
            if group_key in drawn:
                continue
            drawn.add(group_key)
            df = self._plot_df_by_file.get(filename)
            if df is None or df.empty:
                continue
            if not {"X", "Y", "record_id"}.issubset(df.columns):
                continue
            record_ids = pd.to_numeric(df["record_id"], errors="coerce").to_numpy()
            color = palette[(idx + 1) % len(palette)]
            for start, end in group:
                mask = (record_ids >= start) & (record_ids < end)
                seg = df.loc[mask]
                if seg.empty:
                    continue
                self.ax.plot(
                    seg["X"].values,
                    seg["Y"].values,
                    linewidth=3,
                    c=color,
                    zorder=6,
                )

    def _draw_linecut_preview(self):
        if not self._linecut_preview:
            return
        filename, record_id = self._linecut_preview
        intervals = self._line_intervals_by_file.get(filename, [])
        interval = None
        for start, end in intervals:
            if start <= record_id < end:
                interval = (start, end)
                break
        if interval is None:
            return

        df = self._plot_df_by_file.get(filename)
        if df is None or df.empty:
            return
        if not {"X", "Y", "record_id"}.issubset(df.columns):
            return
        record_ids = pd.to_numeric(df["record_id"], errors="coerce").to_numpy()
        start, end = interval
        mask = (record_ids >= start) & (record_ids < end)
        seg = df.loc[mask]
        if seg.empty:
            return
        self.ax.plot(
            seg["X"].values,
            seg["Y"].values,
            linewidth=3,
            c="black",
            zorder=6,
        )

    def updatePlot(self):
        logger.debug("updatePlot")
        cfg = config.get("filters")
        direction_degree = config.get("direction")

        logger.debug(
            f"plot setup: map_type={self.map_type}, cfg_background={cfg.get('background_map_type') if cfg else None}"
        )

        try:
            # --- 1) 선택된 파일 목록 확보 ---
            selected = [item.text() for item in self.fileListWidget.selectedItems()]
            logger.debug(f"plot setup: selected files count={len(selected)}")
            if not selected:
                self.ax.clear()
                self.ax.set_title("No files selected  to plot.")
                self.ax.set_xticks([])
                self.ax.set_yticks([])
                self.canvas.draw()
                return

            # --- 2) 파일별 X, Y, 값 추출 ---
            all_x, all_y, all_vals = [], [], []
            all_lat, all_lon = [], []
            file_data_list = []
            self._plot_df_by_file = {}
            self._base_intervals_by_file = {}
            self._line_intervals_by_file = {}
            self.db.clear_combined_df()
            timeline = None
            timeline_id = "flight:plot"
            source_offsets = {}
            try:
                timeline = self.db.reset_timeline(timeline_id, selected)
                source_offsets = {
                    sid: timeline.offsets[idx]
                    for idx, sid in enumerate(timeline.source_ids)
                }
            except Exception as e:
                logger.error(f"Failed to create timeline for plot: {e}")
            data_epsg = None
            for filename in selected:
                src_df = self.db.get_FlightData(filename)
                if src_df is None or src_df.empty:
                    continue
                filtered_df = self.db.get_filtered_data(
                    src_df, cfg, direction_degree
                )
                if filtered_df is None or filtered_df.empty:
                    continue

                base_df = filtered_df
                if "record_id" not in base_df.columns:
                    base_df = base_df.copy()
                    base_df["record_id"] = np.arange(len(base_df))
                base_intervals = self.db.df_to_intervals(base_df)
                self._base_intervals_by_file[filename] = base_intervals

                edited_df, intervals, _ = self._apply_line_edits(
                    filename, base_df, base_intervals
                )
                self._line_intervals_by_file[filename] = intervals
                if edited_df is None or edited_df.empty or not intervals:
                    continue

                xdata = ydata = vals = None
                seg_df = None
                if timeline is not None and filename in source_offsets:
                    offset = source_offsets[filename]
                    global_intervals = [
                        (offset + s, offset + e) for s, e in intervals
                    ]
                    segment_id = f"{timeline_id}:{filename}"
                    try:
                        self.db.create_segment(
                            segment_id,
                            timeline_id,
                            global_intervals,
                            meta={"source": filename},
                        )
                        xdata, ydata, vals = self.db.get_scatter_arrays(
                            segment_id, "X", "Y", "Mag", stride=1
                        )
                        seg_df = self.db.materialize_segment_df(segment_id)
                    except Exception as e:
                        logger.error(f"Segment scatter failed: {e}")

                if seg_df is None or seg_df.empty:
                    seg_df = edited_df

                if xdata is None or ydata is None or vals is None:
                    xdata, ydata, vals = self.db.get_XYMagData(seg_df)

                if len(xdata) == 0:
                    continue

                self._plot_df_by_file[filename] = seg_df
                self.db.put_combined_df(seg_df)

                lat_series = seg_df.get("Latitude")
                lon_series = seg_df.get("Longitude")
                if "CRS_EPSG" in seg_df.columns and data_epsg is None:
                    try:
                        data_epsg = int(seg_df["CRS_EPSG"].iloc[0])
                    except Exception:
                        data_epsg = None

                if lat_series is not None and lon_series is not None:
                    all_lat.extend(
                        pd.to_numeric(lat_series, errors="coerce").dropna()
                    )
                    all_lon.extend(
                        pd.to_numeric(lon_series, errors="coerce").dropna()
                    )
                file_data_list.append((filename, xdata, ydata, vals))
                all_x.extend(xdata)
                all_y.extend(ydata)
                all_vals.extend(vals)

            self._line_append_groups_by_file = {}
            for filename, intervals in self._line_intervals_by_file.items():
                links = self._line_append_links.get(filename, [])
                self._line_append_groups_by_file[filename] = (
                    self._build_line_append_groups(intervals, links)
                )
            self._validate_line_append_selection()
            self.db.update_scanline_state(
                df_by_file=self._plot_df_by_file,
                groups_by_file=self._line_append_groups_by_file,
                intervals_by_file=self._line_intervals_by_file,
            )

            self.df = self.db.combined_df
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
            map_drawn = False
            if self.map_type and self.map_type != "none":
                map_drawn = self._update_background_map(
                    all_lat, all_lon, data_epsg=data_epsg
                )

            if map_drawn and self._map_extent:
                map_minx, map_maxx, map_miny, map_maxy = self._map_extent
            data_minx, data_maxx, data_miny, data_maxy = self.clac_XYlimit_listAll()
            # 축은 항상 데이터 범위에 맞추어 배경 없음 상태와 동일한 크기로 시작
            # 배경 이미지가 더 크더라도 imshow extent가 지도 전체를 포함하므로 확대/이동 시 모두 볼 수 있음
            self.ax.set_xlim(data_minx, data_maxx)
            self.ax.set_ylim(data_miny, data_maxy)
            if map_drawn and self._map_image is not None and self._map_extent:
                try:
                    # 받은 전체 배경 이미지를 원래 지도 범위에 맞춰 표시
                    display_extent = self._map_extent
                    self.ax.imshow(
                        self._map_image,
                        extent=display_extent,
                        origin="upper",
                        zorder=0,
                        aspect="equal",
                    )
                    logger.debug(
                        f"map draw: imshow done with extent={display_extent}, image_shape={self._map_image.shape if hasattr(self._map_image, 'shape') else None}"
                    )
                except Exception as e:
                    logger.error(f"Failed to draw background map: {e}")
                    map_drawn = False
                    self._map_image = None
                    self._map_extent = None


            # # --- 5) 컬러맵 설정 ---
            show_cb = cfg.get("show_colorbar", False)
            palette = plt.get_cmap("tab10").colors
            if show_cb:
                cmap = plt.cm.get_cmap("jet")
                norm = plt.Normalize(vmin=vmin, vmax=vmax)

            # --- 6) 산점도 표시 ---
            for idx, (fname, x, y, vals) in enumerate(file_data_list):
                if show_cb:
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

            self._draw_linecut_preview()
            self._draw_line_append_overlays(palette)

            if self._linecut_point:
                x, y = self._linecut_point
                self.ax.scatter([x], [y], s=40, marker="x", color="red", zorder=10)
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
            item = QListWidgetItem(file_name)
            self.fileListWidget.addItem(item)
            item.setSelected(True)
            self.fileListWidget.setFocus()

        proj_path = Path(config.get("project_path", ""))
        self.db.clear_FlightData()

        for file_name in files:
            file_path = proj_path / "Measure Flight Folder" / (file_name + ".csv")
            self.db.load_FlightData(file_path)
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
        proj_path = Path(config.get("project_path", ""))
        if not proj_path:
            QMessageBox.warning(self, "ERROR", "Open a project folder first.")
            return
        open_path = proj_path / "Measure Flight Folder"
        files, _ = QFileDialog.getOpenFileNames(
            parent=self,
            caption="Select Mag data files",
            dir=str(open_path),
            filter="Flight data (*.csv);;All files (*)",
        )
        logger.debug(f"Selected files: {files}")
        if not files:
            return

        list_files = config.get("Flight_File_List", [])
        for file in files:
            p = Path(file)
            name_wo_ext = p.stem
            if name_wo_ext not in list_files:
                list_files.append(name_wo_ext)

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

        filters = config.get("filters", {})
        if not filters:
            filters = filters_defaults.copy()
        else:
            for key, value in filters_defaults.items():
                filters.setdefault(key, value)

        # 배경 지도 설정은 저장하지 않고 항상 none으로 시작
        if "background_map_type" in filters:
            filters.pop("background_map_type", None)
        config.set("filters", filters, save=True)
        self.map_type = "none"
        logger.debug(
            f"initialize: filters loaded (background_map_type={self.map_type}, show_backgroundmap={filters.get('show_backgroundmap')})"
        )

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
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.fileListWidget.takeItem(self.fileListWidget.row(item_to_delete))

            list_files = config.get("Flight_File_List", [])
            if name in list_files:
                list_files.remove(name)
            config.set("Flight_File_List", list_files, save=True)

            self.updatePlot()

    def delete_all_items(self):
        self.fileListWidget.clear()
        self.db.clear_FlightData()
        self._line_cut_points.clear()
        self._line_delete_points.clear()
        self._plot_df_by_file.clear()
        self._base_intervals_by_file.clear()
        self._line_intervals_by_file.clear()
        self._line_append_links.clear()
        self._line_append_groups_by_file.clear()
        self._line_append_selected.clear()
        self._linecut_preview = None
        self._linecut_point = None
        self._lineappend_points = []
        self.updatePlot()

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
        self.delete_all_items()

    def show_map_context_menu(self):
        menu = QMenu(self)
        actions = {
            "배경 없음": "none",
            "roadmap": "roadmap",
            "satellite": "satellite",
            "hybrid": "hybrid",
            "terrain": "terrain",
        }
        current = self.map_type or "none"
        logger.debug(f"map menu: current background_map_type={current}")
        for label, value in actions.items():
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(current == value)
            act.setData(value)

        selected_action = menu.exec(QCursor.pos())
        if not selected_action:
            return

        chosen = selected_action.data()
        if chosen == current:
            logger.debug(f"map menu: chosen={chosen}, unchanged -> skip update")
            return

        self.map_type = chosen
        logger.debug(f"map menu: chosen={chosen}, updating plot (not persisted)")
        self.updatePlot()

    def _get_api_key(self) -> Optional[str]:
        # Prefer environment/configured key; embedded key is a last resort and may be blocked.
        key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if key:
            logger.debug("API key source: environment variable GOOGLE_MAPS_API_KEY")
            return key.strip()
        cfg_key = config.get("google_maps_api_key")
        if cfg_key:
            logger.debug("API key source: config['google_maps_api_key']")
            return str(cfg_key).strip()
        if GOOGLE_MAPS_API_KEY_HARDCODED:
            logger.warning(
                "Falling back to embedded Google Maps API key; set GOOGLE_MAPS_API_KEY for reliable access."
            )
            return GOOGLE_MAPS_API_KEY_HARDCODED
        logger.warning("Google Maps API key not configured; skipping background.")
        return None

    def _estimate_zoom(
        self, center_lat: float, lat_span: float, lon_span: float, px_w: int, px_h: int
    ) -> int:
        if px_w <= 0 or px_h <= 0:
            return 15
        meters_lat = max(lat_span, 1e-6) * 111_000
        meters_lon = max(lon_span, 1e-6) * 111_000 * math.cos(
            math.radians(center_lat)
        )
        meters_per_px = max(meters_lat / max(px_h, 1e-6), meters_lon / max(px_w, 1e-6))
        if meters_per_px <= 0:
            return 15
        raw_zoom = math.log2(
            156543.03392 * math.cos(math.radians(center_lat)) / meters_per_px
        )
        return max(0, min(21, int(raw_zoom)))

    def _latlon_bounds(self, latitudes, longitudes):
        if not latitudes or not longitudes:
            return None
        lat_min, lat_max = np.min(latitudes), np.max(latitudes)
        lon_min, lon_max = np.min(longitudes), np.max(longitudes)
        lat_range = lat_max - lat_min
        lon_range = lon_max - lon_min
        min_span = 0.0005
        lat_range = max(lat_range, min_span) * 2
        lon_range = max(lon_range, min_span) * 2
        # 이미지가 정사각형(1280x1280)에 맞게 비율 1:1 유지
        square_span = max(lat_range, lon_range)
        lat_range = square_span
        lon_range = square_span
        center_lat = (lat_max + lat_min) / 2
        center_lon = (lon_max + lon_min) / 2
        return {
            "center": (center_lat, center_lon),
            "lat_span": lat_range,
            "lon_span": lon_range,
            "lat_min": center_lat - lat_range / 2,
            "lat_max": center_lat + lat_range / 2,
            "lon_min": center_lon - lon_range / 2,
            "lon_max": center_lon + lon_range / 2,
        }

    def _qt_image_to_array(self, image: QImage):
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        ptr = image.bits()
        expected_size = image.height() * image.bytesPerLine()
        # PyQt returns a sip.voidptr (needs setsize), PySide6 returns a memoryview (no setsize)
        if hasattr(ptr, "setsize"):
            ptr.setsize(expected_size)
            buffer = ptr
        else:
            buffer = memoryview(ptr)

        arr = np.frombuffer(buffer, np.uint8, count=expected_size).reshape(
            (image.height(), image.bytesPerLine() // 4, 4)
        )
        # copy()로 QImage 소멸 후에도 안전하게 사용
        return arr.copy()

    def _latlon_to_utm_extent(self, bounds: dict, data_epsg: Optional[int]):
        try:
            epsg = data_epsg
            if not epsg:
                epsg = self.db._latlon_to_utm_epsg(
                    bounds["center"][0], bounds["center"][1]
                )
            transformer = Transformer.from_crs(
                "EPSG:4326", f"EPSG:{int(epsg)}", always_xy=True
            )
            x1, y1 = transformer.transform(bounds["lon_min"], bounds["lat_min"])
            x2, y2 = transformer.transform(bounds["lon_max"], bounds["lat_max"])
            xmin, xmax = sorted([x1, x2])
            ymin, ymax = sorted([y1, y2])
            self._last_epsg = epsg
            return xmin, xmax, ymin, ymax
        except Exception as e:
            logger.error(f"Failed to project bounds to UTM: {e}")
            return None

    def _update_background_map(self, latitudes, longitudes, data_epsg=None):
        try:
            bounds = self._latlon_bounds(latitudes, longitudes)
            if not bounds:
                return False
            logger.debug(
                f"map fetch: map_type={self.map_type}, center={bounds['center']}, spans(lat,lon)=({bounds['lat_span']},{bounds['lon_span']})"
            )

            api_key = self._get_api_key()
            if not api_key:
                logger.warning("Google Maps API key not configured; skipping background.")
                return False

            w, h = self.canvas.get_width_height()
            size_w = max(256, min(640, int(w)))
            size_h = max(256, min(640, int(h)))
            scale = 2

            zoom = self._estimate_zoom(
                bounds["center"][0],
                bounds["lat_span"],
                bounds["lon_span"],
                size_w * scale,
                size_h * scale,
            )
            logger.debug(
                f"map fetch: size=({size_w}x{size_h}) scale={scale} zoom={zoom} data_epsg={data_epsg}"
            )

            # 캐시 키: 지도 유형/중심/스팬/줌/EPSG 기준 (size/scale 제외)
            cache_key = (
                self.map_type,
                round(bounds["center"][0], 7),
                round(bounds["center"][1], 7),
                round(bounds["lat_span"], 7),
                round(bounds["lon_span"], 7),
                zoom,
                data_epsg,
            )
            if cache_key in self._map_cache:
                cached_img, cached_extent = self._map_cache[cache_key]
                if cached_img is not None and cached_extent is not None:
                    self._map_image = cached_img
                    self._map_extent = cached_extent
                    logger.debug("map fetch: using cached image (skipping request)")
                    return True

            # 캐시 미스: 이전 지도 상태는 초기화
            self._map_image = None
            self._map_extent = None

            url = (
                "https://maps.googleapis.com/maps/api/staticmap"
                f"?center={bounds['center'][0]},{bounds['center'][1]}"
                f"&zoom={zoom}&size={size_w}x{size_h}&scale={scale}"
                f"&maptype={self.map_type}&key={api_key}"
            )
            safe_url = url.replace(api_key, "***")
            logger.info(f"map fetch url (key masked): {safe_url}")

            resp = None
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                logger.debug(
                    f"map fetch: http_status={resp.status_code} content_length={len(resp.content)}"
                )
            except requests.HTTPError as e:
                status = getattr(resp, "status_code", None)
                if status == 403:
                    logger.error(
                        "Failed to fetch Static Map (403 Forbidden). "
                        "Verify GOOGLE_MAPS_API_KEY, billing status, and Static Maps API enablement."
                    )
                else:
                    logger.error(f"Failed to fetch Static Map (HTTP {status}): {e}")
                return False
            except Exception as e:
                logger.error(f"Failed to fetch Static Map: {e}")
                return False

            pix = QPixmap()
            if not pix.loadFromData(resp.content):
                logger.error("Failed to load map image from response content.")
                return False
            logger.debug(
                f"map fetch: pixmap loaded size=({pix.width()}x{pix.height()}) bytes={resp.headers.get('Content-Length')}"
            )
            self._map_pixmap = pix
            image = pix.toImage()
            self._map_image = self._qt_image_to_array(image)

            extent = self._latlon_to_utm_extent(bounds, data_epsg)
            if not extent:
                logger.error("map fetch: failed to compute UTM extent from bounds")
                return False
            self._map_extent = extent
            self._map_cache[cache_key] = (self._map_image, self._map_extent)
            logger.debug(f"map fetch: computed UTM extent={extent}, last_epsg={self._last_epsg}")
            return True
        except Exception as e:
            logger.exception(f"_update_background_map unexpected failure: {e}")
            return False
