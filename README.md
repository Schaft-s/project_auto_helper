# АвтоНапарник

Русскоязычный Telegram-консультант автовладельца и механика. Один агент, три tool: NHTSA MCP, гибридный RAG, сборочный подагент-заглушка.

Оркестратор и specialist — одна модель OpenRouter `deepseek/deepseek-v4.1-flash-1017` с разными промптами. Своей сборочной модели пока нет.

Спецификация продукта лежит в `autonaparnik_agent_plan_v2/`. Этот каталог — рабочее приложение.

## Что умеет

- Отзывные кампании и жалобы NHTSA по марке/модели/году.
- Поиск по Mechanics Stack Exchange и учебным текстам BCcampus (Qdrant hybrid).
- Черновые подсказки по сборке-разборке (placeholder, модель позже заменят).
- Свободные вопросы по авто своими словами.
- Марку, модель и год модель берёт из текста диалога; отдельной команды и формы нет.

Не ставит диагноз, не проверяет VIN, не подменяет автомобиль похожей моделью.

## Запуск

Нужен Python 3.11+ (проверено на 3.12).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,data]"
cp .env.example .env
```

В `.env`:

```
OPENROUTER_API_KEY=...
TELEGRAM_BOT_TOKEN=...
OPENROUTER_MODEL=deepseek/deepseek-v4.1-flash-1017
MCP_URL=http://127.0.0.1:8765/mcp
QDRANT_URL=http://127.0.0.1:6333
```

Инфраструктура:

```bash
docker compose -f infra/docker-compose.yml up --build -d
python scripts/prepare_mechanics.py
python scripts/prepare_bccampus.py
python scripts/ingest_qdrant.py
```

Если MCP не из compose:

```bash
python -m autonaparnik.mcp_server
```

Бот:

```bash
python -m autonaparnik.bot.main
```

В Telegram: `/start`, затем вопрос своими словами. Команды: `/help`, `/reset`, `/mode`.

## Тесты

```bash
pytest
```

Live smoke (нужны ключ, MCP и по желанию Qdrant):

```bash
python -m autonaparnik.smoke mcp
python -m autonaparnik.smoke router
python -m autonaparnik.eval_golden --live
```

Golden: `evaluation/golden.jsonl`. Offline — clarify/policy/узкий retrieval. Live — MCP + OpenRouter. Пересборка: `python scripts/build_golden.py`.

## Ограничения этого этапа

- Нет SFT/DPO, vLLM, GPU и датасета КСО.
- Сборочный specialist — уверенная заглушка, не заводская карта.
- История чата только в памяти процесса.
- NHTSA отражает рынок США, даже если машина куплена в RU/KZ.
- Форумные тексты CC BY-SA: в ответе ссылка, не перепечатка целиком.
