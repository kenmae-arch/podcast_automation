"""Fish Audio APIで台本テキストを音声化するモジュール。

長文はチャンク分割して個別に音声化し、pydubで結合する。
モデルは必ず s2.1-pro-free(完全無料・フェアユース)を指定する。
TTSが読み間違える固有名詞は pronunciation_dict.json の読み仮名に置換してから送信する。
"""
import io
import json
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path

import requests

import config
from utils import RetryableError, retry_with_backoff

logger = logging.getLogger(__name__)

PRONUNCIATION_DICT_PATH = config.BASE_DIR / "pronunciation_dict.json"


def apply_pronunciation_dict(text: str) -> str:
    """読み間違えやすい語を読み仮名に置換する(長い語から優先して適用)。"""
    if not PRONUNCIATION_DICT_PATH.exists():
        return text
    mapping = json.loads(PRONUNCIATION_DICT_PATH.read_text(encoding="utf-8"))
    for word in sorted(mapping, key=len, reverse=True):
        text = text.replace(word, mapping[word])
    return text


class AudioGenerator(ABC):
    """音声生成のインターフェース。別のTTS APIに差し替え可能。"""

    @abstractmethod
    def generate(self, text: str, output_path: Path) -> Path: ...


class FishAudioGenerator(AudioGenerator):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.FISH_AUDIO_API_KEY
        if not self.api_key:
            raise ValueError("FISH_AUDIO_API_KEY が設定されていません")

    def generate(self, text: str, output_path: Path) -> Path:
        text = apply_pronunciation_dict(text)
        chunks = self._split_text(text, config.TTS_CHUNK_SIZE)
        logger.info("テキストを%dチャンクに分割して音声化します", len(chunks))
        audio_parts = [self._synthesize_chunk(chunk) for chunk in chunks]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if len(audio_parts) == 1:
            output_path.write_bytes(audio_parts[0])
        else:
            self._concat_mp3(audio_parts, output_path)
        logger.info("音声を保存しました: %s (%.1f KB)", output_path, output_path.stat().st_size / 1024)
        return output_path

    @retry_with_backoff
    def _synthesize_chunk(self, text: str) -> bytes:
        payload: dict = {
            "text": text,
            "format": "mp3",
            "mp3_bitrate": 128,
        }
        if config.FISH_AUDIO_REFERENCE_ID:
            payload["reference_id"] = config.FISH_AUDIO_REFERENCE_ID

        response = requests.post(
            config.FISH_AUDIO_API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # 【重要】モデル指定は必ず s2.1-pro-free(ヘッダーで指定する仕様)
                "model": config.FISH_AUDIO_MODEL,
            },
            json=payload,
            timeout=300,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableError(
                f"Fish Audio API {response.status_code}: {response.text[:200]}"
            )
        response.raise_for_status()
        return response.content

    @staticmethod
    def _split_text(text: str, chunk_size: int) -> list[str]:
        """文の区切り(。!? 改行)を優先してchunk_size以内に分割する。"""
        sentences = re.split(r"(?<=[。!?!?\n])", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) > chunk_size:
                chunks.append(current)
                current = sentence
            else:
                current += sentence
        if current.strip():
            chunks.append(current)
        return [c for c in chunks if c.strip()]

    @staticmethod
    def _concat_mp3(parts: list[bytes], output_path: Path) -> None:
        try:
            from pydub import AudioSegment

            combined = AudioSegment.empty()
            for part in parts:
                combined += AudioSegment.from_file(io.BytesIO(part), format="mp3")
            combined.export(output_path, format="mp3", bitrate="128k")
        except Exception as e:
            # ffmpeg未導入環境向けフォールバック: 同一ビットレートのMP3は
            # フレーム単位のバイト連結でもほとんどのプレイヤーで再生可能
            logger.warning("pydubでの結合に失敗、バイト連結にフォールバックします: %s", e)
            output_path.write_bytes(b"".join(parts))


def create_audio_generator() -> AudioGenerator:
    """将来別のTTSに切り替える場合はここを変更する。"""
    return FishAudioGenerator()
