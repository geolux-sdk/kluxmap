import json
import os
import sys

from jsonschema import ValidationError, validate
from loguru import logger


class myConfigs:
    def __init__(self) -> None:
        self.config = {}

    def set_path(self, file_path):
        self.file_path = file_path

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value, save=False):
        self.config[key] = value
        if save:
            self.save()

    @logger.catch()
    def get_subvalue(self, key, subkey, default=None):
        if key in self.config:
            return self.config[key].get(subkey, default)
        return default

    @logger.catch()
    def set_subvalue(self, key, subkey, value, save=False):
        if key not in self.config:
            self.config[key] = {}
        self.config[key][subkey] = value
        if save:
            self.save()

    def save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as file:
                json.dump(self.config, file, indent=4)
        except IOError as err:
            logger.error(f"IOError during write: {err}")
            raise

    def load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
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
        "init": {"splash": True, "project_path": ""},
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
        self, defaults: dict = None, file_name="settings.json", folder_name="./"
    ) -> None:
        self.defaults = defaults if defaults is not None else self.defaults
        self.file_path = os.path.join(folder_name, file_name)

        self.settings = self.read()
        self.logger = self._logger_init()
        self.validate(self.schema)

    def _logger_init(self):
        logger_folder = self.settings.get("logger", {}).get("folder", "./log")
        logger_filename = self.settings.get("logger", {}).get("filename", "app.log")
        logger_level = self.settings.get("logger", {}).get("level", "DEBUG")
        logger_consol = self.settings.get("logger", {}).get("console", False)
        logger_path = os.path.join(logger_folder, logger_filename)

        logger.remove()  # 화면에 안보이기 위해서..

        os.makedirs(logger_folder, exist_ok=True)
        logger.add(logger_path, level=logger_level, rotation="10 MB")

        if logger_consol:
            logger.add(sys.stderr, level=logger_level)
        else:
            logger.debug("Console logger disabled")

        logger.info("Logging started")
        return logger

    def _logger(self, message):
        if hasattr(self, "logger"):
            self.logger.debug(message)
        else:
            print(">> mySettings Logger:", message)

    def read(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
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

    def write(self, data: dict) -> None:
        try:
            with open(self.file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
        except IOError as err:
            self.logger.error(f"IOError during write: {err}")
            raise

    def validate(self, schema):
        try:
            validate(instance=self.settings, schema=schema)
        except ValidationError as err:
            self.logger.error(f"Validation error: {err}")
            raise


config = myConfigs()
