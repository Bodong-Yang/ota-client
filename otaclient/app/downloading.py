r"""Download all the files needed for OTA udpate.

Files are save under <downloaded_ota_files> folder with 
the hash value as file name.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from .common import SimpleTasksTracker
from .configs import config as cfg
from .downloader import Downloader
from .ota_metadata import RegularInf, UpdateMeta
from .proxy_info import proxy_cfg
from .update_stats import (
    OTAUpdateStatsCollector,
    RegInfProcessedStats,
    RegProcessOperation,
)

from .log_setting import get_logger

logger = get_logger(__name__, cfg.LOG_LEVEL_TABLE.get(__name__, cfg.DEFAULT_LOG_LEVEL))


class DownloadMeta:
    total_files_num: int
    total_files_size: int
    files_list: List[RegularInf]


class OTAFilesDownloader:
    def __init__(
        self,
        *,
        downloader: Downloader,
        update_meta: UpdateMeta,
        stats_collector: OTAUpdateStatsCollector,
    ) -> None:
        # extract update meta
        self._otameta = update_meta.metadata
        self._url_base = update_meta.url_base
        self._cookies = update_meta.cookies
        # where the downloaded files will go to
        self._storage_dir = Path(update_meta.download_dir)
        # stats tracker and collector from otaclient
        self._stats_collector = stats_collector

        # configure the downloader
        self._downloader = downloader
        self._proxies = None
        if proxy := proxy_cfg.get_proxy_for_local_ota():
            logger.info(f"use {proxy=} for downloading")
            # NOTE: check requests doc for details
            self._proxies = {"http": proxy}

    def _download_file(self, entry: RegularInf):
        _download_dst = self._storage_dir / entry.sha256hash
        if (_download_dst).is_file():
            return

        _cur_stat = RegInfProcessedStats(op=RegProcessOperation.OP_DOWNLOAD)
        _url, _compression_alg = self._otameta.get_download_url(
            entry, base_url=self._url_base
        )
        _start_time = time.thread_time_ns()
        _cur_stat.errors, _cur_stat.download_bytes = self._downloader.download(
            _url,
            _download_dst,
            digest=entry.sha256hash,
            size=entry.size,
            proxies=self._proxies,
            cookies=self._cookies,
            compression_alg=_compression_alg,
        )
        _cur_stat.size = _download_dst.stat().st_size
        _cur_stat.elapsed_ns = time.thread_time_ns() - _start_time
        # report the stat of this download
        self._stats_collector.report(_cur_stat)

    def download_ota_files(self, download_meta: DownloadMeta):
        logger.info(
            f"start to download files: {download_meta.total_files_num=}, {download_meta.total_files_size=}"
        )
        # limit concurrent downloading tasks
        _tasks_tracker = SimpleTasksTracker(
            max_concurrent=cfg.MAX_CONCURRENT_TASKS,
            title="process_regulars",
        )

        with ThreadPoolExecutor(thread_name_prefix="ota_files_downloading") as pool:
            for _entry in download_meta.files_list:
                # interrupt update if _tasks_tracker collects error
                if e := _tasks_tracker.last_error:
                    logger.error(f"interrupt update due to {e!r}")
                    raise e
                _tasks_tracker.add_task(
                    _fut := pool.submit(self._download_file, _entry)
                )
                _fut.add_done_callback(_tasks_tracker.done_callback)

            logger.info("all downloading tasks are dispatched, wait for finishing...")
            _tasks_tracker.task_collect_finished()
            _tasks_tracker.wait(self._stats_collector.wait_staging)
