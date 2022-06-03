r"""Common used helpers, classes and functions for different bank creating methods."""
import os
import queue
import shutil
import time
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Semaphore
from typing import ClassVar, Generator, List, Dict, Set, Tuple, Union

from app._common import file_sha256
from app.configs import config as cfg
from app.ota_metadata import RegularInf
from app import log_util

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
            sts: List[RegularStats] = fut.result()
            for st in sts:
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


class RegularInfSet:
    def __init__(self, _hash: str, *, skip_verify) -> None:
        self._hash = _hash
        self._no_first_copy = skip_verify
        self.data: Set[RegularInf] = None
        self._first_copy: RegularInf = None

    def __iter__(self):
        return self

    def __next__(self) -> Tuple[bool, RegularInf]:
        """Always return first_copy if possible.

        Returns:
            A bool indicates whether it is the last entry.
        """
        try:
            if self._first_copy:
                res = self._first_copy
                self._first_copy = None
                return self.is_empty(), res

            res = self.data.pop()
            return self.is_empty(), res
        except KeyError:
            raise StopIteration

    def add(self, entry: RegularInf):
        # prepare a first copy for this hash group
        if (
            not self._no_first_copy
            and self._first_copy is None
            and verify_file(entry.path, entry.sha256hash, entry.size)
        ):
            self._first_copy = entry

        if self.data is None:
            self.data = set()
        self.data.add(entry)

    def remove(self, entry: RegularInf):
        self.data.remove(entry)

    def update(self, _other: "RegularInfSet"):
        self.data.update(_other.data)

    def is_empty(self):
        return self._first_copy is None and len(self.data) == 0

    def is_first_copy_available(self) -> bool:
        return self._no_first_copy


class RegularDelta(UserDict):
    def __init__(self, *, skip_verify=True) -> None:
        self._skip_verify = skip_verify
        self.data: Dict[str, RegularInfSet] = dict()

    def add_entry(self, entry: RegularInf):
        _hash = entry.sha256hash
        if _hash in self.data:
            self.data[_hash].add(entry)
        else:
            self.data[_hash] = RegularInfSet(_hash, skip_verify=self._skip_verify)

    def remove_entry(self, entry: RegularInf):
        _hash = entry.sha256hash
        if _hash not in self.data:
            raise KeyError(f"{_hash} not registered")

        _set = self.data[_hash]
        _set.remove(entry)
        if _set.is_empty():  # cleanup empty pathset
            del self.data[_hash]

    def merge_entryset(self, _hash: str, _pathset: RegularInfSet):
        _target_set = self.data[_hash]
        _target_set.update(_pathset)

    def __contains__(self, item: RegularInf):
        _hash = item.sha256hash
        return _hash in self.data and item in self.data[_hash]

    def if_contains_hash(self, _hash: str) -> bool:
        return _hash in self.data


class DeltaGenerator:
    # folders to scan on
    # NOTE: currently only handle /var/lib
    TARGET_FOLDERS: ClassVar[List[str]] = ["/var/lib"]

    def __init__(self, old_reg, new_reg) -> None:
        self._old_reg = old_reg
        self._new_reg = new_reg

    def _calculate_delta_offline(
        self,
    ) -> Tuple[RegularDelta, RegularDelta, RegularDelta]:
        _rm, _new, _hold = (
            RegularDelta(skip_verify=True),
            RegularDelta(skip_verify=True),
            RegularDelta(),  # _hold set needed to be verify
        )
        with open(self._old_reg, "r") as f:
            for l in f:
                entry = RegularInf(l)
                _rm.add_entry(entry)

        with open(self._new_reg, "r") as f:
            for l in f:
                entry = RegularInf(l)
                if entry in _rm:
                    _hold.add_entry(entry)
                    _rm.remove_entry(entry)
                    continue

                # add to _new
                _new.add_entry(entry)

        # optimize the calculated deltas
        _optimized_hash = []
        for _hash, _pathset in _new.items():
            if _hold.if_contains_hash(_hash):
                # merge this entry into the _existed
                _hold.merge_entryset(_hash, _pathset)
                _optimized_hash.append(_hash)

        # discard the optimized hash group
        for _hash in _optimized_hash:
            _new.pop(_hash)

        return _new, _hold, _rm

    def _calculate_delta_online(
        self,
    ) -> Tuple[RegularDelta, RegularDelta, RegularDelta]:
        _rm, _new, _hold = (
            RegularDelta(skip_verify=True),
            RegularDelta(skip_verify=True),
            RegularDelta(),  # _hold set needed to be verify
        )

    def calculate_delta(self) -> Tuple[RegularDelta, RegularDelta, RegularDelta]:
        pass
