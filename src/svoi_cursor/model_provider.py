from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class ModelClient:
    """Small adapter for the user's model endpoint.

    Configure it with:
    - SVOI_MODEL_ENDPOINT: HTTP endpoint that accepts a JSON payload.
    - SVOI_MODEL_API_KEY: optional bearer token.
    - SVOI_MODEL_NAME: optional model name sent in the payload.
    """

    def __init__(self) -> None:
        self.endpoint = os.getenv("SVOI_MODEL_ENDPOINT", "").strip()
        self.api_key = os.getenv("SVOI_MODEL_API_KEY", "").strip()
        self.model_name = os.getenv("SVOI_MODEL_NAME", "svoi-model").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint)

    def complete(self, messages: list[ChatMessage]) -> str:
        if not self.is_configured:
            last_user_message = next(
                (message.content for message in reversed(messages) if message.role == "user"),
                "",
            )
            return (
                "Модель пока не подключена.\n\n"
                "Задайте SVOI_MODEL_ENDPOINT, чтобы правая панель отправляла запросы "
                "в вашу модель.\n\n"
                f"Последний запрос: {last_user_message}"
            )

        payload = {
            "model": self.model_name,
            "messages": [message.__dict__ for message in messages],
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Model endpoint returned {error.code}: {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach model endpoint: {error.reason}") from error

        return self._extract_text(data)

    def _extract_text(self, data: object) -> str:
        if isinstance(data, str):
            return data

        if not isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False, indent=2)

        if isinstance(data.get("response"), str):
            return data["response"]
        if isinstance(data.get("text"), str):
            return data["text"]
        if isinstance(data.get("content"), str):
            return data["content"]

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
                if isinstance(first_choice.get("text"), str):
                    return first_choice["text"]

        return json.dumps(data, ensure_ascii=False, indent=2)
