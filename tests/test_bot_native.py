from __future__ import annotations

from pathlib import Path

import pytest

from autonaparnik.bot.main import BOT_COMMANDS, HELP, LOADING_PHRASES, _replace_notice, next_loading_phrase
from autonaparnik.bot.session import ChatSession
from autonaparnik.config import ROOT
from autonaparnik.domain.models import VehicleProfile, VehicleSafetyArgs
from autonaparnik.tools.vehicle_safety import merge_vehicle


def test_bot_has_no_car_command_or_demo_buttons() -> None:
    source = (ROOT / "autonaparnik" / "bot" / "main.py").read_text(encoding="utf-8")
    assert 'Command("car")' not in source
    assert "/car" not in source
    assert "KeyboardButton" not in source
    assert "ReplyKeyboardMarkup" not in source
    assert "Дребезг" not in source
    assert "Отзывы NHTSA" not in source
    assert all(cmd.command != "car" for cmd in BOT_COMMANDS)
    assert "/car" not in HELP
    assert "Дребезг" not in HELP
    assert "Отзывы NHTSA" not in HELP


def test_session_keeps_history_without_car_entity() -> None:
    session = ChatSession()
    session.remember_user("бмв семёрка")
    session.remember_assistant("Какой год и что случилось?")
    session.remember_user("2017, свистит")
    assert not hasattr(session, "vehicle")
    assert not hasattr(session, "car_draft")
    assert [item.text for item in session.history if item.role == "user"] == ["бмв семёрка", "2017, свистит"]


def test_merge_vehicle_prefers_tool_args() -> None:
    merged = merge_vehicle(
        VehicleProfile(market="unknown"),
        VehicleSafetyArgs(make="Toyota", model="Camry", model_year=2015),
    )
    assert merged.make == "Toyota"
    assert merged.model == "Camry"
    assert merged.model_year == 2015


def test_bot_package_has_no_car_parse() -> None:
    bot_dir = Path(ROOT / "autonaparnik" / "bot")
    names = {path.name for path in bot_dir.iterdir()}
    assert "car_parse.py" not in names


@pytest.mark.asyncio
async def test_replace_notice_sends_if_edit_fails() -> None:
    class Notice:
        async def edit_text(self, *args, **kwargs):
            raise RuntimeError("message can't be edited")

    class Chat:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def answer(self, text, **kwargs):
            self.sent.append(text)

    chat = Chat()
    await _replace_notice(Notice(), chat, "<b>ответ</b>")
    assert chat.sent == ["<b>ответ</b>"]


def test_loading_phrases_rotate() -> None:
    assert len(LOADING_PHRASES) == 50
    assert len(set(LOADING_PHRASES)) == 50
    assert all(phrase == phrase.lower() for phrase in LOADING_PHRASES)
    batch = [next_loading_phrase() for _ in range(50)]
    assert set(batch) == {f"<i>{phrase}</i>" for phrase in LOADING_PHRASES}
    assert next_loading_phrase() == batch[0]
