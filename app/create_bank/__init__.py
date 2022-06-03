from typing import Any, Callable, ClassVar, Dict, Protocol, Type

from app.ota_metadata import OtaMetadata
from app.configs import config as cfg
from app import log_util
from app.update_stats import OtaClientStatistics

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
        reference_root: the root folder to copy from.
        status_tracker: pass real-time update stats to ota-client.
        status_updator: inform which ota phase now.
    """

    cookies: ClassVar[Dict[str, Any]]
    metadata: ClassVar[OtaMetadata]
    url_base: ClassVar[str]
    new_root: ClassVar[str]
    boot_dir: ClassVar[str]
    reference_root: ClassVar[str]
    stats_tracker: ClassVar[OtaClientStatistics]
    status_updator: ClassVar[Callable]

    def create_standby_bank(self):
        ...


def select_mode() -> str:
    """
    TODO: select mode mechanism
    """
    return cfg.SLOT_UPDATE_MODE


def get_bank_creator() -> Type[StandByBankCreatorProtocol]:
    mode = select_mode()

    logger.info(f"use slot update {mode=}")
    if mode == "legacy":
        from app.create_bank._legacy_mode import LegacyMode

        return LegacyMode
    elif mode == "rebuild":
        from app.create_bank._rebuild_mode import RebuildMode

        return RebuildMode
    else:
        raise NotImplementedError(f"slot update {mode=} not implemented")


def get_reference_bank(*, cur_bank: str, standby_bank: str):
    mode = select_mode()
    """Get the bank to copy from."""
    if mode in ("legacy", "rebuild"):
        return cur_bank
    elif mode in ("in_place"):
        return standby_bank
    else:
        raise NotImplementedError(f"slot update {mode=} not implemented")


StandByBankCreator: Type[StandByBankCreatorProtocol] = get_bank_creator()

__All__ = ("StandByBankCreator", "get_reference_bank", "get_bank_creator")
