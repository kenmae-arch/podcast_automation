#!/usr/bin/env python3
"""台本の「読み方が不安な語」を洗い出す事前チェック。

音声生成の前にこれを実行し、フラグが立った語をユーザーに確認してから
`pronunciation_dict.json` に登録する運用にする(読み間違いの作り込み防止)。

  python check_readings.py                     # scripts/pending.json をチェック
  python check_readings.py path/to/script.json
  python check_readings.py --approve 藤本 辻岡  # 「そのままで正しく読める」と確認済みにする

判定の流れ:
  1. pronunciation_dict.json を最長一致で適用し、置換済みの部分を伏せる
  2. 残ったテキストから「読みが割れやすい形」の語を抜き出す
  3. reading_safelist.json (確認済み) と一般語リストに載っていないものを表示

フラグが1つでも残れば終了コード1を返すので、リリース前のゲートに使える。
"""
import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DICT_PATH = BASE / "pronunciation_dict.json"
SAFELIST_PATH = BASE / "reading_safelist.json"
PENDING_PATH = BASE / "scripts" / "pending.json"

# 読みが割れやすい形。ここに当たったものだけを候補にする。
PATTERNS = [
    # U-16 / J1 / ACL / PK / MVP のような英数字トークン
    ("英数字", re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-‐–—][0-9A-Za-z]+)*")),
    # 数字+助数詞。「8分(はちふん/はっぷん)」のように読みが揺れる
    ("数字+助数詞", re.compile(
        r"[0-9]+(?:分|試合|点|人|位|回|本|度目|度|歳|番|節|冠|部|連勝|連敗|得点|失点|万人|億円|年ぶり)")),
    # 漢字2文字以上。固有名詞・熟語はここで拾う
    ("漢字語", re.compile(r"[一-鿿々]{2,}")),
]

# サッカー/ニュースの台本に日常的に出る語。読み間違いの実績がないものだけ入れる。
COMMON = set("""
試合 選手 監督 前半 後半 開始 終了 得点 失点 先制 同点 逆転 勝利 敗戦 完封 黒星
開幕 今季 昨季 今日 明日 昨日 本日 今夜 今週 来週 今年 昨年 来年 現在 直後 直前
出場 先発 交代 途中 負傷 離脱 復帰 加入 移籍 契約 発表 報道 各社 公式 会見 取材
攻撃 守備 中盤 最終 決勝 準決勝 王者 優勝 制覇 首位 上位 下位 順位 勝敗 記録 連続
時間 場所 会場 本拠地 相手 対戦 対応 状況 状態 内容 結果 理由 課題 注目 期待 話題
自分 本人 全員 全体 一戦 一気 一部 今回 前回 次回 毎回 最後 最初 最新 最大 最多
放送 配信 番組 応援 声援 拍手 歓声 満員 観客 動員 増加 減少 用意 企画 設定 開催
日本 東京 大阪 名古屋 神戸 広島 福岡 京都 横浜 埼玉 千葉 新潟 仙台 札幌 川崎 町田 浦和 柏
鹿島 清水 磐田 湘南 岡山 長崎 鳥栖 甲府 山形 秋田 熊本 大分 徳島 愛媛 沖縄
選手権 世代別 代表 育成 昇格 降格 登録 所属 高校 大学 中学 小学 年代 世代 未来
分間 数分 数日 数年 半年 来月 今月 先月 昨夜 早朝 深夜 午前 午後 週末 土曜 日曜 金曜
可能性 必要 重要 大切 大事 十分 若干 若手 中心 主力 補強 戦力 布陣 采配 持ち味
言葉 発言 表情 姿勢 覚悟 意識 判断 選択 挑戦 成長 進化 変化 影響 意味 物語 瞬間
""".split())


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def mask_dictionary_hits(text, mapping):
    """辞書で読みを指定済みの部分を伏せ字にする(最長一致)。"""
    for key in sorted(mapping, key=len, reverse=True):
        if key in text:
            text = text.replace(key, " " * len(key))
    return text


# 人名らしさの判定。この語に続くならほぼ人名なので、必ず目視確認に回す。
NAME_SUFFIX = re.compile(r"(?:選手|監督|コーチ|主将|会長|社長|氏|さん|くん)")


def extract_candidates(text):
    """(語, 種別, 位置, 要確認度) の一覧を出現順で返す。"""
    found = {}
    for label, pattern in PATTERNS:
        for m in pattern.finditer(text):
            token = m.group()
            if token in found:
                continue
            # 英数字と数字+助数詞は読みが割れやすいので常に高。
            # 漢字語は「直後に選手/監督などが続く=人名らしい」ものだけ高にする。
            high = label != "漢字語" or bool(NAME_SUFFIX.match(text, m.end()))
            found[token] = (label, m.start(), high)
    return sorted(((t, l, p, h) for t, (l, p, h) in found.items()), key=lambda x: x[2])


def context_of(text, token, width=22):
    i = text.find(token)
    if i < 0:
        return ""
    s = max(0, i - width)
    e = min(len(text), i + len(token) + width)
    head = "..." if s else ""
    tail = "..." if e < len(text) else ""
    return head + text[s:e].replace("\n", " ") + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?", default=str(PENDING_PATH))
    ap.add_argument("--approve", nargs="+", metavar="語",
                    help="そのままで正しく読めると確認できた語を確認済みリストに追加する")
    ap.add_argument("--seed", action="store_true",
                    help="配信済み台本(scripts/published)に出てきた漢字語を確認済みに取り込む。"
                         "人名らしい語・英数字・数字+助数詞は毎回確認したいので取り込まない")
    args = ap.parse_args()

    safelist = set(load_json(SAFELIST_PATH, []))

    if args.seed:
        mapping = load_json(DICT_PATH, {})
        added = set()
        for p in sorted((BASE / "scripts" / "published").glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            text = "\n".join(str(data.get(k, "")) for k in ("title", "description", "script"))
            for token, label, _, high in extract_candidates(mask_dictionary_hits(text, mapping)):
                if not high and token not in COMMON:
                    added.add(token)
        safelist |= added
        SAFELIST_PATH.write_text(
            json.dumps(sorted(safelist), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"配信済み台本から {len(added)}語を確認済みに取り込みました (計{len(safelist)}語)")
        return 0

    if args.approve:
        safelist |= set(args.approve)
        SAFELIST_PATH.write_text(
            json.dumps(sorted(safelist), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"確認済みに追加: {' '.join(args.approve)} (計{len(safelist)}語)")
        return 0

    path = Path(args.script)
    if not path.exists():
        print(f"台本が見つかりません: {path}", file=sys.stderr)
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = "\n".join(str(data.get(k, "")) for k in ("title", "description", "script"))

    mapping = load_json(DICT_PATH, {})
    masked = mask_dictionary_hits(raw, mapping)

    flagged = [(t, l, h) for t, l, _, h in extract_candidates(masked)
               if t not in safelist and t not in COMMON]
    high = [(t, l) for t, l, h in flagged if h]
    low = [t for t, l, h in flagged if not h]

    print(f"台本: {path}")
    print(f"辞書 {len(mapping)}語 / 確認済み {len(safelist)}語")
    if not flagged:
        print("\n読みの確認が必要な語はありません。")
        return 0

    if high:
        print(f"\n■ 要確認 {len(high)}件 (英数字・数字+助数詞・人名らしい語)")
        for token, label in high:
            print(f"  [{label}] {token}")
            print(f"      {context_of(raw, token)}")
    if low:
        print(f"\n■ 参考 {len(low)}件 (初出の漢字語。目視で違和感があるものだけ拾う)")
        print("  " + " / ".join(low))
    print("\n対応:")
    print("  読みを指定する  -> pronunciation_dict.json に「表記: 読み」を追加")
    print("  そのままで良い  -> python check_readings.py --approve "
          + " ".join(t for t, _, _ in flagged[:5]))
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main())
