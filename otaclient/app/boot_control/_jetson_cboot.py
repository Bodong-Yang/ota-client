# Copyright 2022 TIER IV, INC. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Boot control implementation for NVIDIA Jetson device boot with cboot."""


from __future__ import annotations
import logging
import os
import re
from functools import partial
from pathlib import Path
from subprocess import run, CalledProcessError
from typing import Any, Generator, Literal, Optional

from typing_extensions import NewType, TypeAlias

from otaclient.app import errors as ota_errors
from otaclient.app.common import (
    copytree_identical,
    write_str_to_file_sync,
)

from otaclient.app.proto import wrapper
from ._common import (
    OTAStatusFilesControl,
    SlotMountHelper,
    CMDHelperFuncs,
)
from .configs import cboot_cfg as cfg
from .protocol import BootControllerProtocol

logger = logging.getLogger(__name__)

# some consts

SlotID = NewType("SlotID", str)  # Literal["0", "1"]
SlotIDFlip: dict[SlotID, SlotID] = {SlotID("0"): SlotID("1"), SlotID("1"): SlotID("0")}
SlotIDPartIDMapping: dict[SlotID, str] = {SlotID("0"): "1", SlotID("1"): "2"}

MMCBLK_DEV_PREFIX = "mmcblk"  # internal emmc
NVMESSD_DEV_PREFIX = "nvme"  # external nvme ssd
INTERNAL_EMMC_DEV = "mmcblk0"

NVBootctrlTarget = Literal["bootloader", "rootfs"]
# see https://developer.nvidia.com/embedded/jetson-linux-archive for BSP version history.
BSPVersion: TypeAlias = "tuple[int, int, int]"


class JetsonCBootContrlError(Exception):
    """Exception types for covering jetson-cboot related errors."""


class _NVBootctrl:
    """Helper for calling nvbootctrl commands."""

    NVBOOTCTRL = "nvbootctrl"

    @classmethod
    def _nvbootctrl(
        cls,
        _cmd: str,
        _slot_id: Optional[SlotID] = None,
        *,
        check_output=False,
        target: Optional[NVBootctrlTarget] = None,
    ) -> Any:
        cmd = [cls.NVBOOTCTRL]
        if target:
            cmd.extend(["-t", target])
        cmd.append(_cmd)
        if _slot_id:
            cmd.append(_slot_id)

        res = run(
            cmd,
            check=True,
            capture_output=True,
        )
        if check_output:
            return res.stdout.decode()
        return

    @staticmethod
    def _check_slot_id(slot_id: SlotID) -> SlotID:
        if slot_id not in [SlotID("0"), SlotID("1")]:
            raise ValueError(f"invalid slot id: {slot_id=}")
        return slot_id

    @classmethod
    def get_current_slot(cls, *, target: Optional[NVBootctrlTarget] = None) -> SlotID:
        """Prints currently running SLOT."""
        cmd = "get-current-slot"
        return cls._nvbootctrl(cmd, target=target)

    @classmethod
    def get_standby_slot(cls, *, target: Optional[NVBootctrlTarget] = None) -> SlotID:
        """Prints standby SLOT.

        NOTE: this method is implemented by nvbootctrl get-current-slot.
        """
        return SlotIDFlip[cls.get_current_slot(target=target)]

    @classmethod
    def set_active_boot_slot(
        cls, slot_id: SlotID, *, target: Optional[NVBootctrlTarget] = None
    ) -> None:
        """On next boot, load and execute SLOT."""
        cmd = "set-active-boot-slot"
        return cls._nvbootctrl(cmd, cls._check_slot_id(slot_id), target=target)

    @classmethod
    def set_slot_as_unbootable(
        cls, slot_id: SlotID, *, target: Optional[NVBootctrlTarget] = None
    ) -> None:
        """Mark SLOT as invalid."""
        cmd = "set-slot-as-unbootable"
        return cls._nvbootctrl(cmd, cls._check_slot_id(slot_id), target=target)

    @classmethod
    def dump_slots_info(cls, *, target: Optional[NVBootctrlTarget] = None) -> str:
        """Prints info for slots."""
        cmd = "dump-slots-info"
        return cls._nvbootctrl(cmd, target=target, check_output=True)

    @classmethod
    def is_unified_enabled(cls) -> bool | None:
        """Returns 0 only if unified a/b is enabled.

        NOTE: this command is available after BSP R32.6.1.

        Meaning of return code:
            - 0 if both unified A/B and rootfs A/B are enabled
            - 69 if both unified A/B and rootfs A/B are disabled
            - 70 if rootfs A/B is enabled and unified A/B is disabled

        Returns:
            True for both unified A/B and rootfs A/B are enbaled,
                False for unified A/B disabled but rootfs A/B enabled,
                None for both disabled.
        """
        cmd = "is-unified-enabled"
        try:
            cls._nvbootctrl(cmd)
            return True
        except CalledProcessError as e:
            if e.returncode == 70:
                return False
            elif e.returncode == 69:
                return
            raise ValueError(f"{cmd} returns unexpected result: {e.returncode=}, {e!r}")


class NVUpdateEngine:
    """Firmware update implementation using nv_update_engine."""

    NV_UPDATE_ENGINE = "nv_update_engine"

    @classmethod
    def _nv_update_engine(cls, payload: Path | str):
        cmd = [
            cls.NV_UPDATE_ENGINE,
            "-i",
            "bl",
            "--payload",
            str(payload),
            "--no-reboot",
        ]
        logger.info(f"apply BUP {payload=}")
        run(cmd, check=True, capture_output=True)

    @classmethod
    def _nv_update_engine_unified_ab(cls, payload: Path | str):
        cmd = [
            cls.NV_UPDATE_ENGINE,
            "-i",
            "bl-only",
            "--payload",
            str(payload),
        ]
        logger.info(f"apply BUP {payload=} with unified A/B")
        run(cmd, check=True, capture_output=True)

    @classmethod
    def apply_firmware_update(cls, payload: Path | str, *, unified_ab: bool) -> bool:
        try:
            if unified_ab:
                cls._nv_update_engine_unified_ab(payload)
            else:
                cls._nv_update_engine(payload)
            return True
        except CalledProcessError as e:
            logger.error(
                f"failed to apply BUP {payload}, {unified_ab=}: {e!r}, {e.stderr=}, {e.stdout=}"
            )
        return False

    @classmethod
    def verify_update(cls) -> str:
        """Dump the nv_update_engine update verification."""
        cmd = [cls.NV_UPDATE_ENGINE, "--verify"]
        res = run(cmd, check=False, capture_output=True)
        return res.stdout.decode()


BSP_VER_PA = re.compile(
    (
        r"R(?P<major_ver>\d+) \(\w+\), REVISION: (?P<major_rev>\d+)\.(?P<minor_rev>\d+), "
        r"GCID: (?P<gcid>\d+), BOARD: (?P<board>\w+), EABI: (?P<eabi>\w+)"
    )
)


def parse_bsp_version(nv_tegra_release: str) -> BSPVersion:
    """Get current BSP version from /etc/nv_tegra_release."""
    ma = BSP_VER_PA.match(nv_tegra_release)
    assert ma, f"invalid nv_tegra_release content: {nv_tegra_release}"
    return (
        int(ma.group("major_ver")),
        int(ma.group("major_rev")),
        int(ma.group("minor_rev")),
    )


class _CBootControl:

    def __init__(self):
        # ------ sanity check, confirm we are at jetson device ------ #
        if os.path.exists(cfg.TEGRA_CHIP_ID_PATH):
            _err_msg = f"not a jetson device, {cfg.TEGRA_CHIP_ID_PATH} doesn't exist"
            logger.error(_err_msg)
            raise JetsonCBootContrlError(_err_msg)

        # ------ check BSP version ------ #
        try:
            self.bsp_version = bsp_version = parse_bsp_version(
                Path(cfg.NV_TEGRA_RELEASE_FPATH).read_text()
            )
        except Exception as e:
            _err_msg = f"failed to detect BSP version: {e!r}"
            logger.error(_err_msg)
            raise JetsonCBootContrlError(_err_msg)
        logger.info(f"{bsp_version=}")

        # ------ sanity check, jetson-cboot is not used after BSP R34 ------ #
        if not bsp_version < (34, 0, 0):
            raise JetsonCBootContrlError(
                f"jetson-cboot only supports BSP version < R34, but get {bsp_version=}. "
                "Please use jetson-uefi bootloader type for this device."
            )

        # ------ check if unified A/B is enabled ------ #
        self.unified_ab_enabled = unified_ab_enabled = False
        if bsp_version >= (32, 6, 0):
            # NOTE: unified A/B is supported starting from r32.6
            self.unified_ab_enabled = unified_ab_enabled = (
                _NVBootctrl.is_unified_enabled()
            )
            if unified_ab_enabled is None:
                _err_msg = "rootfs A/B is not enabled!"
                logger.error(_err_msg)
                raise JetsonCBootContrlError(_err_msg)
        else:
            try:
                _NVBootctrl.get_current_slot()
            except CalledProcessError:
                _err_msg = "rootfs A/B is not enabled!"
                logger.error(_err_msg)
                raise JetsonCBootContrlError(_err_msg)

        # ------ check A/B slots ------ #
        # if unified A/B is not enabled, and bootloader slot and rootfs slot mismatch,
        #   try to correct this mismatch by switch bootloader to align with rootfs slot.
        if not unified_ab_enabled:
            current_rootfs_slot = _NVBootctrl.get_current_slot(target="rootfs")
            current_bootloader_slot = _NVBootctrl.get_current_slot()
            if current_rootfs_slot != current_bootloader_slot:
                logger.error(
                    "bootloader and rootfs A/B slot mismatches: "
                    f"{current_rootfs_slot=}, {current_bootloader_slot=}"
                )
                logger.warning(
                    "try to correct this mismatch by switch bootloader slot "
                    "to align with rootfs slot"
                )
                logger.warning("rebooting now ...")
                _NVBootctrl.set_active_boot_slot(current_rootfs_slot)
                CMDHelperFuncs.reboot()

        # at this point bootloader slot and rootfs slot is the same
        self.current_slot = current_slot = _NVBootctrl.get_current_slot()
        self.standby_slot = standby_slot = _NVBootctrl.get_standby_slot()

        # ------ detect rootfs_dev and parent_dev ------ #
        rootfs_dev_path = CMDHelperFuncs.get_current_rootfs_dev().strip()
        current_rootfs_dev = Path(rootfs_dev_path).name
        parent_dev_path = CMDHelperFuncs.get_parent_dev(rootfs_dev_path)
        self.parent_dev = parent_dev = Path(parent_dev_path).name

        self.external_rootfs = False
        if parent_dev.startswith(MMCBLK_DEV_PREFIX):
            logger.info(f"device boots from internal emmc: {parent_dev}")
        elif parent_dev.startswith(NVMESSD_DEV_PREFIX):
            logger.info(f"device boots from external nvme ssd: {parent_dev}")
            self.external_rootfs = True
        else:
            _err_msg = f"we don't support boot from {parent_dev=} currently"
            logger.error(_err_msg)
            raise JetsonCBootContrlError(_err_msg) from NotImplementedError(
                f"unsupported bootdev {parent_dev}"
            )

        # rootfs partition
        self.current_rootfs_dev = current_rootfs_dev
        current_rootfs_dev_partuuid = CMDHelperFuncs.get_partuuid_by_dev(
            rootfs_dev_path
        )
        self.standby_rootfs_dev = f"{parent_dev}p{SlotIDPartIDMapping[standby_slot]}"
        self.standby_rootfs_dev_partuuid = CMDHelperFuncs.get_partuuid_by_dev(
            f"/dev/{self.standby_rootfs_dev}"
        )

        # internal emmc partition
        self.current_internal_emmc_dev = (
            f"{INTERNAL_EMMC_DEV}p{SlotIDPartIDMapping[current_slot]}"
        )
        self.standby_internal_emmc_dev = (
            f"{INTERNAL_EMMC_DEV}p{SlotIDPartIDMapping[standby_slot]}"
        )

        logger.info(
            f"finished cboot control init: {current_rootfs_dev=},{current_slot=}\n"
            f"{current_rootfs_dev_partuuid=}, {self.standby_rootfs_dev_partuuid=}"
        )
        logger.info(f"{_NVBootctrl.dump_slots_info()=}")

    # API

    @property
    def external_rootfs_enabled(self) -> bool:
        return self.external_rootfs

    def finalize_switching_boot(self) -> bool:
        """Dump information after OTA reboot, this method always return True.

        Actually we don't need to do anything for finalizing jetson-cboot, as:

            1. if rootfs/bootloader boots failed, jetson boot will automatically
                fallback to previous slot. This situation can be handled by OTAStatusFilesControl.

            2. if boot switches successfully, the jetson boot will automatically
                set the status of slots to success.
        """
        try:
            logger.info(f"nv_update_engine verify: {NVUpdateEngine.verify_update()}")
            logger.info(f"{_NVBootctrl.dump_slots_info()=}")
            logger.info(f"{_NVBootctrl.dump_slots_info(target='rootfs')}")
        except CalledProcessError as e:
            logger.warning(f"failed to dump info: {e!r}")

        return True

    def set_standby_rootfs_unbootable(self):
        _NVBootctrl.set_slot_as_unbootable(self.standby_slot, target="rootfs")

    def switch_boot(self) -> None:
        target_slot = self.standby_slot

        logger.info(f"switch boot to {target_slot=}")
        if not self.unified_ab_enabled:
            # when unified_ab enabled, switching bootloader slot will also switch
            #   the rootfs slot.
            _NVBootctrl.set_active_boot_slot(target_slot, target="bootloader")
        # NOTE: the set-active-boot-slot command can be called multiple time.
        _NVBootctrl.set_active_boot_slot(target_slot)

    def prepare_standby_dev(self, *, erase_standby: bool):
        if CMDHelperFuncs.is_target_mounted(self.standby_rootfs_dev):
            CMDHelperFuncs.umount(self.standby_rootfs_dev)

        if erase_standby:
            try:
                CMDHelperFuncs.mkfs_ext4(self.standby_rootfs_dev)
            except Exception as e:
                _err_msg = f"failed to mkfs.ext4 on standby dev: {e!r}"
                logger.error(_err_msg)
                raise JetsonCBootContrlError(_err_msg) from e
        # TODO: in the future if in-place update mode is implemented, do a
        #   fschck over the standby slot file system.

    @staticmethod
    def update_extlinux_cfg(_input: str, partuuid: str) -> str:
        """Update input exlinux text with input rootfs <partuuid_str>."""

        partuuid_str = f"PARTUUID={partuuid}"

        def _replace(ma: re.Match, repl: str):
            append_l: str = ma.group(0)
            if append_l.startswith("#"):
                return append_l
            res, n = re.compile(r"root=[\w\-=]*").subn(repl, append_l)
            if not n:  # this APPEND line doesn't contain root= placeholder
                res = f"{append_l} {repl}"

            return res

        _repl_func = partial(_replace, repl=f"root={partuuid_str}")
        return re.compile(r"\n\s*APPEND.*").sub(_repl_func, _input)


class JetsonCBootControl(BootControllerProtocol):
    """BootControllerProtocol implementation for jetson-cboot."""

    def __init__(self) -> None:
        try:
            self._cboot_control = _CBootControl()

            # mount point prepare
            self._mp_control = SlotMountHelper(
                standby_slot_dev=self._cboot_control.standby_rootfs_dev,
                standby_slot_mount_point=cfg.MOUNT_POINT,
                active_slot_dev=self._cboot_control.current_rootfs_dev,
                active_slot_mount_point=cfg.ACTIVE_ROOT_MOUNT_POINT,
            )
            # init ota-status files
            self._ota_status_control = OTAStatusFilesControl(
                active_slot=self._cboot_control.current_slot,
                standby_slot=self._cboot_control.standby_slot,
                current_ota_status_dir=Path(cfg.ACTIVE_ROOTFS_PATH)
                / Path(cfg.OTA_STATUS_DIR).relative_to("/"),
                # NOTE: might not yet be populated before OTA update applied!
                standby_ota_status_dir=Path(cfg.MOUNT_POINT)
                / Path(cfg.OTA_STATUS_DIR).relative_to("/"),
                finalize_switching_boot=self._cboot_control.finalize_switching_boot,
            )

        except Exception as e:
            _err_msg = f"failed to start jetson-cboot controller: {e!r}"
            raise ota_errors.BootControlStartupFailed(_err_msg, module=__name__) from e

    def _copy_standby_slot_boot_to_internal_emmc(self):
        """Copy the standby slot's /boot to internal emmc dev.

        This method is involved when external rootfs is enabled, aligning with
            the behavior with the NVIDIA flashing script.

        NOTE: at the time this method is called, the /boot folder at
            standby slot rootfs MUST be fully setup!
        """
        # mount the actual standby_boot_dev now
        _internal_emmc_mp = Path(cfg.SEPARATE_BOOT_MOUNT_POINT)
        _internal_emmc_mp.mkdir(exist_ok=True, parents=True)

        try:
            CMDHelperFuncs.mount_rw(
                self._cboot_control.standby_internal_emmc_dev,
                _internal_emmc_mp,
            )
        except Exception as e:
            _msg = f"failed to mount standby internal emmc dev: {e!r}"
            logger.error(_msg)
            raise JetsonCBootContrlError(_msg) from e

        try:
            dst = _internal_emmc_mp / "boot"
            dst.mkdir(exist_ok=True, parents=True)
            src = self._mp_control.standby_slot_mount_point / "boot"

            # copy the standby slot's boot folder to emmc boot dev
            copytree_identical(src, dst)
        except Exception as e:
            _msg = f"failed to populate standby slot's /boot folder to standby internal emmc dev: {e!r}"
            logger.error(_msg)
            raise JetsonCBootContrlError(_msg) from e
        finally:
            CMDHelperFuncs.umount(_internal_emmc_mp, ignore_error=True)

    def _preserve_ota_config_files_to_standby(self):
        """Preserve /boot/ota to standby /boot folder."""
        src = self._mp_control.active_slot_mount_point / "boot" / "ota"
        if not src.is_dir():  # basically it is not possible
            logger.info(f"{src} doesn't exist, skip preserve /boot/ota folder.")
            return

        dst = self._mp_control.standby_slot_mount_point / "boot" / "ota"
        # TODO: (20240411) reconsidering should we preserve /boot/ota?
        copytree_identical(src, dst)

    def _update_standby_slot_extlinux_cfg(self):
        src = standby_slot_extlinux = self._mp_control.standby_slot_mount_point / Path(
            cfg.EXTLINUX_FILE
        ).relative_to("/")
        if not standby_slot_extlinux.is_file():
            src = self._mp_control.active_slot_mount_point / Path(
                cfg.EXTLINUX_FILE
            ).relative_to("/")

        # update the extlinux.conf with standby slot rootfs' partuuid
        updated_extlinux_cfg = self._cboot_control.update_extlinux_cfg(
            src.read_text(),
            self._cboot_control.standby_rootfs_dev_partuuid,
        )
        write_str_to_file_sync(standby_slot_extlinux, updated_extlinux_cfg)

    def _nv_firmware_update(self):
        logger.info("jetson-cboot: nv firmware update ...")
        firmware_dpath = self._mp_control.standby_slot_mount_point / "opt/ota_package"
        firmware_fnames = ["bl_only_payload", "xusb_only_payload"]
        unified_ab = bool(self._cboot_control.unified_ab_enabled)

        _firmware_applied = False
        for firmware in firmware_fnames:
            firmware_fpath = firmware_dpath / firmware
            if firmware_fpath.is_file():
                logger.info(f"nv_firmware: apply {firmware_fpath} ...")
                NVUpdateEngine.apply_firmware_update(
                    firmware_fpath, unified_ab=unified_ab
                )
                _firmware_applied = True

        if _firmware_applied:
            # TODO: update firmware_bsp_version file
            logger.info(
                "nv_firmware: apply firmware completed, bootloader slot "
                f"will switch to {self._cboot_control.standby_slot}"
            )
        else:
            logger.info("no firmware payload BUP available, skip firmware update")

    # APIs

    def get_standby_slot_path(self) -> Path:
        return self._mp_control.standby_slot_mount_point

    def get_standby_boot_dir(self) -> Path:
        return self._mp_control.standby_boot_dir

    def pre_update(self, version: str, *, standby_as_ref: bool, erase_standby: bool):
        try:
            logger.info("jetson-cboot: pre-update ...")
            # udpate active slot's ota_status
            self._ota_status_control.pre_update_current()

            # set standby rootfs as unbootable as we are going to update it
            self._cboot_control.set_standby_rootfs_unbootable()

            # prepare standby slot dev
            self._cboot_control.prepare_standby_dev(erase_standby=erase_standby)
            # mount slots
            self._mp_control.mount_standby()
            self._mp_control.mount_active()

            # update standby slot's ota_status files
            self._ota_status_control.pre_update_standby(version=version)
        except Exception as e:
            _err_msg = f"failed on pre_update: {e!r}"
            logger.error(_err_msg)
            raise ota_errors.BootControlPreUpdateFailed(
                _err_msg, module=__name__
            ) from e

    def post_update(self) -> Generator[None, None, None]:
        try:
            logger.info("jetson-cboot: post-update ...")
            # ------ processing standby slot rootfs' /boot folder ------ #
            self._update_standby_slot_extlinux_cfg()
            self._preserve_ota_config_files_to_standby()
            if self._cboot_control.external_rootfs:
                logger.info(
                    "rootfs on external storage detected: "
                    "copy standby slot rootfs' /boot folder "
                    "to corresponding internal emmc dev ..."
                )
                self._copy_standby_slot_boot_to_internal_emmc()

            # ------ firmware update ------ #
            self._nv_firmware_update()
            # ------ switch boot to standby ------ #
            self._cboot_control.switch_boot()

            # ------ prepare to reboot ------ #
            self._mp_control.umount_all(ignore_error=True)
            logger.info(f"[post-update]: {_NVBootctrl.dump_slots_info()=}")

            logger.info("post update finished, wait for reboot ...")
            yield  # hand over control back to otaclient
            CMDHelperFuncs.reboot()
        except Exception as e:
            _err_msg = f"failed on post_update: {e!r}"
            logger.error(_err_msg)
            raise ota_errors.BootControlPostUpdateFailed(
                _err_msg, module=__name__
            ) from e

    def pre_rollback(self):
        try:
            logger.info("jetson-cboot: pre-rollback setup ...")
            self._ota_status_control.pre_rollback_current()
            self._mp_control.mount_standby()
            self._ota_status_control.pre_rollback_standby()
        except Exception as e:
            _err_msg = f"failed on pre_rollback: {e!r}"
            logger.error(_err_msg)
            raise ota_errors.BootControlPreRollbackFailed(
                _err_msg, module=__name__
            ) from e

    def post_rollback(self):
        try:
            logger.info("jetson-cboot: post-rollback setup...")
            self._mp_control.umount_all(ignore_error=True)
            self._cboot_control.switch_boot()
            CMDHelperFuncs.reboot()
        except Exception as e:
            _err_msg = f"failed on post_rollback: {e!r}"
            logger.error(_err_msg)
            raise ota_errors.BootControlPostRollbackFailed(
                _err_msg, module=__name__
            ) from e

    def on_operation_failure(self):
        """Failure registering and cleanup at failure."""
        logger.warning("on failure try to unmounting standby slot...")
        self._ota_status_control.on_failure()
        self._mp_control.umount_all(ignore_error=True)

    def load_version(self) -> str:
        return self._ota_status_control.load_active_slot_version()

    def get_booted_ota_status(self) -> wrapper.StatusOta:
        return self._ota_status_control.booted_ota_status