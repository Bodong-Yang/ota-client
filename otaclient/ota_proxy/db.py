import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, List, Optional, Type, TypeVar, Callable

from .config import config as cfg
from ._orm import ColumnDescriptor, ORMBase

import logging

logger = logging.getLogger(__name__)
logger.setLevel(cfg.LOG_LEVEL)


@dataclass
class CacheMeta(ORMBase):
    url: ColumnDescriptor[str] = ColumnDescriptor(
        str, "TEXT UNIQUE NOT NULL PRIMARY KEY"
    )
    bucket: ColumnDescriptor[int] = ColumnDescriptor(
        int, "INTEGER NOT NULL", type_guard=True
    )
    last_access: ColumnDescriptor[int] = ColumnDescriptor(
        int, "INTEGER NOT NULL", type_guard=True
    )
    hash: ColumnDescriptor[str] = ColumnDescriptor(str, "TEXT NOT NULL")
    size: ColumnDescriptor[int] = ColumnDescriptor(
        int, "INTEGER NOT NULL", type_guard=True
    )
    content_type: ColumnDescriptor[str] = ColumnDescriptor(str, "TEXT")
    content_encoding: ColumnDescriptor[str] = ColumnDescriptor(str, "TEXT")


class OTACacheDB:
    TABLE_NAME: str = cfg.TABLE_NAME
    ROW_TYPE = CacheMeta
    OTA_CACHE_IDX: List[str] = [
        cfg.BUCKET_LAST_ACCESS_IDX,
    ]

    def __init__(self, db_file: str, init=False):
        logger.debug("init database...")
        self._db_file = db_file
        self._connect_db(init)

    def close(self):
        self._con.close()

    def _connect_db(self, init: bool):
        """Connects to database(and initialize database if needed).

        If database doesn't have required table, or init==True,
        we will initialize the table here.

        Args:
            init: whether to init database table or not

        Raise:
            Raises sqlite3.Error if database init/configuration failed.
        """
        if init:
            Path(self._db_file).unlink(missing_ok=True)

        self._con = sqlite3.connect(
            self._db_file,
            check_same_thread=True,  # one thread per connection in the threadpool
            # isolation_level=None,  # enable autocommit mode
        )
        self._con.row_factory = sqlite3.Row

        # check if the table exists/check whether the db file is valid
        try:
            with self._con as con:
                cur = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (self.TABLE_NAME,),
                )

                if cur.fetchone() is None:
                    logger.warning(f"{self.TABLE_NAME} not found, init db...")
                    # create ota_cache table
                    con.execute(
                        self.ROW_TYPE.get_create_table_stmt(self.TABLE_NAME),
                        (),
                    )

                    # create indices
                    for idx in self.OTA_CACHE_IDX:
                        con.execute(idx, ())

                ### db performance tunning
                # enable WAL mode
                con.execute("PRAGMA journal_mode = WAL;")
                # set synchronous mode
                con.execute("PRAGMA synchronous = normal;")
                # set temp_store to memory
                con.execute("PRAGMA temp_store = memory;")
                # enable mmap (size in bytes)
                mmap_size = 16 * 1024 * 1024  # 16MiB
                con.execute(f"PRAGMA mmap_size = {mmap_size};")
        except sqlite3.Error as e:
            logger.debug(f"init db failed: {e!r}")
            raise e

    def remove_entries_by_field(self, fd: ColumnDescriptor, *_inputs: Any) -> int:
        if not _inputs:
            return 0
        if self.ROW_TYPE.contains_field(fd) and fd.check_type(_inputs[0]):
            with self._con as con:
                _regulated_input = [(i,) for i in _inputs]
                cur = con.executemany(
                    f"DELETE FROM {self.TABLE_NAME} WHERE {fd.field_name}=?",
                    _regulated_input,
                )
                return cur.rowcount
        return 0

    def lookup_entry_by_field(
        self, fd: ColumnDescriptor, _input: Any
    ) -> Optional[CacheMeta]:
        if not self.ROW_TYPE.contains_field(fd) or fd.check_type(_input):
            return
        with self._con as con:
            cur = con.execute(
                f"SELECT * FROM {self.TABLE_NAME} WHERE {fd.field_name}=?",
                (_input,),
            )
            if row := cur.fetchone():
                # warm up the cache(update last_access timestamp) here
                res = CacheMeta.row_to_meta(row)
                cur = con.execute(
                    (
                        f"UPDATE {self.TABLE_NAME} SET {self.ROW_TYPE.last_access.field_name}=? "  # type: ignore
                        f"WHERE {self.ROW_TYPE.url.field_name}=?"  # type: ignore
                    ),
                    (int(datetime.now().timestamp()), res.url),
                )
                return res

    def insert_entry(self, *cache_meta: CacheMeta) -> int:
        if not cache_meta:
            return 0
        with self._con as con:
            cur = con.executemany(
                f"INSERT OR REPLACE INTO {self.TABLE_NAME} VALUES ({self.ROW_TYPE.get_shape()})",
                [m.to_tuple() for m in cache_meta],
            )
            return cur.rowcount

    def lookup_all(self) -> List[CacheMeta]:
        with self._con as con:
            cur = con.execute(f"SELECT * FROM {self.TABLE_NAME}", ())
            return [CacheMeta.row_to_meta(row) for row in cur.fetchall()]

    def rotate_cache(self, bucket: int, num: int) -> Optional[List[str]]:
        """Rotate cache entries in LRU flavour.

        Args:
            bucket: which bucket for space reserving
            num: num of entries needed to be deleted in this bucket

        Return:
            A list of hashes that needed to be deleted for space reserving,
                or None if no enough entries for space reserving.
        """
        bucket_fn, last_access_fn = (
            self.ROW_TYPE.bucket.field_name,  # type: ignore
            self.ROW_TYPE.last_access.field_name,  # type: ignore
        )
        # first, check whether we have required number of entries in the bucket
        with self._con as con:
            cur = con.execute(
                (
                    f"SELECT COUNT(*) FROM {self.TABLE_NAME} WHERE {bucket_fn}=? "
                    f"ORDER BY {last_access_fn} LIMIT ?"  # type: ignore
                ),
                (bucket, num),
            )
            if not (_raw_res := cur.fetchone()):
                return

            # NOTE: if we can upgrade to sqlite3 >= 3.35,
            # use RETURNING clause instead of using 2 queries as below

            # if we have enough entries for space reserving
            if _raw_res[0] >= num:
                # first select those entries
                cur = con.execute(
                    (
                        f"SELECT * FROM {self.TABLE_NAME} "
                        f"WHERE {bucket_fn}=? "
                        f"ORDER BY {last_access_fn} "
                        "LIMIT ?"
                    ),
                    (bucket, num),
                )
                _rows = cur.fetchall()

                # and then delete those entries with same conditions
                con.execute(
                    (
                        f"DELETE FROM {self.TABLE_NAME} "
                        f"WHERE {bucket_fn}=? "
                        f"ORDER BY {last_access_fn} "
                        "LIMIT ?"
                    ),
                    (bucket, num),
                )
                return [row["hash"] for row in _rows]


def _proxy_wrapper(attr_n: str) -> Callable:
    """A wrapper helper that proxys method to threadpool.

    Requires the object of the wrapped method to have
    thread_local db connection(self._thread_local.db)
    and threadpool(self._executor) defined.

    Returns:
        A wrapped callable.
    """

    def _wrapped(self, *args, **kwargs):
        # get the handler from underlaying db connector
        def _inner():
            _db = self._thread_local.db
            f = partial(getattr(_db, attr_n), *args, **kwargs)
            return f()

        # inner is dispatched to the db connection threadpool
        fut: Future = self._executor.submit(_inner)
        return fut.result()

    return _wrapped


_GENERIC_CLS = TypeVar("_GENERIC_CLS")
_WRAPPED_CLS = TypeVar("_WRAPPED_CLS")


def _proxy_cls_factory(
    cls: Type[_GENERIC_CLS],
    *,
    wrapper: Callable[[str], Callable],
    target: Type[_GENERIC_CLS],
) -> Type[_WRAPPED_CLS]:
    """A proxy class factory that wraps all public methods with <wrapper>.

    Args:
        cls: input class
        wrapper: proxy wrapper
        target: which class to be proxied

    Returns:
        A new proxy class for <target>.
    """
    for attr_n, attr in target.__dict__.items():
        if not attr_n.startswith("_") and callable(attr):
            # override method
            setattr(cls, attr_n, wrapper(attr_n))

    return cls


@partial(_proxy_cls_factory, wrapper=_proxy_wrapper, target=OTACacheDB)
class DBProxy:
    """A proxy class for OTACacheDB that dispatches all requests into a threadpool."""

    def __init__(self, db_f: str):
        """Init the database connecting thread pool."""
        self._thread_local = threading.local()

        def _initializer():
            """Init a db connection for each thread worker"""
            self._thread_local.db = OTACacheDB(db_f, init=False)

        self._executor = ThreadPoolExecutor(max_workers=6, initializer=_initializer)

    def close(self):
        self._executor.shutdown(wait=True)


# cleanup namespace
del _make_cachemeta_cls, _proxy_cls_factory, _proxy_wrapper
