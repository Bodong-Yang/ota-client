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
        mount_point: the destination of new created bank.
    """

    cookies: ClassVar[Dict[str, Any]]
    metadata: ClassVar[OtaMetadata]
    url_base: ClassVar[str]
    mount_point: ClassVar[str]

    def create_standby_bank(self):
        ...


__All__ = ("LegacyMode",)
