from autonaparnik.mcp_server import _nhtsa_count, _nhtsa_rows


def test_lowercase_results_and_count() -> None:
    payload = {
        "count": 2,
        "results": [{"NHTSACampaignNumber": "19V182000"}, {"NHTSACampaignNumber": "16V061000"}],
    }
    rows = _nhtsa_rows(payload)
    assert len(rows) == 2
    assert _nhtsa_count(payload, rows) == 2
