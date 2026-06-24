import os
import re
import struct
import ctypes
from io import StringIO

import numpy as np
import pandas as pd
from loguru import logger
from scipy.ndimage import median_filter


class DataConverter:
    # 고정 상수
    ADS131A_SCALE_FACTOR = 4.0 / 0x800000
    VOLTAGE_TO_VALUE = 100 / 3.0
    CONVERSION_GAIN = VOLTAGE_TO_VALUE * ADS131A_SCALE_FACTOR * 1000
    LONGITUDE_FRAC_LEN = 5
    LATITUDE_FRAC_LEN = 5
    ALTITUDE_FRAC_LEN = 1
    BLOCK_FORMAT = "<2BHHHIIhH3i"
    V2025_BLOCK_FORMAT = "<6BHddh6x4i"
    V2025_SHORT_BLOCK_HEADER = 0xAAAA
    V2025_ADC_DATA_FORMAT = "<4i"
    _minilzo_lib = None

    def __init__(self):
        pass

    def gps_to_decimal(self, degrees_minutes):
        degrees = int(degrees_minutes // 100)
        minutes = degrees_minutes % 100
        return degrees + minutes / 60

    def _extract_file_time(self, input_file, pattern):
        match = re.search(pattern, os.path.basename(input_file), re.IGNORECASE)
        if not match:
            raise ValueError(
                f"Input file name does not match expected Mag Hawk format: {input_file}"
            )
        return match.group(1), match.group(2)[:2]

    def _save_dataframe(self, df, output_file, filetype):
        if filetype == "xlsx":
            df.to_excel(output_file, index=False, engine="xlsxwriter")
        else:
            df.to_csv(output_file, index=False)

    def _empty_output_dataframe(self):
        return pd.DataFrame(
            columns=[
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
        )

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
        df_mean["Mag"] = (
            (df_mean[["Sensor_X", "Sensor_Y", "Sensor_Z"]] ** 2).sum(axis=1) ** 0.5
        )

        # --- 시간 필드 및 Counter 생성 ---
        formatted_date = f"20{date[:2]}-{date[2:4]}-{date[4:]}"
        df_mean.insert(0, "Date", formatted_date)

        ms_int = df_mean["Miliseconds"].astype(int)
        ms_adj = (ms_int // subsample) * subsample

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

    def _load_minilzo_library(self):
        if DataConverter._minilzo_lib is not None:
            return DataConverter._minilzo_lib

        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "minilzo.dll"),
            os.path.join(base_dir, "minilzo.so"),
        ]
        errors = []
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                lib = ctypes.cdll.LoadLibrary(path)
                DataConverter._minilzo_lib = lib
                return lib
            except OSError as err:
                errors.append(f"{path}: {err}")

        msg = "V2025 compressed data requires a minilzo native library."
        if errors:
            msg += " Load attempts failed: " + "; ".join(errors)
        raise RuntimeError(msg)

    def _decompress_v2025_block(self, block: bytes, raw_remaining: int) -> bytes:
        lib = self._load_minilzo_library()
        in_buf = ctypes.create_string_buffer(block)
        in_len = ctypes.c_int(len(block))
        out_size = max(len(block) * 10, 65536)
        if raw_remaining > 0:
            out_size = min(max(out_size, len(block)), raw_remaining)

        while True:
            out_buf = ctypes.create_string_buffer(out_size)
            out_len = ctypes.c_int(out_size)
            result = lib.lzo1x_decompress(
                ctypes.byref(in_buf),
                in_len,
                ctypes.byref(out_buf),
                ctypes.byref(out_len),
            )
            if result == 0:
                return out_buf.raw[: out_len.value]

            if raw_remaining <= 0 or out_size >= raw_remaining:
                raise RuntimeError(f"minilzo decompression failed with code {result}")
            out_size = min(out_size * 2, raw_remaining)

    def _decompress_v2025_data(self, binary_data: bytes) -> bytes:
        raw_data_size = int.from_bytes(binary_data[4:8], byteorder="little")
        decompressed_data = bytearray()
        read_idx = 8
        block_num = 0

        while read_idx < len(binary_data):
            if read_idx + 4 > len(binary_data):
                raise ValueError(f"Truncated V2025 compression header at block {block_num}")

            file_compression_flag = binary_data[read_idx]
            checksum = binary_data[read_idx + 1]
            block_size = int.from_bytes(
                binary_data[read_idx + 2 : read_idx + 4], byteorder="little"
            )
            read_idx += 4
            block_end = read_idx + block_size
            if block_end > len(binary_data):
                raise ValueError(f"Truncated V2025 compression block {block_num}")

            block = binary_data[read_idx:block_end]
            if sum(block) & 0xFF != checksum:
                raise ValueError(
                    f"V2025 checksum error at block {block_num} "
                    f"with compressed size {block_size}"
                )

            if file_compression_flag:
                raw_remaining = raw_data_size - len(decompressed_data)
                decompressed_data += self._decompress_v2025_block(block, raw_remaining)
            else:
                decompressed_data += block

            block_num += 1
            read_idx += block_size + (4 - block_size % 4) % 4

        return bytes(decompressed_data)

    def parse_input_data_v2025(
        self, subsample: int, binary_data: bytes
    ) -> pd.DataFrame:
        if subsample <= 0:
            raise ValueError("subsample must be greater than zero")

        if binary_data.startswith(b"MLZO"):
            binary_data = self._decompress_v2025_data(binary_data)

        full_block_size = struct.calcsize(self.V2025_BLOCK_FORMAT)
        adc_data_size = struct.calcsize(self.V2025_ADC_DATA_FORMAT)
        short_block_size = 2 + 2 + adc_data_size
        records = []
        offset = 0
        total_len = len(binary_data)
        ctx = {
            "year": 0,
            "month": 0,
            "day": 0,
            "hours": 0,
            "minutes": 0,
            "seconds": 0,
            "latitude": 0.0,
            "longitude": 0.0,
            "altitude": 0,
        }

        while offset < total_len:
            is_short_block = False
            if offset > 0:
                if total_len - offset < 2:
                    logger.warning(f"Stopping V2025 parse: short header at {offset}")
                    break
                (header,) = struct.unpack_from("<H", binary_data, offset)
                is_short_block = header == self.V2025_SHORT_BLOCK_HEADER

            if is_short_block:
                if total_len - offset < short_block_size:
                    logger.warning(f"Stopping V2025 parse: short block at {offset}")
                    break
                (subseconds,) = struct.unpack_from("<H", binary_data, offset + 2)
                adc_values = struct.unpack_from(
                    self.V2025_ADC_DATA_FORMAT, binary_data, offset + 4
                )
                records.append(
                    [
                        ctx["year"],
                        ctx["month"],
                        ctx["day"],
                        ctx["hours"],
                        ctx["minutes"],
                        ctx["seconds"],
                        subseconds,
                        ctx["latitude"],
                        ctx["longitude"],
                        ctx["altitude"],
                        *adc_values,
                    ]
                )
                offset += short_block_size
                continue

            if total_len - offset < full_block_size:
                logger.warning(f"Stopping V2025 parse: full block at {offset}")
                break

            (
                month,
                day,
                year,
                hours,
                minutes,
                seconds,
                subseconds,
                latitude,
                longitude,
                altitude,
                *adc_values,
            ) = struct.unpack_from(self.V2025_BLOCK_FORMAT, binary_data, offset)

            ctx.update(
                {
                    "year": year,
                    "month": month,
                    "day": day,
                    "hours": hours,
                    "minutes": minutes,
                    "seconds": seconds,
                    "latitude": latitude,
                    "longitude": longitude,
                    "altitude": altitude,
                }
            )
            records.append(
                [
                    year,
                    month,
                    day,
                    hours,
                    minutes,
                    seconds,
                    subseconds,
                    latitude,
                    longitude,
                    altitude,
                    *adc_values,
                ]
            )
            offset += full_block_size

        if not records:
            return self._empty_output_dataframe()

        df_all = pd.DataFrame(
            records,
            columns=[
                "Year",
                "Month",
                "Day",
                "Hours",
                "Minutes",
                "Seconds",
                "Miliseconds",
                "Latitude",
                "Longitude",
                "Altitude",
                "ADC0",
                "ADC1",
                "ADC2",
                "ADC3",
            ],
        )

        df_sensor_data = (
            df_all[["ADC0", "ADC1", "ADC2"]]
            .rename(
                columns={
                    "ADC0": "Sensor_X",
                    "ADC1": "Sensor_Y",
                    "ADC2": "Sensor_Z",
                }
            )
            * self.CONVERSION_GAIN
        )
        for col in ["Sensor_X", "Sensor_Y", "Sensor_Z"]:
            df_sensor_data[col] = median_filter(
                df_sensor_data[col], size=5, mode="nearest"
            )

        df_position = df_all[["Latitude", "Longitude", "Altitude"]].copy()
        for col in ["Longitude", "Latitude", "Altitude"]:
            s = df_position[col].astype(float)
            df_position[col] = s.interpolate(method="linear", limit_direction="both")

        df_time = df_all[
            ["Year", "Month", "Day", "Hours", "Minutes", "Seconds", "Miliseconds"]
        ].copy()
        df_samples = pd.concat([df_time, df_position, df_sensor_data], axis=1)

        num_groups = len(df_samples) // subsample
        if num_groups == 0:
            return self._empty_output_dataframe()

        valid_len = num_groups * subsample
        df_samples = df_samples.iloc[:valid_len].copy()
        df_samples["__group"] = np.repeat(np.arange(num_groups), subsample)
        grouped = df_samples.groupby("__group")
        df_mean = grouped.mean(numeric_only=True).reset_index(drop=True)
        df_mean["Mag"] = (
            (df_mean[["Sensor_X", "Sensor_Y", "Sensor_Z"]] ** 2).sum(axis=1) ** 0.5
        )
        df_first = grouped[["Year", "Month", "Day"]].first().reset_index(drop=True)
        df_mean[["Year", "Month", "Day"]] = df_first[["Year", "Month", "Day"]]

        year = df_mean["Year"].astype(int).astype(str).str.zfill(2)
        month = df_mean["Month"].astype(int).astype(str).str.zfill(2)
        day = df_mean["Day"].astype(int).astype(str).str.zfill(2)
        df_mean.insert(0, "Date", "20" + year + "-" + month + "-" + day)

        ms_int = df_mean["Miliseconds"].astype(int)
        ms_adj = (ms_int // subsample) * subsample

        df_mean["Time"] = (
            df_mean["Hours"].astype(int).astype(str).str.zfill(2)
            + ":"
            + df_mean["Minutes"].astype(int).astype(str).str.zfill(2)
            + ":"
            + df_mean["Seconds"].astype(int).astype(str).str.zfill(2)
            + "."
            + ms_adj.astype(int).astype(str).str.zfill(3)
        )

        df_mean["Counter"] = (
            df_mean["Hours"].astype(int) * 3600000
            + df_mean["Minutes"].astype(int) * 60000
            + df_mean["Seconds"].astype(int) * 1000
            + df_mean["Miliseconds"].astype(int)
        ).astype(np.int32)

        return df_mean[
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

    def convert_file(self, input_file, output_file, filetype, subsample, hemisphere):
        try:
            date, hour = self._extract_file_time(input_file, r"_(\d{6})_(\d{4})")
            with open(input_file, "rb") as file:
                binary_data = file.read()
            df = self.parse_input_data(subsample, binary_data, date, hour)
            if hemisphere != "Northern Hemisphere":
                df["Latitude"] = df["Latitude"] * -1

            self._save_dataframe(df, output_file, filetype)
        except FileNotFoundError:
            logger.error(f"Error: File '{input_file}' not found.")
        except PermissionError:
            logger.error(
                f"Error: File {output_file} is already in use so it cannot be saved."
            )
        except Exception:
            logger.exception(f"Unexpected error while converting '{input_file}'")

    def convert_file_v2025(self, input_file, output_file, filetype, subsample):
        try:
            self._extract_file_time(input_file, r"^Mag_(\d{6})_(\d{4})\.dat$")
            with open(input_file, "rb") as file:
                binary_data = file.read()
            df = self.parse_input_data_v2025(subsample, binary_data)
            self._save_dataframe(df, output_file, filetype)
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
        # df_list = [pd.read_csv(os.path.join(folder_path, f)) for f in sorted(csv_files)]

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

    def convert_diurnal_folder(
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


def import_mag_arrow_file(file_path, dest_folder_path, cfg):
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
