# 3番組デイリーアナリティクス

3つのポッドキャスト(鹿島アントラーズ デイリー / 日本語ラップ アルバム全曲解説 / アルバム全曲解説)と
albumatlas.jp のアクセス数を毎朝1枚のダッシュボードにまとめる仕組み。

## 構成

| ファイル | 役割 |
|---|---|
| `data/store.json` | 全データの正規化ストア(日次時系列)。毎朝のジョブが追記してコミットする |
| `ga4_fetch.py` | GA4 Data API から albumatlas.jp の日次データを取得して store.json にマージ |
| `report.py` | store.json からダッシュボード HTML を生成(`python analytics/report.py -o dashboard.html`) |
| `requirements.txt` | 追加依存(google-auth) |

## データの流れ

```
GA4 Data API ──ga4_fetch.py──▶
Google Drive「podcast-analytics-inbox」の CSV ──毎朝のClaudeが取込──▶  data/store.json ──report.py──▶ ダッシュボード(Artifact)
(Spotify / Apple / Amazon の公式エクスポート)
```

- **GA4**: 環境変数 `GA4_PROPERTY_ID` と `GA4_SERVICE_ACCOUNT_JSON`(サービスアカウント鍵のJSON文字列そのまま)
  または `GA4_SERVICE_ACCOUNT_FILE`(鍵ファイルパス)が必要。
- **Spotify / Apple / Amazon**: 公式アナリティクスAPIが存在しないため、各ダッシュボードから
  エクスポートした CSV を Google Drive のフォルダ **`podcast-analytics-inbox`** に入れておくと、
  毎朝のジョブが読み取って store.json に正規化して取り込む。取り込んだファイル名は
  `meta.processedFiles` に記録し、二重計上しない。
  - どの番組の CSV か分かるよう、ファイル名の先頭に `antlers_` / `jrap_` / `music_` を付けるのが確実
    (無い場合は CSV 内の番組名から判断する)。

## store.json スキーマ

```jsonc
{
  "meta": {
    "lastUpdated": "2026-09-01T07:05:00+09:00",
    "connections": {            // ダッシュボードの連携ステータス表示に使う
      "ga4":     {"state": "pending"},   // pending | ok | error(+ "note")
      "spotify": {"state": "csv", "lastData": "2026-08-30"},
      "apple":   {"state": "pending"},
      "amazon":  {"state": "pending"}
    },
    "processedFiles": ["antlers_spotify_2026-08-31.csv"]
  },
  "shows": {                    // 表示順もこの順
    "antlers": {"title": "鹿島アントラーズ デイリー"},
    "jrap":    {"title": "日本語ラップ アルバム全曲解説"},
    "music":   {"title": "アルバム全曲解説"}
  },
  "series": {
    // series.<show>.<platform>.<metric> = {"YYYY-MM-DD": number}
    // platform: spotify | apple | amazon
    // metric:   plays(その日の再生/視聴数) | followers(その日時点の累計) | listeners
    "antlers": {
      "spotify": {"plays": {"2026-08-30": 12}, "followers": {"2026-08-30": 34}}
    }
  },
  "episodes": {
    // 任意: エピソード別の累計値スナップショット(取れた日に上書き)
    "antlers": {"エピソードタイトル": {"spotify_plays": 120, "date": "2026-08-30"}}
  },
  "web": {
    "ga4": {
      "users":     {"2026-08-31": 42},
      "newUsers":  {"2026-08-31": 30},
      "sessions":  {"2026-08-31": 55},
      "pageviews": {"2026-08-31": 130},
      "topPages":  {"2026-08-31": [["/", 60], ["/lux", 25]]},
      "channels":  {"2026-08-31": [["Organic Search", 20], ["Direct", 15]]}
    }
  }
}
```

ルール:

- **数値は必ず実データ**。取れなかった日は書かない(0で埋めない)。憶測で補完しない。
- followers 系は「その日時点の累計」、plays 系は「その日1日の数」。CSVの意味を確認してから入れる。
- 日付キーはすべて **JST** の日付。

## 毎朝のジョブ(ルーティン)がやること

1. このリポジトリの `claude/product-analytics-dashboard-vyhgh4` ブランチを最新化
2. `python analytics/ga4_fetch.py`(環境変数があれば)
3. Drive の `podcast-analytics-inbox` に新しい CSV があれば store.json に取込
4. `python analytics/report.py -o dashboard.html` → 既存 Artifact を同一URLで更新
5. store.json の変更をコミットして push
