"""ポッドキャスト自動生成のメインスクリプト。

- manualモード(既定): scripts/pending.json の台本を音声化してRSS更新。
  台本はClaude Code等が事前に作成する(LLM API不要・無料)。
- gemini/groqモード: トピック取得 → LLMで台本生成 → 音声化 → RSS更新。
"""
import json
import logging
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import episode_art
from audio_generator import create_audio_generator
from rss_manager import RSSManager
from script_generator import create_script_generator
from topic_fetcher import RSSTopicFetcher

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _used_episode_stems() -> set[str]:
    """過去に一度でも使った音声ファイル名(拡張子なし)を集める。

    ディスク上の音声だけを見ると、差し替えで旧音声を削除した際に同じ名前が
    再利用され、配信側のキャッシュに古い音声が残ったままになる。
    アーカイブ済み台本とRSSの記録も併せて見て、名前を使い回さないようにする。
    """
    stems = {p.stem for p in config.AUDIO_DIR.glob("*.mp3")}
    if config.PUBLISHED_SCRIPTS_DIR.exists():
        stems |= {p.stem for p in config.PUBLISHED_SCRIPTS_DIR.glob("*.json")}
    episodes_json = config.DOCS_DIR / "episodes.json"
    if episodes_json.exists():
        try:
            for ep in json.loads(episodes_json.read_text(encoding="utf-8")):
                if ep.get("audio_file"):
                    stems.add(Path(ep["audio_file"]).stem)
        except (ValueError, TypeError):
            logger.warning("episodes.json を読めませんでした(名前の重複チェックは音声ファイルのみ)")
    return stems


def _unique_episode_path(jst_now: datetime) -> "config.Path":
    """JST日付ベースで衝突しない音声ファイルパスを返す。

    GitHub Actionsランナーは時刻がUTCのため、JST基準で日付を決める。
    同一JST日に複数回生成された場合は連番を付けて上書きを防ぐ。
    過去に使った名前は(ファイルを消していても)再利用しない。
    """
    jst_today = jst_now.strftime("%Y-%m-%d")
    used = _used_episode_stems()
    stem = f"episode_{jst_today}"
    n = 2
    while stem in used:
        stem = f"episode_{jst_today}_{n}"
        n += 1
    return config.AUDIO_DIR / f"{stem}.mp3"


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
        jst_now = datetime.now(JST)
        audio_path = _unique_episode_path(jst_now)
        create_audio_generator().generate(episode.script, audio_path)

        # 3.5 エピソード別ジャケット生成(失敗しても配信は継続)
        image_path = config.DOCS_DIR / "images" / f"{audio_path.stem}.jpg"
        image_path = episode_art.generate_card(
            episode.title, jst_now.strftime("%Y.%m.%d"), image_path
        )

        # 4. RSSフィード更新
        logger.info("=== 4/4 RSSフィード更新 ===")
        RSSManager().add_episode(
            episode.title, episode.description, audio_path, image_path
        )

        # manualモード: 使用済み台本をアーカイブして二重配信を防ぐ
        if is_manual and config.PENDING_SCRIPT_PATH.exists():
            config.PUBLISHED_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            # 音声ファイルと同じ名前でアーカイブ(1日複数回でも衝突しない)
            archived = config.PUBLISHED_SCRIPTS_DIR / f"{audio_path.stem}.json"
            shutil.move(config.PENDING_SCRIPT_PATH, archived)
            logger.info("台本をアーカイブしました: %s", archived)

        logger.info("すべての処理が完了しました")
        return 0
    except Exception:
        logger.exception("処理中にエラーが発生しました")
        return 1


if __name__ == "__main__":
    sys.exit(main())
