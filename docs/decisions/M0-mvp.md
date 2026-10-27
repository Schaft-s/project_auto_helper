# ADR: MCP-обёртка NHTSA на официальном Python SDK

Статус: принято для MVP без SFT/КСО.
Дата: 2026-10-24.

## Контекст

Спека указывает готовый `cyanheads/nhtsa-vehicle-safety-mcp-server`. Для локального Python-запуска без закреплённого Node/digest нужен воспроизводимый процесс.

## Решение

Оркестратор вызывает только MCP (`initialize` / `tools/list` / `tools/call`). Прямой REST из фасада `vehicle_safety_lookup` запрещён.

Поставляем минимальный MCP-сервер `python -m autonaparnik.mcp_server` с allowlist:

- `nhtsa_search_recalls`
- `nhtsa_search_complaints`
- `nhtsa_lookup_vehicles` (только `operation=models`)

Сервер ходит в публичные `api.nhtsa.gov` / `vpic.nhtsa.dot.gov`. Имена инструментов совпадают с кандидатом cyanheads, чтобы фасад не менять.

## Последствия

- Протокол настоящий; mock/replay по умолчанию выключены.
- Это не заявление, что cyanheads прогнан live в этой среде.
- Подмена автомобиля похожей моделью по-прежнему запрещена в фасаде.
