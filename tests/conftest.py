from __future__ import annotations

import pytest

from autonaparnik.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openrouter_api_key="test-key",
        openrouter_model="deepseek/deepseek-v4.1-flash-1017",
        telegram_bot_token="test-token",
        mcp_url="http://127.0.0.1:8765/mcp",
        mcp_listen_host="127.0.0.1",
        mcp_listen_port=8765,
        qdrant_url="http://127.0.0.1:6333",
    )
