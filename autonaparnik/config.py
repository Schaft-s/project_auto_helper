from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ROUTER_MODEL = "deepseek/deepseek-v4.1-flash-1017"
SPECIALIST_PROMPT_VERSION = "specialist.v2"
ORCHESTRATOR_PROMPT_VERSION = "orchestrator.v2"
ASSUME_EVIDENCE_ID = "EASSUME"


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    openrouter_model: str
    telegram_bot_token: str | None
    mcp_url: str
    mcp_listen_host: str
    mcp_listen_port: int
    qdrant_url: str
    deadline_seconds: float = 90.0
    router_calls_max: int = 3
    specialist_calls_max: int = 2
    mcp_calls_max: int = 4
    complaint_pages_max: int = 2
    complaints_page_size: int = 20
    rag_top_k: int = 4
    connect_timeout_seconds: float = 5.0
    router_call_timeout_seconds: float = 25.0
    specialist_call_timeout_seconds: float = 35.0
    mcp_call_timeout_seconds: float = 10.0
    cache_ttl_seconds: float = 86400.0
    negative_cache_ttl_seconds: float = 3600.0
    rate_limit_per_minute: int = 3
    app_concurrency: int = 2


def load_settings() -> Settings:
    return Settings(
        openrouter_api_key=_env("OPENROUTER_API_KEY", "openrouter_api_key") or "",
        openrouter_model=_env("OPENROUTER_MODEL", default=ROUTER_MODEL) or ROUTER_MODEL,
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        mcp_url=_env("MCP_URL", default="http://127.0.0.1:8765/mcp") or "http://127.0.0.1:8765/mcp",
        mcp_listen_host=_env("MCP_LISTEN_HOST", default="127.0.0.1") or "127.0.0.1",
        mcp_listen_port=int(_env("MCP_LISTEN_PORT", default="8765") or "8765"),
        qdrant_url=_env("QDRANT_URL", default="http://127.0.0.1:6333") or "http://127.0.0.1:6333",
    )


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "vehicle_safety_lookup",
            "description": (
                "Search recall campaigns and optionally complaints via NHTSA MCP. "
                "Extract make, model and model_year from the current message or history. "
                "Call only when all three are already known; pass them as arguments."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "make": {"type": "string", "minLength": 1, "maxLength": 100},
                    "model": {"type": "string", "minLength": 1, "maxLength": 100},
                    "model_year": {"type": "integer", "minimum": 1886, "maximum": 2100},
                    "market": {
                        "type": "string",
                        "enum": ["US", "KZ", "RU", "EU", "other", "unknown"],
                    },
                    "symptom": {"type": "string", "maxLength": 1000, "default": ""},
                    "include_complaints": {"type": "boolean", "default": True},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workshop_consult",
            "description": (
                "Assembly/disassembly specialist only: clips, trim panels, headlights, "
                "post-install checks, plan review. Put make/model/year into query when "
                "they are known from the current message or history. "
                "Do not call for overheating, noise, fuel economy, diagnostics or NHTSA lookups."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task": {
                        "type": "string",
                        "enum": ["assembly_checklist", "review_plan", "post_repair_checks"],
                    },
                    "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "user_plan": {"type": ["string", "null"], "maxLength": 4000},
                },
                "required": ["task", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_discussions",
            "description": (
                "Hybrid search over Mechanics Stack Exchange Q&A and BCcampus trade manuals. "
                "Returns short hits with URLs, not official procedures or NHTSA data."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "collection": {
                        "type": "string",
                        "enum": ["mechanics", "manuals", "both"],
                        "default": "both",
                    },
                },
                "required": ["query"],
            },
        },
    },
]
