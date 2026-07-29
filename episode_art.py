"""エピソード別ジャケット画像を生成するモジュール。

番組カバー(docs/cover.jpg)を背景に、EP番号・その日の見出し・日付を重ねる。
フォントはローカル(macOS=ヒラギノ角ゴシック)とGitHub Actions(Linux=Noto CJK)の
両方で解決できるように候補を順に探索する。
"""
import glob
import logging
import re
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# 太字(見出し・EP番号)用フォント候補(上から優先)
_HEAVY_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
]
# 中字(ワードマーク・日付)用フォント候補
_MEDIUM_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
]
# Linux(Actions)向け: /usr/share/fonts 以下のNoto CJKをglobで探す
_NOTO_GLOBS = [
    "/usr/share/fonts/**/NotoSansCJK*.ttc",
    "/usr/share/fonts/**/NotoSansCJK*.otf",
    "/usr/share/fonts/**/NotoSansJP*.otf",
    "/usr/share/fonts/**/NotoSansJP*.ttf",
]


def _resolve_font(preferred: list[str], weight_keywords: list[str]) -> str | None:
    for p in preferred:
        if Path(p).exists():
            return p
    found: list[str] = []
    for pat in _NOTO_GLOBS:
        found.extend(glob.glob(pat, recursive=True))
    for kw in weight_keywords:
        for f in found:
            if kw.lower() in Path(f).name.lower():
                return f
    return found[0] if found else None


def _clean_headline(title: str) -> tuple[str, str | None]:
    """タイトルから見出し本体とEP番号を取り出す。

    例: "#2 夏の移籍市場が活発!…(2026年7月26日)" → ("夏の移籍市場が活発!…", "2")
    """
    ep_no = None
    m = re.match(r"^#(\d+)\s*(.*)$", title.strip())
    if m:
        ep_no, title = m.group(1), m.group(2)
    # 末尾の日付括弧を除去(全角/半角)
    title = re.sub(r"[（(][^）)]*[）)]\s*$", "", title).strip()
    return title, ep_no


def generate_card(
    title: str,
    date_str: str,
    out_path: Path,
    ep_no: str | None = None,
    cover_path: Path | None = None,
) -> Path | None:
    """エピソードジャケットを生成して out_path に保存する。

    フォントが見つからない等で失敗した場合は None を返す(音声配信は継続させる)。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow未導入のためジャケット生成をスキップします")
        return None

    cover_path = cover_path or (config.DOCS_DIR / "cover.jpg")
    if not cover_path.exists():
        logger.warning("カバー画像が無いためジャケット生成をスキップ: %s", cover_path)
        return None

    heavy = _resolve_font(_HEAVY_CANDIDATES, ["Black", "Bold", "Heavy"])
    medium = _resolve_font(_MEDIUM_CANDIDATES, ["Medium", "Regular", "Bold"])
    if not heavy or not medium:
        logger.warning("日本語フォントが見つからずジャケット生成をスキップ")
        return None

    headline, parsed_ep = _clean_headline(title)
    ep_no = ep_no or parsed_ep

    S = 2048
    base = Image.open(cover_path).convert("RGB").resize((S, S))

    # 全体を暗くしつつ下部ほど濃く(テキスト可読性の確保)
    overlay = Image.new("RGB", (S, S), (0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    for y in range(S):
        md.line([(0, y), (S, y)], fill=int(70 + (y / S) ** 1.6 * 175))
    base = Image.composite(overlay, base, mask)

    # 下半分にアントラーズレッドのグラデを軽く重ねる
    red = Image.new("RGB", (S, S), (0x8F, 0x14, 0x22))
    rmask = Image.new("L", (S, S), 0)
    rd = ImageDraw.Draw(rmask)
    for y in range(S):
        a = 0 if y < S * 0.5 else int((y - S * 0.5) / (S * 0.5) * 150)
        rd.line([(0, y), (S, y)], fill=a)
    base = Image.composite(red, base, rmask)

    d = ImageDraw.Draw(base)
    f_mark = ImageFont.truetype(medium, 62)
    f_ep = ImageFont.truetype(heavy, 155)
    f_date = ImageFont.truetype(medium, 64)
    f_head = ImageFont.truetype(heavy, 130)

    def st(x, y, text, font, fill="#FFFFFF", sh=4):
        d.text((x + sh, y + sh), text, font=font, fill=(0, 0, 0))
        d.text((x, y), text, font=font, fill=fill)

    # 上部: 赤アクセントバー + ワードマーク + EP番号
    d.rectangle([120, 150, 190, 161], fill="#E8384E")
    st(120, 182, config.PODCAST_TITLE, f_mark)
    if ep_no:
        st(118, 268, f"EP.{ep_no}", f_ep, fill="#E8384E")

    # 見出しを13文字で折り返し、下部から積む
    lines = [headline[i : i + 13] for i in range(0, len(headline), 13)][:4]
    st(120, S - 150 - 64, date_str, f_date, fill="#FFD2D8")
    y = S - 230
    for line in reversed(lines):
        y -= 148
        st(120, y, line, f_head)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(out_path, quality=90)
    logger.info("ジャケットを生成しました: %s", out_path)
    return out_path
