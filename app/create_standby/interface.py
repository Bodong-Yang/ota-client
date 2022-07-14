from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, Protocol
from app.ota_metadata import OtaMetadata
from app.update_phase import OTAUpdatePhase
from app.update_stats import OTAUpdateStatsCollector


@dataclass
class UpdateMeta:
    """Meta info for standby slot creator to update slot."""

    cookies: Dict[str, Any]  # cookies needed for requesting remote ota files
    metadata: OtaMetadata  # meta data for the update request
    url_base: str  # base url of the remote ota image
    boot_dir: str  # where to populate files under /boot
    standby_slot_mount_point: str
    ref_slot_mount_point: str


class StandbySlotCreatorProtocol(Protocol):
    """Protocol that describes standby slot creating mechanism.
    Attrs:
        cookies: authentication cookies used by ota_client to fetch files from the remote ota server.
        metadata: metadata of the requested ota image.
        url_base: base url that ota image located.
        new_root: the root folder of bank to be updated.
        reference_root: the root folder to copy from.
        status_tracker: pass real-time update stats to ota-client.
        status_updator: inform which ota phase now.
    """

    stats_collector: OTAUpdateStatsCollector
    update_phase_tracker: Callable[[OTAUpdatePhase], None]

    def __init__(
        self,
        update_meta: UpdateMeta,
        stats_collector: OTAUpdateStatsCollector,
        update_phase_tracker: Callable[[OTAUpdatePhase], None],
    ) -> None:
        ...

    @abstractmethod
    def create_standby_slot(self):
        ...

    @classmethod
    @abstractmethod
    def should_erase_standby_slot(cls) -> bool:
        """Tell whether standby slot should be erased
        under this standby slot creating mode."""

    @classmethod
    @abstractmethod
    def is_standby_as_ref(cls) -> bool:
        """Tell whether the slot creator intends to use
        in-place update."""
