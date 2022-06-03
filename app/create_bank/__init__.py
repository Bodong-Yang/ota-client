from typing import Any, Callable, ClassVar, Dict, Protocol, Type

from app.ota_metadata import OtaMetadata
from app.configs import config as cfg
from app import log_util

logger = log_util.get_logger(
    __name__, cfg.LOG_LEVEL_TABLE.get(__name__, cfg.DEFAULT_LOG_LEVEL)
)


class StandByBankCreatorProtocol(Protocol):
    """Protocol that describes bank creating.
    Attrs:
        cookies: authentication cookies used by ota_client to fetch files from the remote ota server.
        metadata: metadata of the requested ota image.
        url_base: base url that ota image located.
        new_root: the root folder of bank to be updated.
        old_root: the root folder of old bank.
    """

    cookies: ClassVar[Dict[str, Any]]
    metadata: ClassVar[OtaMetadata]
    url_base: ClassVar[str]
    new_root: ClassVar[str]
    boot_dir: ClassVar[str]
    old_root: ClassVar[str]
    stats_tracker: ClassVar
    status_updator: ClassVar[Callable]

    def create_standby_bank(self):
        ...


def get_bank_creator(mode: str) -> Type[StandByBankCreatorProtocol]:
    logger.info(f"use slot update {mode=}")
    if mode == "legacy":
        from app.create_bank._legacy_mode import LegacyMode

        return LegacyMode
    elif mode == "rebuild":
        from app.create_bank._rebuild_mode import RebuildMode

        return RebuildMode
    else:
        raise NotImplementedError(f"slot update {mode=} not implemented")


StandByBankCreator: Type[StandByBankCreatorProtocol] = get_bank_creator(
    cfg.SLOT_UPDATE_MODE
)

__All__ = ("StandByBankCreator",)
