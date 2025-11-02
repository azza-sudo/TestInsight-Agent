# utils.py
import os
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

@dataclass
class AppConfig:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    slack_webhook_url: Optional[str] = os.getenv("SLACK_WEBHOOK_URL") or None

    def validate(self):
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        return self


class OpenAITextClient:
    """
    Thin wrapper around OpenAI's Responses API for text generation.
    Swap model via env: OPENAI_MODEL.
    """
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg.validate()
        # The API key is read by the SDK from env automatically,
        # but we call the constructor to be explicit.
        self._client = OpenAI(api_key=self.cfg.openai_api_key)

    def generate(self, user_content: str) -> str:
        """
        Returns a single text string (no streaming) for simplicity.
        """
        resp = self._client.responses.create(
            model=self.cfg.openai_model,
            input=[{"role": "user", "content": user_content}],
            temperature=self.cfg.temperature,
        )
        return resp.output_text.strip()
