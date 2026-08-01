# 鹿島アントラーズ デイリー — AIポッドキャスト自動化システム

鹿島アントラーズに関する最新ニュースを毎日調査し、日本語の音声で届けるポッドキャスト「鹿島アントラーズ デイリー」の制作・配信システムです。

試合、選手、移籍、クラブの発表など直近の重要トピックを中心に、ニュースが少ない日はクラブの歴史を振り返る「栄光の軌跡」などの常設企画を交えて構成します。台本作成(AIエージェント) → 音声生成(Fish Audio) → RSS配信(GitHub Pages)までを一貫して行います。

## 運用フロー(manualモード・既定)

1. AIエージェントに「今日の鹿島アントラーズのエピソードを作って」と依頼
2. AIエージェントが鹿島アントラーズの最新情報を調べて台本を書き、`scripts/pending.json` に保存して `python main.py` を実行
3. `main.py` が Fish Audio で音声化し、`docs/feed.xml` を更新、台本を `scripts/published/` にアーカイブ
4. GitHubにpushすればGitHub Pages経由でSpotify等に配信される

台本のJSON形式: `{"title": "...", "description": "...", "script": "台本全文"}`

LLM APIで全自動生成したい場合は `.env` で `LLM_PROVIDER=gemini`(または `groq`)に切り替え可能です。

## 構成

```
main.py               # メイン処理(4ステップを統合)
topic_fetcher.py      # ニュースRSSからトピック取得
script_generator.py   # LLMで台本+タイトル+概要を生成(Gemini/Groq切替可)
audio_generator.py    # Fish Audio API(s2.1-pro-free)で音声化+チャンク結合
rss_manager.py        # feedgenでポッドキャストRSS(docs/feed.xml)を生成
config.py             # 設定の一元管理
utils.py              # Exponential Backoffリトライ
docs/                 # GitHub Pages公開ディレクトリ(音声+feed.xml)
.github/workflows/daily_podcast.yml  # pending.jsonのpushまたは手動操作で実行
```

各モジュールは抽象クラス(`TopicFetcher` / `ScriptGenerator` / `AudioGenerator`)ベースの疎結合設計で、別のLLMやTTSへの差し替えが容易です。

## セットアップ

### 1. ローカルで試す

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg   # pydubの音声結合に必要(macOS)
cp .env.example .env  # APIキーを記入
python main.py
```

APIキーの取得先:
- **Fish Audio**: https://fish.audio (モデルは `s2.1-pro-free` を使用 — 完全無料・フェアユース)
- **Gemini/Groq** (LLM APIモードを使う場合のみ): https://aistudio.google.com/apikey / https://console.groq.com

### 2. GitHubで運用する

1. このディレクトリをGitHubリポジトリとしてpush
2. リポジトリの **Settings → Secrets and variables → Actions** で Secret `FISH_AUDIO_API_KEY` を登録
3. **Settings → Pages** で Source を `main` ブランチの `/docs` フォルダに設定

以後、`scripts/pending.json`(台本)をpushするたびにGitHub Actionsが音声化・配信します。ローカルで `python main.py` まで実行して生成物(`docs/`)をpushする運用でもOKです(その場合Actionsは不要)。

### 3. Spotifyに登録する

1. https://podcasters.spotify.com にログイン
2. RSSフィードURL `https://<username>.github.io/<repo>/feed.xml` を登録

## カスタマイズ

`.env`(ローカル)または Actions の Variables で変更できます:

| 変数 | 説明 |
|---|---|
| `NEWS_FEED_URLS` | 鹿島アントラーズ関連情報の収集に使うニュースソースのRSS URL(カンマ区切り) |
| `MAX_TOPICS` | 1エピソードで扱うトピック数(既定: 5) |
| `FISH_AUDIO_REFERENCE_ID` | Fish Audioボイスライブラリの音声ID |
| `PODCAST_TITLE` ほか | 番組名・説明・作者などのRSSメタデータ |
