import time
import asyncio
from typing import Optional

from otaclient.app.ota_client_call import OtaClientCall

from . import _logutil

logger = _logutil.get_logger(__name__)


def call_status(
    ecu_id: str,
    ecu_ip: str,
    ecu_port: int,
    *,
    interval: float = 1,
    count: Optional[float] = None,
):
    logger.debug(f"request status API on ecu(@{ecu_id}) at {ecu_ip}:{ecu_port}")
    if count is None:
        count = float("inf")

    _count = 0
    while _count < count:
        logger.debug(f"status request#{_count}")
        try:
            if response := asyncio.run(
                OtaClientCall.status_call(
                    ecu_id,
                    ecu_ip,
                    ecu_port,
                )
            ):
                logger.debug(f"{response.data=}")
        except Exception as e:
            logger.debug(f"API request failed: {e!r}")
            continue
        time.sleep(interval)