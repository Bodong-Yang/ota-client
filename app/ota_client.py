import json
import tempfile
import time
from contextlib import contextmanager
from json.decoder import JSONDecodeError
from pathlib import Path
from threading import Event, Lock
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from app.copy_tree import CopyTree
from app.create_bank import StandByBankCreator, get_reference_bank
from app.downloader import Downloader
from app.update_phase import OtaClientUpdatePhase
from app.interface import OtaClientInterface
from app.ota_metadata import OtaMetadata, PersistentInf
from app.ota_status import OtaStatus, OtaStatusControlMixin
from app.ota_error import (
    OtaClientFailureType,
    OtaErrorUnrecoverable,
    OtaErrorRecoverable,
    OtaErrorBusy,
)
from app.update_stats import OtaClientStatistics
from app.configs import OTAFileCacheControl, config as cfg
from app.proxy_info import proxy_cfg
from app import log_util

logger = log_util.get_logger(
    __name__, cfg.LOG_LEVEL_TABLE.get(__name__, cfg.DEFAULT_LOG_LEVEL)
)


class OtaStateSync:
    """State machine that synchronzing ota_service and ota_client.

    States switch:
        START -> S0, caller P1_ota_service:
            ota_service start the ota_proxy,
            wait for ota_proxy to finish initializing(scrub cache),
            and then signal ota_client
        S0 -> S1, caller P2_ota_client:
            ota_client wait for ota_proxy finish intializing,
            and then finishes pre_update procedure,
            signal ota_service to send update requests to all subecus
        S1 -> S2, caller P2_ota_client:
            ota_client finishes local update,
            signal ota_service to cleanup after all subecus are ready
        S2 -> END
            ota_service finishes cleaning up,
            signal ota_client to reboot

    Typical usage:
    a. wait on specific state
        fsm: OtaStateSync
        fsm.wait_on(fsm._S0, timeout=6)
    b. expect <state>, and doing something to switch to next state
        fsm: OtaStateSync
        with fsm.proceed(fsm._P1, expect=fsm._START) as _next:
            # do something here...
            print(f"done! switch to next state {_next}")
    """

    ######## state machine definition ########
    # states definition
    _START, _S0, _S1, _S2, _END = (
        "_START",  # start
        "_S0",  # cache_scrub_finished
        "_S1",  # pre_update_finished
        "_S2",  # apply_update_finished
        "_END",  # end
    )
    _STATE_LIST = [_START, _S0, _S1, _S2, _END]
    # participators definition
    _P1_ota_service, _P2_ota_client = "ota_service", "ota_client"
    # which participator can start the fsm
    _STARTER = _P1_ota_service

    # input: (<expected_state>, <caller>)
    # output: (<next_state>)
    _STATE_SWITCH = {
        (_START, _P1_ota_service): _S0,
        (_S0, _P2_ota_client): _S1,
        (_S1, _P2_ota_client): _S2,
        (_S2, _P1_ota_service): _END,
    }
    ######## end of state machine definition ########

    def __init__(self):
        """Init the state machine.

        Init Event for every state.
        Lower state name is the attribute name for state's Event.
            <state_name> -> <state_event>
            _S1 -> self._s1
        """
        for state_name in self._STATE_LIST:
            _state_event = Event()
            # create new state event
            setattr(self, state_name.lower(), _state_event)

    def start(self, caller: str):
        if caller != self._STARTER:
            raise RuntimeError(
                f"unexpected {caller=} starts status machine, expect {self._STARTER}"
            )

        _start_state: Event = getattr(self, self._START.lower())
        if not _start_state.is_set():
            _start_state.set()

    def _state_selector(self, caller, *, state: str) -> Tuple[Event, Event, str]:
        _input = (state, caller)
        if _input in self._STATE_SWITCH:
            cur_event = getattr(self, state.lower())
            next_state = self._STATE_SWITCH[_input]
            next_event = getattr(self, next_state.lower())
            return cur_event, next_event, next_state
        else:
            raise RuntimeError(f"unexpected {caller=} or {state=}")

    def wait_on(self, state: str, *, timeout: float = None) -> bool:
        """Wait on expected state."""
        _wait_on: Event = getattr(self, state.lower())
        return _wait_on.wait(timeout=timeout)

    @contextmanager
    def proceed(self, caller, *, expect, timeout: float = None) -> int:
        """State switching logic.

        This method support context protocol, run the state switching functions
        within with statement.
        """
        _wait_on, _next, _next_state = self._state_selector(caller, state=expect)

        if not _wait_on.wait(timeout=timeout):
            raise TimeoutError(f"timeout waiting state={expect}")

        try:
            # yield the next state to the caller
            yield _next_state
        finally:
            # after finish state switching functions, switch state
            if not _next.is_set():
                _next.set()
            else:
                raise RuntimeError(f"expect {_next_state=} not being set yet")


class _BaseOtaClient(OtaStatusControlMixin, OtaClientInterface):
    def __init__(self):
        self._lock = Lock()  # NOTE: can't be referenced from pool.apply_async target.
        self._failure_type = OtaClientFailureType.NO_FAILURE
        self._failure_reason = ""
        self._update_phase = OtaClientUpdatePhase.INITIAL
        self._update_start_time: int = 0  # unix time in milli-seconds

        self._mount_point = Path(cfg.MOUNT_POINT)
        self._passwd_file = Path(cfg.PASSWD_FILE)
        self._group_file = Path(cfg.GROUP_FILE)

        # statistics
        self._statistics = OtaClientStatistics()

        # downloader
        self._downloader = Downloader()

    def update(
        self,
        version,
        url_base,
        cookies_json: str,
        *,
        fsm: OtaStateSync,
    ):
        """
        main entry of the ota update logic
        exceptions are captured and recorded here
        """
        logger.debug("[update] entering...")

        try:
            cookies = json.loads(cookies_json)
            self._update(version, url_base, cookies, fsm=fsm)
            return self._result_ok()
        except OtaErrorBusy:  # there is an on-going update
            # not setting ota_status
            logger.exception("update busy")
            return OtaClientFailureType.RECOVERABLE
        except (JSONDecodeError, OtaErrorRecoverable) as e:
            logger.exception(msg="recoverable")
            self.set_ota_status(OtaStatus.FAILURE)
            self.store_standby_ota_status(OtaStatus.FAILURE)
            return self._result_recoverable(e)
        except (OtaErrorUnrecoverable, Exception) as e:
            logger.exception(msg="unrecoverable")
            self.set_ota_status(OtaStatus.FAILURE)
            self.store_standby_ota_status(OtaStatus.FAILURE)
            return self._result_unrecoverable(e)

    def rollback(self):
        try:
            self._rollback()
            return self._result_ok()
        except OtaErrorBusy:  # there is an on-going update
            # not setting ota_status
            logger.exception("rollback busy")
            return OtaClientFailureType.RECOVERABLE
        except OtaErrorRecoverable as e:
            logger.exception(msg="recoverable")
            self.set_ota_status(OtaStatus.ROLLBACK_FAILURE)
            self.store_standby_ota_status(OtaStatus.ROLLBACK_FAILURE)
            return self._result_recoverable(e)
        except (OtaErrorUnrecoverable, Exception) as e:
            logger.exception(msg="unrecoverable")
            self.set_ota_status(OtaStatus.ROLLBACK_FAILURE)
            self.store_standby_ota_status(OtaStatus.ROLLBACK_FAILURE)
            return self._result_unrecoverable(e)

    # NOTE: status should not update any internal status
    def status(self):
        try:
            status = self._status()
            return OtaClientFailureType.NO_FAILURE, status
        except OtaErrorRecoverable:
            logger.exception("recoverable")
            return OtaClientFailureType.RECOVERABLE, None
        except (OtaErrorUnrecoverable, Exception):
            logger.exception("unrecoverable")
            return OtaClientFailureType.UNRECOVERABLE, None

    """ private functions from here """

    def _result_ok(self):
        self._failure_type = OtaClientFailureType.NO_FAILURE
        self._failure_reason = ""
        return OtaClientFailureType.NO_FAILURE

    def _result_recoverable(self, e):
        logger.exception(e)
        self._failure_type = OtaClientFailureType.RECOVERABLE
        self._failure_reason = str(e)
        return OtaClientFailureType.RECOVERABLE

    def _result_unrecoverable(self, e):
        logger.exception(e)
        self._failure_type = OtaClientFailureType.UNRECOVERABLE
        self._failure_reason = str(e)
        return OtaClientFailureType.UNRECOVERABLE

    def _update(
        self,
        version,
        url_base: str,
        cookies: Dict[str, Any],
        *,
        fsm: OtaStateSync,
    ):
        logger.info(f"{version=},{url_base=},{cookies=}")
        """
        e.g.
        cookies = {
            "CloudFront-Policy": "eyJTdGF0ZW1lbnQ...",
            "CloudFront-Signature": "o4ojzMrJwtSIg~izsy...",
            "CloudFront-Key-Pair-Id": "K2...",
        }
        """
        # unconditionally regulate the url_base
        _url_base = urlparse(url_base)
        _path = f"{_url_base.path.rstrip('/')}/"
        url = _url_base._replace(path=_path).geturl()

        # set the status for ota-updating
        with self._lock:
            self.check_update_status()

            # set ota status
            self.set_ota_status(OtaStatus.UPDATING)
            # set update status
            self._update_phase = OtaClientUpdatePhase.INITIAL
            self._failure_type = OtaClientFailureType.NO_FAILURE
            self._update_start_time = int(time.time() * 1000)
            self._failure_reason = ""
            self._statistics.clear()

        proxy = proxy_cfg.get_proxy_for_local_ota()
        if proxy:
            fsm.wait_on(fsm._S0)
            self._downloader.configure_proxy(proxy)
            # wait for local ota cache scrubing finish

        with fsm.proceed(fsm._P2_ota_client, expect=fsm._S0) as _next:
            logger.debug("ota_client: signal ota_stub that pre_update finished")
            assert _next == fsm._S1

        # pre-update
        self.enter_update(version)

        # process metadata.jwt
        logger.debug("[update] process metadata...")
        self._update_phase = OtaClientUpdatePhase.METADATA
        metadata = self._process_metadata(url, cookies)
        total_regular_file_size = metadata.get_total_regular_file_size()
        if total_regular_file_size:
            self._statistics.set("total_regular_file_size", total_regular_file_size)

        # process bank creating
        def _update_phase(phase):
            self._update_phase = phase

        _standby_bank_creator = StandByBankCreator(
            cookies=cookies,
            metadata=metadata,
            url_base=url,
            new_root=str(self._mount_point),
            reference_root=get_reference_bank(
                cur_bank="/", standby_bank=str(self._mount_point)
            ),
            boot_dir=str(self.get_standby_boot_partition_path()),
            stats_tracker=self._statistics,
            status_updator=_update_phase,
        )
        _standby_bank_creator.create_standby_bank()

        # standby slot preparation finished, set phase to POST_PROCESSING
        logger.info("[update] update finished, entering post-update...")
        self._update_phase = OtaClientUpdatePhase.POST_PROCESSING

        # finish update, we reset the downloader's proxy setting
        self._downloader.cleanup_proxy()

        with fsm.proceed(fsm._P2_ota_client, expect=fsm._S1) as _next:
            assert _next == fsm._S2
            logger.debug("[update] signal ota_service that local update finished")

        logger.info("[update] leaving update, wait on ota_service and then reboot...")
        fsm.wait_on(fsm._END)
        self.leave_update()

    def _rollback(self):
        with self._lock:
            # enter rollback
            self.enter_rollback()
            self._failure_type = OtaClientFailureType.NO_FAILURE
            self._failure_reason = ""
        # leave rollback
        self.leave_rollback()

    def _status(self) -> dict:
        if self.get_ota_status() == OtaStatus.UPDATING:
            total_elapsed_time = int(time.time() * 1000) - self._update_start_time
            self._statistics.set("total_elapsed_time", total_elapsed_time)
        update_progress = self._statistics.get_snapshot().export_as_dict()
        # add extra fields
        update_progress["phase"] = self._update_phase.name

        return {
            "status": self.get_ota_status().name,
            "failure_type": self._failure_type.name,
            "failure_reason": self._failure_reason,
            "version": self.get_version(),
            "update_progress": update_progress,
        }

    def _verify_metadata(self, url_base, cookies, list_info, metadata):
        with tempfile.TemporaryDirectory(prefix=__name__) as d:
            file_name = Path(d) / list_info["file"]
            # NOTE: do not use cache when fetching metadata
            self._downloader.download(
                list_info["file"],
                file_name,
                list_info["hash"],
                url_base=url_base,
                cookies=cookies,
                headers={
                    OTAFileCacheControl.header_lower.value: OTAFileCacheControl.no_cache.value
                },
            )
            metadata.verify(open(file_name).read())
            logger.info("done")

    def _process_metadata(self, url_base, cookies: Dict[str, str]):
        with tempfile.TemporaryDirectory(prefix=__name__) as d:
            file_name = Path(d) / "metadata.jwt"
            # NOTE: do not use cache when fetching metadata
            self._downloader.download(
                "metadata.jwt",
                file_name,
                None,
                url_base=url_base,
                cookies=cookies,
                headers={
                    OTAFileCacheControl.header_lower.value: OTAFileCacheControl.no_cache.value
                },
            )

            metadata = OtaMetadata(open(file_name, "r").read())
            certificate_info = metadata.get_certificate_info()
            self._verify_metadata(url_base, cookies, certificate_info, metadata)
            logger.info("done")
            return metadata

    def _copy_persistent_files(self, list_file, standby_path):
        copy_tree = CopyTree(
            src_passwd_file=self._passwd_file,
            src_group_file=self._group_file,
            dst_passwd_file=standby_path / self._passwd_file.relative_to("/"),
            dst_group_file=standby_path / self._group_file.relative_to("/"),
        )
        lines = open(list_file).read().splitlines()
        for line in lines:
            perinf = PersistentInf(line)
            if (
                perinf.path.is_file()
                or perinf.path.is_dir()
                or perinf.path.is_symlink()
            ):  # NOTE: not equivalent to perinf.path.exists()
                copy_tree.copy_with_parents(perinf.path, standby_path)

    def enter_update(self, version):
        logger.debug("pre-update setup...")
        self.boot_ctrl_pre_update(version)
        self.store_standby_ota_status(OtaStatus.UPDATING)
        logger.debug("finished pre-update setup")

    def leave_update(self):
        logger.debug("post-update setup...")
        self.boot_ctrl_post_update()

    def enter_rollback(self):
        self.check_rollback_status()
        self.set_ota_status(OtaStatus.ROLLBACKING)
        self.store_standby_ota_status(OtaStatus.ROLLBACKING)

    def leave_rollback(self):
        self.boot_ctrl_post_rollback()


def gen_ota_client_class(bootloader: str):
    if bootloader == "grub":

        from app.grub_ota_partition import GrubControlMixin, OtaPartitionFile

        class OtaClient(_BaseOtaClient, GrubControlMixin):
            def __init__(self):
                super().__init__()

                self._boot_control: OtaPartitionFile = OtaPartitionFile()
                self._ota_status: OtaStatus = self.initialize_ota_status()

                logger.debug(f"ota status: {self._ota_status.name}")

    elif bootloader == "cboot":

        from app.extlinux_control import CBootControl, CBootControlMixin

        class OtaClient(_BaseOtaClient, CBootControlMixin):
            def __init__(self):
                super().__init__()

                # current slot
                self._ota_status_dir: Path = Path(cfg.OTA_STATUS_DIR)
                self._ota_status_file: Path = (
                    self._ota_status_dir / cfg.OTA_STATUS_FNAME
                )
                self._ota_version_file: Path = (
                    self._ota_status_dir / cfg.OTA_VERSION_FNAME
                )
                self._slot_in_use_file: Path = Path(cfg.SLOT_IN_USE_FILE)

                # standby slot
                self._standby_ota_status_dir: Path = (
                    self._mount_point / self._ota_status_dir.relative_to("/")
                )
                self._standby_ota_status_file = (
                    self._standby_ota_status_dir / cfg.OTA_STATUS_FNAME
                )
                self._standby_ota_version_file = (
                    self._standby_ota_status_dir / cfg.OTA_VERSION_FNAME
                )
                self._standby_slot_in_use_file = (
                    self._mount_point / self._slot_in_use_file.relative_to("/")
                )

                # standby bootdev
                self._standby_boot_mount_point = Path(cfg.SEPARATE_BOOT_MOUNT_POINT)

                self._boot_control: CBootControl = CBootControl()
                self._ota_status: OtaStatus = self.initialize_ota_status()
                self._slot_in_use = self.load_slot_in_use_file()

                logger.info(f"ota status: {self._ota_status.name}")

    return OtaClient


def _ota_client_class():
    bootloader = cfg.BOOTLOADER
    logger.debug(f"ota_client is running with {bootloader=}")

    return gen_ota_client_class(bootloader)


OtaClient = _ota_client_class()

if __name__ == "__main__":
    ota_client = OtaClient()
    ota_client.update("123.x", "http://localhost:8080", "{}")
