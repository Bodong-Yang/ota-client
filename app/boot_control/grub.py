from pathlib import Path
from typing import Tuple

from app.boot_control._grub import OtaPartitionFile
from app.boot_control.common import (
    BootControlInternalError,
    CMDHelperFuncs,
    OTAStatusMixin,
    SlotInUseMixin,
    VersionControlMixin,
    BootControllerProtocol,
)
from app.configs import BOOT_LOADER, grub_cfg as cfg
from app.ota_status import OTAStatusEnum
from app import log_util

assert BOOT_LOADER == "grub", f"ERROR, try to use grub on {BOOT_LOADER}, abort"

logger = log_util.get_logger(
    __name__, cfg.LOG_LEVEL_TABLE.get(__name__, cfg.DEFAULT_LOG_LEVEL)
)


class ABPartitionDetecter:
    """
    Expected layout:
        /dev/sdx
            - sdx1: dedicated boot partition
            - sdx2: A partition
            - sdx3: B partition

    slot_name is the dev name of the A/B partition
    """

    def __init__(self) -> None:
        self.active_slot, self.active_dev = self._detect_active_slot()
        self.standby_slot, self.standby_dev = self._detect_standby_slot(self.active_dev)

    @staticmethod
    def _get_sibling_dev(slot_dev_path: str) -> str:
        """
        Expected partition layout:
            /dev/sdx
                - sdx1: dedicated boot partition
                - sdx2: A partition
                - sdx3: B partition
        """
        parent = CMDHelperFuncs.get_parent_dev(slot_dev_path)
        family = CMDHelperFuncs.get_dev_family(parent)

        # NOTE: skip the first 2 lines: parent dev and boot dev
        res = set(family[2:]) - {slot_dev_path}
        if len(res) == 1:
            return list(res)[0]
        else:
            raise BootControlInternalError(
                f"device is has unexpected partition layout: {family=}"
            )

    def _detect_active_slot(self) -> Tuple[str, str]:
        """
        Returns:
            A tuple contains the slot_name and the full dev path
            of the active slot.
        """
        dev_path = CMDHelperFuncs.get_current_rootfs_dev()
        slot_name = dev_path.lstrip("/dev/")
        return slot_name, dev_path

    def _detect_standby_slot(self, active_dev: str) -> Tuple[str, str]:
        """
        Returns:
            A tuple contains the slot_name and the full dev path
            of the standby slot.
        """
        dev_path = self._get_sibling_dev(active_dev)
        slot_name = dev_path.lstrip("/dev/")
        return slot_name, dev_path

    ###### public methods ######
    def get_standby_slot(self) -> str:
        return self.standby_slot

    def get_standby_slot_dev(self) -> str:
        return self.standby_dev

    def get_active_slot(self) -> str:
        return self.active_slot

    def get_active_slot_dev(self) -> str:
        return self.active_dev


class GrubController(
    VersionControlMixin, OTAStatusMixin, SlotInUseMixin, BootControllerProtocol
):
    def __init__(self) -> None:
        self._boot_control = OtaPartitionFile()
        self._ab_detecter = ABPartitionDetecter()

        # load paths
        self.standby_slot_path = Path(cfg.MOUNT_POINT)
        self.standby_slot_path.mkdir(exist_ok=True)
        self.standby_slot_dev = self._ab_detecter.get_standby_slot_dev()

        ## ota-status dir
        ### current slot: /boot/ota-partition.<rootfs_dev_active>
        # NOTE: BOOT_OTA_PARTITION_FILE is a directory, should we change it?
        self.current_ota_status_dir = (
            Path(cfg.BOOT_DIR)
            / f"{cfg.BOOT_OTA_PARTITION_FILE}.{self._ab_detecter.get_active_slot()}"
        )
        self.current_ota_status_dir.mkdir(exist_ok=True)

        ## standby slot: /boot/ota-partition.<rootfs_dev_standby>
        self.standby_ota_status_dir = (
            Path(cfg.BOOT_DIR)
            / f"{cfg.BOOT_OTA_PARTITION_FILE}.{self._ab_detecter.get_standby_slot()}"
        )
        self.standby_ota_status_dir.mkdir(exist_ok=True)

        self.ota_status = self._init_boot_control()

    def _finalize_update(self) -> OTAStatusEnum:
        if self._boot_control.is_switching_boot_partition_from_active_to_standby():
            self._boot_control.update_grub_cfg()
            # switch should be called last.
            self._boot_control.switch_boot_partition_from_active_to_standby()
            return OTAStatusEnum.SUCCESS
        else:
            return OTAStatusEnum.FAILURE

    _finalize_rollback = _finalize_update

    def _init_boot_control(self) -> OTAStatusEnum:
        _ota_status = self._load_current_ota_status()

        if _ota_status == OTAStatusEnum.UPDATING:
            _ota_status = self._finalize_update()
        elif _ota_status == OTAStatusEnum.ROLLBACKING:
            _ota_status = self._finalize_rollback()
        elif _ota_status == OTAStatusEnum.SUCCESS:
            # need to check whether it is negative SUCCESS
            current_slot = self._ab_detecter.get_active_slot()
            try:
                slot_in_use = self._load_current_slot_in_use()
                # cover the case that device reboot into unexpected slot
                if current_slot != slot_in_use:
                    logger.error(
                        f"boot into old slot {current_slot}, "
                        f"expect to boot into {slot_in_use}"
                    )
                    _ota_status = OTAStatusEnum.FAILURE

            except FileNotFoundError:
                # init slot_in_use file and ota_status file
                self._store_current_slot_in_use(current_slot)
                _ota_status = OTAStatusEnum.INITIALIZED

        # FAILURE, INITIALIZED and ROLLBACK_FAILURE are remained as it

        # NOTE: only update the current ota_status at ota-client launching up!
        self._store_current_ota_status(_ota_status)
        logger.info(f"loaded ota_status: {_ota_status}")
        return _ota_status

    def _mount_standby(self, erase_standby: bool):
        # mount standby slot
        self._boot_control.cleanup_standby_boot_partition()
        if erase_standby:
            self._boot_control.mount_standby_root_partition_and_clean(
                self.standby_slot_path
            )
        else:
            # directly mount standby without cleaning up
            CMDHelperFuncs.mount(str(self.standby_slot_dev), self.standby_slot_path)

    def _mount_refroot(self, standby_as_ref: bool):
        Path(cfg.REF_ROOT_MOUNT_POINT).mkdir(exist_ok=True)
        CMDHelperFuncs.mount_refroot(
            standby_slot_dev=self._ab_detecter.get_standby_slot_dev(),
            active_slot_dev=self._ab_detecter.get_active_slot_dev(),
            refroot_mount_point=cfg.REF_ROOT_MOUNT_POINT,
            standby_as_ref=standby_as_ref,
        )

    def _on_operation_failure(self, e: Exception):
        """Failure registering and cleanup at failure."""
        self._store_standby_ota_status(OTAStatusEnum.FAILURE)

        try:
            logger.warning("on failure try to unmounting standby slot...")
            CMDHelperFuncs.umount_dev(str(self.standby_slot_dev))
        finally:
            raise e

    ###### public methods ######
    # also includes methods from OTAStatusMixin, VersionControlMixin

    def get_standby_slot_path(self) -> Path:
        return self.standby_slot_path

    def get_standby_boot_dir(self) -> Path:
        """
        NOTE: in grub_controller, kernel and initrd images are stored under
        the ota_status_dir(ota_partition_dir)
        """
        return self.standby_ota_status_dir

    def pre_update(self, version: str, *, standby_as_ref: bool, erase_standby=False):
        try:
            self._mount_standby(erase_standby)
            self._mount_refroot(standby_as_ref)

            # store status and version to standby
            self._store_standby_ota_status(OTAStatusEnum.UPDATING)
            self._store_standby_version(version)

            # store slot_in_use to both slots
            _target_slot = self._boot_control.get_standby_root_device_name()
            self._store_current_slot_in_use(_target_slot)
            self._store_standby_slot_in_use(_target_slot)
        except Exception as e:  # TODO: use BootControlError for any exceptions
            logger.error(f"failed on pre_update: {e!r}")
            self._on_operation_failure(e)

    def post_update(self):
        try:
            self._boot_control.update_fstab(self.standby_slot_path)
            self._boot_control.create_custom_cfg_and_reboot()
        except Exception as e:  # TODO: use BootControlError for any exceptions
            logger.error(f"failed on pre_update: {e!r}")
            self._on_operation_failure(e)

    def post_rollback(self):
        try:
            self._boot_control.create_custom_cfg_and_reboot(rollback=True)
        except Exception as e:
            logger.error(f"failed on pre_rollback: {e!r}")
            self._on_operation_failure(e)
