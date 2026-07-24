"""ポッドキャスト自動生成のメインスクリプト。

- manualモード(既定): scripts/pending.json の台本を音声化してRSS更新。
  台本はClaude Code等が事前に作成する(LLM API不要・無料)。
- gemini/groqモード: トピック取得 → LLMで台本生成 → 音声化 → RSS更新。
"""
import logging
import shutil
import sys
from datetime import date

import config
from audio_generator import create_audio_generator
from rss_manager import RSSManager
from script_generator import create_script_generator
from topic_fetcher import RSSTopicFetcher

logger = logging.getLogger(__name__)


def main() -> int:
    try:
        is_manual = config.LLM_PROVIDER.lower() in ("manual", "claude")

        # 1. トピック取得(manualモードでは台本が既にあるため不要)
        topics = []
        if not is_manual:
            logger.info("=== 1/4 トピック取得 ===")
            topics = RSSTopicFetcher().fetch()

        # 2. 台本の取得・生成
        logger.info("=== 2/4 台本取得 (%s) ===", config.LLM_PROVIDER)
        episode = create_script_generator().generate(topics)
        logger.info("台本: %s (%d文字)", episode.title, len(episode.script))

        # 3. 音声生成
        logger.info("=== 3/4 音声生成 (Fish Audio: %s) ===", config.FISH_AUDIO_MODEL)
        audio_path = config.AUDIO_DIR / f"episode_{date.today().isoformat()}.mp3"
        create_audio_generator().generate(episode.script, audio_path)

        # 4. RSSフィード更新
        logger.info("=== 4/4 RSSフィード更新 ===")
        RSSManager().add_episode(episode.title, episode.description, audio_path)

        # manualモード: 使用済み台本をアーカイブして二重配信を防ぐ
        if is_manual and config.PENDING_SCRIPT_PATH.exists():
            config.PUBLISHED_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            archived = config.PUBLISHED_SCRIPTS_DIR / f"{date.today().isoformat()}.json"
            shutil.move(config.PENDING_SCRIPT_PATH, archived)
            logger.info("台本をアーカイブしました: %s", archived)

        logger.info("すべての処理が完了しました")
        return 0
    except Exception:
        logger.exception("処理中にエラーが発生しました")
        return 1


if __name__ == "__main__":
    sys.exit(main())
