import dataclasses
from contextlib import contextmanager
from threading import Lock
from typing import Any


@dataclasses.dataclass
class _OtaClientStatisticsStorage:
    total_regular_files: int = 0
    total_regular_file_size: int = 0
    regular_files_processed: int = 0
    files_processed_copy: int = 0
    files_processed_link: int = 0
    files_processed_download: int = 0
    file_size_processed_copy: int = 0
    file_size_processed_link: int = 0
    file_size_processed_download: int = 0
    elapsed_time_copy: int = 0
    elapsed_time_link: int = 0
    elapsed_time_download: int = 0
    errors_download: int = 0
    total_elapsed_time: int = 0

    def copy(self):
        return dataclasses.replace(self)

    def export_as_dict(self) -> dict:
        return dataclasses.asdict(self)

    def __getitem__(self, key) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any):
        setattr(self, key, value)


class OtaClientStatistics:
    def __init__(self):
        self._lock = Lock()
        self._slot = _OtaClientStatisticsStorage()

    def get_snapshot(self):
        """Return a copy of statistics storage."""
        return self._slot.copy()

    def get_processed_num(self) -> int:
        return self._slot.regular_files_processed

    def set(self, attr: str, value):
        """Set a single attr in the slot."""
        with self._lock:
            setattr(self._slot, attr, value)

    def clear(self):
        """Clear the storage slot and reset to empty."""
        self._slot = _OtaClientStatisticsStorage()

    @contextmanager
    def acquire_staging_storage(self):
        """Acquire a staging storage for updating the slot atomically and thread-safely."""
        try:
            self._lock.acquire()
            staging_slot: _OtaClientStatisticsStorage = self._slot.copy()
            yield staging_slot
        finally:
            self._slot = staging_slot
            self._lock.release()
