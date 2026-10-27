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
    "Ретекулирую шлицы. Без этого никак…",
    "Ищу болт, который остался после сборки…",
    "Листаю мануал. Страница 347 из 12…",
    "Сверяюсь с веткой форума 2009 года…",
    "Стучу по капоту. Для калибровки…",
    "Перевожу «тарахтит» на язык запчастей…",
    "Считаю щелчки реле. Уже сорок семь…",
    "Ищу ту гайку. Она обычно под сиденьем…",
    "Грею осциллограф об кружку чая…",
    "Протираю щуп. Так солиднее…",
    "Спрашиваю соседа по гаражу. Он кивает…",
    "Листаю отзывы, как сериал на ночь…",
    "Ищу момент затяжки. И момент истины…",
    "Сдуваю пыль с бумажного мануала…",
    "Читаю: «у меня тоже так было»…",
    "Калибрую удачу. Пока двенадцать процентов…",
    "Перевожу коды ошибок. Получается «ой»…",
    "Ищу прокладку. Нашёл её в расписании…",
    "Сверяю год модели. Год Дракона не подходит…",
    "Ищу электросхему. Нашёл схему метро…",
    "Кручу ключ на девяносто. Не тот ключ…",
    "Сравниваю два одинаковых болта. Они разные…",
    "Ищу крышку бачка. Она уже в руке…",
    "Смотрю, кто ещё жаловался на такой стук…",
    "Читаю бюллетень шёпотом, чтобы не сглазить…",
    "Смазываю факты графиткой…",
    "Жду, пока остынет чужое мнение…",
    "Ищу болт М8. Пока только М6 и саморезы…",
    "Считаю лампочки Check Engine. Одна, но яркая…",
    "Ищу проводку. Проводка ищет меня…",
    "Перебираю симптомы, как носки в бардачке…",
    "Смотрю, чем кончилось у такой же машины…",
    "Полирую коды ошибок до блеска…",
    "Спрашиваю дядю Васю. Он есть в источниках…",
    "Листаю каталог. Деталь называется «ну та»…",
    "Ищу отзыв, где всё кончилось хорошо…",
    "Пишу на завод. Завод молчит по-японски…",
    "Собираю пазл из чужих поломок…",
    "Проверяю давление. Социальное тоже…",
    "Ищу ветку, где починили стуком кулака…",
    "Наливаю кофе. Почти не в воронку…",
    "Загрузка гаража: 99% уже час…",
    "Откручиваю совет «просто замени всё»…",
    "Генерирую подкапотное пространство…",
    "Прислушиваюсь к мотору через интернет…",
    "Сравниваю два стука. Третий лишний…",
    "Загружаю DLC: здравый смысл…",
    "Не забывайте дышать. И не забывайте щуп…",
    "Вставляю диск 7 из 3. Классика…",
    "Смотрю источники. Иногда они смотрят в ответ…",
)
_loading_phrases = itertools.cycle(LOADING_PHRASES)


def next_loading_phrase() -> str:
    return next(_loading_phrases)


def session_for(chat_id: int) -> ChatSession:
    return SESSIONS.setdefault(chat_id, ChatSession())


def hide_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


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
    notice = await message.answer(next_loading_phrase(), reply_markup=hide_keyboard())
    try:
        async with asyncio.timeout(2):
            await BUSY.acquire()
    except TimeoutError:
        await notice.edit_text("Сейчас занято, повторите через несколько секунд.")
        return
    try:
        answer = await orchestrator.handle(request)
    except Exception:
        log.exception("consult failed")
        await notice.edit_text("Сбой обработки. Повторите запрос.")
        return
    finally:
        BUSY.release()
    session.remember_assistant(answer.summary)
    chunks = render_answer(answer)
    await notice.edit_text(chunks[0], parse_mode="HTML", disable_web_page_preview=True)
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
