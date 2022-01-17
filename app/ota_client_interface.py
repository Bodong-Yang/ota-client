# interface definition for ota-client
# fmt: off
import abc
from pathlib import Path
from threading import Event
from typing import Any

from ota_status import OtaStatus


class BootControlInterface(metaclass=abc.ABCMeta):
    """
    platform neutral boot control interface
    """
    def initialize_ota_status(self): ...
    def store_standby_ota_status(self, status: OtaStatus): ...
    def store_ota_status(self, status): ...
    def load_ota_status(self) -> str: ...
    def get_standby_boot_partition_path(self) -> Path: ...
    def get_version(self) -> str: ...
    def boot_ctrl_pre_update(self, version: str): ...
    def boot_ctrl_post_update(self): ...
    def boot_ctrl_pre_rollback(self): ...
    def boot_ctrl_post_rollback(self): ...
    def finalize_update(self) -> OtaStatus: ...
    def finalize_rollback(self) -> OtaStatus: ...


class OtaClientInterface(metaclass=abc.ABCMeta):
    def update(
        self, 
        version, url_base, cookies_json: str, 
        *, 
        pre_update_event: Event = None, post_update_event: Event = None) -> Any: ...

    def rollback(self) -> Any: ...
    def status(self) -> Any: ...

# fmt: on
