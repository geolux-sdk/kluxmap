# KLuxMap 코드 리뷰 (2026-06-24)

PySide6 기반 자기탐사(magnetic survey) 데이터 처리 GUI 애플리케이션, 약 11,600줄 / 16개 Python 모듈을 4개 영역으로 나눠 리뷰한 결과입니다. 전체 코드 품질은 양호합니다 — 파일 IO는 일관되게 `with` + `encoding="utf-8"`를 쓰고, loguru 로깅과 설정 영속화 구조가 깔끔합니다. 아래는 **확인된 버그** 위주의 목록입니다.

> 본 문서는 읽기 전용 분석 결과이며, 작성 시점에 코드 수정은 하지 않았습니다.

## 🔴 HIGH — 실제 버그 (우선 수정 권장)

### 1. 장치명 불일치로 Arrow "rate" 설정이 저장되지 않음 — ✅ 수정 완료 (2026-06-24)
- 위치: `myConvertDlg.py:486` vs `myConvertDlg.py:523`
- `get_selection()`은 `sel["device"] = "Mag Arrow"`로 설정하지만, `_on_accept()`의 직렬화는 `elif new_cfg["device"] == "Mag Hawk Arrow":`를 검사함. 이 분기는 절대 실행되지 않아 사용자가 선택한 `rate`(1000/100/10Hz)가 config에 저장되지 않음.
- 수정: 523행을 `"Mag Arrow"`로 통일.
- **상태: 해결됨.** `myConvertDlg.py:523`이 `elif new_cfg["device"] == "Mag Arrow":`로 수정되어 486행과 일치, `rate`가 정상 저장됨.

### 2. `convert_with_progress`가 메서드 객체를 반환 — ✅ 수정 완료 (2026-06-24)
- 위치: `myConvertDlg.py:713`
- `return progress.result` → `QDialog.result`는 메서드. `progress.result()`로 호출해야 실제 accept/reject 코드가 반환됨. (현재 호출자가 무시 중이라 잠재 버그)
- 수정: `return progress.result()`.
- **상태: 해결됨.** `myConvertDlg.py:713`이 `return progress.result()`로 수정됨.

### 3. `Converter.__init__`이 프로젝트 경로 없을 때 크래시 — ⚠️ 오판정 정정 (실제 버그 아님)
- 위치: `myConvertDlg.py:556-560`
- 최초 우려: `proj_path = config.get("project_path")`가 `None`이면 `os.path.join(None, ...)`에서 `TypeError`.
- **재검토 결과(2026-06-24): 정상 흐름에서 도달 불가.**
  - `convert_action`은 초기 비활성(`mainWindow.py:172`)이며 프로젝트를 열/생성할 때만 `_set_menu_actions_enabled(True)`로 활성화됨(`mainWindow.py:343`). 그 시점에 `project_path`가 반드시 설정됨(`mainWindow.py:377`, `:455`).
  - `saveto`는 `get_selection()`에서 `self._get_saveto()`로 항상 문자열을 반환(`myConvertDlg.py:440`).
- 결론: HIGH 버그 아님. 굳이 보강하려면 방어적 가드를 두는 정도의 LOW 항목.

### 4. V1 파서에 빈 데이터 / 0 분할 가드 누락 — ✅ 수정 완료 (2026-06-24)
- 위치: `Data_Parse.py:124-127`
- `parse_input_data_v2025`는 `subsample <= 0`과 `num_groups == 0`을 막지만, 레거시 `parse_input_data`에는 동일 가드가 없어 짧은 입력에서 `ZeroDivisionError` 또는 빈 프레임 연산으로 깨짐.
- 수정: v2025와 동일한 가드 추가.
- **상태: 해결됨.** `parse_input_data`에 `subsample <= 0`/`num_groups == 0` 가드를 추가해 두 경우 모두 `_empty_output_dataframe()`를 반환함 (커밋 8e9ff64).

### 5. `df.columns.get_loc(selected_col_name)`이 "Mag" 부재 시 KeyError — ✅ 수정 완료 (2026-06-24)
- 위치: `LinePlotWidget.py:497`
- 클릭한 스캔라인 CSV에 해당 컬럼이 없거나 df가 비어 있으면 클릭 핸들러가 크래시.
- 수정: 컬럼 존재 / 빈 df 검증 후 폴백.
- **상태: 해결됨.** `on_item_clicked`에서 `df.empty` 또는 컬럼 부재 시 표만 채우고 조기 리턴하도록 가드 추가 (커밋 911ea8c).

### 6. `plt.cm.get_cmap("jet")` — matplotlib ≥3.9에서 제거됨 — ✅ 수정 완료 (2026-06-24)
- 위치: `FlightPlotWidget.py:1916`
- 설치된 버전에 따라 `AttributeError`로 런타임 크래시. `LinePlotWidget.py:405`는 올바르게 `plt.get_cmap`을 씀.
- 수정: `plt.get_cmap("jet")`으로 통일.
- **상태: 해결됨.** `plt.get_cmap("jet")`으로 변경. 설치된 matplotlib 3.10.7에서 발생하던 활성 크래시 제거 (커밋 5ae646a).

## 🟠 MEDIUM

### 7. `filtering()`이 루프 변수 `df`를 루프 밖에서 사용 — ✅ 수정 완료 (2026-06-24)
- 위치: `LinePlotWidget.py:796`
- 루프 종료 후 마지막 반복의 `df`로 `col_name`을 정하고 이를 **모든** 스캔라인에 적용. `scanline_df`가 비면 `df` 미정의로 `NameError`.
- 수정: 빈 dict 가드 + col_name을 결정적으로 계산.
- **상태: 해결됨.** 빈 `scanline_df` 조기 리턴 가드 추가, `col_name`을 필터 적용 순서(diurnal→igrf→median→lowpass→calibration) 기준으로 결정적으로 산출 (커밋 a08a8b6).

### 8. `_apply_calibration`이 조기 종료 시 `None` 반환 — ✅ 수정 완료 (2026-06-24)
- 위치: `LinePlotWidget.py:1111-1137` (1114, 1117, 1131행)
- 다른 필터 헬퍼는 모두 `return filtered_mag`인데 이것만 `return`(None). 현재는 체인의 마지막이라 영향이 제한적이나, 필터 순서를 바꾸면 즉시 깨지는 잠재 버그.
- 수정: 조기 종료 분기에서도 `filtered_mag` 반환.
- **상태: 해결됨.** 세 조기 종료 분기(disabled / X·Y 컬럼 부재 / direction None)를 모두 `return filtered_mag`로 변경 (커밋 8762a19).

### 9. 필터 적용 중 예외를 삼키고 부분 데이터로 진행 — ✅ 수정 완료 (2026-06-24)
- 위치: `DataManager.py:216-218`
- `except Exception`으로 로깅만 하고 `if df.empty` 분기로 떨어져, 중간에 실패한 부분 필터링 결과를 정상처럼 반환.
- 수정: except 내에서 `return None` 또는 재발생.
- **상태: 해결됨.** `get_filtered_data`의 `except` 블록에서 `return None`을 추가해, 필터 도중 실패 시 부분 데이터 대신 `None`을 반환하도록 변경. 호출자 `get_filtered_intervals`는 `None`을 빈 리스트로 안전 처리함.

### 10. KDTree에 NaN 좌표 유입 가능
- 위치: `micro_levelling_medain_filter.py:158-164` (+ `:111`)
- `pd.to_numeric(..., errors="coerce")`로 비수치값이 NaN이 되면 `cKDTree`가 미정의/garbage 이웃 결과를 냄.
- 수정: 트리 생성 전 NaN 좌표 행 마스킹/검증. `median2d_on`은 입력을 `np.asarray(values, float)`로 강제.

### 11. 공유 가변 config dict 참조 — ⚠️ 오판정 정정 (의도된 설계)
- 위치: `kriging_dialog.py:341`
- 최초 우려: `self.filters = config.get("kriging", {})`가 라이브 dict를 반환해 여러 다이얼로그가 상태를 공유/덮어쓸 수 있음.
- **재검토 결과(2026-06-24): 의도된 설계.** 다이얼로그의 변경을 전역 config에 즉시 반영하기 위해 라이브 참조를 일부러 사용함. kriging 다이얼로그를 동시에 여러 개 띄우는 흐름이 없으므로 상호 간섭 위험도 실재하지 않음.
- 결론: 버그 아님. 복사가 필요한 경우는 동시 오픈 시나리오가 생길 때뿐.

### 12. 콜백 / close 정리 시 `self.im` / `parent()` 가정 — ✅ 수정 완료 (2026-06-24)
- 위치: `kriging_dialog.py:1413-1430`
- `hasattr(self, "colorbar")`는 `None`으로 초기화돼 항상 True → kriging 실패 후 콜러바 클릭 시 `self.im.get_clim()`이 `AttributeError`. closeEvent의 `self.parent()`도 teardown 중 None 가능.
- 수정: 저장된 `self.parentWindow` 사용 + `self.im` 존재 검사.
- **상태: 해결됨.** `on_canvas_click`을 `self.colorbar is None or not hasattr(self, "im")` 조기 리턴으로 가드(811·925행과 동일 관례). `closeEvent`는 teardown 중 None이 될 수 있는 `self.parent()` 대신 `self.parentWindow`를 사용.

## 🟡 LOW / 정리

- **하드코딩된 Google Maps API 키가 소스에 커밋됨** — `FlightPlotWidget.py:14`. 즉시 회수/회전하고 env·settings에서만 로드. (가장 시급한 보안 항목)
- **클라이언트 측 라이선스 만료 체크** — `main.py:18,49` `LICENSE_EXPIRY_DATE = 2026-10-01`. 약 3개월 뒤(2026-06-24 기준) 경고/유예 없이 하드 스톱하며 소스 수정·시계 롤백으로 우회 가능. 사전 경고 기간 + env/settings 설정값화 권장.
- **죽은 코드**:
  - `Data_Parse.py:517` 읽고 버려지던 CSV 로드 — ✅ 수정 완료(주석 처리됨). 단, 남은 주석 라인 자체는 삭제 권장.
  - `FlightPlotWidget.py:94` 값 버리는 `config.get("filters", {})` — ✅ 수정 완료(2026-06-24, 주석 처리). 줄 번호 보존을 위해 삭제 대신 주석 처리함.
  - ~~`parse_input_data` vs `parse_input_data_v2025` 중복~~ — **오판정 정정**: 내용이 비슷하나 처리 형식이 다른 별개 로직으로, 중복 아님.
- **오타**: `CalibrationFlightWidget.py:690` `_main_direiion_str`(미사용), `myWidgets.py` `browse_multidirectiorys`.
- **deprecated API**: `datetime.utcnow()`(`LinePlotWidget.py:980`), `QDialog.exec_()`(`myConvertDlg.py:712`), `ContourSet.collections`(`kriging_dialog.py:1272`).
- **pyplot 전역 등록 figure 누수**: LinePlotWidget/FlightPlotWidget은 `plt.subplots`를 쓰는데, CalibrationFlightWidget처럼 `Figure(...)` 직접 생성이 위젯 재생성 시 누수가 없어 일관적임.

## 검증 완료 / 이상 없음 (참고)
- `segment_utils.py`의 interval 알고리즘(`normalize`/`intersect`/`subtract`/`split_by_cuts`) — `[start, end)` 시맨틱으로 off-by-one 없음.
- `ppigrf.py`의 `geod2geoc(lat, h, h, h)` 더미 인자는 의도된 좌표 변환 용법.
- `direction_utils.py`의 `arctan2(dx, dy)`(나침반 방위, 0=북) 및 `classify_heading` 경계값은 정상.

## 우선순위 제안
1. **#1, #2, #3** — 변환 다이얼로그의 확정 로직 버그 / 크래시
2. **#6** — matplotlib 버전 의존 크래시
3. **Google Maps API 키 회수**
4. **#4, #5, #7** — 엣지케이스 크래시 방어

---
*리뷰 도구: Claude Code (모듈별 병렬 분석). 행 번호는 2026-06-24 기준 `main` 브랜치(커밋 b8d9434) 시점.*
