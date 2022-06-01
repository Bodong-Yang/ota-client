r"""Common used helpers, classes and functions for different bank creating methods."""
import time
import weakref
import queue
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Semaphore
from typing import List, Dict, Tuple

from app.configs import config as cfg

import log_util

logger = log_util.get_logger(
    __name__, cfg.LOG_LEVEL_TABLE.get(__name__, cfg.DEFAULT_LOG_LEVEL)
)


class _WeakRef:
    pass


class _HardlinkTracker:
    POLLINTERVAL = 0.1

    def __init__(self, first_copy_path: Path, ref: _WeakRef, count: int):
        self._first_copy_ready = Event()
        self._failed = Event()
        # hold <count> refs to ref
        self._ref_holder: List[_WeakRef] = [ref for _ in range(count)]

        self.first_copy_path = first_copy_path

    def writer_done(self):
        self._first_copy_ready.set()

    def writer_on_failed(self):
        self._failed.set()
        self._ref_holder.clear()

    def subscribe(self) -> Path:
        # wait for writer
        while not self._first_copy_ready.is_set():
            if self._failed.is_set():
                raise ValueError(f"writer failed on path={self.first_copy_path}")

            time.sleep(self.POLLINTERVAL)

        try:
            self._ref_holder.pop()
        except IndexError:
            # it won't happen generally as this tracker will be gc
            # after the ref holder holds no more ref.
            pass

        return self.first_copy_path


class HardlinkRegister:
    def __init__(self):
        self._lock = Lock()
        self._hash_ref_dict: Dict[str, _WeakRef] = weakref.WeakValueDictionary()
        self._ref_tracker_dict: Dict[
            _WeakRef, _HardlinkTracker
        ] = weakref.WeakKeyDictionary()

    def get_tracker(
        self, _identifier: str, path: Path, nlink: int
    ) -> "Tuple[_HardlinkTracker, bool]":
        """Get a hardlink tracker from the register.

        Args:
            _identifier: a string that can identify a group of hardlink file.
            path: path that the caller wants to save file to.
            nlink: number of hard links in this hardlink group.

        Returns:
            A hardlink tracker and a bool to indicates whether the caller is the writer or not.
        """
        with self._lock:
            _ref = self._hash_ref_dict.get(_identifier)
            if _ref:
                _tracker = self._ref_tracker_dict[_ref]
                return _tracker, False
            else:
                _ref = _WeakRef()
                _tracker = _HardlinkTracker(path, _ref, nlink - 1)

                self._hash_ref_dict[_identifier] = _ref
                self._ref_tracker_dict[_ref] = _tracker
                return _tracker, True


@dataclass
class RegularStats:
    """processed_list have dictionaries as follows:
    {"size": int}  # file size
    {"elapsed": int}  # elapsed time in seconds
    {"op": str}  # operation. "copy", "link" or "download"
    {"errors": int}  # number of errors that occurred when downloading.
    """

    op: str = ""
    size: int = 0
    elapsed: int = 0
    errors: int = 0


class CreateRegularStatsCollector:
    COLLECT_INTERVAL = cfg.STATS_COLLECT_INTERVAL

    def __init__(
        self,
        store,
        *,
        total_regular_num: int,
        max_concurrency_tasks: int,
    ) -> None:
        self._que = queue.Queue()
        self._store = store

        self.abort_event = Event()
        self.finished_event = Event()
        self.last_error = None
        self.se = Semaphore(max_concurrency_tasks)
        self.total_regular_num = total_regular_num

    def acquire_se(self):
        """Acquire se for dispatching task to threadpool,
        block if concurrency limit is reached."""
        self.se.acquire()

    def collector(self):
        _staging: List[RegularStats] = []
        _cur_time = time.time()
        while True:
            if self.abort_event.is_set():
                logger.error("abort event is set, collector exits")
                break

            if self._store.get_processed_num() < self.total_regular_num:
                try:
                    sts = self._que.get_nowait()
                    _staging.append(sts)
                except queue.Empty:
                    # if no new stats available, wait <_interval> time
                    time.sleep(self.COLLECT_INTERVAL)
            else:
                # all sts are processed
                self.finished_event.set()
                break

            # collect stats every <_interval> seconds
            if _staging and time.time() - _cur_time > self.COLLECT_INTERVAL:
                with self._store.acquire_staging_storage() as staging_storage:
                    staging_storage.regular_files_processed += len(_staging)

                    for st in _staging:
                        _suffix = st.op
                        if _suffix in {"copy", "link", "download"}:
                            staging_storage[f"files_processed_{_suffix}"] += 1
                            staging_storage[f"file_size_processed_{_suffix}"] += st.size
                            staging_storage[f"elapsed_time_{_suffix}"] += int(
                                st.elapsed * 1000
                            )

                            if _suffix == "download":
                                staging_storage[f"errors_{_suffix}"] += st.errors

                    # cleanup already collected stats
                    _staging.clear()

                _cur_time = time.time()

    def callback(self, fut: Future):
        """Callback for create regular files
        sts will also being put into que from this callback
        """
        try:
            sts: RegularStats = fut.result()
            self._que.put_nowait(sts)

            self.se.release()
        except Exception as e:
            self.last_error = e
            # if any task raises exception,
            # interrupt the background collector
            self.abort_event.set()
            raise

    def wait(self):
        """Waits until all regular files have been processed
        and detect any exceptions raised by background workers.

        Raise:
            Last error happens among worker threads.
        """
        # loop detect exception
        while not self.finished_event.is_set():
            # if done_event is set before all tasks finished,
            # it means exception happened
            time.sleep(self.COLLECT_INTERVAL)
            if self.abort_event.is_set():
                logger.error(
                    f"create_regular_files failed, last error: {self.last_error!r}"
                )
                raise self.last_error from None
