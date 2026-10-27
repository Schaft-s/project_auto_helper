# ADR: полный H4 Mechanics SE + BCcampus в Qdrant hybrid

Статус: принято после переделки UX.
Дата: 2026-10-26.

## Решение

1. В индекс идёт весь shard `mechanics.stackexchange.com` из HuggingFaceH4/stack-exchange-preferences (rev `c7bda740`), не топ-400. Пустые ответы отбрасываются, фотозависимые помечаются, не удаляются.
2. Второй корпус — текст BCcampus / Camosun Trades Access (C-1, E-4), CC BY 4.0, без иллюстраций ITA.
3. Поиск — Qdrant hybrid: dense `paraphrase-multilingual-MiniLM-L12-v2` (fastembed, 384d; e5-small в этой версии FastEmbed нет) + sparse BM25, fusion RRF. Один tool `search_discussions` с `collection=mechanics|manuals|both`.
4. Не берём Flax Mechanics (нет URL/автора, NC) и SHP-2 Reddit (нет чистой лицензии).

## Последствия

- Offline-тесты остаются на лексическом `qa.jsonl`, если Qdrant не поднят.
- `raw.parquet` по-прежнему не в git.
