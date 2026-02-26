"""
NetTap Daemon — Entry point

Runs the storage manager and SMART monitor on a periodic schedule.
"""

import os
import time
import logging

from storage.manager import StorageManager, RetentionConfig
from smart.monitor import SmartMonitor

logging.basicConfig(
    level=logging.INFO,
    format="[NetTap] %(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nettap")

STORAGE_CHECK_INTERVAL = 300   # 5 minutes
SMART_CHECK_INTERVAL = 3600    # 1 hour


def main():
    config = RetentionConfig(
        hot_days=int(os.environ.get("RETENTION_HOT", 90)),
        warm_days=int(os.environ.get("RETENTION_WARM", 180)),
        cold_days=int(os.environ.get("RETENTION_COLD", 30)),
        disk_threshold=int(os.environ.get("DISK_THRESHOLD_PERCENT", 80)) / 100,
    )
    opensearch_url = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")

    storage = StorageManager(config, opensearch_url)
    smart = SmartMonitor()

    logger.info("NetTap daemon started")
    last_smart_check = 0

    while True:
        storage.run_cycle()

        now = time.monotonic()
        if now - last_smart_check >= SMART_CHECK_INTERVAL:
            smart.check_health()
            last_smart_check = now

        time.sleep(STORAGE_CHECK_INTERVAL)


if __name__ == "__main__":
    main()
