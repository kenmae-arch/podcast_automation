#!/usr/bin/env python3
"""常設コーナー「栄光の軌跡」で過去に扱った題材を一覧する。

台本を書く前にこれを実行し、**同じ試合・同じタイトルを二度扱わない**ことを確認する。
(2026-08-25: 名勝負編⑦⑧が①②と同じ試合を繰り返していたため導入)

  python list_retrospectives.py          # 一覧
  python list_retrospectives.py 2016     # 「2016」を含む回だけ絞り込み
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PUBLISHED_DIR = BASE / "scripts" / "published"
EPISODES_JSON = BASE / "docs" / "episodes.json"

# 【栄光の軌跡・名勝負編⑧】2016年... のような見出しから題材を抜き出す
CORNER = re.compile(r"【栄光の軌跡[・]?([^】]*)】([^(（]*)")


def live_audio_files():
    """フィードに現存するエピソードの音声ファイル名(差し替え済みの旧回を除くため)。"""
    if not EPISODES_JSON.exists():
        return None
    try:
        return {e["audio_file"] for e in json.loads(EPISODES_JSON.read_text(encoding="utf-8"))}
    except (ValueError, KeyError, TypeError):
        return None


def main():
    needle = sys.argv[1] if len(sys.argv) > 1 else ""
    live = live_audio_files()
    rows = []
    for p in sorted(PUBLISHED_DIR.glob("*.json")):
        if live is not None and f"{p.stem}.mp3" not in live:
            continue  # 差し替えで消した回は数えない
        title = json.loads(p.read_text(encoding="utf-8")).get("title", "")
        m = CORNER.search(title)
        if not m:
            continue
        ep = re.match(r"#(\d+)", title)
        rows.append((int(ep.group(1)) if ep else 0, m.group(1).strip(), m.group(2).strip()))

    rows.sort()
    shown = [r for r in rows if needle in r[1] + r[2]]
    print(f"栄光の軌跡: 配信中 {len(rows)}回" + (f" / 「{needle}」に一致 {len(shown)}回" if needle else ""))
    seen = {}
    for ep, chapter, topic in shown:
        dup = "  <-- 重複" if topic in seen else ""
        print(f"  #{ep:<4} [{chapter}] {topic}{dup}")
        seen.setdefault(topic, ep)

    dups = [(t, e) for t, e in seen.items() if sum(1 for r in rows if r[2] == t) > 1]
    if dups:
        print("\n同じ題材が複数回:")
        for t, _ in dups:
            eps = [f"#{r[0]}" for r in rows if r[2] == t]
            print(f"  {t} -> {' , '.join(eps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
