from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from autonaparnik.config import Settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class ChatResult:
    content: str
    tool_calls: list[dict[str, Any]]
    raw_message: dict[str, Any]


class OpenRouterClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owned = client is None

    async def aclose(self) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.settings.router_call_timeout_seconds))
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        force_json: bool = False,
        max_tokens: int | None = None,
    ) -> ChatResult:
        if not self.settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        payload: dict[str, Any] = {
            "model": self.settings.openrouter_model,
            "messages": messages,
            "temperature": 0.2,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if force_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/autonaparnik",
            "X-Title": "Autonaparnik",
        }
        response = await self._http().post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=timeout or self.settings.router_call_timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {response.text[:400]}")
        data = response.json()
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        if not content:
            content = message.get("reasoning") or ""
        tool_calls = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            arguments = function.get("arguments") or "{}"
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)
            tool_calls.append(
                {
                    "id": item.get("id") or f"call_{function.get('name')}",
                    "type": "function",
                    "function": {"name": function.get("name"), "arguments": arguments},
                }
            )
        return ChatResult(content=content, tool_calls=tool_calls, raw_message=message)
