import itertools
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, wait as concurrent_futures_wait
from pathlib import Path
from threading import Semaphore
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

from app import log_util

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
        old_bank_root: str,
    ) -> None:
        from app.proxy_info import proxy_cfg

        self.cookies = cookies
        self.metadata = metadata
        self.url_base = url_base
        self.old_bank_root = Path(old_bank_root)  # TODO: old bank
        self.new_bank_root = Path(mount_point)
        self.boot_dir = Path(boot_dir)
        self.stats_tracker = stats_tracker
        self.status_update: Callable = status_updator
        # the location of image at the ota server root
        self.image_base_dir = self.metadata.get_rootfsdir_info()["file"]
        self.image_base_url = urljoin(url_base, f"{self.image_base_dir}/")

        # temp storage
        # TODO: considering cross reboot persistent of /tmp/store
        # TODO: reused if update interrupted, unconditionally
        self._meta_folder: Path = None  # TODO: configured by cfg
        self._tmp_store = Path("/var/tmp/ota-tmp")  # TODO: configured by cfg
        self._tmp_folder = Path(self._tmp_store.name)

        # configure the downloader
        self._downloader = Downloader()
        proxy = proxy_cfg.get_proxy_for_local_ota()
        if proxy:
            logger.info(f"use {proxy=} for downloading")
            self._downloader.configure_proxy(proxy)

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
            bank_root=self.old_bank_root,
        )

        (
            self._new,
            self._hold,
            self._rm,
            self.total_files_num,
        ) = delta_calculator.calculate_delta()

    def _process_persistents(self):
        """NOTE: just copy from legacy mode"""
        from app.copy_tree import CopyTree

        self.status_update(OtaClientUpdatePhase.PERSISTENT)
        _passwd_file = Path(cfg.PASSWD_FILE)
        _group_file = Path(cfg.GROUP_FILE)
        _copy_tree = CopyTree(
            src_passwd_file=_passwd_file,
            src_group_file=_group_file,
            dst_passwd_file=self.new_bank_root / _passwd_file.relative_to("/"),
            dst_group_file=self.new_bank_root / _group_file.relative_to("/"),
        )

        with open(self._meta_folder / "persistents.txt", "r") as f:
            for l in f:
                perinf = PersistentInf(l)
                if (
                    perinf.path.is_file()
                    or perinf.path.is_dir()
                    or perinf.path.is_symlink()
                ):  # NOTE: not equivalent to perinf.path.exists()
                    _copy_tree.copy_with_parents(perinf.path, self.new_bank_root)

    def _process_dirs(self):
        self.status_update(OtaClientUpdatePhase.DIRECTORY)
        with open(self._meta_folder / "dirs.txt", "r") as f:
            for l in f:
                DirectoryInf(l).mkdir2bank(self.new_bank_root)

        # TODO: save metadata to /opt/ota/image_meta

    def _process_symlinks(self):
        with open(self._meta_folder / "symlinks.txt", "r") as f:
            for l in f:
                SymbolicLinkInf(l).symlink2bank(self.new_bank_root)

    def _process_regulars(self):
        self.status_update(OtaClientUpdatePhase.REGULAR)

        self._hardlink_register = HardlinkRegister()
        self._download_se = Semaphore(self.MAX_CONCURRENT_DOWNLOAD)
        _collector = CreateRegularStatsCollector(
            self.stats_tracker,
            total_regular_num=self.total_files_num,
            max_concurrency_tasks=self.MAX_CONCURRENT_TASKS,
        )

        with ThreadPoolExecutor(thread_name_prefix="create_standby_bank") as pool:
            # collect recycled files from _rm
            futs = []
            for _, _pathset in self._rm.items():
                futs.append(
                    pool.submit(
                        _pathset.collect_entries_to_be_recycled,
                        dst=self._tmp_folder,
                        root=self.old_bank_root,
                    )
                )

            concurrent_futures_wait(futs)
            del futs  # cleanup

            # apply delta _hold and _new
            pool.submit(_collector.collector)
            for _hash, _regulars_set in itertools.chain(
                self._hold.items(), self._new.items()
            ):
                _collector.acquire_se()
                fut = pool.submit(
                    self._apply_delta,
                    _hash,
                    _regulars_set,
                )
                fut.add_done_callback(_collector.callback)

            logger.info("all process_regulars tasks dispatched, wait for finishing")
            _collector.wait()

    def _apply_delta(self, _hash: str, _regs_set: RegularInfSet) -> List[RegularStats]:
        stats_list = []
        skip_cleanup = _regs_set.skip_cleanup

        _first_copy = self._tmp_folder / _hash
        for is_last, entry in _regs_set.iter_entries():
            _start = time.thread_time()
            _stat = RegularStats()

            # prepare first copy for the hash group
            if not _first_copy.is_file():
                _collected_entry = _regs_set.entry_to_be_collected
                try:
                    if _collected_entry is None:
                        raise FileNotFoundError

                    # copy from the current bank
                    _collected_entry.copy2dst(_first_copy, src_root=self.old_bank_root)
                    _stat.op = "copy"
                except FileNotFoundError:  # fallback to download from remote
                    _stat.op = "download"
                    with self._download_se:  # limit on-going downloading
                        _stat.errors = self._downloader.download(
                            entry.path,
                            _first_copy,
                            entry.sha256hash,
                            url_base=self.image_base_url,
                            cookies=self.cookies,
                        )

            # special treatment on /boot folder
            _mount_point = (
                self.new_bank_root
                if not str(entry.path).startswith("/boot")
                else self.boot_dir
            )

            # prepare this entry
            if entry.nlink == 1:
                if is_last and not skip_cleanup:  # move the tmp entry to the dst
                    entry.move_from_src(_first_copy, dst_root=_mount_point)
                else:  # copy from the tmp dir
                    entry.copy_from_src(_first_copy, dst_root=_mount_point)
            else:
                # NOTE(20220523): for regulars.txt that support hardlink group,
                #   use inode to identify the hardlink group.
                #   otherwise, use hash to identify the same hardlink file.
                _identifier = entry.sha256hash if entry.inode is None else entry.inode

                _dst = entry.relative_to(_mount_point)
                _hardlink_tracker, _is_writer = self._hardlink_register.get_tracker(
                    _identifier, _dst, entry.nlink
                )
                if _is_writer:
                    entry.copy_from_src(_first_copy, dst_root=_mount_point)
                else:
                    _stat.op = "link"
                    _src = _hardlink_tracker.subscribe_no_wait()
                    _src.link_to(_dst)

                if is_last and not skip_cleanup:
                    _first_copy.unlink(missing_ok=True)

            # finish up, collect stats
            _stat.elapsed = time.thread_time() - _start
            stats_list.append(_stat)

        return stats_list

    def create_standby_bank(self):
        # TODO: erase bank on create_standby_bank
        self._prepare_meta_files()  # download meta and calculate
        self._process_dirs()
        self._process_regulars()
        self._process_symlinks()
        self._process_persistents()

        # TODO: cleanup the the tmp folder
