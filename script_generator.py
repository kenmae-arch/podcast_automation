"""LLMでポッドキャスト台本を生成するモジュール。

GeminiとGroqの両方に対応。LLM_PROVIDER環境変数で切り替える。
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

import config
from topic_fetcher import Topic
from utils import RetryableError, retry_with_backoff

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """あなたはプロのポッドキャストパーソナリティです。
以下の今日のニューストピックをもとに、1人語りのポッドキャスト台本を日本語で作成してください。

# 条件
- 自然な語り口(です・ます調)で、聞き手に話しかけるように
- オープニングの挨拶 → 各トピックの解説 → クロージングの構成
- 目安は2000〜3000文字程度
- 効果音の指示や「(笑)」などの記号は入れず、読み上げる文章のみ
- 台本内に見出しやマークダウン記法を使わない

# 今日のトピック
{topics}

# 出力形式
必ず以下のJSON形式のみで出力してください(コードブロック不要):
{{
  "title": "エピソードのタイトル(日付を含む簡潔なもの)",
  "description": "エピソード概要・ショーノート(200文字程度、扱ったトピックの列挙を含む)",
  "script": "台本全文"
}}
"""


@dataclass
class Episode:
    title: str
    description: str
    script: str


class ScriptGenerator(ABC):
    """台本生成のインターフェース。別のLLMに差し替え可能。"""

    @abstractmethod
    def generate(self, topics: list[Topic]) -> Episode: ...

    @staticmethod
    def _build_prompt(topics: list[Topic]) -> str:
        topic_lines = "\n".join(
            f"- {t.title}: {re.sub(r'<[^>]+>', '', t.summary)[:200]}" for t in topics
        )
        return PROMPT_TEMPLATE.format(topics=topic_lines)

    @staticmethod
    def _parse_response(text: str) -> Episode:
        # コードブロックで囲まれて返ってきた場合に備えて剥がす
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"LLM応答からJSONを抽出できませんでした: {text[:200]}")
        data = json.loads(match.group(0))
        return Episode(
            title=data["title"],
            description=data["description"],
            script=data["script"],
        )


class GeminiScriptGenerator(ScriptGenerator):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        import google.generativeai as genai

        genai.configure(api_key=api_key or config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(model or config.GEMINI_MODEL)

    @retry_with_backoff
    def generate(self, topics: list[Topic]) -> Episode:
        try:
            response = self.model.generate_content(self._build_prompt(topics))
            return self._parse_response(response.text)
        except Exception as e:
            # 429(レート制限)や5xxはリトライ対象
            msg = str(e)
            if "429" in msg or "500" in msg or "503" in msg or "quota" in msg.lower():
                raise RetryableError(msg) from e
            raise


class GroqScriptGenerator(ScriptGenerator):
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or config.GROQ_API_KEY
        self.model = model or config.GROQ_MODEL

    @retry_with_backoff
    def generate(self, topics: list[Topic]) -> Episode:
        response = requests.post(
            self.API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": self._build_prompt(topics)}],
                "temperature": 0.8,
            },
            timeout=120,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableError(f"Groq API {response.status_code}: {response.text[:200]}")
        response.raise_for_status()
        return self._parse_response(response.json()["choices"][0]["message"]["content"])


class ManualScriptGenerator(ScriptGenerator):
    """scripts/pending.json に置かれた台本を読み込む。

    Claude Codeなど外部で作成した台本を使うモード。LLM APIを呼ばないため無料。
    JSON形式: {"title": ..., "description": ..., "script": ...}
    """

    def __init__(self, script_path=None):
        self.script_path = script_path or config.PENDING_SCRIPT_PATH

    def generate(self, topics: list[Topic]) -> Episode:
        if not self.script_path.exists():
            raise FileNotFoundError(
                f"台本ファイルがありません: {self.script_path}\n"
                "Claude Codeに台本を作成してもらい、"
                '{"title", "description", "script"} を含むJSONとして保存してください。'
            )
        data = json.loads(self.script_path.read_text(encoding="utf-8"))
        return Episode(
            title=data["title"],
            description=data["description"],
            script=data["script"],
        )


def create_script_generator(provider: str | None = None) -> ScriptGenerator:
    """設定に応じたScriptGenerator実装を返すファクトリ。"""
    provider = (provider or config.LLM_PROVIDER).lower()
    if provider in ("manual", "claude"):
        return ManualScriptGenerator()
    if provider == "gemini":
        return GeminiScriptGenerator()
    if provider == "groq":
        return GroqScriptGenerator()
    raise ValueError(f"未対応のLLMプロバイダ: {provider}")
