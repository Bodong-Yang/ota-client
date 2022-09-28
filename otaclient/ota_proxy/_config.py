from logging import INFO
from dataclasses import dataclass


@dataclass
class Config:
    BASE_DIR: str = "/ota-cache"
    CHUNK_SIZE: int = 4 * 1024 * 1024  # 4MB
    DISK_USE_LIMIT_SOFT_P = 70  # in p%
    DISK_USE_LIMIT_HARD_P = 80  # in p%
    DISK_USE_PULL_INTERVAL = 2  # in seconds
    # value is the largest numbers of files that
    # might need to be deleted for the bucket to hold a new entry
    # if we have to reserve space for this file.
    BUCKET_FILE_SIZE_DICT = {
        0: 0,  # not filtered
        2 * 1024: 1,  # 2KiB
        3 * 1024: 1,
        4 * 1024: 1,
        5 * 1024: 1,
        8 * 1024: 2,
        16 * 1024: 2,  # 16KiB
        32 * 1024: 8,
        256 * 1024: 16,  # 256KiB
        4 * (1024**2): 2,  # 4MiB
        8 * (1024**2): 32,  # 8MiB
        256 * (1024**2): 2,
        512 * (1024**2): 0,  # not filtered
    }
    DB_FILE = f"{BASE_DIR}/cache_db"

    LOG_LEVEL = INFO

    # DB configuration/setup
    # ota-cache table
    # NOTE: use table name to keep track of table scheme version
    TABLE_DEFINITION_VERSION = "v2"
    TABLE_NAME: str = f"ota_cache_{TABLE_DEFINITION_VERSION}"

    BUCKET_LAST_ACCESS_IDX: str = (
        f"CREATE INDEX bucket_last_access_idx ON {TABLE_NAME}(bucket, last_access)"
    )


config = Config()
