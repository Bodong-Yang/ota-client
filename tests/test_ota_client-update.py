import os
import pytest
import json
import shutil
import requests
import requests_mock
from urllib.parse import urljoin
from pytest_mock import MockerFixture
from pathlib import Path
from threading import Thread

from tests.conftest import (
    CUSTOM_CFG,
    DEFAULT_GRUB,
    DEFUALT_PROXY_INFO,
    FSTAB_DEV_DISK_BY_UUID_STANDBY,
    FSTAB_DEV_DISK_BY_UUID,
    GRUB_CFG_WO_SUBMENU,
    MockedCfgBundle,
    URL_BASE,
)


@pytest.fixture
def setup_test(tmp_path: Path):
    """Prepare test environment and return the corresponding configs bundle for testing.

    Configuration:
        1. partitions:
            a. current: sdx3 (UUID=01234567-0123-0123-0123-0123456789ab)
            b. standby: sdx4 (UUID=76543210-3210-3210-3210-ba9876543210)
            c. boot: sdx2
        2. ota status: INITIALIZED

    Folders setup:
        tmp_path/boot
                /boot/grub/
                /boot/grub/grub.cfg -> ../ota-partition/grub.cfg
                /boot/grub/custom.cfg
                /boot/ota-partition
                /boot/ota-partition.sdx3
                /boot/ota-partition.sdx4
                /etc/fstab
                /mnt/standby/
        /dev/sdx
        /dev/sdx2 /boot
        /dev/sdx3 / (UUID: 01234567-0123-0123-0123-0123456789ab)
        /dev/sdx4 (unmounted) (UUID: 76543210-3210-3210-3210-ba9876543210)
    """
    from app.configs import create_config
    import app.proxy_info as proxy_info

    ###### environment setup ######
    base_dir = tmp_path

    # boot
    boot_dir = base_dir / "boot"
    ota_dir = boot_dir / "ota"
    ota_dir.mkdir(parents=True, exist_ok=True)

    ## boot dir setup
    kernel_version = "5.4.0-73-generic"
    vmlinuz_file = f"vmlinuz-{kernel_version}"
    initrd_img_file = f"initrd.img-{kernel_version}"
    config_file = f"config-{kernel_version}"
    system_map_file = f"System.map-{kernel_version}"

    (boot_dir / vmlinuz_file).write_text(vmlinuz_file)
    (boot_dir / initrd_img_file).write_text(initrd_img_file)
    (boot_dir / config_file).write_text(config_file)
    (boot_dir / system_map_file).write_text(system_map_file)

    ## slots
    sdx3 = boot_dir / "ota-partition.sdx3"
    sdx4 = boot_dir / "ota-partition.sdx4"
    sdx3.mkdir(parents=True, exist_ok=True)
    sdx4.mkdir(parents=True, exist_ok=True)
    ota_partition = boot_dir / "ota-partition"
    ota_partition.symlink_to("ota-partition.sdx3")
    # NOTE: initialized
    (sdx4 / "status").write_text("INITIALIZED")
    (sdx3 / "version").write_text("a.b.c")

    ## grub
    grub_dir = boot_dir / "grub"
    grub_dir.mkdir()
    grub_cfg = grub_dir / "grub.cfg"
    grub_cfg.symlink_to(Path("..") / "ota-partition" / "grub.cfg")
    grub_cfg.write_text(GRUB_CFG_WO_SUBMENU)

    # etc
    etc_dir = tmp_path / "etc"
    etc_dir.mkdir()

    default_dir = etc_dir / "default"
    default_dir.mkdir()
    default_grub = default_dir / "grub"
    default_grub.write_text(DEFAULT_GRUB)

    fstab = etc_dir / "fstab"
    fstab.write_text(FSTAB_DEV_DISK_BY_UUID)

    # prepare passwd and group
    shutil.copy("/etc/passwd", etc_dir / "passwd")
    shutil.copy("/etc/group", etc_dir / "group")

    # mount point
    mount_point = base_dir / "mnt"
    mount_point.mkdir()
    standby_slot_mount = mount_point / "standby"

    ###### create test cfg ######
    cfg = create_config("grub")

    cfg.BOOT_DIR = str(boot_dir)
    cfg.MOUNT_POINT = str(standby_slot_mount)
    cfg.GRUB_CFG_FILE = str(grub_cfg)
    cfg.CUSTOM_CFG_FILE = str(grub_dir / "custom.cfg")
    cfg.FSTAB_FILE = str(etc_dir / "fstab")
    cfg.DEFAULT_GRUB_FILE = str(etc_dir / "default" / "grub")
    cfg.PROXY_INFO_FILE = str(ota_dir / "proxy_info.yaml")

    # proxy_info.yaml
    Path(cfg.PROXY_INFO_FILE).write_text(DEFUALT_PROXY_INFO)

    ###### create fixture ######
    return MockedCfgBundle(
        cfg=cfg, proxy_info=proxy_info.parse_proxy_info(cfg.PROXY_INFO_FILE)
    )


@pytest.fixture
def mocked_ota_client_mod(
    setup_test: MockedCfgBundle, mocker: MockerFixture, tmp_path: Path
):
    """Mocked ota_client module that configured by setup_test."""

    from app import ota_client
    from app.grub_ota_partition import OtaPartition, OtaPartitionFile
    from app.grub_control import GrubControl
    import app.create_bank._legacy_mode as legacy_mode

    ###### load cfgs ######
    _cfg, _proxy_info = setup_test
    boot_dir = Path(_cfg.BOOT_DIR)
    etc_dir = tmp_path / "etc"

    # patch OtaPartition
    mocker.patch.object(OtaPartition, "BOOT_DIR", boot_dir)
    mocker.patch.object(OtaPartition, "_get_root_device_file", return_value="/dev/sdx3")
    mocker.patch.object(OtaPartition, "_get_boot_device_file", return_value="/dev/sdx2")
    mocker.patch.object(
        OtaPartition, "_get_parent_device_file", return_value="/dev/sdx"
    )
    mocker.patch.object(
        OtaPartition, "_get_standby_device_file", return_value="/dev/sdx4"
    )

    # patch OtaPartitionFile
    mocker.patch.object(OtaPartitionFile, "_mount_cmd", return_value=0)

    # path GrubControl
    mocker.patch.object(GrubControl, "GRUB_CFG_FILE", boot_dir / "grub" / "grub.cfg")
    mocker.patch.object(
        GrubControl, "CUSTOM_CFG_FILE", boot_dir / "grub" / "custom.cfg"
    )
    mocker.patch.object(GrubControl, "FSTAB_FILE", tmp_path / "etc" / "fstab")
    mocker.patch.object(GrubControl, "DEFAULT_GRUB_FILE", etc_dir / "default" / "grub")

    def mock__get_uuid(_, device):
        if device == "sdx3":
            return "01234567-0123-0123-0123-0123456789ab"
        if device == "sdx4":
            return "76543210-3210-3210-3210-ba9876543210"

    mocker.patch.object(GrubControl, "_get_uuid", mock__get_uuid)
    cmdline = "BOOT_IMAGE=/vmlinuz-5.4.0-73-generic root=UUID=01234567-0123-0123-0123-0123456789ab ro maybe-ubiquity"

    mocker.patch.object(GrubControl, "_get_cmdline", return_value=cmdline)
    mocker.patch.object(GrubControl, "reboot", return_value=0)
    mocker.patch.object(GrubControl, "_grub_reboot_cmd", return_value=0)

    # NOTE:
    # basically patch to _count_menuentry is not required if
    # mock__grub_mkconfig_cmd is more sophisticated.
    mocker.patch.object(GrubControl, "_count_menuentry", return_value=1)

    def mock__grub_mkconfig_cmd(_, outfile):
        # TODO: depend on the outfile, grub.cfg with vmlinuz-ota entry should be output.
        outfile.write_text(GRUB_CFG_WO_SUBMENU)

    mocker.patch.object(GrubControl, "_grub_mkconfig_cmd", mock__grub_mkconfig_cmd)

    ###### load configs ######
    mocker.patch.object(legacy_mode, "proxy_cfg", setup_test.proxy_info)
    mocker.patch.object(ota_client, "proxy_cfg", _proxy_info)
    mocker.patch.object(ota_client, "cfg", _cfg)

    return ota_client


def test_ota_client_update(
    mocked_ota_client_mod,
    setup_test: MockedCfgBundle,
    tmp_path: Path,
):
    from app.ota_client import OtaClientFailureType, OtaStateSync
    from app.ota_status import OtaStatus

    ####### preload cfgs ######
    _cfg, _ = setup_test
    boot_dir = Path(_cfg.BOOT_DIR)

    ###### test settings ######
    target_version = "123.x"

    ####### test start ######
    ota_client_instance = mocked_ota_client_mod.OtaClient()

    ota_fsm = OtaStateSync()
    ota_fsm.start(caller=ota_fsm._P1_ota_service)

    with ota_fsm.proceed(ota_fsm._P1_ota_service, expect=ota_fsm._START) as _next:
        # simulate the local ota_proxy initialization
        assert _next == ota_fsm._S0

    _update_thread = Thread(
        target=ota_client_instance.update,
        args=(
            target_version,
            URL_BASE,
            json.dumps({"test": "my-cookie"}),
        ),
        kwargs={"fsm": ota_fsm},
    )
    _update_thread.start()

    assert ota_fsm.wait_on(ota_fsm._S2)
    with ota_fsm.proceed(ota_fsm._P1_ota_service, expect=ota_fsm._S2) as next_state:
        assert next_state == ota_fsm._END
    _update_thread.join()

    result, status = ota_client_instance.status()
    assert result == OtaClientFailureType.NO_FAILURE
    assert status["status"] == "UPDATING"
    assert status["failure_type"] == "NO_FAILURE"
    assert status["failure_reason"] == ""
    assert status["version"] == "a.b.c"
    progress = status["update_progress"]
    assert progress["phase"] == "POST_PROCESSING"
    # NOTE: numbers are depends on ota-image
    # total file size processed is:
    # find data/ -type f | xargs ls -l | awk '{total += $5}; END {print total}'
    TOTAL_FILES = 2499
    # NOTE: There is difference between github actins and local environment, so
    # approximate value is used.
    TOTAL_FILE_SIZE_APPROX = 108700000
    assert progress["total_regular_files"] == TOTAL_FILES
    assert progress["regular_files_processed"] == progress["total_regular_files"]
    assert (
        progress["files_processed_copy"]
        + progress["files_processed_link"]
        + progress["files_processed_download"]
        == progress["total_regular_files"]
    )
    assert (
        progress["file_size_processed_copy"]
        + progress["file_size_processed_link"]
        + progress["file_size_processed_download"]
    ) // 100000 == TOTAL_FILE_SIZE_APPROX // 100000
    assert type(progress["elapsed_time_copy"]) == int  # in milliseconds
    assert type(progress["elapsed_time_link"]) == int  # in milliseconds
    assert type(progress["elapsed_time_download"]) == int  # in milliseconds

    # make sure boot ota-partition is NOT switched
    assert os.readlink(boot_dir / "ota-partition") == "ota-partition.sdx3"
    assert (
        os.readlink(boot_dir / "vmlinuz-ota.standby")
        == "ota-partition.sdx4/vmlinuz-ota"
    )
    assert (
        os.readlink(boot_dir / "initrd.img-ota.standby")
        == "ota-partition.sdx4/initrd.img-ota"
    )

    assert (
        os.readlink(boot_dir / "ota-partition.sdx4" / "vmlinuz-ota")
        == "vmlinuz-5.8.0-53-generic"  # FIXME
    )
    assert (
        os.readlink(boot_dir / "ota-partition.sdx4" / "initrd.img-ota")
        == "initrd.img-5.8.0-53-generic"  # FIXME
    )
    assert open(boot_dir / "ota-partition.sdx4" / "status").read() == "UPDATING"
    assert open(boot_dir / "ota-partition.sdx4" / "version").read() == target_version
    # make sure grub.cfg is not created yet in standby boot partition
    assert not (boot_dir / "ota-partition.sdx4" / "grub.cfg").is_file()

    # custom.cfg is created
    assert (boot_dir / "grub" / "custom.cfg").is_file()
    assert open(boot_dir / "grub" / "custom.cfg").read() == CUSTOM_CFG

    # number of menuentry in GRUB_CFG_WO_SUBMENU is 9
    ota_client_instance._boot_control._grub_control._grub_reboot_cmd.assert_called_once_with(
        9
    )
    ota_client_instance._boot_control._grub_control.reboot.assert_called_once()

    # fstab
    assert (
        tmp_path / "mnt" / "standby" / "etc" / "fstab"
    ).read_text() == FSTAB_DEV_DISK_BY_UUID_STANDBY
    assert ota_client_instance.get_ota_status() == OtaStatus.UPDATING


def test_ota_client_update_multiple_call(mocked_ota_client_mod):
    from app.ota_client import OtaClientFailureType, OtaStateSync

    ###### test settings ######
    target_version = "123.x"

    ####### test start ######
    ota_client_instance = mocked_ota_client_mod.OtaClient()
    # check if _failure_type and _failure_reason are cleared by update call.
    ota_client_instance._failure_type = OtaClientFailureType.UNRECOVERABLE
    ota_client_instance._failure_reason = "fuga"

    # This test makes sure that event is set and failure type and reason are cleared.

    # p1: ota_service, p2: ota_client
    _main_fsm = OtaStateSync()
    _main_fsm.start(caller=_main_fsm._P1_ota_service)

    with _main_fsm.proceed(_main_fsm._P1_ota_service, expect=_main_fsm._START) as _next:
        # simulate the local ota_proxy initialization
        assert _next == _main_fsm._S0

    _main_update_thread = Thread(
        target=ota_client_instance.update,
        args=(
            target_version,
            URL_BASE,
            json.dumps({"test": "main-thread"}),
        ),
        kwargs={"fsm": _main_fsm},
    )
    _main_update_thread.start()
    # wait for ota_client to do update up to S2 state
    assert _main_fsm.wait_on(_main_fsm._S2)
    # not transit to the _END state now to block the main update thread

    result, status = ota_client_instance.status()
    assert result == OtaClientFailureType.NO_FAILURE
    assert status["status"] == "UPDATING"
    assert status["failure_reason"] == ""  # make sure failure_reason is cleared
    assert status["failure_type"] == "NO_FAILURE"  # make sure failure_type is cleared
    assert status["version"] == "a.b.c"

    # This request fails since ota status is UPDATING and returns immediately.
    _thread2_fsm = OtaStateSync()
    _thread2_fsm.start(caller=_thread2_fsm._P1_ota_service)

    with _thread2_fsm.proceed(
        _thread2_fsm._P1_ota_service, expect=_thread2_fsm._START
    ) as _next:
        # simulate the local ota_proxy initialization
        assert _next == _thread2_fsm._S0

    class _Wrapper:
        def __init__(self, func):
            self._failure = None
            self._func = func

        def __call__(self, *args, **kwargs):
            self._failure = self._func(*args, **kwargs)

        def result(self):
            return self._failure

    _wrapped_t = _Wrapper(ota_client_instance.update)
    th2 = Thread(
        target=_wrapped_t,
        args=(
            target_version,
            URL_BASE,
            json.dumps({"test": "thread2"}),
        ),
        kwargs={"fsm": _thread2_fsm},
    )
    th2.start()
    # ensure that the overlapping update doesn't happend,
    # the state machine will never reach to state S1(pre_update finished)
    assert not _thread2_fsm.wait_on(_thread2_fsm._S1, timeout=3)

    th2.join()
    # expect the above illegal update return a recoverable failure
    assert _wrapped_t.result() == OtaClientFailureType.RECOVERABLE

    result, status = ota_client_instance.status()
    assert result == OtaClientFailureType.NO_FAILURE
    assert status["status"] == "UPDATING"
    assert status["failure_reason"] == ""  # make sure failure_reason is unchanged
    assert status["failure_type"] == "NO_FAILURE"  # make sure failure_type is unchanged
    assert status["version"] == "a.b.c"

    # let the main update thread finish its job
    with _main_fsm.proceed(
        _main_fsm._P1_ota_service, expect=_main_fsm._S2
    ) as next_state:
        assert next_state == _main_fsm._END
    _main_update_thread.join()

    # ensure no errors
    result, status = ota_client_instance.status()
    assert result == OtaClientFailureType.NO_FAILURE
    assert status["status"] == "UPDATING"
    assert (
        status["update_progress"]["phase"] == "POST_PROCESSING"
    )  # ensure post_processing
    assert status["failure_reason"] == ""  # make sure failure_reason is unchanged
    assert status["failure_type"] == "NO_FAILURE"  # make sure failure_type is unchanged
    assert status["version"] == "a.b.c"


@pytest.mark.parametrize(
    "error_injection, failure_reason_has",
    [
        ({"status_code": 403}, "403"),
        (
            {"exc": requests.exceptions.ConnectTimeout},
            "ConnectTimeout",
        ),
        (
            {"exc": requests.exceptions.ReadTimeout},
            "ReadTimeout",
        ),
        (
            {"exc": requests.exceptions.ChunkedEncodingError},
            "ChunkedEncodingError",
        ),
    ],
)
def test_ota_client_update_regular_download_error(
    mocked_ota_client_mod,
    setup_test: MockedCfgBundle,
    error_injection,
    failure_reason_has,
):
    from app.ota_client import OtaClientFailureType, OtaStateSync
    from app.ota_status import OtaStatus

    # preload
    _cfg, _ = setup_test
    boot_dir = Path(_cfg.BOOT_DIR)

    ###### test settings ######
    target_version = "123.x"

    # test start
    ota_client_instance = mocked_ota_client_mod.OtaClient()

    ota_fsm = OtaStateSync()
    ota_fsm.start(caller=ota_fsm._P1_ota_service)

    with ota_fsm.proceed(ota_fsm._P1_ota_service, expect=ota_fsm._START) as _next:
        # simulate the local ota_proxy initialization
        assert _next == ota_fsm._S0

    def _background_update():
        with requests_mock.Mocker(real_http=True) as m:
            m.register_uri(
                "GET",
                urljoin(URL_BASE, "data/usr/bin/kill"),
                **error_injection,
            )

            ota_client_instance.update(
                target_version,
                URL_BASE,
                json.dumps({"test": "my-cookie"}),
                fsm=ota_fsm,
            )

    _update_thread = Thread(target=_background_update)
    _update_thread.start()

    # wait for update method to failed
    _update_thread.join()

    result, status = ota_client_instance.status()
    assert result == OtaClientFailureType.NO_FAILURE
    assert status["status"] == "FAILURE"
    assert status["failure_type"] == "RECOVERABLE"
    failure_reason = status["failure_reason"]
    assert failure_reason.find(failure_reason_has) != -1
    assert status["version"] == "a.b.c"
    assert status["failure_type"] == "RECOVERABLE"

    # make sure boot ota-partition is NOT switched
    assert os.readlink(boot_dir / "ota-partition") == "ota-partition.sdx3"
    assert not (boot_dir / "vmlinuz-ota.standby").exists()
    assert not (boot_dir / "initrd.img-ota.standby").exists()

    assert not (boot_dir / "ota-partition.sdx4" / "vmlinuz-ota").exists()
    assert not (boot_dir / "ota-partition.sdx4" / "initrd.img-ota").exists()
    assert open(boot_dir / "ota-partition.sdx4" / "status").read() == "FAILURE"
    assert open(boot_dir / "ota-partition.sdx4" / "version").read() == "123.x"
    # make sure grub.cfg is not created yet in standby boot partition
    assert not (boot_dir / "ota-partition.sdx4" / "grub.cfg").is_file()

    # custom.cfg is not created
    assert not (boot_dir / "grub" / "custom.cfg").exists()

    ota_client_instance._boot_control._grub_control._grub_reboot_cmd.assert_not_called()
    ota_client_instance._boot_control._grub_control.reboot.assert_not_called()

    assert ota_client_instance.get_ota_status() == OtaStatus.FAILURE


def test_ota_client_update_with_initialize_boot_partition(
    mocked_ota_client_mod,
    setup_test: MockedCfgBundle,
    mocker: MockerFixture,
    tmp_path: Path,
):
    from app.ota_client import OtaStateSync
    from app.ota_status import OtaStatus
    from app.grub_control import GrubControl

    ###### preload cfgs ######
    _cfg, _ = setup_test
    boot_dir = Path(_cfg.BOOT_DIR)
    grub_cfg = str(_cfg.GRUB_CFG_FILE)

    ###### extra patch ######
    grub_cfg_salt = "grub_cfg_salt"

    def mock__grub_mkconfig_cmd(_, outfile):
        # TODO: depend on the outfile, grub.cfg with vmlinuz-ota entry should be output.
        # to make the data different from GRUB_CFG_WO_SUBMENU
        outfile.write_text(GRUB_CFG_WO_SUBMENU + grub_cfg_salt)

    # re-patch again
    mocker.patch.object(GrubControl, "_grub_mkconfig_cmd", mock__grub_mkconfig_cmd)

    # remove the ota status file to let ota_client initialize grub configuration
    ota_partition_sdx3 = boot_dir / "ota-partition.sdx3"
    ota_partition_sdx4 = boot_dir / "ota-partition.sdx4"
    (ota_partition_sdx3 / "version").unlink(missing_ok=True)
    (ota_partition_sdx4 / "status").unlink(missing_ok=True)

    ###### test settings ######
    target_version = "123.x"

    ###### test start ######
    ota_client_instance = mocked_ota_client_mod.OtaClient()

    ota_fsm = OtaStateSync()
    ota_fsm.start(caller=ota_fsm._P1_ota_service)

    with ota_fsm.proceed(ota_fsm._P1_ota_service, expect=ota_fsm._START) as _next:
        # simulate the local ota_proxy initialization
        assert _next == ota_fsm._S0

    # make sure grub.cfg is not created yet in standby boot partition
    assert not (boot_dir / "ota-partition.sdx4" / "grub.cfg").is_file()

    # changed from regular file to symlink file
    assert os.readlink(grub_cfg) == str(Path("..") / "ota-partition" / "grub.cfg")
    # grub.cfg is generated under ota-partition
    assert (
        open(boot_dir / "ota-partition" / "grub.cfg").read()
        == GRUB_CFG_WO_SUBMENU + grub_cfg_salt
    )
    assert (
        open(boot_dir / "ota-partition.sdx3" / "grub.cfg").read()
        == GRUB_CFG_WO_SUBMENU + grub_cfg_salt
    )

    # start the update in another thread
    _update_thread = Thread(
        target=ota_client_instance.update,
        args=(
            target_version,
            URL_BASE,
            json.dumps({"test": "my-cookie"}),
        ),
        kwargs={"fsm": ota_fsm},
    )
    _update_thread.start()

    # finish up state machine
    assert ota_fsm.wait_on(ota_fsm._S2)
    with ota_fsm.proceed(ota_fsm._P1_ota_service, expect=ota_fsm._S2) as next_state:
        assert next_state == ota_fsm._END
    _update_thread.join()

    # make sure boot ota-partition is NOT switched
    assert os.readlink(boot_dir / "ota-partition") == "ota-partition.sdx3"
    assert (
        os.readlink(boot_dir / "vmlinuz-ota.standby")
        == "ota-partition.sdx4/vmlinuz-ota"
    )
    assert (
        os.readlink(boot_dir / "initrd.img-ota.standby")
        == "ota-partition.sdx4/initrd.img-ota"
    )

    assert (
        os.readlink(boot_dir / "ota-partition.sdx4" / "vmlinuz-ota")
        == "vmlinuz-5.8.0-53-generic"  # FIXME
    )
    assert (
        os.readlink(boot_dir / "ota-partition.sdx4" / "initrd.img-ota")
        == "initrd.img-5.8.0-53-generic"  # FIXME
    )
    assert open(boot_dir / "ota-partition.sdx4" / "status").read() == "UPDATING"
    assert open(boot_dir / "ota-partition.sdx4" / "version").read() == target_version

    # custom.cfg is created
    assert (boot_dir / "grub" / "custom.cfg").is_file()
    assert open(boot_dir / "grub" / "custom.cfg").read() == CUSTOM_CFG

    # number of menuentry in GRUB_CFG_WO_SUBMENU is 9
    ota_client_instance._boot_control._grub_control._grub_reboot_cmd.assert_called_once_with(
        9
    )
    ota_client_instance._boot_control._grub_control.reboot.assert_called_once()

    # fstab
    assert (
        open(tmp_path / "mnt" / "standby" / "etc" / "fstab").read()
        == FSTAB_DEV_DISK_BY_UUID_STANDBY
    )
    assert ota_client_instance.get_ota_status() == OtaStatus.UPDATING


def test_ota_client_update_post_process(
    mocked_ota_client_mod,
    setup_test: MockedCfgBundle,
    mocker: MockerFixture,
):
    from app.grub_ota_partition import OtaPartition
    from app.ota_status import OtaStatus

    ####### preload cfgs ######
    _cfg, _ = setup_test
    boot_dir = Path(_cfg.BOOT_DIR)

    ###### extra patching #######
    # now we are at new slot
    mocker.patch.object(OtaPartition, "_get_root_device_file", return_value="/dev/sdx4")
    mocker.patch.object(
        OtaPartition, "_get_standby_device_file", return_value="/dev/sdx3"
    )
    sdx4 = boot_dir / "ota-partition.sdx4"
    (sdx4 / "status").write_text("UPDATING")

    ###### test start ######
    # simulate reboot finished, let ota_client init
    ota_client_instance = mocked_ota_client_mod.OtaClient()

    # make sure boot ota-partition is switched
    assert os.readlink(boot_dir / "ota-partition") == "ota-partition.sdx4"

    assert open(boot_dir / "ota-partition.sdx3" / "status").read() == "SUCCESS"
    assert ota_client_instance.get_ota_status() == OtaStatus.SUCCESS

    assert (  # NOTE: mock__grub_mkconfig_cmd returns GRUB_CFG_WO_SUBMENU
        open(boot_dir / "ota-partition.sdx4" / "grub.cfg").read() == GRUB_CFG_WO_SUBMENU
    )

    ota_client_instance._boot_control._grub_control._grub_reboot_cmd.assert_not_called()
    ota_client_instance._boot_control._grub_control.reboot.assert_not_called()
    # TODO:
    # assert /etc/default/grub is updated
    # assert /boot/grub/grub.cfg is updated


PERSISTENTS_TXT = """\
'/etc/hosts'
'/etc/hostname'
'/etc/resolv.conf'
'/etc/netplan'
'/foo/bar'
"""


def test_ota_client__copy_persistent_files(
    mocked_ota_client_mod,
    setup_test: MockedCfgBundle,
    tmp_path: Path,
):
    ####### load cfgs ######
    _cfg, _ = setup_test
    etc_dir = tmp_path / "etc"
    etc_dir.mkdir(exist_ok=True)
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()

    ####### prepare standby slot ######
    mount_dir = Path(_cfg.MOUNT_POINT)
    passwd_file = mount_dir / "etc" / "passwd"
    group_file = mount_dir / "etc" / "group"
    (mount_dir / "etc").mkdir(parents=True, exist_ok=True)
    # copy /etc/passwd to mount_dir / "etc/passwd"
    shutil.copy("/etc/passwd", passwd_file)
    # copy /etc/group to mount_dir / "etc/group"
    shutil.copy("/etc/group", group_file)

    ####### prepare persistents file ######
    persistents_txt = tmp_dir / "persistents.txt"
    persistents_txt.write_text(PERSISTENTS_TXT)

    ####### test start ######
    ota_client_instance = mocked_ota_client_mod.OtaClient()
    ota_client_instance._copy_persistent_files(persistents_txt, mount_dir)

    assert open("/etc/hostname").read() == open(mount_dir / "etc" / "hostname").read()
