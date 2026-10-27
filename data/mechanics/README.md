# Mechanics Stack Exchange RAG

Источник: [HuggingFaceH4/stack-exchange-preferences](https://huggingface.co/datasets/HuggingFaceH4/stack-exchange-preferences), shard `mechanics.stackexchange.com`, revision `c7bda740`.

Тексты CC BY-SA. В каждом фрагменте есть URL вопроса, автор ответа и revision корпуса. Это не официальные сервисные инструкции.

Почему весь shard, а не топ-400: отбор по голосам выкидывает типичные владельческие вопросы. Почему не Flax и не Reddit — см. `docs/decisions/M2-hybrid-rag.md`.

```bash
pip install -e ".[data]"
python scripts/prepare_mechanics.py
python scripts/prepare_bccampus.py
python scripts/ingest_qdrant.py
```

`raw.parquet` в git не кладётся.
