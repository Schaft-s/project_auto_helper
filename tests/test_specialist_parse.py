from autonaparnik.adapters.specialist import _try_parse


def test_try_parse_drops_extra_fields_and_caps_checks() -> None:
    payload = {
        "task": "post_repair_checks",
        "status": "general_only",
        "summary": "ok",
        "extra": "drop me",
        "checks": [
            {
                "text": "проверить клипсу",
                "relation": "required_check",
                "evidence_ids": ["ETRIM-01"],
                "comment": "noise",
            }
        ]
        + [
            {"text": f"ещё {i}", "relation": "required_check", "evidence_ids": ["ETRIM-01"]}
            for i in range(20)
        ],
        "missing_information": [],
        "limitations": ["демо"],
    }
    import json

    parsed, ok = _try_parse("post_repair_checks", json.dumps(payload, ensure_ascii=False))
    assert ok and parsed is not None
    assert len(parsed.checks) == 7
