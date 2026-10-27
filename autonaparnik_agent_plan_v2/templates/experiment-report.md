# Эксперимент SFT — заполнить фактическими результатами

Статус: planned. Результаты обучения отсутствуют.

## Гипотеза

На заданном техническом контексте SFT улучшит полноту проверок и сохранение ограничений относительно той же исходной малой модели. Значение прироста заранее не задано.

## Данные

Corpus manifest/hash; права; source_group_id counts; train/validation/test counts; operation types; доля synthetic; reviewer; источники; правила дедупликации; дата freeze; кто имел доступ к test labels.

## Конфигурация

Base/tokenizer revision; LoRA/quantization; prompt/template hash; seed; package locks; GPU/VRAM; sequence length; batch/accumulation; learning rate; epochs/steps; проверка loss mask; train runtime; memory peak; adapter hash.

## Методика

Одинаковые входные packets и decoding. Primary rubric frozen до test. Правило abstention; raw/after-repair отдельно. Paired resampling по source_group_id. Записать число проверяющих и долю повторного слепого review.

## Результаты

| Показатель | Base | SFT | Разница / неопределённость |
|---|---|---|---|
| Primary 0–10 | не измерено | не измерено | не измерено |
| Unsupported claims | не измерено | не измерено | не измерено |
| Correct abstention / лишний отказ | не измерено | не измерено | не измерено |
| Raw / after-repair JSON valid | не измерено | не измерено | не измерено |
| p50 / p95 latency | не измерено | не измерено | не измерено |

Контроль полной системы: strong+sources, strong+base, strong+SFT на одинаковом поднаборе. Отдельно real MCP live smoke. Не помещать гипотетические числа в таблицу фактических результатов.

## Ошибки и выбор

3–5 разрешённых характерных примеров с gold rubric; случаи регрессии; ограничения переноса; честный вывод об улучшении или его отсутствии; selected checkpoint и причина.

## Export / deployment

Фактически размещённый artifact hash; merge/quantization config; parity check; training-manifest public_serve check; ссылка на run evidence; какие материалы можно публиковать.
