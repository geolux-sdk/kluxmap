import glob
import os

from loguru import logger
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QProgressDialog,
    QRadioButton,
    QVBoxLayout,
)

from Data_Parse import DataConverter, import_mag_arrow_file
from mySettings import config


class ConvertDataDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data Load")

        # ---- defaults & cfg ----
        defaults = {
            "device": "Mag Hawk V2023",
            "option": {
                "hemisphere": "Northern Hemisphere",  # for V2022/V2023
                "mode": "folder",  # for V2022/V2023/V2025: "folder"|"file"
                # "rate": "10Hz"                      # for Arrow: "1000Hz"|"100Hz"|"10Hz"
            },
            "saveto": "Measure Flight Folder",  # "Measure Flight Folder" | "Calibration Flight Folder" | "Diurnal Data Folder"
        }
        # config는 외부에 있다고 가정합니다.
        self.cfg = config.get("dataloaddlg", defaults)
        self.selection = None  # OK 후 호출자가 읽을 수 있게 보관

        layout = QVBoxLayout(self)

        # ===========================
        # V2022
        # ===========================
        self.grp_v2022 = QGroupBox("Mag Hawk V2022")
        self.grp_v2022.setCheckable(True)
        self.grp_v2022.setChecked(False)
        v2022_v = QVBoxLayout(self.grp_v2022)

        # hemisphere
        v2022_hemi_h = QHBoxLayout()
        self.opt_v2022_north = QCheckBox("Northern Hemisphere")
        self.opt_v2022_south = QCheckBox("Southern Hemisphere")
        self.v2022_opts = QButtonGroup(self)
        self.v2022_opts.setExclusive(True)
        self.v2022_opts.addButton(self.opt_v2022_north)
        self.v2022_opts.addButton(self.opt_v2022_south)
        v2022_hemi_h.addWidget(self.opt_v2022_north)
        v2022_hemi_h.addWidget(self.opt_v2022_south)
        v2022_v.addLayout(v2022_hemi_h)

        # V2022: Folder/File radio
        v2022_path_h = QHBoxLayout()
        self.v2022_radio_folder = QRadioButton("Folder")
        self.v2022_radio_file = QRadioButton("File")
        self.v2022_radio_group = QButtonGroup(self)
        self.v2022_radio_group.addButton(self.v2022_radio_folder)
        self.v2022_radio_group.addButton(self.v2022_radio_file)
        v2022_path_h.addWidget(self.v2022_radio_folder)
        v2022_path_h.addWidget(self.v2022_radio_file)
        v2022_v.addLayout(v2022_path_h)

        layout.addWidget(self.grp_v2022)

        # ===========================
        # V2023
        # ===========================
        self.grp_v2023 = QGroupBox("Mag Hawk V2023")
        self.grp_v2023.setCheckable(True)
        self.grp_v2023.setChecked(False)
        v2023_v = QVBoxLayout(self.grp_v2023)

        v2023_hemi_h = QHBoxLayout()
        self.opt_v2023_north = QCheckBox("Northern Hemisphere")
        self.opt_v2023_south = QCheckBox("Southern Hemisphere")
        self.v2023_opts = QButtonGroup(self)
        self.v2023_opts.setExclusive(True)
        self.v2023_opts.addButton(self.opt_v2023_north)
        self.v2023_opts.addButton(self.opt_v2023_south)
        v2023_hemi_h.addWidget(self.opt_v2023_north)
        v2023_hemi_h.addWidget(self.opt_v2023_south)
        v2023_v.addLayout(v2023_hemi_h)

        v2023_path_h = QHBoxLayout()
        self.v2023_radio_folder = QRadioButton("Folder")
        self.v2023_radio_file = QRadioButton("File")
        self.v2023_radio_group = QButtonGroup(self)
        self.v2023_radio_group.addButton(self.v2023_radio_folder)
        self.v2023_radio_group.addButton(self.v2023_radio_file)
        v2023_path_h.addWidget(self.v2023_radio_folder)
        v2023_path_h.addWidget(self.v2023_radio_file)
        v2023_v.addLayout(v2023_path_h)

        layout.addWidget(self.grp_v2023)

        # ===========================
        # V2025
        # ===========================
        self.grp_v2025 = QGroupBox("Mag Hawk V2025")
        self.grp_v2025.setCheckable(True)
        self.grp_v2025.setChecked(False)
        v2025_v = QHBoxLayout(self.grp_v2025)

        self.v2025_radio_folder = QRadioButton("Folder")
        self.v2025_radio_file = QRadioButton("File")
        self.v2025_radio_group = QButtonGroup(self)
        self.v2025_radio_group.addButton(self.v2025_radio_folder)
        self.v2025_radio_group.addButton(self.v2025_radio_file)
        v2025_v.addWidget(self.v2025_radio_folder)
        v2025_v.addWidget(self.v2025_radio_file)

        layout.addWidget(self.grp_v2025)

        # ===========================
        # Arrow
        # ===========================
        self.grp_arrow = QGroupBox("Mag Hawk Arrow")
        self.grp_arrow.setCheckable(True)
        self.grp_arrow.setChecked(False)
        arrow_layout = QHBoxLayout(self.grp_arrow)

        self.opt_arrow_1000 = QCheckBox("1000Hz")
        self.opt_arrow_100 = QCheckBox("100Hz")
        self.opt_arrow_10 = QCheckBox("10Hz")
        self.arrow_opts = QButtonGroup(self)
        self.arrow_opts.setExclusive(True)
        self.arrow_opts.addButton(self.opt_arrow_1000)
        self.arrow_opts.addButton(self.opt_arrow_100)
        self.arrow_opts.addButton(self.opt_arrow_10)
        arrow_layout.addWidget(self.opt_arrow_1000)
        arrow_layout.addWidget(self.opt_arrow_100)
        arrow_layout.addWidget(self.opt_arrow_10)

        layout.addWidget(self.grp_arrow)

        # ===========================
        # Save To
        # ===========================
        self.grp_save = QGroupBox("Save to:")
        save_v = QVBoxLayout(self.grp_save)
        self.opt_save_flight = QRadioButton("Measure Flight Folder")
        self.opt_save_calib = QRadioButton("Calibration Flight Folder")
        self.opt_save_diurnal = QRadioButton("Diurnal Data Folder")
        self.save_radio_group = QButtonGroup(self)
        self.save_radio_group.addButton(self.opt_save_flight)
        self.save_radio_group.addButton(self.opt_save_calib)
        self.save_radio_group.addButton(self.opt_save_diurnal)
        save_v.addWidget(self.opt_save_flight)
        save_v.addWidget(self.opt_save_calib)
        save_v.addWidget(self.opt_save_diurnal)
        layout.addWidget(self.grp_save)

        # ===========================
        # Mutual exclusivity among 4 device groups
        # ===========================
        self._all_groups = [
            self.grp_v2022,
            self.grp_v2023,
            self.grp_v2025,
            self.grp_arrow,
        ]
        for grp in self._all_groups:
            grp.toggled.connect(self._on_groupbox_toggled)

        # --- OK/Cancel ---
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        self.button_box.accepted.connect(self._on_accept)  # ← OK 처리
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # --- apply cfg before first update ---
        self._apply_cfg(self.cfg)

        # init state
        self._update_enabled_states()
        self._update_ok_enabled()

        # validation hooks
        self.opt_v2022_north.toggled.connect(self._update_ok_enabled)
        self.opt_v2022_south.toggled.connect(self._update_ok_enabled)
        self.opt_v2023_north.toggled.connect(self._update_ok_enabled)
        self.opt_v2023_south.toggled.connect(self._update_ok_enabled)
        self.opt_arrow_1000.toggled.connect(self._update_ok_enabled)
        self.opt_arrow_100.toggled.connect(self._update_ok_enabled)
        self.opt_arrow_10.toggled.connect(self._update_ok_enabled)

    # ----------------- cfg 적용 -----------------
    def _apply_cfg(self, cfg: dict):
        dev = (cfg.get("device") or "").strip().lower()
        opt = cfg.get("option") or {}
        hemi = (opt.get("hemisphere") or "").strip().lower()
        mode = (opt.get("mode") or "").strip().lower()
        rate = (opt.get("rate") or "").strip().lower()
        saveto = (cfg.get("saveto") or "").strip()

        # block signals
        for w in (
            self.grp_v2022,
            self.grp_v2023,
            self.grp_v2025,
            self.grp_arrow,
            self.opt_v2022_north,
            self.opt_v2022_south,
            self.v2022_radio_folder,
            self.v2022_radio_file,
            self.opt_v2023_north,
            self.opt_v2023_south,
            self.v2023_radio_folder,
            self.v2023_radio_file,
            self.v2025_radio_folder,
            self.v2025_radio_file,
            self.opt_arrow_1000,
            self.opt_arrow_100,
            self.opt_arrow_10,
            self.opt_save_flight,
            self.opt_save_calib,
            self.opt_save_diurnal,
        ):
            w.blockSignals(True)

        try:
            # reset
            self.grp_v2022.setChecked(False)
            self.grp_v2023.setChecked(False)
            self.grp_v2025.setChecked(False)
            self.grp_arrow.setChecked(False)

            self.opt_v2022_north.setChecked(False)
            self.opt_v2022_south.setChecked(False)
            self.v2022_radio_folder.setChecked(False)
            self.v2022_radio_file.setChecked(False)

            self.opt_v2023_north.setChecked(False)
            self.opt_v2023_south.setChecked(False)
            self.v2023_radio_folder.setChecked(False)
            self.v2023_radio_file.setChecked(False)

            self.v2025_radio_folder.setChecked(False)
            self.v2025_radio_file.setChecked(False)

            self.opt_arrow_1000.setChecked(False)
            self.opt_arrow_100.setChecked(False)
            self.opt_arrow_10.setChecked(False)

            self.opt_save_flight.setChecked(False)
            self.opt_save_calib.setChecked(False)
            self.opt_save_diurnal.setChecked(False)

            # device
            if "v2022" in dev:
                self.grp_v2022.setChecked(True)
                if hemi.startswith("northern") or hemi == "north":
                    self.opt_v2022_north.setChecked(True)
                elif hemi.startswith("southern") or hemi == "south":
                    self.opt_v2022_south.setChecked(True)
                if mode == "folder":
                    self.v2022_radio_folder.setChecked(True)
                elif mode == "file":
                    self.v2022_radio_file.setChecked(True)

            elif "v2023" in dev:
                self.grp_v2023.setChecked(True)
                if hemi.startswith("northern") or hemi == "north":
                    self.opt_v2023_north.setChecked(True)
                elif hemi.startswith("southern") or hemi == "south":
                    self.opt_v2023_south.setChecked(True)
                if mode == "folder":
                    self.v2023_radio_folder.setChecked(True)
                elif mode == "file":
                    self.v2023_radio_file.setChecked(True)

            elif "v2025" in dev:
                self.grp_v2025.setChecked(True)
                if mode == "folder":
                    self.v2025_radio_folder.setChecked(True)
                elif mode == "file":
                    self.v2025_radio_file.setChecked(True)

            elif "arrow" in dev:
                self.grp_arrow.setChecked(True)
                # rate optional
                if rate == "1000hz":
                    self.opt_arrow_1000.setChecked(True)
                elif rate == "100hz":
                    self.opt_arrow_100.setChecked(True)
                elif rate == "10hz":
                    self.opt_arrow_10.setChecked(True)

            # save-to
            if saveto == "Measure Flight Folder":
                self.opt_save_flight.setChecked(True)
            elif saveto == "Calibration Flight Folder":
                self.opt_save_calib.setChecked(True)
            elif saveto == "Diurnal Data Folder":
                self.opt_save_diurnal.setChecked(True)
            else:
                # 기본값
                self.opt_save_flight.setChecked(True)

        finally:
            for w in (
                self.grp_v2022,
                self.grp_v2023,
                self.grp_v2025,
                self.grp_arrow,
                self.opt_v2022_north,
                self.opt_v2022_south,
                self.v2022_radio_folder,
                self.v2022_radio_file,
                self.opt_v2023_north,
                self.opt_v2023_south,
                self.v2023_radio_folder,
                self.v2023_radio_file,
                self.v2025_radio_folder,
                self.v2025_radio_file,
                self.opt_arrow_1000,
                self.opt_arrow_100,
                self.opt_arrow_10,
                self.opt_save_flight,
                self.opt_save_calib,
                self.opt_save_diurnal,
            ):
                w.blockSignals(False)

        # 서로 하나만
        self._ensure_device_exclusive()

    def _ensure_device_exclusive(self):
        if self.grp_v2022.isChecked():
            self.grp_v2023.setChecked(False)
            self.grp_v2025.setChecked(False)
            self.grp_arrow.setChecked(False)
        elif self.grp_v2023.isChecked():
            self.grp_v2022.setChecked(False)
            self.grp_v2025.setChecked(False)
            self.grp_arrow.setChecked(False)
        elif self.grp_v2025.isChecked():
            self.grp_v2022.setChecked(False)
            self.grp_v2023.setChecked(False)
            self.grp_arrow.setChecked(False)
        elif self.grp_arrow.isChecked():
            self.grp_v2022.setChecked(False)
            self.grp_v2023.setChecked(False)
            self.grp_v2025.setChecked(False)

    # ----------------- state & validation -----------------
    def _on_groupbox_toggled(self, checked):
        if checked:
            sender = self.sender()
            for grp in self._all_groups:
                if grp is not sender and grp.isChecked():
                    grp.blockSignals(True)
                    grp.setChecked(False)
                    grp.blockSignals(False)
        self._update_enabled_states()
        self._update_ok_enabled()

    def _update_enabled_states(self):
        v2022_active = self.grp_v2022.isChecked()
        v2023_active = self.grp_v2023.isChecked()
        v2025_active = self.grp_v2025.isChecked()
        arrow_active = self.grp_arrow.isChecked()

        # V2022
        for w in (
            self.opt_v2022_north,
            self.opt_v2022_south,
            self.v2022_radio_folder,
            self.v2022_radio_file,
        ):
            w.setEnabled(v2022_active)

        # V2023
        for w in (
            self.opt_v2023_north,
            self.opt_v2023_south,
            self.v2023_radio_folder,
            self.v2023_radio_file,
        ):
            w.setEnabled(v2023_active)

        # V2025
        for w in (self.v2025_radio_folder, self.v2025_radio_file):
            w.setEnabled(v2025_active)

        # Arrow
        for w in (self.opt_arrow_1000, self.opt_arrow_100, self.opt_arrow_10):
            w.setEnabled(arrow_active)

    def _update_ok_enabled(self):
        ok_enabled = False
        if self.grp_v2022.isChecked():
            ok_enabled = (
                self.opt_v2022_north.isChecked() or self.opt_v2022_south.isChecked()
            )
        elif self.grp_v2023.isChecked():
            ok_enabled = (
                self.opt_v2023_north.isChecked() or self.opt_v2023_south.isChecked()
            )
        elif self.grp_v2025.isChecked():
            ok_enabled = True
        elif self.grp_arrow.isChecked():
            ok_enabled = (
                self.opt_arrow_1000.isChecked()
                or self.opt_arrow_100.isChecked()
                or self.opt_arrow_10.isChecked()
            )
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(ok_enabled)

    # ----------------- selection helpers -----------------
    def _get_saveto(self):
        if self.opt_save_flight.isChecked():
            return "Measure Flight Folder"
        if self.opt_save_calib.isChecked():
            return "Calibration Flight Folder"
        if self.opt_save_diurnal.isChecked():
            return "Diurnal Data Folder"
        return "Measure Flight Folder"

    def get_selection(self):
        """Return selection dict based on current UI."""
        sel = {"saveto": self._get_saveto()}

        if self.grp_v2022.isChecked():
            sel["device"] = "Mag Hawk V2022"
            sel["option"] = {
                "hemisphere": (
                    "Northern Hemisphere"
                    if self.opt_v2022_north.isChecked()
                    else "Southern Hemisphere"
                ),
                "mode": (
                    "folder"
                    if self.v2022_radio_folder.isChecked()
                    else ("file" if self.v2022_radio_file.isChecked() else None)
                ),
            }
            return sel

        if self.grp_v2023.isChecked():
            sel["device"] = "Mag Hawk V2023"
            sel["option"] = {
                "hemisphere": (
                    "Northern Hemisphere"
                    if self.opt_v2023_north.isChecked()
                    else "Southern Hemisphere"
                ),
                "mode": (
                    "folder"
                    if self.v2023_radio_folder.isChecked()
                    else ("file" if self.v2023_radio_file.isChecked() else None)
                ),
            }
            return sel

        if self.grp_v2025.isChecked():
            sel["device"] = "Mag Hawk V2025"
            sel["option"] = {
                "mode": (
                    "folder"
                    if self.v2025_radio_folder.isChecked()
                    else ("file" if self.v2025_radio_file.isChecked() else None)
                ),
            }
            return sel

        if self.grp_arrow.isChecked():
            sel["device"] = "Mag Arrow"
            rate = None
            if self.opt_arrow_1000.isChecked():
                rate = "1000Hz"
            elif self.opt_arrow_100.isChecked():
                rate = "100Hz"
            elif self.opt_arrow_10.isChecked():
                rate = "10Hz"
            sel["option"] = {"rate": rate}
            return sel

        return None

    # ----------------- OK handler (validate + save cfg + accept) -----------------
    def _on_accept(self):
        sel = self.get_selection()
        if not sel:
            # 방어적: 이론상 OK가 비활성화되어 여기 못 옴
            return

        # cfg로 직렬화 (저장 포맷 유지)
        new_cfg = {
            "device": sel.get("device"),
            "option": {},
            "saveto": sel.get("saveto"),
        }

        opt = sel.get("option") or {}
        if new_cfg["device"] in ("Mag Hawk V2022", "Mag Hawk V2023"):
            # hemisphere & mode
            if "hemisphere" in opt:
                new_cfg["option"]["hemisphere"] = opt["hemisphere"]
            if "mode" in opt:
                new_cfg["option"]["mode"] = opt["mode"]
        elif new_cfg["device"] == "Mag Hawk V2025":
            if "mode" in opt:
                new_cfg["option"]["mode"] = opt["mode"]
        elif new_cfg["device"] == "Mag Hawk Arrow":
            if "rate" in opt:
                new_cfg["option"]["rate"] = opt["rate"]

        # 외부 config에 저장
        try:
            config.set("dataloaddlg", new_cfg)
            config.save()
        except Exception:
            # 저장 실패는 다이얼로그 진행 자체를 막을 필요는 없다고 판단(로그는 호출측에서)
            logger.exception("Failed to save data load dialog settings")
            pass

        # 선택 결과 보관 후 accept
        self.selection = sel
        self.accept()


class Converter(QThread):
    # TaskProgressDialog가 기대하는 표준 시그널들
    maximum = Signal(int)  # 전체 작업 개수
    progress = Signal(int)  # 현재 진행 값 (0..N)
    text = Signal(str)  # 상태 메시지
    finished_ok = Signal()  # 정상 완료
    failed = Signal(str)  # 실패/취소 (사유 메시지)

    def __init__(self, files=None, folder=None, selection=None, parent=None):
        super().__init__(parent)
        self.files = list(files or [])
        self.folder = folder or ""
        self.selection = selection or {}
        self._cancel = False
        self.MagHawkConverter = DataConverter()
        proj_path = config.get("project_path")
        saveto = self.selection.get("saveto")
        self.saved_folder_path = os.path.join(proj_path, saveto)
        os.makedirs(self.saved_folder_path, exist_ok=True)
        self.processed_folder_path = os.path.join(proj_path, ".processed")

    # TaskProgressDialog.canceled → bind_worker()에서 호출될 메서드
    def stop(self):
        self._cancel = True

    def _collect_files(self):
        """selection 정보를 바탕으로 실제 변환 대상 파일 리스트 구성"""
        dev = self.selection.get("device") or ""
        option = self.selection.get("option") or {}
        mode = option.get("mode") or ""
        # Arrow는 파일 다중 선택
        if "Mag Arrow" in dev:
            return list(self.files)

        # V2022/V2023/V2025: file 모드면 files, folder 모드면 폴더 내 확장자 매칭
        if mode == "file":
            return list(self.files)

        # folder 모드
        if not self.folder:
            return []

        # 필요 시 장치별 패턴 분기 가능. 기본은 *.dat
        patterns = ["*.dat"]
        results = []
        for p in patterns:
            results.extend(glob.glob(os.path.join(self.folder, p)))
        return sorted(set(results))

    def run(self):
        try:
            targets = self._collect_files()
            n = len(targets)

            # 다이얼로그에 전체 개수 알림 + 진행 0으로 초기화
            self.maximum.emit(n)
            self.progress.emit(0)

            if n == 0:
                msg = "No input files to convert."
                logger.warning("Conversion aborted because no input files were found")
                self.text.emit(msg)
                self.failed.emit(msg)
                return

            device = self.selection.get("device")
            logger.info(
                f"Starting data conversion: device={device}, files={n}, destination={self.saved_folder_path}"
            )
            if device[:8] == "Mag Hawk":
                parent_dir = os.path.dirname(targets[0])
                last_folder = os.path.basename(parent_dir)
                processed_dir = os.path.join(self.processed_folder_path, last_folder)
                os.makedirs(processed_dir, exist_ok=True)
                hemi = self.selection.get("option")["hemisphere"]

            for i, fpath in enumerate(targets, start=1):
                if self._cancel:
                    msg = "Conversion cancelled by user."
                    logger.warning("Data conversion cancelled by user")
                    self.text.emit(msg)
                    self.failed.emit(msg)
                    return

                status = f"Converting: {os.path.basename(fpath)} ({i}/{n})"
                self.text.emit(status)
                if device == "Mag Arrow":
                    import_mag_arrow_file(
                        fpath, self.saved_folder_path, self.selection
                    )
                else:
                    basename = os.path.basename(fpath)
                    name_only, ext = os.path.splitext(basename)
                    output = os.path.join(processed_dir, name_only + ".csv")
                    self.MagHawkConverter.convert_file(fpath, output, "csv", 1000, hemi)

                # i개 처리 완료 → 진행값 i로 갱신
                self.progress.emit(i)

            if device[:8] == "Mag Hawk":
                self.MagHawkConverter.merge_csv_files_in_folder(
                    processed_dir, self.saved_folder_path, "1Hz"
                )

            logger.info(
                f"Completed data conversion: device={device}, files={n}, destination={self.saved_folder_path}"
            )
            self.text.emit("Done")
            self.finished_ok.emit()

        except Exception as e:
            logger.exception("Converter.run error")
            self.failed.emit(f"Error: {e}")


class TaskProgressDialog(QProgressDialog):
    """
    QProgressDialog를 깔끔하게 감싼 공용 진행창.
    - worker.maximum(int)  : 전체 작업 수(최대값) 연결
    - worker.progress(int) : 현재 진행 단계(값) 연결
    - worker.text(str)     : 라벨 텍스트 연결
    - worker.finished_ok() : 정상 완료 시 accept()
    - worker.failed(str)   : 실패 시 메시지 보여주고 reject()
    - canceled()           : 사용자가 취소 시 worker.stop() 호출
    """

    def __init__(
        self, label: str = "작업 중...", cancel_text: str = "취소", parent=None
    ):
        super().__init__(label, cancel_text, 0, 0, parent)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle("Progress")
        self.setAutoReset(False)
        self.setAutoClose(False)
        self.setMinimumDuration(0)  # 즉시 표시

    def bind_worker(self, worker: QThread):
        # Worker → Dialog
        if hasattr(worker, "maximum"):
            worker.maximum.connect(self.setMaximum)
        if hasattr(worker, "progress"):
            worker.progress.connect(self.setValue)
        if hasattr(worker, "text"):
            worker.text.connect(self.setLabelText)

        # 완료/실패
        if hasattr(worker, "finished_ok"):
            worker.finished_ok.connect(self.accept)
        # 실패 시 메시지 보여주고 닫기
        if hasattr(worker, "failed"):
            worker.failed.connect(
                lambda msg: (self.setLabelText(f"오류: {msg}"), self.reject())
            )

        # 취소 누르면 worker 정지
        self.canceled.connect(getattr(worker, "stop", lambda: None))


def convert_with_progress(files=None, folder=None, selection=None, parent=None):
    progress = TaskProgressDialog(parent=parent)
    worker = Converter(files, folder, selection, parent)
    progress.bind_worker(worker)
    worker.start()
    progress.exec_()
    return progress.result
