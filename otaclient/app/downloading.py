r"""Download all the files needed for OTA udpate.

Files are save under <downloaded_ota_files> folder with 
the hash value as file name.
"""
import time
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from typing import List, Generator, Any

from .common import (
    OTAFileCacheControl,
    RetryTaskMap,
    InterruptTaskWaiting,
    urljoin_ensure_base,
    verify_file,
)
from .configs import config as cfg
from .downloader import (
    Downloader,
    HashVerificaitonError,
    DestinationNotAvailableError,
    DownloadError,
)
from .errors import (
    OTAMetaVerificationFailed,
    OTAErrorUnRecoverable,
    OTAMetaDownloadFailed,
    NetworkError,
)
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
        self._download_dir = Path(update_meta.download_dir)
        # where to store the OTA image meta
        self._image_meta_dir = Path(update_meta.ota_meta_dir)
        # stats tracker and collector from otaclient
        self._stats_collector = stats_collector

        # configure the downloader
        self._downloader = downloader
        self._proxies = None
        if proxy := proxy_cfg.get_proxy_for_local_ota():
            logger.info(f"use {proxy=} for downloading")
            # NOTE: check requests doc for details
            self._proxies = {"http": proxy}

        # check the download folder if there are files in it
        self._download_dir.mkdir(exist_ok=True, parents=True)
        for _f in self._download_dir.glob("*"):
            if not verify_file(_f, _f.name, None):
                _f.unlink(missing_ok=True)

    def _download_file(self, entry: RegularInf):
        _download_dst = self._download_dir / entry.sha256hash
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

    def prepare_ota_image_meta(self):
        """Download the OTA image meta files to the <image_meta_dir>."""
        try:
            for _meta_f in self._otameta.get_img_metafiles():
                meta_f_url = urljoin_ensure_base(self._url_base, quote(_meta_f.file))
                self._downloader.download(
                    meta_f_url,
                    self._image_meta_dir / _meta_f.file,
                    digest=_meta_f.hash,
                    proxies=self._proxies,
                    cookies=self._cookies,
                    headers={
                        OTAFileCacheControl.header_lower.value: OTAFileCacheControl.no_cache.value
                    },
                )
        except HashVerificaitonError as e:
            raise OTAMetaVerificationFailed from e
        except DestinationNotAvailableError as e:
            raise OTAErrorUnRecoverable from e
        except DownloadError as e:
            raise OTAMetaDownloadFailed from e

    def download_ota_files(
        self, download_meta: DownloadMeta
    ) -> Generator[Any, None, None]:
        """Download OTA files as download_meta indicated.

        This method will keep retrying until all the files are downloaded.
        """
        logger.info(
            f"start to download files: {download_meta.total_files_num=}, {download_meta.total_files_size=}"
        )
        try:
            with ThreadPoolExecutor(thread_name_prefix="ota_files_downloading") as pool:
                # limit concurrent downloading tasks
                _tasks_executor = RetryTaskMap(
                    self._download_file,
                    max_concurrent=cfg.MAX_CONCURRENT_TASKS,
                    executor=pool,
                    title="downloading_files",
                )
                for _res in _tasks_executor.map(download_meta.files_list):
                    try:
                        yield _res
                    except InterruptTaskWaiting:
                        _tasks_executor.shutdown()

                # wait for all stats being processed
                self._stats_collector.wait_staging()
        except Exception as e:
            raise NetworkError from e

    def cleanup_download_dir(self):
        shutil.rmtree(self._download_dir, ignore_errors=True)
