import os

import geopandas as gpd
import numpy as np
import pandas as pd
from loguru import logger
from shapely.geometry import Point, Polygon

import mySettings
from mySettings import config


class DataManager:
    def __init__(self, settings: mySettings):
        self.settings = settings
        self.combined_df = pd.DataFrame()

    def clear_FlightData(self):
        logger.debug("clear_FlightData")
        self.fileDataBase = {}

    def load_FlightData(self, file_name):
        basename = os.path.basename(file_name)
        try:
            self.fileDataBase[basename] = self._convert(pd.read_csv(file_name))
        except Exception as e:
            logger.error(f"Error loading {file_name}: {e}")

    def merge_CSVtodf(self, files) -> pd.DataFrame | None:
        """여러 CSV 파일을 하나의 DataFrame으로 병합해서 리턴"""
        df_list = []
        for file_name in files:
            try:
                df = pd.read_csv(file_name)
                df = self._convert(df)  # 기존 변환 함수 적용
                df_list.append(df)
            except Exception as e:
                logger.error(f"Error loading {file_name}: {e}")

        if not df_list:
            logger.warning("No CSV files merged.")
            return None

        # ignore_index=True로 새 인덱스 생성
        merged_df = pd.concat(df_list, ignore_index=True)
        return merged_df

    def _convert(self, df):
        df["record_id"] = range(len(df))
        # 중앙값 기반으로 존/반구 결정(노이즈에 덜 민감)
        try:
            lat_med = float(pd.to_numeric(df["Latitude"], errors="coerce").median())
            lon_med = float(pd.to_numeric(df["Longitude"], errors="coerce").median())
            if np.isnan(lat_med) or np.isnan(lon_med):
                raise ValueError("lat/lon contains no valid numeric values.")
            epsg_code = self._latlon_to_utm_epsg(lat_med, lon_med)
        except Exception as e:
            logger.error(f"Failed to infer UTM EPSG from lat/lon: {e}")
            # 기본값(한국 대부분 52N)으로 폴백하거나, 변환 생략 가능
            epsg_code = 32652
            logger.warning(f"Fallback to EPSG:{epsg_code}")

        # GeoDataFrame 변환
        try:
            gdf = gpd.GeoDataFrame(
                df.copy(),
                geometry=[Point(xy) for xy in zip(df["Longitude"], df["Latitude"])],
                crs="EPSG:4326",
            ).to_crs(epsg=epsg_code)

            df["X"] = gdf.geometry.x
            df["Y"] = gdf.geometry.y
            df["CRS_EPSG"] = epsg_code  # (선택) 현재 좌표계 기록
            logger.debug(f"Lat/Lon → UTM(EPSG:{epsg_code}) 변환 완료.")
        except Exception as e:
            logger.error(f"Error converting lat/lon to UTM: {e}")

        return df

    @staticmethod
    def _latlon_to_utm_epsg(lat: float, lon: float) -> int:
        """
        주어진 위도/경도로 UTM EPSG 코드를 반환.
        북반구: 326xx, 남반구: 327xx
        """
        # 경도 -180~180 범위를 벗어나면 정규화
        if lon < -180 or lon > 180:
            lon = ((lon + 180) % 360) - 180
        zone = int((lon + 180) / 6) + 1
        if zone < 1:
            zone = 1
        elif zone > 60:
            zone = 60
        return (32600 if lat >= 0 else 32700) + zone

    def get_FlightData(self, file_name):
        return self.fileDataBase.get(file_name)

    def get_XYMagData(self, df):
        return df["X"], df["Y"], df["Mag"]

    def get_filtered_data(self, df, settings):
        logger.debug(settings)
        try:
            # df = self.filter_by_dist(df, 1.0)
            # if df.empty:
            #     logger.warning("Filtered DataFrame is empty.")
            #     return None

            if settings.get("show_area_bound", False):
                df = self.boundary_rejection(df, config.get("bound_area_points"))
            if df.empty:
                logger.warning("Filtered DataFrame is empty.")
                return None

            if settings["direction_filter"].get("enabled", False):
                df = self.filter_cardinal_directions(
                    df, settings["direction_filter"].get("threshold", 5)
                )
            if df.empty:
                logger.warning("Filtered DataFrame is empty.")
                return None

            if settings["continuity_filter"].get("enabled", False):

                df = self.filter_by_continuous_record_id(
                    df, settings["continuity_filter"]["num_points"]
                )
            if df.empty:
                logger.warning("Filtered DataFrame is empty.")
                return None

            if settings["speed_filter"].get("enabled", False):
                sp = settings["speed_filter"]
                df = self.filter_by_speed_using_counter(
                    df, sp["target_speed"], sp["tolerance"]
                )
            if df.empty:
                logger.warning("Filtered DataFrame is empty.")
                return None

        except Exception as e:
            logger.error(f"Error in get_filtered_data: {e}")

        if df.empty:
            logger.warning("Filtered DataFrame is empty.")
            return None

        return df

    def put_combined_df(self, df: pd.DataFrame):
        self.combined_df = pd.concat([self.combined_df, df], ignore_index=True)

    def clear_combined_df(self):
        self.combined_df = pd.DataFrame()

    def save_all_continuous_record_groups(
        self,
        output_dir: str,
        samping_rate: str,
        prefix: str = "line",
    ) -> list[str]:
        """
        record_id 기준으로 연속된 값들을 그룹으로 묶고,
        각 그룹을 CSV 파일로 저장합니다 (길이에 관계없이 모두 저장).

        Parameters
        ----------
        df : pd.DataFrame
            반드시 'record_id' 컬럼을 포함해야 함.
        output_dir : str
            저장할 디렉토리 경로
        prefix : str
            저장 파일 접두어 (예: group → group_000.csv)

        Returns
        -------
        list of str
            저장된 파일 경로 리스트
        """
        df = getattr(self, "combined_df", pd.DataFrame())
        if df is None or df.empty:
            return []

        if "record_id" not in df.columns:
            return []

        os.makedirs(output_dir, exist_ok=True)
        # df = df.sort_values("record_id").reset_index(drop=True)

        saved_files = []
        current_group = [df.iloc[0]]

        for i in range(1, len(df)):
            prev_id = df.iloc[i - 1]["record_id"]
            curr_id = df.iloc[i]["record_id"]

            if curr_id == prev_id + 1:
                current_group.append(df.iloc[i])
            else:
                group_df = pd.DataFrame(current_group)
                file_path = os.path.join(
                    output_dir,
                    f"{prefix}_{(len(saved_files)+1):03d}.csv",
                )
                group_df.to_csv(file_path, index=False)
                logger.debug(f"Saved group to {file_path}")
                saved_files.append(file_path)
                current_group = [df.iloc[i]]

        # 마지막 그룹 저장
        if current_group:
            group_df = pd.DataFrame(current_group)
            file_path = os.path.join(
                output_dir, f"{prefix}_{(len(saved_files)+1):03d}.csv"
            )
            group_df.to_csv(file_path, index=False)
            logger.debug(f"Saved last group to {file_path}")
            saved_files.append(file_path)

        return saved_files

    # def filter_straight_segments(
    #     self, df: pd.DataFrame, angle_change_threshold_deg: float = 1.0
    # ) -> pd.DataFrame:
    #     """
    #     방향 변화량(각도 변화)이 angle_change_threshold_deg 이하인 연속 구간만 유지
    #     → 직선 구간만 유지하고 회전 구간 제거
    #     """
    #     if "X" not in df.columns or "Y" not in df.columns:
    #         raise ValueError("DataFrame must contain 'X' and 'Y' columns.")

    #     # 1. 이동 방향 계산 (북 기준, 시계방향)
    #     dx = df["X"].diff()
    #     dy = df["Y"].diff()
    #     directions = (np.degrees(np.arctan2(dx, dy)) + 360) % 360

    #     # 2. 방향 변화량 계산 (Δθ, angle difference)
    #     delta_angle = directions.diff().abs()
    #     delta_angle = delta_angle.map(
    #         lambda x: 360 - x if x > 180 else x
    #     )  # 최소각 계산

    #     # 3. 기준 이하인 경우만 유지 (회전이 크지 않은 직선)
    #     mask = delta_angle < angle_change_threshold_deg
    #     mask.iloc[0:2] = False  # 첫 2개는 diff로 NaN/불확정 → 제외

    #     return df[mask.fillna(False)].copy()

    # def filter_cardinal_directions(
    #     self,
    #     df: pd.DataFrame,
    #     tolerance_deg: float = 5.0,
    #     step: int = 10,  # ← N개 뒤와 비교
    # ) -> pd.DataFrame:
    #     """
    #     XY 변화 방향이 동/서/남/북 (0°, 90°, 180°, 270°) ± tolerance_deg 이내인 경우만 유지
    #     방향은 현재 지점 → step개 뒤 지점 벡터 기준으로 계산.
    #     """
    #     if not {"X", "Y"}.issubset(df.columns):
    #         raise ValueError("DataFrame must contain 'X' and 'Y' columns.")

    #     # 현재 → step개 뒤 점으로 향하는 벡터
    #     x_next = df["X"].shift(-step)
    #     y_next = df["Y"].shift(-step)
    #     dx = x_next - df["X"]
    #     dy = y_next - df["Y"]

    #     # 이동 방향(북 기준, 시계방향). 기존 코드 컨벤션 유지: arctan2(dx, dy)
    #     directions = (np.degrees(np.arctan2(dx, dy)) + 360) % 360

    #     # 기준 각도: 동서남북
    #     targets = [0, 90, 180, 270]

    #     # tolerance 이내 포함 여부 마스크
    #     mask = pd.Series(False, index=df.index)
    #     for target in targets:
    #         lower = (target - tolerance_deg) % 360
    #         upper = (target + tolerance_deg) % 360
    #         if lower < upper:
    #             mask |= (directions >= lower) & (directions <= upper)
    #         else:
    #             # 360도 래핑 구간
    #             mask |= (directions >= lower) | (directions <= upper)

    #     # step개 뒤가 없는 마지막 step개 행은 NaN → 자동 제외
    #     return df.loc[mask.fillna(False)].copy()

    def filter_cardinal_directions(
        self, df: pd.DataFrame, tolerance_deg: float = 5.0
    ) -> pd.DataFrame:
        """
        XY 변화 방향이 동/서/남/북 (0°, 90°, 180°, 270°) ± tolerance_deg 이내인 경우만 유지
        """
        if "X" not in df.columns or "Y" not in df.columns:
            raise ValueError("DataFrame must contain 'X' and 'Y' columns.")

        dx = df["X"].diff()
        dy = df["Y"].diff()

        # 이동 방향 계산 (북 기준, 시계방향)
        directions = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
        directions.iloc[0] = np.nan  # 첫 행 제외

        # 기준 각도: 동서남북
        targets = [0, 90, 180, 270]

        # tolerance 이내 포함 여부 마스크 계산
        mask = pd.Series(False, index=df.index)
        for target in targets:
            lower = (target - tolerance_deg) % 360
            upper = (target + tolerance_deg) % 360

            if lower < upper:
                mask |= (directions >= lower) & (directions <= upper)
            else:
                # 360도 범위 넘어가는 경우
                mask |= (directions >= lower) | (directions <= upper)

        return df[mask.fillna(False)].copy()

    def filter_by_speed_using_counter(
        self, df: pd.DataFrame, target_speed: float, tolerance: float = 0.1
    ) -> pd.DataFrame:
        """
        'Counter' 컬럼(밀리초 단위 시간)을 기준으로 실제 시간 간격을 계산하고,
        XY 좌표 변화량을 통해 속도를 추정하여 특정 속도 범위 내 데이터만 필터링합니다.

        Parameters
        ----------
        df : pd.DataFrame
            'X', 'Y', 'Counter' 컬럼을 포함하는 DataFrame
        target_speed : float
            기준 속도 (m/s)
        tolerance : float
            허용 오차 (±)

        Returns
        -------
        pd.DataFrame
            속도 조건에 부합하는 행만 포함하는 DataFrame
        """
        if not {"X", "Y", "Counter"}.issubset(df.columns):
            raise ValueError("DataFrame must contain 'X', 'Y', and 'Counter' columns.")

        # 시간 차 (초 단위)
        dt = df["Counter"].diff().fillna(1) / 1000.0  # ms → sec

        # 이동 거리 (유클리드 거리)
        dx = df["X"].diff()
        dy = df["Y"].diff()
        dist = np.sqrt(dx**2 + dy**2)

        # 속도 계산 (m/s)
        speed = dist / dt.replace(0, np.nan)
        speed.iloc[0] = np.nan  # 첫 행은 비교 불가

        # 속도 범위 조건
        low, high = target_speed - tolerance, target_speed + tolerance
        mask = (speed >= low) & (speed <= high)

        return df[mask.fillna(False)].copy()

    def filter_by_continuous_record_id(
        self, df: pd.DataFrame, min_length: int = 5
    ) -> pd.DataFrame:
        """
        record_id 값이 연속되는 블록 중 길이가 min_length 미만인 것은 제거합니다.

        Parameters
        ----------
        df : pd.DataFrame
            'record_id' 컬럼을 포함한 DataFrame
        min_length : int
            유지할 연속 구간의 최소 길이

        Returns
        -------
        pd.DataFrame
            연속 길이 조건을 만족하는 record_id 블록만 유지한 DataFrame
        """
        if "record_id" not in df.columns:
            raise ValueError("DataFrame must contain 'record_id' column.")

        # record_id 차분이 1이 아닐 때 블록 나눔
        diff = df["record_id"].diff().fillna(1)
        block_id = (diff != 1).cumsum()

        # 블록별 크기 계산
        block_sizes = block_id.value_counts()

        # 유효한 블록만 선택
        valid_blocks = block_sizes[block_sizes >= min_length].index
        mask = block_id.isin(valid_blocks)

        return df[mask].copy().reset_index(drop=True)

    def boundary_rejection(
        self, df: pd.DataFrame, bound_points: list[tuple[float, float]]
    ) -> pd.DataFrame:
        """
        주어진 경계(bound_points) 외부의 데이터를 제거합니다.
        :param df: 원본 DataFrame
        :param bound_points: [(x1, y1), (x2, y2), ...] 형식의 좌표 리스트
        :return: 필터링된 DataFrame
        """
        if not bound_points or len(bound_points) < 3:
            logger.warning("Invalid or too few boundary points.")
            return df

        # --- 폴리곤 닫혀있는지 확인하고 자동으로 닫기 ---
        if bound_points[0] != bound_points[-1]:
            bound_points = bound_points + [bound_points[0]]
            logger.debug("Boundary polygon was not closed. Automatically closed it.")

        try:
            poly = Polygon(bound_points)
            if not poly.is_valid:
                logger.warning("Polygon is invalid.")
                return df

            # GeoDataFrame 생성 및 필터링
            gdf = gpd.GeoDataFrame(
                df.copy(),
                geometry=gpd.points_from_xy(df["X"], df["Y"]),
                crs="EPSG:3857",
            )
            # inside_mask = gdf.geometry.within(poly)
            inside_mask = gdf.geometry.apply(poly.covers)
            filtered = gdf[inside_mask].drop(columns="geometry")

            logger.debug(f"Boundary rejection: {len(df)} → {len(filtered)} rows")
            return filtered

        except Exception as e:
            logger.error(f"Boundary rejection failed: {e}")
            return df

    def filter_by_dist(self, df: pd.DataFrame, threshold: float = 1.0) -> pd.DataFrame:
        if not {"X", "Y"}.issubset(df.columns):
            raise ValueError("DataFrame must contain 'X' and 'Y' columns.")

        # 이동 거리 (유클리드 거리)
        dx = df["X"].diff()
        dy = df["Y"].diff()
        dist = np.sqrt(dx**2 + dy**2)

        # 첫 행은 비교 불가 → NaN 지정
        dist.iloc[0] = np.nan

        # threshold 이상만 유지
        mask = (dist >= threshold).fillna(False)

        # df와 같은 인덱스를 유지한 채 필터링
        return df.loc[mask].copy()
