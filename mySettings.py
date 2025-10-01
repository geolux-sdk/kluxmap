import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from xmlrpc.client import Boolean

from jsonschema import ValidationError, validate
from loguru import logger


class myConfigs:
    def __init__(self) -> None:
        self.config = {}

    def set_path(self, file_path: str) -> None:
        self.__file_path = Path(file_path)

    def get(self, key: str, default=Optional[Any]) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value=Any, save=False) -> None:
        self.config[key] = value
        if save:
            self.save()

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def get_subvalue(self, key: str, subkey: str, default=Optional[Any]) -> Any:
        if key in self.config:
            return self.config[key].get(subkey, default)
        return default

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def set_subvalue(
        self, key: str, subkey: str, value=Any, save: Boolean = False
    ) -> None:
        if key not in self.config:
            self.config[key] = {}
        self.config[key][subkey] = value
        if save:
            self.save()

    def save(self) -> None:
        try:
            with self.__file_path.open("w", encoding="utf-8") as file:
                json.dump(self.config, file, indent=4)
        except IOError as err:
            logger.error(f"IOError during write: {err}")
            raise

    def load(self) -> None:
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
        defaults: Optional[Dict[str, Any]] = None,
        file_name: str = "settings.json",
        folder_name: str = "./",
    ) -> None:
        self.defaults = defaults if defaults is not None else self.defaults
        self.__file_path = Path(folder_name) / file_name

        self.settings = self.read()
        self.logger = self._logger_init()
        self.validate(self.schema)

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

        logger.info("Logging started")
        return logger

    def _logger(self, message: str) -> None:
        if hasattr(self, "logger"):
            self.logger.debug(message)
        else:
            print(">> mySettings Logger:", message)

    def read(self) -> Dict:
        try:
            with self.__file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return data
        except FileNotFoundError as err:
            self._logger(f"File not found, using defaults: {err}")
            self.write(self.defaults)
            self._logger(">> ------------ USING DEFAULTS -------------")
            return self.defaults
        except json.JSONDecodeError as err:
            self._logger(f"JSON decode error: {err}")
            raise

    def write(self, data: Dict) -> None:
        try:
            with self.__file_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
        except IOError as err:
            self.logger.error(f"IOError during write: {err}")
            raise

    def validate(self, schema: Dict) -> None:
        try:
            validate(instance=self.settings, schema=schema)
        except ValidationError as err:
            self.logger.error(f"Validation error: {err}")
            raise

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def set(self, key: str, value: Any, save=False) -> None:
        self.settings[key] = value
        if save:
            self.write(self.settings)

    @logger.catch()  # 함수 안에서 발생하는 모든 예외(Exception)를 자동으로 잡아서 로깅
    def get(self, key: str, default: Any) -> Any:
        return self.settings.get(key, default)


config = myConfigs()
