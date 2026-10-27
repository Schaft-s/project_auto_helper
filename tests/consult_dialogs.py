"""Multi-turn dialogues. Each step declares tools before the run."""

from __future__ import annotations

DIALOGS: list[dict] = [
    {
        "id": "hello-bmw7-whistle",
        "note": "Привет → машина → свист на прогреве.",
        "steps": [
            {
                "message": "привет",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "route_in": ["general"],
                    "max_chars": 500,
                    "must_not": ["NHTSA", "кампания"],
                },
            },
            {
                "message": "автомобиль бмв семёрка",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "max_chars": 800,
                    "must_any": ["BMW", "7", "семёр", "семер"],
                    "must_not": ["Honda", "Camry"],
                },
            },
            {
                "message": "свистит когда прогревается",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["свист"],
                    "must_not": ["Honda", "спасибо"],
                },
            },
        ],
    },
    {
        "id": "camry-consumption-thanks",
        "note": "Вопрос сразу, потом нейтральное спасибо — без повторного поиска.",
        "steps": [
            {
                "message": "привет, вопрос по камри 3.5, почему расход огромный",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["расход", "Camry", "камри"],
                },
            },
            {
                "message": "спасибо",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "route_in": ["general"],
                    "max_chars": 400,
                    "must_not": ["NHTSA", "мультиметр", "Use Multimeters"],
                },
            },
        ],
    },
    {
        "id": "knock-then-discovery",
        "note": "Симптом раньше машины: стук коробки, потом Discovery.",
        "steps": [
            {
                "message": "стучит коробка",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["короб"],
                },
            },
            {
                "message": "рендж ровер дискавери",
                "expect": {
                    "must_any": ["Discovery", "Range", "Рендж", "Дискавери", "Land Rover", "Rover"],
                    "must_not": ["BMW", "Camry"],
                },
            },
        ],
    },
    {
        "id": "overheat-followup-traffic",
        "note": "Консультация и уточнение «в пробке» — не здороваться заново.",
        "steps": [
            {
                "message": "бмв 320 li m sport перегрев",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["перегрев", "антифриз", "вентилятор"],
                },
            },
            {
                "message": "в пробке на месте",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["пробк", "вентилятор", "радиатор"],
                    "must_not": ["Привет"],
                    "max_chars": 2000,
                },
            },
        ],
    },
    {
        "id": "ok-after-help",
        "note": "Нейтральные /help и ок.",
        "steps": [
            {
                "message": "help",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "route_in": ["general"],
                    "max_chars": 600,
                },
            },
            {
                "message": "ок",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "route_in": ["general"],
                    "max_chars": 300,
                },
            },
        ],
    },
    {
        "id": "clip-then-thanks",
        "note": "Сборка, затем спасибо без повторного workshop.",
        "steps": [
            {
                "message": "После установки декоративной панели появился дребезг. Что проверить?",
                "expect": {"tools_include": ["workshop_consult"]},
            },
            {
                "message": "спасибо большое",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "route_in": ["general"],
                    "max_chars": 300,
                },
            },
        ],
    },
]
