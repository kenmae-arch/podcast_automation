#!/usr/bin/env python3
"""台本の「読み方が不安な語」を音声生成の前に洗い出す。

`main.py` から呼ばれ、危険度の高い語が未登録なら音声生成を中止する
(ユーザー方針: 誤読が実際に起きたクラスだけは必ず人の確認を通す)。

  python check_readings.py                     # scripts/pending.json をチェック
  python check_readings.py path/to/script.json
  python check_readings.py --approve 藤本 辻岡  # 「そのままで正しく読める」と確認済みにする
  python check_readings.py --seed              # 配信済み台本の漢字語を確認済みに取り込む

危険度:
  block  数字+分/試合、U-16型の英数字、辞書にない人名(直後が「選手」「監督」など)
         → 実際に誤読が報告されたクラス。未登録なら音声を作らない。
  warn   その他の英数字・数字+助数詞。生成は止めず、朝の報告で一覧にする。
  info   初出の漢字語。目視で違和感があるものだけ拾う。
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
PUBLISHED_DIR = BASE / "scripts" / "published"

# 誤読が実際に起きたクラス。ここに当たるものは未登録なら生成を止める。
RE_MINUTE = re.compile(r"[0-9]+(?:分|試合)")
RE_ALNUM_MIX = re.compile(
    r"[A-Za-z]+(?:[-‐–— ][0-9][0-9.]*|[0-9][0-9.]*)")
# 生成は止めないが報告はする
RE_ALPHA = re.compile(r"[A-Za-z]{2,}")
RE_COUNTER = re.compile(
    r"[0-9]+(?:点|人|位|回|本|度目|度|歳|番|節|冠|部|連勝|連敗|連覇|得点|失点|万人|億円|年ぶり)")
RE_KANJI = re.compile(r"[一-鿿々]{2,}")
# 「◯◯選手」「◯◯監督」の◯◯は人名とみなす(敬称は漢字なので語ごと拾って外す)
RE_NAME = re.compile(r"([一-鿿々]{2,6}?)(?:選手|監督|コーチ|主将|会長|社長|氏|CEO|CTO|CFO|COO)")

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


def analyze(text, mapping=None, safelist=None):
    """台本テキストを危険度別に分類して返す。

    戻り値: {"block": [(語, 種別)], "warn": [...], "info": [語, ...]}
    """
    mapping = load_json(DICT_PATH, {}) if mapping is None else mapping
    safelist = set(load_json(SAFELIST_PATH, [])) if safelist is None else safelist
    masked = mask_dictionary_hits(text, mapping)

    seen = {}

    def add(level, label, token, pos):
        if token in seen or token in safelist or token in COMMON:
            return
        seen[token] = (level, label, pos)

    for m in RE_MINUTE.finditer(masked):
        add("block", "数字+分/試合", m.group(), m.start())
    for m in RE_ALNUM_MIX.finditer(masked):
        add("block", "英数字混在", m.group(), m.start())
    for m in RE_NAME.finditer(masked):
        add("block", "人名らしい語", m.group(1), m.start())
    for m in RE_ALPHA.finditer(masked):
        add("warn", "英字", m.group(), m.start())
    for m in RE_COUNTER.finditer(masked):
        add("warn", "数字+助数詞", m.group(), m.start())
    for m in RE_KANJI.finditer(masked):
        add("info", "漢字語", m.group(), m.start())

    out = {"block": [], "warn": [], "info": []}
    for token, (level, label, pos) in sorted(seen.items(), key=lambda kv: kv[1][2]):
        out[level].append(token if level == "info" else (token, label))
    return out


def context_of(text, token, width=22):
    i = text.find(token)
    if i < 0:
        return ""
    s = max(0, i - width)
    e = min(len(text), i + len(token) + width)
    head = "..." if s else ""
    tail = "..." if e < len(text) else ""
    return head + text[s:e].replace("\n", " ") + tail


def script_text(data):
    return "\n".join(str(data.get(k, "")) for k in ("title", "description", "script"))


def report(text, result, stream=print):
    if result["block"]:
        stream(f"■ 要確認 {len(result['block'])}件 -- 未登録のまま音声を作らない")
        for token, label in result["block"]:
            stream(f"  [{label}] {token}")
            stream(f"      {context_of(text, token)}")
    if result["warn"]:
        stream(f"■ 参考(生成は継続) {len(result['warn'])}件")
        stream("  " + " / ".join(t for t, _ in result["warn"]))
    if result["info"]:
        stream(f"■ 初出の漢字語 {len(result['info'])}件")
        stream("  " + " / ".join(result["info"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?", default=str(PENDING_PATH))
    ap.add_argument("--approve", nargs="+", metavar="語",
                    help="そのままで正しく読めると確認できた語を確認済みリストに追加する")
    ap.add_argument("--seed", action="store_true",
                    help="配信済み台本(scripts/published)に出てきた漢字語を確認済みに取り込む。"
                         "人名・英数字・数字+助数詞は毎回確認したいので取り込まない")
    args = ap.parse_args()

    safelist = set(load_json(SAFELIST_PATH, []))
    mapping = load_json(DICT_PATH, {})

    if args.seed:
        added = set()
        for p in sorted(PUBLISHED_DIR.glob("*.json")):
            res = analyze(script_text(json.loads(p.read_text(encoding="utf-8"))),
                          mapping, safelist)
            added |= set(res["info"])
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
    text = script_text(json.loads(path.read_text(encoding="utf-8")))
    result = analyze(text, mapping, safelist)

    print(f"台本: {path}")
    print(f"辞書 {len(mapping)}語 / 確認済み {len(safelist)}語\n")
    if not any(result.values()):
        print("読みの確認が必要な語はありません。")
        return 0
    report(text, result)
    print("\n対応:")
    print("  読みを指定する  -> pronunciation_dict.json に「表記: 読み」を追加")
    print("  そのままで良い  -> python check_readings.py --approve <語> ...")
    return 1 if result["block"] else 0


if __name__ == "__main__":
    sys.exit(main())
