"""ポッドキャストRSSフィード(feed.xml)を生成・更新するモジュール。

エピソードのメタデータは docs/episodes.json に永続化し、
毎回そこから全エピソードを含むフィードを再生成する。
"""
import json
import logging
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from feedgen.feed import FeedGenerator

import config

logger = logging.getLogger(__name__)

EPISODES_JSON = config.DOCS_DIR / "episodes.json"


class RSSManager:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or config.SITE_BASE_URL).rstrip("/")

    def add_episode(self, title: str, description: str, audio_path: Path) -> None:
        """エピソードを登録してフィードを再生成する。"""
        episodes = self._load_episodes()
        episodes.append(
            {
                "title": title,
                "description": description,
                "audio_file": audio_path.name,
                "size_bytes": audio_path.stat().st_size,
                "published": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save_episodes(episodes)
        self._generate_feed(episodes)

    def _generate_feed(self, episodes: list[dict]) -> None:
        fg = FeedGenerator()
        fg.load_extension("podcast")
        fg.title(config.PODCAST_TITLE)
        fg.description(config.PODCAST_DESCRIPTION)
        fg.link(href=self.base_url, rel="alternate")
        fg.link(href=f"{self.base_url}/feed.xml", rel="self")
        fg.language(config.PODCAST_LANGUAGE)
        fg.author({"name": config.PODCAST_AUTHOR, "email": config.PODCAST_EMAIL})
        cover_url = f"{self.base_url}/cover.jpg"
        fg.image(url=cover_url, title=config.PODCAST_TITLE, link=self.base_url)
        fg.podcast.itunes_image(cover_url)
        fg.podcast.itunes_author(config.PODCAST_AUTHOR)
        fg.podcast.itunes_category(config.PODCAST_CATEGORY)
        fg.podcast.itunes_explicit("no")
        fg.podcast.itunes_owner(config.PODCAST_AUTHOR, config.PODCAST_EMAIL)

        # feedgenは追加した逆順で出力するため、古い順に追加する
        for ep in episodes:
            fe = fg.add_entry()
            audio_url = f"{self.base_url}/audio/{ep['audio_file']}"
            fe.id(audio_url)
            fe.title(ep["title"])
            fe.description(ep["description"])
            fe.enclosure(audio_url, str(ep["size_bytes"]), "audio/mpeg")
            fe.published(datetime.fromisoformat(ep["published"]))

        config.FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
        fg.rss_file(str(config.FEED_PATH), pretty=True)
        logger.info("RSSフィードを更新しました: %s (%d エピソード)", config.FEED_PATH, len(episodes))

    @staticmethod
    def _load_episodes() -> list[dict]:
        if EPISODES_JSON.exists():
            return json.loads(EPISODES_JSON.read_text(encoding="utf-8"))
        return []

    @staticmethod
    def _save_episodes(episodes: list[dict]) -> None:
        EPISODES_JSON.parent.mkdir(parents=True, exist_ok=True)
        EPISODES_JSON.write_text(
            json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
