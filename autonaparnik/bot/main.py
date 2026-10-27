from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, Message, ReplyKeyboardRemove

from autonaparnik.application.orchestrator import Orchestrator
from autonaparnik.bot.render import SESSION_LIMITATIONS, render_answer
from autonaparnik.bot.session import ChatSession
from autonaparnik.config import load_settings
from autonaparnik.domain.models import ChatRequest, VehicleProfile
from autonaparnik.factory import build_orchestrator

log = logging.getLogger("autonaparnik.bot")
router = Router()

SESSIONS: dict[int, ChatSession] = {}
RATE: dict[int, deque[float]] = defaultdict(deque)
BUSY = asyncio.Semaphore(2)

BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу"),
    BotCommand(command="help", description="Справка и команды"),
    BotCommand(command="reset", description="Очистить историю"),
    BotCommand(command="mode", description="Режим: owner или mechanic"),
]

HELP = (
    "АвтоНапарник — консультант по машине.\n"
    "Пишите своими словами: марку, год и что случилось.\n\n"
    f"{SESSION_LIMITATIONS}\n\n"
    "Команды:\n"
    "/help — эта справка\n"
    "/reset — очистить историю\n"
    "/mode owner|mechanic — тон ответа"
)

LOADING_PHRASES = (
    "ретекулирую шлицы. без этого никак…",
    "ищу болт, который остался после сборки…",
    "листаю мануал. страница 347 из 12…",
    "сверяюсь с веткой форума 2009 года…",
    "стучу по капоту. для калибровки…",
    "перевожу «тарахтит» на язык запчастей…",
    "считаю щелчки реле. уже сорок семь…",
    "ищу ту гайку. она обычно под сиденьем…",
    "грею осциллограф об кружку чая…",
    "протираю щуп. так солиднее…",
    "спрашиваю соседа по гаражу. он кивает…",
    "листаю отзывы, как сериал на ночь…",
    "ищу момент затяжки. и момент истины…",
    "сдуваю пыль с бумажного мануала…",
    "читаю: «у меня тоже так было»…",
    "калибрую удачу. пока двенадцать процентов…",
    "перевожу коды ошибок. получается «ой»…",
    "ищу прокладку. нашёл её в расписании…",
    "сверяю год модели. год дракона не подходит…",
    "ищу электросхему. нашёл схему метро…",
    "кручу ключ на девяносто. не тот ключ…",
    "сравниваю два одинаковых болта. они разные…",
    "ищу крышку бачка. она уже в руке…",
    "смотрю, кто ещё жаловался на такой стук…",
    "читаю бюллетень шёпотом, чтобы не сглазить…",
    "смазываю факты графиткой…",
    "жду, пока остынет чужое мнение…",
    "ищу болт м8. пока только м6 и саморезы…",
    "считаю лампочки check engine. одна, но яркая…",
    "ищу проводку. проводка ищет меня…",
    "перебираю симптомы, как носки в бардачке…",
    "смотрю, чем кончилось у такой же машины…",
    "полирую коды ошибок до блеска…",
    "спрашиваю дядю васю. он есть в источниках…",
    "листаю каталог. деталь называется «ну та»…",
    "ищу отзыв, где всё кончилось хорошо…",
    "пишу на завод. завод молчит по-японски…",
    "собираю пазл из чужих поломок…",
    "проверяю давление. социальное тоже…",
    "ищу ветку, где починили стуком кулака…",
    "наливаю кофе. почти не в воронку…",
    "загрузка гаража: 99% уже час…",
    "откручиваю совет «просто замени всё»…",
    "генерирую подкапотное пространство…",
    "прислушиваюсь к мотору через интернет…",
    "сравниваю два стука. третий лишний…",
    "загружаю dlc: здравый смысл…",
    "не забывайте дышать. и не забывайте щуп…",
    "вставляю диск 7 из 3. классика…",
    "смотрю источники. иногда они смотрят в ответ…",
)
_loading_phrases = itertools.cycle(LOADING_PHRASES)


def next_loading_phrase() -> str:
    return f"<i>{next(_loading_phrases)}</i>"


def session_for(chat_id: int) -> ChatSession:
    return SESSIONS.setdefault(chat_id, ChatSession())


def hide_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


async def _replace_notice(notice: Message, message: Message, text: str) -> None:
    body = (text or "").strip() or "Не удалось собрать ответ. Повторите запрос."
    html_kwargs = {"parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        await notice.edit_text(body, **html_kwargs)
        return
    except Exception:
        log.exception("could not edit loading message")
    try:
        await message.answer(body, reply_markup=hide_keyboard(), **html_kwargs)
    except Exception:
        log.exception("could not send html answer")
        await message.answer(body, reply_markup=hide_keyboard())


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    session_for(message.chat.id)
    await message.answer(HELP, reply_markup=hide_keyboard(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=hide_keyboard(), parse_mode="HTML")


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    SESSIONS[message.chat.id] = ChatSession()
    await message.answer(
        f"История очищена.\n\n{SESSION_LIMITATIONS}",
        reply_markup=hide_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("mode"))
async def cmd_mode(message: Message) -> None:
    session = session_for(message.chat.id)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip() not in {"owner", "mechanic"}:
        await message.answer("Использование: /mode owner или /mode mechanic", reply_markup=hide_keyboard())
        return
    session.audience = parts[1].strip()
    await message.answer(f"Режим: {session.audience}.", reply_markup=hide_keyboard())


@router.message(F.text)
async def on_text(message: Message, orchestrator: Orchestrator) -> None:
    await _consult(message, orchestrator, (message.text or "").strip())


def _rate_ok(chat_id: int, limit: int) -> bool:
    now = time.time()
    bucket = RATE[chat_id]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


async def _consult(message: Message, orchestrator: Orchestrator, text: str) -> None:
    session = session_for(message.chat.id)
    settings = orchestrator.settings
    if not _rate_ok(message.chat.id, settings.rate_limit_per_minute):
        await message.answer("Слишком часто. Подождите минуту.", reply_markup=hide_keyboard())
        return
    session.remember_user(text)
    request = ChatRequest(
        message=text[:6000],
        vehicle=VehicleProfile(),
        audience=session.audience,  # type: ignore[arg-type]
        intent="auto",
        history=list(session.history[:-1]),
    )
    # ReplyKeyboardRemove makes the notice uneditable (Telegram: "message can't be edited").
    notice = await message.answer(next_loading_phrase(), parse_mode="HTML")
    try:
        async with asyncio.timeout(2):
            await BUSY.acquire()
    except TimeoutError:
        await _replace_notice(notice, message, "Сейчас занято, повторите через несколько секунд.")
        return
    try:
        answer = await orchestrator.handle(request)
    except Exception:
        log.exception("consult failed")
        await _replace_notice(notice, message, "Сбой обработки. Повторите запрос.")
        return
    finally:
        BUSY.release()
    session.remember_assistant(answer.summary)
    chunks = render_answer(answer)
    await _replace_notice(notice, message, chunks[0])
    for chunk in chunks[1:]:
        await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    if not settings.openrouter_api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    orchestrator = build_orchestrator(settings)
    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    dp["orchestrator"] = orchestrator
    dp.include_router(router)
    await bot.set_my_commands(BOT_COMMANDS)
    await dp.start_polling(bot)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
