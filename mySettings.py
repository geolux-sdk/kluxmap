import json
import sys
from pathlib import Path
from typing import Any, Optional, Union

from jsonschema import ValidationError, validate
from loguru import logger


class myConfigs:
    def __init__(self) -> None:
        self.__file_path: Optional[Path] = None
        self.config: dict[str, Any] = {}

    def set_path(self, file_path: str | Path) -> None:
        self.__file_path = Path(file_path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any, save: bool = False) -> None:
        self.config[key] = value
        if save:
            self.save()

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def get_subvalue(self, key: str, subkey: str, default: Any = None) -> Any:
        if key in self.config:
            return self.config[key].get(subkey, default)
        return default

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def set_subvalue(
        self, key: str, subkey: str, value: Any, save: bool = False
    ) -> None:
        if key not in self.config or not isinstance(self.config[key], dict):
            self.config[key] = {}
        self.config[key][subkey] = value
        if save:
            self.save()

    def save(self) -> None:
        if self.__file_path is None:
            raise ValueError("Config file path is not set. Call set_path() first.")

        try:
            with self.__file_path.open("w", encoding="utf-8") as file:
                json.dump(self.config, file, indent=4)
        except IOError as err:
            logger.error(f"IOError during write: {err}")
            raise

    def load(self) -> None:
        if self.__file_path is None:
            raise ValueError("Config file path is not set. Call set_path() first.")

        try:
            with self.__file_path.open("r", encoding="utf-8") as file:
                self.config = json.load(file)
        except FileNotFoundError as err:
            logger.warning(f"Config File not found: {err}")
            return
        except json.JSONDecodeError as err:
            logger.error(f"JSON decode error: {err}")
            raise

    def clear(self):
        self.config = {}

    @property
    def file_path(self) -> Optional[Path]:
        return self.__file_path


class mySettings:
    defaults = {
        "logger": {
            "folder": "./log",
            "filename": "KMagHunters.log",
            "level": "DEBUG",
            "console": True,
        },
        "init": {
            "splash": True,
            "size": {"width": 800, "height": 600},
            "project_path": "",
        },
    }

    schema = {
        "type": "object",
        "properties": {
            "logger": {"type": "object"},
            "init": {"type": "object"},
        },
        "required": [
            "logger",
            "init",
        ],
    }

    def __init__(
        self,
        defaults: Optional[dict[str, Any]] = None,
        file_name: str = "settings.json",
        folder_name: str = "./",
    ) -> None:
        self.defaults = defaults if defaults is not None else self.defaults
        self.__file_path = Path(folder_name) / file_name

        self.settings = self._read_or_initialize(self.schema)
        self._logger_init()

    def _logger_init(self) -> None:
        logger_folder = Path(self.settings.get("logger", {}).get("folder", "./log"))
        logger_filename = self.settings.get("logger", {}).get("filename", "app.log")
        logger_level = self.settings.get("logger", {}).get("level", "DEBUG")
        logger_consol = self.settings.get("logger", {}).get("console", False)
        logger_path = logger_folder / logger_filename

        logger.remove()  # 화면에 안보이기 위해서..

        logger_folder.mkdir(parents=True, exist_ok=True)
        logger.add(logger_path, level=logger_level, rotation="10 MB")

        if logger_consol:
            logger.add(sys.stderr, level=logger_level)
        else:
            logger.debug("Console logger disabled")

        logger.info("====================== Logging started ======================")

    def _read_or_initialize(self, schema: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.__file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            validate(instance=data, schema=schema)
            return data
        except ValidationError as err:
            logger.error(f"{self.__file_path} File Validation Error: {err}")
            raise
        except FileNotFoundError as err:
            logger.warning(f"{self.__file_path} File not found, using defaults: {err}")
            self.write(self.defaults)
            logger.info(">> ------------ USING DEFAULTS -------------")
            return dict(self.defaults)
        except json.JSONDecodeError as err:
            logger.error(f"{self.__file_path} JSON decode error: {err}")
            raise

    def write(self, data: dict[str, Any]) -> None:
        try:
            with self.__file_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
        except OSError as err:
            if hasattr(self, "logger"):
                self.logger.error(f"IOError during write: {err}")
            else:
                print(f"IOError during write: {err}")
            raise

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def set(
        self, key: Union[str, list[str], tuple[str]], value: Any, save: bool = False
    ) -> None:
        if isinstance(key, str):
            self.settings[key] = value

        if isinstance(key, (list, tuple)):
            d = self.settings
            for k in key[:-1]:
                if k not in d or not isinstance(d[k], dict):
                    d[k] = {}
                d = d[k]
            d[key[-1]] = value

        if save:
            self.write(self.settings)

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def get(self, key: Union[str, list[str], tuple[str]], default: Any = None) -> Any:
        if isinstance(key, str):
            return self.settings.get(key, default)
        if isinstance(key, (list, tuple)):
            d = self.settings
            for k in key:
                if not isinstance(d, dict) or k not in d:
                    return default
                d = d[k]
            return d

    @property
    def file_path(self) -> Optional[Path]:
        return self.__file_path


config = myConfigs()
