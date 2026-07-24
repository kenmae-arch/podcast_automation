"""ニュースRSSからその日のトピックを取得するモジュール。"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import feedparser
import requests

import config

logger = logging.getLogger(__name__)


@dataclass
class Topic:
    title: str
    summary: str
    link: str


class TopicFetcher(ABC):
    """トピック取得のインターフェース。別のニュースソースに差し替え可能。"""

    @abstractmethod
    def fetch(self, max_topics: int) -> list[Topic]: ...


class RSSTopicFetcher(TopicFetcher):
    """複数のRSSフィードからトピックを取得する。"""

    def __init__(self, feed_urls: list[str] | None = None):
        self.feed_urls = feed_urls or config.NEWS_FEED_URLS

    def fetch(self, max_topics: int = config.MAX_TOPICS) -> list[Topic]:
        topics: list[Topic] = []
        seen_titles: set[str] = set()
        for url in self.feed_urls:
            try:
                # feedparserの内蔵urllibはSSL証明書の扱いが環境依存のため、
                # certifi同梱のrequestsで取得してから解析する
                response = requests.get(
                    url, timeout=30, headers={"User-Agent": "podcast-automation/1.0"}
                )
                response.raise_for_status()
                feed = feedparser.parse(response.content)
                for entry in feed.entries:
                    title = entry.get("title", "").strip()
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)
                    topics.append(
                        Topic(
                            title=title,
                            summary=entry.get("summary", "").strip(),
                            link=entry.get("link", ""),
                        )
                    )
            except Exception as e:
                logger.warning("フィード取得失敗 (%s): %s", url, e)
        if not topics:
            raise RuntimeError("トピックを1件も取得できませんでした")
        logger.info("トピックを%d件取得(使用: %d件)", len(topics), min(len(topics), max_topics))
        return topics[:max_topics]
