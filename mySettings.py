import json
from pathlib import Path
from typing import Any, Optional, Union

from loguru import logger


class myConfigs:
    def __init__(self) -> None:
        self.__file_path: Optional[Path] = None
        self.config: dict[str, Any] = {}

    def set_path(self, file_path: str | Path) -> None:
        self.__file_path = Path(file_path)

    @logger.catch()
    def set(
        self, key: Union[str, list[str], tuple[str]], value: Any, save: bool = False
    ) -> None:
        if isinstance(key, str):
            self.config[key] = value
        elif isinstance(key, (list, tuple)):
            d = self.config
            for k in key[:-1]:
                if k not in d or not isinstance(d[k], dict):
                    d[k] = {}
                d = d[k]
            d[key[-1]] = value

        if save:
            self.save()

    @logger.catch()
    def get(self, key: Union[str, list[str], tuple[str]], default: Any = None) -> Any:
        if isinstance(key, str):
            return self.config.get(key, default)

        if isinstance(key, (list, tuple)):
            d = self.config
            for k in key:
                if not isinstance(d, dict) or k not in d:
                    return default
                d = d[k]
            return d

    @logger.catch()
    def get_subvalue(self, key: str, subkey: str, default: Any = None) -> Any:
        if key in self.config:
            return self.config[key].get(subkey, default)
        return default

    @logger.catch()
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


# Project-scoped configuration store
config = myConfigs()
