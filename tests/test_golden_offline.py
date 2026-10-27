from autonaparnik.eval_golden import build_runtime, load_cases, run_one


async def test_offline_golden_cases() -> None:
    runtime = build_runtime()
    ran = 0
    for case in load_cases():
        if case.get("live"):
            continue
        result = await run_one(case, runtime)
        assert result["failures"] == [], (case["id"], result["failures"], result.get("got"))
        ran += 1
    assert ran >= 30
