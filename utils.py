"""共通ユーティリティ。Exponential Backoffリトライなど。"""
import logging
import random
import time
from functools import wraps

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class RetryableError(Exception):
    """レート制限や一時的なサーバーエラーなど、リトライすべきエラー。"""


def retry_with_backoff(func):
    """Exponential Backoff + ジッターでリトライするデコレータ。

    RetryableError が送出された場合のみリトライし、
    それ以外の例外は即座に呼び出し元へ伝播する。
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        for attempt in range(config.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except RetryableError as e:
                if attempt == config.MAX_RETRIES - 1:
                    raise
                delay = config.RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "リトライ %d/%d (%.1f秒待機): %s",
                    attempt + 1,
                    config.MAX_RETRIES,
                    delay,
                    e,
                )
                time.sleep(delay)

    return wrapper
