import os
import re
import struct
from io import StringIO

import numpy as np
import pandas as pd
from loguru import logger
from scipy.ndimage import median_filter


class DataConverter:
    # 고정 상수
    ADS131A_SCALE_FACTOR = 4.0 / 0x800000
    VOLTAGE_TO_VALUE = 100 / 3.0
    CONVERSION_GAIN = VOLTAGE_TO_VALUE * ADS131A_SCALE_FACTOR
    LONGITUDE_FRAC_LEN = 5
    LATITUDE_FRAC_LEN = 5
    ALTITUDE_FRAC_LEN = 1
    BLOCK_FORMAT = "<2BHHHIIhH3i"

    def __init__(self):
        pass

    def gps_to_decimal(self, degrees_minutes):
        degrees = int(degrees_minutes // 100)
        minutes = degrees_minutes % 100
        return degrees + minutes / 60

    def parse_input_data(
        self, subsample: int, binary_data: bytes, date, hour
    ) -> pd.DataFrame:
        num_blocks = len(binary_data) // struct.calcsize(self.BLOCK_FORMAT)
        timestamp, position, adc_data = [], [], []

        for i in range(num_blocks):
            (
                minutes,
                seconds,
                subseconds,
                latitude,
                longitude,
                latitude_frac,
                longitude_frac,
                altitude,
                altitude_frac,
                *adc_values,
            ) = struct.unpack_from(
                self.BLOCK_FORMAT, binary_data, struct.calcsize(self.BLOCK_FORMAT) * i
            )

            latitude += latitude_frac / 10**self.LATITUDE_FRAC_LEN
            longitude += longitude_frac / 10**self.LONGITUDE_FRAC_LEN
            altitude += (altitude_frac / 10**self.ALTITUDE_FRAC_LEN) * (
                -1 if altitude <= 0 else 1
            )

            latitude = self.gps_to_decimal(latitude)
            longitude = self.gps_to_decimal(longitude)

            timestamp.append([int(minutes), int(seconds), int(subseconds)])
            position.append([longitude, latitude, altitude])
            adc_data.append(adc_values)

        df_timestamp = pd.DataFrame(
            timestamp, columns=["Minutes", "Seconds", "Miliseconds"]
        )
        df_position = pd.DataFrame(
            position, columns=["Longitude", "Latitude", "Altitude"]
        )
        df_sensor_data = (
            pd.DataFrame(adc_data, columns=["Sensor_Z", "Sensor_Y", "Sensor_X"])
            * self.CONVERSION_GAIN
        )

        # --- Sensor에 median filter 적용 ---
        for col in ["Sensor_X", "Sensor_Y", "Sensor_Z"]:
            df_sensor_data[col] = median_filter(
                df_sensor_data[col], size=5, mode="nearest"
            )

        df_sensor_data["Mag"] = ((df_sensor_data**2).sum(axis=1) ** 0.5) * 1000

        for col in ["Longitude", "Latitude", "Altitude"]:
            s = df_position[col].astype(float)
            # (선택) 스파이크 제거/스무딩 후
            df_position[col] = s.interpolate(method="linear", limit_direction="both")

        # --- 전체 병합 후 subsample 평균 ---
        df_all = pd.concat([df_timestamp, df_position, df_sensor_data], axis=1)

        num_groups = len(df_all) // subsample
        valid_len = num_groups * subsample
        df_all = df_all.iloc[:valid_len].copy()
        df_all["__group"] = np.repeat(np.arange(num_groups), subsample)

        df_mean = (
            df_all.groupby("__group").mean(numeric_only=True).reset_index(drop=True)
        )

        # --- 시간 필드 및 Counter 생성 ---
        formatted_date = f"20{date[:2]}-{date[2:4]}-{date[4:]}"
        df_mean.insert(0, "Date", formatted_date)

        step = 1000 / subsample
        ms_sec = df_mean["Miliseconds"].astype(int) / 1000
        ms_adj = np.floor(ms_sec * step) / step * 1000

        df_mean["Time"] = (
            str(hour).zfill(2)
            + ":"
            + df_mean["Minutes"].astype(int).astype(str).str.zfill(2)
            + ":"
            + df_mean["Seconds"].astype(int).astype(str).str.zfill(2)
            + "."
            # + df_mean["Miliseconds"].astype(int).astype(str).str.zfill(3)
            + ms_adj.astype(int).astype(str).str.zfill(3)
        )

        df_mean["Counter"] = (
            int(hour) * 3600000
            + df_mean["Minutes"].astype(int) * 60000
            + df_mean["Seconds"].astype(int) * 1000
            + df_mean["Miliseconds"].astype(int)
        ).astype(np.int32)

        # --- 최종 컬럼 정리 ---
        df_out = df_mean[
            [
                "Counter",
                "Date",
                "Time",
                "Latitude",
                "Longitude",
                "Mag",
                "Sensor_X",
                "Sensor_Y",
                "Sensor_Z",
            ]
        ].copy()

        return df_out

    def convert_file(self, input_file, output_file, filetype, subsample, hemisphere):
        match = re.search(r"_(\d{6})_(\d{4})", input_file)
        date, hour = match.group(1), match.group(2)[:2]

        try:
            with open(input_file, "rb") as file:
                binary_data = file.read()
            df = self.parse_input_data(subsample, binary_data, date, hour)
            if hemisphere != "Northern Hemisphere":
                df["Latitude"] = df["Latitude"] * -1

            if filetype == "xlsx":
                df.to_excel(output_file, index=False, engine="xlsxwriter")
            else:
                df.to_csv(output_file, index=False)
        except FileNotFoundError:
            logger.error(f"Error: File '{input_file}' not found.")
        except PermissionError:
            logger.error(
                f"Error: File {output_file} is already in use so it cannot be saved."
            )
        except Exception:
            logger.exception(f"Unexpected error while converting '{input_file}'")

    def merge_csv_files_in_folder(self, folder_path, results_path, sampling_rate):
        csv_files = [f for f in os.listdir(folder_path) if f.endswith(".csv")]
        df_list = [pd.read_csv(os.path.join(folder_path, f)) for f in sorted(csv_files)]

        df_list = []
        for f in sorted(csv_files):
            df = pd.read_csv(os.path.join(folder_path, f))
            if not df.empty:
                df_list.append(df)
            else:
                logger.warning(f"Empty DataFrame found in {f}. Skipping.")

        if df_list:
            merged_df = pd.concat(df_list, ignore_index=True)
            folder_name = os.path.basename(folder_path)
            output_path = os.path.join(
                results_path, f"{folder_name}_{sampling_rate}.csv"
            )
            merged_df.to_csv(output_path, index=False)
            logger.info(f"Merged {len(df_list)} CSV file(s) into {output_path}")
        else:
            logger.error(f"No CSV files found in {folder_path}")

    def convert_folder(
        self, folder_path: str, subsample: int, sampling_rate: str, hemisphere: str
    ):
        subdirs = [
            d
            for d in os.listdir(folder_path)
            if os.path.isdir(os.path.join(folder_path, d))
        ]
        processed_path = os.path.join(folder_path, ".processed")
        imported_path = os.path.join(folder_path, ".processed", "imported")
        os.makedirs(processed_path, exist_ok=True)
        os.makedirs(imported_path, exist_ok=True)

        for subdir in subdirs:
            if subdir in [".processed", "results"]:
                continue
            input_dir = os.path.join(folder_path, subdir)
            out_path = os.path.join(processed_path, subdir)
            os.makedirs(out_path, exist_ok=True)

            dat_files = sorted([f for f in os.listdir(input_dir) if f.endswith(".dat")])
            for file in dat_files:
                input_file = os.path.join(input_dir, file)
                output_file = (
                    os.path.splitext(os.path.join(out_path, file))[0]
                    + f"_{sampling_rate}.csv"
                )
                self.convert_file(input_file, output_file, "csv", subsample, hemisphere)

            self.merge_csv_files_in_folder(out_path, imported_path, sampling_rate)

    def convert_Diurnal_folder(
        self,
        project_path: str,
        folder_path: str,
        subsample: int,
        sampling_rate: str,
        hemisphere: str,
    ):
        processed_path = os.path.join(project_path, ".processed", "diurnal_data")
        imported_path = os.path.join(project_path, ".processed", "diurnal_imported")
        os.makedirs(processed_path, exist_ok=True)
        os.makedirs(imported_path, exist_ok=True)

        input_dir = folder_path
        out_path = os.path.join(processed_path)
        os.makedirs(out_path, exist_ok=True)

        dat_files = sorted([f for f in os.listdir(input_dir) if f.endswith(".dat")])
        for file in dat_files:
            input_file = os.path.join(input_dir, file)
            output_file = (
                os.path.splitext(os.path.join(out_path, file))[0]
                + f"_{sampling_rate}.csv"
            )
            self.convert_file(input_file, output_file, "csv", subsample, hemisphere)

        self.merge_csv_files_in_folder(out_path, imported_path, sampling_rate)


def importMagArrowFile(file_path, dest_folder_path, cfg):
    if os.path.exists(file_path):
        basename = os.path.basename(file_path)
        name_only, ext = os.path.splitext(basename)
        dest_path = os.path.join(dest_folder_path, name_only + ".csv")
        try:
            rows_buf = StringIO()
            with open(file_path, "r", encoding="utf-8", errors="replace") as fr:
                for line in fr:
                    parts = line.rstrip("\n").split(",")
                    kept = parts[:6]  # 앞 6개 필드만
                    rows_buf.write(",".join(kept) + "\n")
            rows_buf.seek(0)

            df = pd.read_csv(rows_buf)

            df_1hz = df[df["Time"].astype(str).str.endswith(".000")].copy()
            if df_1hz["Date"].str.contains("/").any():
                df_1hz["Date"] = df_1hz["Date"].str.replace("/", "-", regex=False)

            df_1hz.loc[:, "Time"] = (
                pd.to_datetime(df_1hz["Time"], format="%H:%M:%S.%f")
                .dt.strftime("%H:%M:%S.%f")
                .str[:-3]
            )

            df_1hz.to_csv(dest_path, index=False)
            return True
        except Exception:
            logger.exception(f"Failed to import Mag Arrow file: {file_path}")
            return False
