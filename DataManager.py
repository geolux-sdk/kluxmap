from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from loguru import logger
from shapely.geometry import Point, Polygon

from direction_utils import (
    heading_from_deltas,
    heading_matches_project_directions,
)
from mySettings import config
from segment_utils import normalize_intervals


@dataclass
class Source:
    source_id: str
    path: str
    df: pd.DataFrame  # Treat as immutable; do not mutate in place.


@dataclass
class Timeline:
    timeline_id: str
    source_ids: list[str]
    offsets: list[int] = field(default_factory=list)
    length: int = 0

    def build_offsets(self, sources: dict[str, "Source"]) -> None:
        offsets: list[int] = []
        total = 0
        for source_id in self.source_ids:
            src = sources.get(source_id)
            if src is None:
                raise KeyError(f"Unknown source_id: {source_id}")
            offsets.append(total)
            total += len(src.df)
        self.offsets = offsets
        self.length = total

    def global_to_local(self, gidx: int) -> tuple[str, int]:
        if not self.offsets:
            raise ValueError("Offsets not built. Call build_offsets() first.")
        if gidx < 0 or gidx >= self.length:
            raise IndexError(f"Global index out of range: {gidx}")
        pos = bisect_right(self.offsets, gidx) - 1
        if pos < 0 or pos >= len(self.source_ids):
            raise IndexError(f"Global index out of range: {gidx}")
        local_idx = gidx - self.offsets[pos]
        return self.source_ids[pos], local_idx


@dataclass
class Segment:
    segment_id: str
    timeline_id: str
    intervals: list[tuple[int, int]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class DataManager:
    def __init__(self):
        self.sources: dict[str, Source] = {}
        self.timelines: dict[str, Timeline] = {}
        self.segments: dict[str, Segment] = {}
        self.active_timeline_id: str | None = None
        self.active_segment_ids: list[str] = []
        self.fileDataBase: dict[str, pd.DataFrame] = {}
        # DEPRECATED: legacy combined dataframe path.
        self.combined_df = pd.DataFrame()
        # Per-file scanline state from FlightPlot.
        self.scanline_df_by_file: dict[str, pd.DataFrame] = {}
        self.scanline_groups_by_file: dict[str, list[list[tuple[int, int]]]] = {}
        self.scanline_intervals_by_file: dict[str, list[tuple[int, int]]] = {}
        self.scanline_cross_groups: list[list[tuple[str, list[tuple[int, int]]]]] = []

    def clear_flight_data(self):
        self.fileDataBase = {}
        self.sources = {}
        self.timelines = {}
        self.segments = {}
        self.active_timeline_id = None
        self.active_segment_ids = []
        self.scanline_df_by_file = {}
        self.scanline_groups_by_file = {}
        self.scanline_intervals_by_file = {}
        self.scanline_cross_groups = []

    def load_flight_data(self, file_name):
        basename = Path(file_name).stem
        try:
            df = self._convert(pd.read_csv(file_name))
            self.sources[basename] = Source(
                source_id=basename, path=str(file_name), df=df
            )
            self.fileDataBase[basename] = df
        except Exception as e:
            logger.error(f"Error loading {file_name}: {e}")

    # DEPRECATED: legacy merge path; kept for compatibility.
    def merge_csv_to_df(self, files) -> pd.DataFrame | None:
        """Merge multiple CSV files into a single DataFrame."""
        df_list = []
        for file_name in files:
            try:
                df = pd.read_csv(file_name)
                df = self._convert(df)  # Apply the standard coordinate conversion.
                df_list.append(df)
            except Exception as e:
                logger.error(f"Error loading {file_name}: {e}")

        if not df_list:
            logger.warning("No CSV files merged.")
            return None

        # Rebuild the row index after concatenation.
        merged_df = pd.concat(df_list, ignore_index=True)
        return merged_df

    def _convert(self, df):
        df["record_id"] = range(len(df))
        # Infer the target UTM zone from the median lat/lon values.
        try:
            lat_med = float(pd.to_numeric(df["Latitude"], errors="coerce").median())
            lon_med = float(pd.to_numeric(df["Longitude"], errors="coerce").median())
            if np.isnan(lat_med) or np.isnan(lon_med):
                raise ValueError("lat/lon contains no valid numeric values.")
            epsg_code = self._latlon_to_utm_epsg(lat_med, lon_med)
        except Exception as e:
            logger.error(f"Failed to infer UTM EPSG from lat/lon: {e}")
            # Fall back to EPSG:32652 when inference is not possible.
            epsg_code = 32652
            logger.warning(f"Fallback to EPSG:{epsg_code}")

        # Convert WGS84 coordinates into the inferred UTM CRS.
        try:
            gdf = gpd.GeoDataFrame(
                df.copy(),
                geometry=[Point(xy) for xy in zip(df["Longitude"], df["Latitude"])],
                crs="EPSG:4326",
            ).to_crs(epsg=epsg_code)

            df["X"] = gdf.geometry.x
            df["Y"] = gdf.geometry.y
            df["CRS_EPSG"] = epsg_code  # Keep the active projected CRS in the table.
        except Exception as e:
            logger.error(f"Error converting lat/lon to UTM: {e}")

        return df

    @staticmethod
    def _latlon_to_utm_epsg(lat: float, lon: float) -> int:
        """
        Return the UTM EPSG code for the given latitude/longitude.
        Northern hemisphere uses 326xx, southern hemisphere uses 327xx.
        """
        # Normalize longitude into the valid [-180, 180] range.
        if lon < -180 or lon > 180:
            lon = ((lon + 180) % 360) - 180
        zone = int((lon + 180) / 6) + 1
        if zone < 1:
            zone = 1
        elif zone > 60:
            zone = 60
        return (32600 if lat >= 0 else 32700) + zone

    def get_flight_data(self, file_name):
        src = self.sources.get(file_name)
        if src is not None:
            return src.df
        return self.fileDataBase.get(file_name)

    def get_xy_mag_data(self, df):
        return df["X"], df["Y"], df["Mag"]

    def get_filtered_data(self, df, settings, degree):
        try:

            if settings.get("show_area_bound", False):
                df = self.boundary_rejection(df, config.get("bound_area_points"))
            if df.empty:
                return None

            if settings["direction_filter"].get("enabled", False):
                df = self.filter_cardinal_directions(
                    df, settings["direction_filter"].get("threshold", 5), degree=degree
                )
                # Drop intervals whose end-to-end direction no longer matches the target azimuth.
                df = self.filter_intervals_by_endpoint_angle(
                    df, settings["direction_filter"].get("threshold", 5), degree=degree
                )
            if df.empty:
                return None

            if settings["continuity_filter"].get("enabled", False):

                df = self.filter_by_continuous_record_id(
                    df, settings["continuity_filter"]["num_points"]
                )
            if df.empty:
                return None

            if settings["speed_filter"].get("enabled", False):
                sp = settings["speed_filter"]
                df = self.filter_by_speed_using_counter(
                    df, sp["target_speed"], sp["tolerance"]
                )
            if df.empty:
                return None

        except Exception as e:
            logger.exception("Error while applying flight data filters")

        if df.empty:
            return None

        return df

    def get_filtered_intervals(self, df, settings, degree) -> list[tuple[int, int]]:
        if df is None or df.empty:
            return []
        filtered = self.get_filtered_data(df, settings, degree)
        if filtered is None or filtered.empty:
            return []
        return self.df_to_intervals(filtered)

    def put_combined_df(self, df: pd.DataFrame):
        # DEPRECATED: legacy combined dataframe path.
        self.combined_df = pd.concat([self.combined_df, df], ignore_index=True)

    def clear_combined_df(self):
        self.combined_df = pd.DataFrame()

    def update_scanline_state(
        self,
        df_by_file: dict[str, pd.DataFrame] | None = None,
        groups_by_file: dict[str, list[list[tuple[int, int]]]] | None = None,
        intervals_by_file: dict[str, list[tuple[int, int]]] | None = None,
        cross_groups: list[list[tuple[str, list[tuple[int, int]]]]] | None = None,
    ) -> None:
        if df_by_file is None:
            self.scanline_df_by_file = {}
        else:
            self.scanline_df_by_file = dict(df_by_file)

        if groups_by_file is None:
            self.scanline_groups_by_file = {}
        else:
            self.scanline_groups_by_file = {
                key: [list(group) for group in groups]
                for key, groups in groups_by_file.items()
            }

        if intervals_by_file is None:
            self.scanline_intervals_by_file = {}
        else:
            self.scanline_intervals_by_file = {
                key: list(intervals) for key, intervals in intervals_by_file.items()
            }

        if cross_groups is None:
            self.scanline_cross_groups = []
        else:
            self.scanline_cross_groups = [
                [(fname, list(intervals)) for fname, intervals in group]
                for group in cross_groups
            ]

    def clear_segments_for_timeline(self, timeline_id: str) -> None:
        if not timeline_id:
            return
        to_remove = [
            seg_id
            for seg_id, seg in self.segments.items()
            if seg.timeline_id == timeline_id
        ]
        for seg_id in to_remove:
            self.segments.pop(seg_id, None)
        if self.active_segment_ids:
            self.active_segment_ids = [
                seg_id for seg_id in self.active_segment_ids if seg_id not in to_remove
            ]

    def reset_timeline(self, timeline_id: str, source_ids: list[str]) -> Timeline:
        timeline = self.timelines.get(timeline_id)
        if timeline is None:
            timeline = Timeline(timeline_id=timeline_id, source_ids=list(source_ids))
            self.timelines[timeline_id] = timeline
        else:
            if timeline.source_ids != list(source_ids):
                timeline.source_ids = list(source_ids)
        timeline.build_offsets(self.sources)
        self.active_timeline_id = timeline_id
        self.clear_segments_for_timeline(timeline_id)
        return timeline

    def create_timeline(self, timeline_id: str, source_ids: list[str]) -> Timeline:
        timeline = Timeline(timeline_id=timeline_id, source_ids=list(source_ids))
        timeline.build_offsets(self.sources)
        self.timelines[timeline_id] = timeline
        self.active_timeline_id = timeline_id
        return timeline

    def create_segment_from_range(
        self,
        segment_id: str,
        timeline_id: str,
        g0: int,
        g1: int,
        meta: dict[str, Any] | None = None,
    ) -> Segment:
        if g0 >= g1:
            raise ValueError(f"Invalid interval: [{g0}, {g1})")
        return self.create_segment(segment_id, timeline_id, [(g0, g1)], meta=meta)

    def create_segment(
        self,
        segment_id: str,
        timeline_id: str,
        intervals: list[tuple[int, int]],
        meta: dict[str, Any] | None = None,
    ) -> Segment:
        if timeline_id not in self.timelines:
            raise KeyError(f"Unknown timeline_id: {timeline_id}")
        cleaned = normalize_intervals(intervals)
        seg = Segment(
            segment_id=segment_id,
            timeline_id=timeline_id,
            intervals=cleaned,
            meta=dict(meta) if meta else {},
        )
        self.segments[segment_id] = seg
        if segment_id not in self.active_segment_ids:
            self.active_segment_ids.append(segment_id)
        return seg

    def df_to_intervals(self, df: pd.DataFrame) -> list[tuple[int, int]]:
        if df is None or df.empty:
            return []
        if "record_id" in df.columns:
            ids = pd.to_numeric(df["record_id"], errors="coerce").dropna()
            values = ids.astype(int).to_numpy()
        else:
            values = np.arange(len(df), dtype=int)
        if values.size == 0:
            return []
        values = np.unique(values)
        values.sort()

        intervals: list[tuple[int, int]] = []
        start = int(values[0])
        prev = int(values[0])
        for val in values[1:]:
            cur = int(val)
            if cur == prev + 1:
                prev = cur
                continue
            intervals.append((start, prev + 1))
            start = cur
            prev = cur
        intervals.append((start, prev + 1))
        return intervals

    def _iter_interval_slices(
        self, timeline: Timeline, g0: int, g1: int
    ) -> list[tuple[Source, int, int]]:
        if g0 >= g1:
            return []
        if not timeline.offsets:
            timeline.build_offsets(self.sources)
        if g0 < 0 or g1 > timeline.length:
            raise ValueError(
                f"Interval out of range: [{g0}, {g1}) length={timeline.length}"
            )

        slices: list[tuple[Source, int, int]] = []
        start_idx = bisect_right(timeline.offsets, g0) - 1
        if start_idx < 0:
            start_idx = 0
        for idx in range(start_idx, len(timeline.source_ids)):
            source_id = timeline.source_ids[idx]
            src = self.sources.get(source_id)
            if src is None:
                raise KeyError(f"Unknown source_id: {source_id}")
            start = timeline.offsets[idx]
            end = start + len(src.df)
            if g1 <= start:
                break
            if g0 >= end:
                continue
            local_start = max(g0, start) - start
            local_end = min(g1, end) - start
            if local_start < local_end:
                slices.append((src, int(local_start), int(local_end)))
        return slices

    def materialize_segment_df(
        self, segment_id: str, columns: list[str] | str | None = None
    ) -> pd.DataFrame:
        seg = self.segments.get(segment_id)
        if seg is None:
            raise KeyError(f"Unknown segment_id: {segment_id}")
        timeline = self.timelines.get(seg.timeline_id)
        if timeline is None:
            raise KeyError(f"Unknown timeline_id: {seg.timeline_id}")
        col_list: list[str] | None
        if columns is None:
            col_list = None
        elif isinstance(columns, str):
            col_list = [columns]
        else:
            col_list = list(columns)

        parts: list[pd.DataFrame] = []
        for g0, g1 in seg.intervals:
            for src, local_start, local_end in self._iter_interval_slices(
                timeline, g0, g1
            ):
                if col_list is None:
                    part = src.df.iloc[local_start:local_end].copy()
                else:
                    part = src.df.iloc[local_start:local_end][col_list].copy()
                if not part.empty:
                    parts.append(part)

        if not parts:
            if col_list is None:
                return pd.DataFrame()
            return pd.DataFrame(columns=col_list)

        return pd.concat(parts, ignore_index=True)

    def get_scatter_arrays(
        self,
        segment_id: str,
        x_col: str,
        y_col: str,
        c_col: str | None = None,
        stride: int = 1,
    ):
        if stride < 1:
            raise ValueError("stride must be >= 1")
        seg = self.segments.get(segment_id)
        if seg is None:
            raise KeyError(f"Unknown segment_id: {segment_id}")
        timeline = self.timelines.get(seg.timeline_id)
        if timeline is None:
            raise KeyError(f"Unknown timeline_id: {seg.timeline_id}")

        xs: list[np.ndarray] = []
        ys: list[np.ndarray] = []
        cs: list[np.ndarray] = []
        for g0, g1 in seg.intervals:
            for src, local_start, local_end in self._iter_interval_slices(
                timeline, g0, g1
            ):
                sl = slice(local_start, local_end, stride)
                xs.append(src.df[x_col].iloc[sl].to_numpy(copy=False))
                ys.append(src.df[y_col].iloc[sl].to_numpy(copy=False))
                if c_col is not None:
                    cs.append(src.df[c_col].iloc[sl].to_numpy(copy=False))

        if not xs:
            empty = np.array([], dtype=float)
            if c_col is None:
                return empty, empty
            return empty, empty, empty

        x_arr = np.concatenate(xs)
        y_arr = np.concatenate(ys)
        if c_col is None:
            return x_arr, y_arr
        c_arr = np.concatenate(cs) if cs else np.array([], dtype=float)
        return x_arr, y_arr, c_arr

    def _debug_dump(self) -> None:
        logger.info(
            "debug_dump: sources=%d timelines=%d segments=%d",
            len(self.sources),
            len(self.timelines),
            len(self.segments),
        )
        for timeline_id, timeline in self.timelines.items():
            logger.info(
                "debug_dump: timeline_id=%s length=%d sources=%d",
                timeline_id,
                timeline.length,
                len(timeline.source_ids),
            )

    def save_all_continuous_record_groups(
        self,
        output_dir: str,
        sampling_rate: str,
        prefix: str = "line",
    ) -> list[str]:
        """
        Group continuous `record_id` ranges and save each group as a CSV file.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain a `record_id` column.
        output_dir : str
            Output directory path.
        prefix : str
            Output file prefix, for example `group_000.csv`.

        Returns
        -------
        list of str
            Saved file paths.
        """
        df = getattr(self, "combined_df", pd.DataFrame())
        if df is None or df.empty or "record_id" not in df.columns:
            return []

        # Preserve the current row order and ensure `record_id` is numeric.
        work = df.copy()
        # work["record_id"] = pd.to_numeric(work["record_id"], errors="coerce")

        grp_labels = work["record_id"].diff().ne(1).cumsum()

        outdir = Path(output_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        saved_files: list[str] = []
        for idx, (_, g) in enumerate(work.groupby(grp_labels, sort=False), start=1):
            g = g.reset_index(drop=True)
            fpath = outdir / f"{prefix}_{idx}.csv"
            try:
                g.to_csv(fpath, index=False)
                saved_files.append(str(fpath))
            except Exception as e:
                logger.error(f"Failed to save group #{idx} to {fpath}: {e}")

        if saved_files:
            logger.info(
                f"Saved {len(saved_files)} continuous record group file(s) to {outdir}"
            )
        return saved_files

    def merge_and_save_scanlines_by_direction(
        self,
        output_dir: str,
        prefix: str = "line",
        angle_tol_deg: float = 5.0,
        join_gap_max: float = 20.0,
        exclude_endpoints_within: float = 40.0,
    ) -> list[str]:
        from pathlib import Path

        import numpy as np
        import pandas as pd

        def _line_order_value(df: pd.DataFrame) -> float:
            if df is None or df.empty or not {"X", "Y"}.issubset(df.columns):
                return float("inf")
            x = pd.to_numeric(df["X"], errors="coerce")
            y = pd.to_numeric(df["Y"], errors="coerce")
            mask = x.notna() & y.notna()
            if not mask.any():
                return float("inf")
            ref_x = float(x[mask].mean())
            ref_y = float(y[mask].mean())

            # Ignore the forward/backward sign of the project azimuth so
            # N/S and S/N share the same left->right ordering, and E/W and
            # W/E share the same top->bottom ordering.
            main_axis_deg = float(config.get("direction", 0) or 0) % 180.0
            cross_axis_deg = (main_axis_deg + 90.0) % 360.0
            ux = float(np.sin(np.deg2rad(cross_axis_deg)))
            uy = float(np.cos(np.deg2rad(cross_axis_deg)))
            return ref_x * ux + ref_y * uy

        scanline_df_by_file = getattr(self, "scanline_df_by_file", {})
        if scanline_df_by_file:
            saved_files: list[str] = []
            line_entries: list[dict[str, object]] = []
            groups_by_file = getattr(self, "scanline_groups_by_file", {}) or {}
            intervals_by_file = getattr(self, "scanline_intervals_by_file", {}) or {}
            cross_groups = getattr(self, "scanline_cross_groups", []) or []
            skip_groups: set[tuple[str, tuple[tuple[int, int], ...]]] = set()

            if cross_groups:
                for group in cross_groups:
                    for fname, intervals in group:
                        skip_groups.add((fname, tuple(intervals)))

                for group in cross_groups:
                    parts: list[pd.DataFrame] = []
                    for fname, intervals in group:
                        df = scanline_df_by_file.get(fname)
                        if df is None or df.empty:
                            continue
                        work = df
                        if "record_id" not in work.columns:
                            work = work.copy()
                            work["record_id"] = np.arange(len(work))
                        record_ids = pd.to_numeric(
                            work["record_id"], errors="coerce"
                        ).to_numpy()
                        if record_ids.size == 0:
                            continue
                        mask = np.zeros(len(work), dtype=bool)
                        for start, end in intervals:
                            mask |= (record_ids >= start) & (record_ids < end)
                        g = work.loc[mask].copy()
                        if g.empty:
                            continue
                        g["record_id"] = pd.to_numeric(
                            g["record_id"], errors="coerce"
                        )
                        g = g.sort_values("record_id").reset_index(drop=True)
                        parts.append(g)

                    if not parts:
                        continue

                    merged = pd.concat(parts, ignore_index=True)
                    line_entries.append(
                        {"df": merged, "order_value": _line_order_value(merged)}
                    )
            for filename, df in scanline_df_by_file.items():
                if df is None or df.empty:
                    continue
                work = df
                if "record_id" not in work.columns:
                    work = work.copy()
                    work["record_id"] = np.arange(len(work))
                record_ids = pd.to_numeric(
                    work["record_id"], errors="coerce"
                ).to_numpy()
                if record_ids.size == 0:
                    continue

                groups = groups_by_file.get(filename)
                if not groups:
                    intervals = intervals_by_file.get(filename)
                    if not intervals:
                        intervals = self.df_to_intervals(work)
                    groups = [[interval] for interval in intervals]

                for group in groups:
                    if not group:
                        continue
                    if (filename, tuple(group)) in skip_groups:
                        continue
                    mask = np.zeros(len(work), dtype=bool)
                    for start, end in group:
                        mask |= (record_ids >= start) & (record_ids < end)
                    g = work.loc[mask].copy()
                    if g.empty:
                        continue
                    g["record_id"] = pd.to_numeric(g["record_id"], errors="coerce")
                    g = g.sort_values("record_id").reset_index(drop=True)
                    line_entries.append({"df": g, "order_value": _line_order_value(g)})

            if not line_entries:
                return saved_files

            line_entries.sort(key=lambda item: item["order_value"])
            outdir = Path(output_dir)
            outdir.mkdir(parents=True, exist_ok=True)
            total = len(line_entries)
            width = max(2, len(str(total)))
            for entry in line_entries:
                g = entry["df"]
                idx = len(saved_files) + 1
                fpath = outdir / f"{prefix}_{idx:0{width}d}.csv"
                try:
                    g.to_csv(fpath, index=False)
                    saved_files.append(str(fpath))
                except Exception as e:
                    logger.error(
                        f"Failed to save group #{len(saved_files) + 1} to {fpath}: {e}"
                    )

            if saved_files:
                logger.info(
                    f"Saved {len(saved_files)} scanline group file(s) to {outdir}"
                )
            return saved_files

        df = getattr(self, "combined_df", pd.DataFrame())
        if df is None or df.empty or not {"record_id", "X", "Y"}.issubset(df.columns):
            return []

        work = df.copy()
        work["record_id"] = pd.to_numeric(work["record_id"], errors="coerce")

        # 1) Label continuous `record_id` groups while preserving the current order.
        grp_labels = work["record_id"].diff().ne(1).cumsum()
        groups = []
        for gid, g in work.groupby(grp_labels, sort=False):
            g = g.reset_index(drop=True)
            if len(g) == 0:
                continue
            dx = float(g["X"].iloc[-1]) - float(g["X"].iloc[0])
            dy = float(g["Y"].iloc[-1]) - float(g["Y"].iloc[0])
            angle = heading_from_deltas(dx, dy)
            groups.append(
                {
                    "gid": gid,
                    "df": g,
                    "n": len(g),
                    "start": (float(g["X"].iloc[0]), float(g["Y"].iloc[0])),
                    "end": (float(g["X"].iloc[-1]), float(g["Y"].iloc[-1])),
                    "angle": angle,
                }
            )

        if not groups:
            return []

        def _safe_order_value(value: float) -> float:
            try:
                order_value = float(value)
            except (TypeError, ValueError):
                return float("inf")
            return order_value if np.isfinite(order_value) else float("inf")

        groups.sort(key=lambda it: _safe_order_value(_line_order_value(it["df"])))

        # Merge-by-direction disabled; save each continuous record_id group as-is.
        saved_files: list[str] = []
        outdir = Path(output_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        total = len(groups)
        width = max(2, len(str(total)))
        for idx, item in enumerate(groups, start=1):
            g = item["df"].reset_index(drop=True)
            if "record_id" in g.columns:
                g["record_id"] = pd.to_numeric(g["record_id"], errors="coerce")
                g = g.sort_values("record_id").reset_index(drop=True)
            fpath = outdir / f"{prefix}_{idx:0{width}d}.csv"
            try:
                g.to_csv(fpath, index=False)
                saved_files.append(str(fpath))
            except Exception as e:
                logger.error(f"Failed to save group #{idx} to {fpath}: {e}")

        if saved_files:
            logger.info(f"Saved {len(saved_files)} scanline group file(s) to {outdir}")
        return saved_files

    def filter_cardinal_directions(
        self, df: pd.DataFrame, tolerance_deg: float = 5.0, degree=0
    ) -> pd.DataFrame:
        """
        XY 변화 방향이 동/서/남/북 (0°, 90°, 180°, 270°) + degree ± tolerance_deg 이내인 경우만 유지
        """
        if "X" not in df.columns or "Y" not in df.columns:
            raise ValueError("DataFrame must contain 'X' and 'Y' columns.")

        dx = df["X"].diff().to_numpy()
        dy = df["Y"].diff().to_numpy()
        directions = pd.Series(heading_from_deltas(dx, dy), index=df.index, dtype=float)
        directions.iloc[0] = np.nan  # Exclude the first row.
        mask = pd.Series(
            heading_matches_project_directions(
                directions.to_numpy(), degree, tolerance_deg
            ),
            index=df.index,
        )
        mask &= directions.notna()
        return df[mask.fillna(False)].copy()

    def filter_intervals_by_endpoint_angle(
        self, df: pd.DataFrame, tolerance_deg: float = 5.0, degree=0
    ) -> pd.DataFrame:
        """
        direction 필터 후, 연속 record_id 구간별로 시작-끝 벡터의 각도를 확인하여
        기준 방향(tolerance 범위) 밖이면 해당 구간 전체를 제거한다.
        """
        if df is None or df.empty or not {"X", "Y"}.issubset(df.columns):
            return df

        work = df.copy()
        if "record_id" not in work.columns:
            work["record_id"] = np.arange(len(work))
        work["record_id"] = pd.to_numeric(work["record_id"], errors="coerce")

        intervals = self.df_to_intervals(work)
        if not intervals:
            return work.iloc[0:0]

        keep_masks = []
        for start, end in intervals:
            mask = (work["record_id"] >= start) & (work["record_id"] < end)
            seg = work.loc[mask]
            if seg.empty:
                continue
            try:
                sx, sy = float(seg["X"].iloc[0]), float(seg["Y"].iloc[0])
                ex, ey = float(seg["X"].iloc[-1]), float(seg["Y"].iloc[-1])
            except Exception:
                continue
            dx = ex - sx
            dy = ey - sy
            angle = heading_from_deltas(dx, dy)
            if angle is None:
                continue
            if heading_matches_project_directions(angle, degree, tolerance_deg):
                keep_masks.append(mask)

        if not keep_masks:
            return work.iloc[0:0]

        final_mask = keep_masks[0].copy()
        for m in keep_masks[1:]:
            final_mask |= m
        return work.loc[final_mask].copy()

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

        # Time difference in seconds.
        dt = df["Counter"].diff().fillna(1) / 1000.0  # ms -> sec

        # Travel distance (Euclidean).
        dx = df["X"].diff()
        dy = df["Y"].diff()
        dist = np.sqrt(dx**2 + dy**2)

        # Compute speed in m/s.
        speed = dist / dt.replace(0, np.nan)
        speed.iloc[0] = np.nan  # The first row cannot be compared.

        # Speed range filter.
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

        # Split blocks whenever the record_id difference is not 1.
        diff = df["record_id"].diff().fillna(1)
        block_id = (diff != 1).cumsum()

        # Compute the size of each block.
        block_sizes = block_id.value_counts()

        # Select only valid blocks.
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

        # --- Ensure the polygon is closed; close it automatically if needed. ---
        if bound_points[0] != bound_points[-1]:
            bound_points = bound_points + [bound_points[0]]

        try:
            poly = Polygon(bound_points)
            if not poly.is_valid:
                logger.warning("Polygon is invalid.")
                return df

            # Build a GeoDataFrame and apply the polygon filter.
            gdf = gpd.GeoDataFrame(
                df.copy(),
                geometry=gpd.points_from_xy(df["X"], df["Y"]),
                crs="EPSG:3857",
            )
            inside_mask = gdf.geometry.apply(poly.covers)
            filtered = gdf[inside_mask].drop(columns="geometry")

            return filtered

        except Exception as e:
            logger.exception("Boundary rejection failed")
            return df

    def filter_by_dist(self, df: pd.DataFrame, threshold: float = 1.0) -> pd.DataFrame:
        if not {"X", "Y"}.issubset(df.columns):
            raise ValueError("DataFrame must contain 'X' and 'Y' columns.")

        # Travel distance (Euclidean).
        dx = df["X"].diff()
        dy = df["Y"].diff()
        dist = np.sqrt(dx**2 + dy**2)

        # The first row cannot be compared, so mark it as NaN.
        dist.iloc[0] = np.nan

        # Keep only rows at or above the threshold.
        mask = (dist >= threshold).fillna(False)

        # Filter while preserving the original dataframe index.
        return df.loc[mask].copy()
