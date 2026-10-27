"""Minimal NHTSA MCP server (official Python SDK) wrapping public NHTSA HTTP APIs.

cyanheads/nhtsa-vehicle-safety-mcp-server remains the preferred upstream candidate.
This wrapper exists so the app can run initialize/tools/list/tools/call without a
pinned Node image. It is a real MCP endpoint, not a mock and not a direct REST
call from the orchestrator.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from autonaparnik.config import load_settings

NHTSA_RECALLS = "https://api.nhtsa.gov/recalls/recallsByVehicle"
NHTSA_COMPLAINTS = "https://api.nhtsa.gov/complaints/complaintsByVehicle"
VPIC_MODELS = "https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMake/{make}"
USER_AGENT = "autonaparnik/0.1 (student project; nhtsa mcp wrapper)"

mcp = FastMCP("nhtsa-autonaparnik", stateless_http=True, json_response=True, port=8765)
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
    return _client


def _empty(message: str) -> dict[str, Any]:
    return {"status": "ok", "message": message, "Count": 0, "total": 0, "Results": []}


def _nhtsa_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("Results", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _nhtsa_count(data: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    for key in ("Count", "count", "total"):
        if data.get(key) is not None:
            try:
                return int(data[key])
            except (TypeError, ValueError):
                continue
    return len(rows)


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = await _http().get(url, params=params)
    if response.status_code == 400:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict) and int(payload.get("Count") or 0) == 0:
            return payload
        return _empty("empty or unsupported vehicle combination")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("unexpected NHTSA payload")
    return data


@mcp.tool(name="nhtsa_search_recalls")
async def nhtsa_search_recalls(make: str, model: str, modelYear: int) -> dict[str, Any]:
    data = await _get_json(NHTSA_RECALLS, {"make": make, "model": model, "modelYear": modelYear})
    results = []
    for row in _nhtsa_rows(data):
        results.append(
            {
                "campaignNumber": row.get("NHTSACampaignNumber") or row.get("campaignNumber"),
                "component": row.get("Component"),
                "summary": row.get("Summary"),
                "consequence": row.get("Consequence"),
                "remedy": row.get("Remedy"),
                "reportReceivedDate": row.get("ReportReceivedDate"),
                "make": row.get("Make"),
                "model": row.get("Model"),
                "modelYear": row.get("ModelYear"),
            }
        )
    total = _nhtsa_count(data, results)
    return {
        "status": "ok",
        "Count": int(total),
        "total": int(total),
        "Results": results,
        "query": {"make": make, "model": model, "modelYear": modelYear},
    }


@mcp.tool(name="nhtsa_search_complaints")
async def nhtsa_search_complaints(
    make: str,
    model: str,
    modelYear: int,
    limit: int = 20,
    offset: int = 0,
    component: str | None = None,
) -> dict[str, Any]:
    data = await _get_json(NHTSA_COMPLAINTS, {"make": make, "model": model, "modelYear": modelYear})
    rows = _nhtsa_rows(data)
    if component:
        needle = component.lower()
        rows = [row for row in rows if needle in str(row.get("components") or row.get("Component") or "").lower()]
    total = len(rows)
    page = rows[offset : offset + max(1, min(limit, 50))]
    results = []
    for row in page:
        products = row.get("products") or []
        product = products[0] if products and isinstance(products[0], dict) else {}
        results.append(
            {
                "odiNumber": str(row.get("odiNumber") or row.get("ODINumber") or ""),
                "component": row.get("components") or row.get("Component"),
                "summary": row.get("summary") or row.get("Summary"),
                "dateComplaintFiled": row.get("dateComplaintFiled") or row.get("DateComplaintFiled"),
                "crash": row.get("crash"),
                "fire": row.get("fire"),
                "make": product.get("productMake") or row.get("Make"),
                "model": product.get("productModel") or row.get("Model"),
                "modelYear": product.get("productYear") or row.get("ModelYear"),
            }
        )
    return {
        "status": "ok",
        "Count": total,
        "total": total,
        "offset": offset,
        "limit": limit,
        "Results": results,
        "query": {"make": make, "model": model, "modelYear": modelYear},
        "is_partial": offset + len(results) < total,
    }


@mcp.tool(name="nhtsa_lookup_vehicles")
async def nhtsa_lookup_vehicles(
    operation: str,
    make: str,
    modelYear: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if operation != "models":
        return {"status": "unsupported", "message": "only operation=models is implemented", "Results": []}
    url = VPIC_MODELS.format(make=make)
    params: dict[str, Any] = {"format": "json"}
    if modelYear is not None:
        url = (
            "https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMakeYear/"
            f"make/{make}/modelyear/{modelYear}"
        )
    data = await _get_json(url, params)
    rows = _nhtsa_rows(data)
    page = rows[offset : offset + max(1, min(limit, 100))]
    return {
        "status": "ok",
        "Count": len(rows),
        "Results": [
            {
                "make": row.get("Make_Name") or make,
                "model": row.get("Model_Name"),
                "modelYear": modelYear,
            }
            for row in page
        ],
    }


def main() -> None:
    settings = load_settings()
    host = os.getenv("MCP_LISTEN_HOST", settings.mcp_listen_host)
    port = int(os.getenv("MCP_LISTEN_PORT", str(settings.mcp_listen_port)))
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
