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
    {
        "id": "bmw7-then-headlight-workshop",
        "note": "После обсуждения BMW 7 — снятие фары без потери контекста в подагенте.",
        "steps": [
            {
                "message": "ещё думаю про bmw 7 серии, дорест, 2021-2022 года",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["BMW", "7", "семёр", "семер"],
                    "must_not": ["Audi", "RS3"],
                },
            },
            {
                "message": "вот сейчас общался с другом по этой машине, ему фару снять собрать надо, как это сделать",
                "expect": {
                    "tools_include": ["workshop_consult"],
                    "see_workshop": True,
                    "specialist_must_any": ["BMW", "7", "фару", "фар"],
                    "must_any": ["фар"],
                    "must_not": [
                        "о какой машине",
                        "какая марка",
                        "марку, модель",
                        "марка, модель и год",
                        "не вижу, о какой",
                    ],
                },
            },
        ],
    },
    {
        "id": "camry-then-door-card-workshop",
        "note": "Известная Camry → карта двери; подагент видит историю, не переспрашивает марку.",
        "steps": [
            {
                "message": "у меня toyota camry 2015",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["Camry", "камри", "Toyota"],
                },
            },
            {
                "message": "снял карту двери, ставлю обратно — что проверить по клипсам?",
                "expect": {
                    "tools_include": ["workshop_consult"],
                    "see_workshop": True,
                    "specialist_must_any": ["Camry", "камри", "Toyota", "карт", "клипс"],
                    "must_not": [
                        "о какой машине",
                        "какая марка",
                        "марку, модель",
                        "марка, модель и год",
                    ],
                },
            },
        ],
    },
    {
        "id": "switch-car-then-panel-workshop",
        "note": "Смена машины: сначала Audi, потом Civic и панель — в подагенте Civic, не Audi.",
        "steps": [
            {
                "message": "смотрю audi a4 2018, что по надёжности",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["Audi", "A4", "ауди"],
                },
            },
            {
                "message": "нет, лучше honda civic 2012 — после установки декоративной панели дребезг, что проверить?",
                "expect": {
                    "tools_include": ["workshop_consult"],
                    "see_workshop": True,
                    "specialist_must_any": ["Civic", "Honda", "панел", "дребезг"],
                    "must_any": ["Civic", "Honda", "панел", "дребезг"],
                    "must_not": ["о какой машине", "какая марка", "Audi A4"],
                },
            },
        ],
    },
    {
        "id": "workshop-followup-same-car",
        "note": "Сборка → follow-up по другой детали той же машины без повтора марки.",
        "steps": [
            {
                "message": "honda accord 2014, накладка центральной консоли защёлкнулась криво, чек-лист после сборки",
                "expect": {
                    "tools_include": ["workshop_consult"],
                    "see_workshop": True,
                    "specialist_must_any": ["Accord", "Honda", "консол"],
                },
            },
            {
                "message": "а клипсы подкрылка на этой же машине как проверить после установки?",
                "expect": {
                    "tools_include": ["workshop_consult"],
                    "see_workshop": True,
                    "specialist_must_any": ["Accord", "Honda", "подкрыл", "клипс"],
                    "must_not": [
                        "о какой машине",
                        "какая марка",
                        "марку, модель",
                        "марка, модель и год",
                    ],
                },
            },
        ],
    },
    {
        "id": "pronoun-this-car-workshop",
        "note": "Местоимение «эта машина» после известной модели → workshop без уточнения марки.",
        "steps": [
            {
                "message": "volkswagen jetta 2015",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["Jetta", "Volkswagen", "VW", "джетт"],
                },
            },
            {
                "message": "на этой машине другу надо снять и поставить фару, как сделать",
                "expect": {
                    "tools_include": ["workshop_consult"],
                    "see_workshop": True,
                    "specialist_must_any": ["Jetta", "Volkswagen", "VW", "фар"],
                    "must_any": ["фар"],
                    "must_not": [
                        "о какой машине",
                        "какая марка",
                        "марку, модель",
                        "не вижу, о какой",
                    ],
                },
            },
        ],
    },
    {
        "id": "symptom-then-assembly-switch",
        "note": "Симптом (не workshop) → затем сборка; контекст машины сохраняется.",
        "steps": [
            {
                "message": "acura rdx 2012, свистит на холодную",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["свист", "Acura", "RDX"],
                },
            },
            {
                "message": "ладно, другой вопрос по ней: после установки декоративной панели дребезг, что проверить?",
                "expect": {
                    "tools_include": ["workshop_consult"],
                    "see_workshop": True,
                    "specialist_must_any": ["Acura", "RDX", "панел", "дребезг"],
                    "must_not": ["о какой машине", "какая марка"],
                },
            },
        ],
    },
    {
        "id": "bmw3-ignition-angle",
        "note": "Марка → симптом; без дублей уточнений и сырых Complaint-заголовков.",
        "steps": [
            {
                "message": "привет",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "route_in": ["general"],
                    "max_chars": 500,
                },
            },
            {
                "message": "как дела",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "route_in": ["general"],
                    "max_chars": 400,
                },
            },
            {
                "message": "бмв",
                "expect": {
                    "tools_exclude": ["vehicle_safety_lookup", "workshop_consult", "search_discussions"],
                    "must_any": ["BMW", "бмв", "модель"],
                },
            },
            {
                "message": "3-ка, 2021 года, маленький угол зажигания",
                "expect": {
                    "tools_exclude": ["workshop_consult"],
                    "must_any": ["угол", "зажиган"],
                    "must_not": ["Complaint ", "I'd like to understand", "My 1997 BMW"],
                    "max_chars": 2800,
                },
            },
        ],
    },
]
