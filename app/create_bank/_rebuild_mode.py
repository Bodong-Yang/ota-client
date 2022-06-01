import itertools
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Semaphore
from typing import Any, Callable, ClassVar, Dict, List
from urllib.parse import urljoin

from app.create_bank._common import (
    HardlinkRegister,
    CreateRegularStatsCollector,
    RegularStats,
    RegularInfSet,
    DeltaGenerator,
)
from app.configs import OTAFileCacheControl, config as cfg
from app.downloader import Downloader
from app.ota_update_stats import OtaClientStatistics
from app.ota_update_phase import OtaClientUpdatePhase
from app.ota_metadata import (
    DirectoryInf,
    OtaMetadata,
    PersistentInf,
    SymbolicLinkInf,
)

import log_util

logger = log_util.get_logger(
    __name__, cfg.LOG_LEVEL_TABLE.get(__name__, cfg.DEFAULT_LOG_LEVEL)
)


class RebuildMode:
    MAX_CONCURRENT_DOWNLOAD = cfg.MAX_CONCURRENT_DOWNLOAD
    MAX_CONCURRENT_TASKS = cfg.MAX_CONCURRENT_TASKS
    META_FILES: ClassVar[Dict[str, str]] = {
        "dirs.txt": "get_directories_info",
        "regulars.txt": "get_regulars_info",
        "persistents.txt": "get_persistent_info",
        "symlinks.txt": "get_symboliclinks_info",
    }

    def __init__(
        self,
        *,
        cookies: Dict[str, Any],
        metadata: OtaMetadata,
        url_base: str,
        mount_point: str,
        boot_dir: str,
        stats_tracker: OtaClientStatistics,
        status_updator: Callable,
    ) -> None:
        from app.proxy_info import proxy_cfg

        self.cookies = cookies
        self.metadata = metadata
        self.url_base = url_base
        self.mount_point = Path(mount_point)
        self.boot_dir = Path(boot_dir)
        self.stats_tracker = stats_tracker
        self.status_update: Callable = status_updator

        # the location of image at the ota server root
        self.image_base_dir = self.metadata.get_rootfsdir_info()["file"]
        self.image_base_url = urljoin(url_base, f"{self.image_base_dir}/")

        # temp storage
        self._meta_storage = tempfile.TemporaryDirectory(prefix="ota_metadata")
        self._meta_folder = Path(self._meta_storage.name)
        self._tmp_store = tempfile.TemporaryDirectory(prefix="ota_tmpstore")
        self._tmp_folder = Path(self._tmp_store.name)

        # configure the downloader
        self._downloader = Downloader()
        proxy = proxy_cfg.get_proxy_for_local_ota()
        if proxy:
            logger.info(f"use {proxy=} for downloading")
            self._downloader.configure_proxy(proxy)

    def __del__(self):
        self._meta_storage.cleanup()
        self._tmp_store.cleanup()

    def _prepare_meta_files(self):
        for fname, method in self.META_FILES:
            list_info = getattr(self.metadata, method)()
            self._downloader.download(
                path=list_info["file"],
                dst=self._meta_folder / fname,
                digest=list_info["hash"],
                url_base=self.url_base,
                cookies=self.cookies,
                headers={
                    OTAFileCacheControl.header_lower.value: OTAFileCacheControl.no_cache.value
                },
            )

        # TODO: hardcoded old_reg location
        delta_calculator = DeltaGenerator(
            old_reg="/opt/ota/image_meta/regulars.txt",
            new_reg=self._meta_folder / "regulars.txt",
        )
        _new, _hold, _ = delta_calculator.calculate_delta()
        self._new = _new
        self._hold = _hold

    def _process_persistents(self):
        """NOTE: just copy from legacy mode"""
        from app.copy_tree import CopyTree

        self.status_update(OtaClientUpdatePhase.PERSISTENT)
        _passwd_file = Path(cfg.PASSWD_FILE)
        _group_file = Path(cfg.GROUP_FILE)
        _copy_tree = CopyTree(
            src_passwd_file=_passwd_file,
            src_group_file=_group_file,
            dst_passwd_file=self.mount_point / _passwd_file.relative_to("/"),
            dst_group_file=self.mount_point / _group_file.relative_to("/"),
        )

        with open(self._meta_folder / "persistents.txt", "r") as f:
            for l in f:
                perinf = PersistentInf(l)
                if (
                    perinf.path.is_file()
                    or perinf.path.is_dir()
                    or perinf.path.is_symlink()
                ):  # NOTE: not equivalent to perinf.path.exists()
                    _copy_tree.copy_with_parents(perinf.path, self.mount_point)

    def _process_dirs(self):
        self.status_update(OtaClientUpdatePhase.DIRECTORY)
        with open(self._meta_folder / "dirs.txt", "r") as f:
            for l in f:
                DirectoryInf(l).mkdir2dst(self.mount_point)

        # TODO: save metadata to /opt/ota/image_meta

    def _process_symlinks(self):
        with open(self._meta_folder / "symlinks.txt", "r") as f:
            for l in f:
                SymbolicLinkInf(l).symlink2dst(self.mount_point)

    def _process_regulars(self):
        self.status_update(OtaClientUpdatePhase.REGULAR)
        with open(self._meta_folder / "regulars.txt", "r") as f:
            total_files_num = len(f.readlines())

        self.stats_tracker.set("total_regular_files", total_files_num)

        _hardlink_register = HardlinkRegister()
        _download_se = Semaphore(self.MAX_CONCURRENT_DOWNLOAD)
        _collector = CreateRegularStatsCollector(
            self.stats_tracker,
            total_regular_num=total_files_num,
            max_concurrency_tasks=self.MAX_CONCURRENT_TASKS,
        )

        with ThreadPoolExecutor(thread_name_prefix="create_standby_bank") as pool:
            # fire up background collector
            pool.submit(_collector.collector)

            for _hash, _regulars_set in itertools.chain(
                self._hold.items(), self._new.items()
            ):
                _collector.acquire_se()
                fut = pool.submit(
                    self._create_from_regs_set,
                    _hash,
                    _regulars_set,
                    hardlink_register=_hardlink_register,
                    download_se=_download_se,
                )
                fut.add_done_callback(_collector.callback)

            logger.info("all create_regular_files tasks dispatched, wait for collector")
            _collector.wait()

    def _create_from_regs_set(
        self,
        _hash: str,
        _regs_set: RegularInfSet,
        *,
        hardlink_register: HardlinkRegister,
        download_se: Semaphore,
    ) -> List[RegularStats]:
        _first_copy: Path = self._tmp_folder / _hash
        _first_copy_prepared = Event()
        if _first_copy.is_file():
            _first_copy_prepared.set()

        stats_list: List[RegularStats] = []
        for is_last, entry in _regs_set:
            _start = time.thread_time()
            _stat = RegularStats()

            # prepare first copy for the hash group
            if not _first_copy_prepared.is_set():
                if _regs_set.is_first_copy_available() or (
                    is_last and not entry.path.is_file()
                ):  # download the file to the tmp dir
                    _stat.op = "download"
                    with download_se:  # limit on-going downloading
                        _stat.errors = self._downloader.download(
                            entry.path,
                            _first_copy,
                            entry.sha256hash,
                            url_base=self.image_base_url,
                            cookies=self.cookies,
                        )
                else:  # copy from current bank
                    _stat.op = "copy"
                    entry.copy2dst(self._tmp_folder / _hash)

                _first_copy_prepared.set()

            # special treatment on /boot folder
            _mount_point = self.mount_point
            if Path("/boot") in entry.path.parents:
                _mount_point = self.boot_dir

            # prepare this entry
            if entry.nlink == 1:
                if is_last:  # move the tmp entry to the dst
                    entry.move_from_src(_first_copy, _mount_point=_mount_point)
                else:  # copy from the tmp dir
                    entry.copy_from_src(_first_copy, _mount_point=_mount_point)
            else:
                _stat.op = "link"
                # NOTE(20220523): for regulars.txt that support hardlink group,
                #   use inode to identify the hardlink group.
                #   otherwise, use hash to identify the same hardlink file.
                _identifier = entry.sha256hash
                if entry.inode:
                    _identifier = entry.inode

                _dst = _mount_point / entry.path.relative_to("/")
                _hardlink_tracker, _is_writer = hardlink_register.get_tracker(
                    _identifier, _dst, entry.nlink
                )
                if _is_writer:
                    entry.copy_from_src(_first_copy, _mount_point=_mount_point)
                    _hardlink_tracker.writer_done()
                else:
                    _src = _hardlink_tracker.subscribe()
                    _src.link_to(_dst)

                if is_last:  # cleanup last entry in tmp if not needed
                    _first_copy.unlink(missing_ok=True)

            _stat.elapsed = time.thread_time() - _start
            stats_list.append(_stat)

        return stats_list

    ###### exposed API ######
    def create_standby_bank(self):
        # TODO: erase bank on create_standby_bank
        self._prepare_meta_files()  # download meta and calculate
        self._process_dirs()
        self._process_regulars()
        self._process_symlinks()
        self._process_persistents()
