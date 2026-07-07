#!/usr/bin/env python3
"""Build the static market-pulse JSON used by the public website."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ENV_FILE = Path.home() / ".secrets" / "fmp.env"
DEFAULT_OUTPUT = Path("assets/data/market-pulse.json")
QUOTE_ENDPOINT = "https://financialmodelingprep.com/stable/quote"
BATCH_ENDPOINTS = {
    "Index": "https://financialmodelingprep.com/stable/batch-index-quotes",
    "FX": "https://financialmodelingprep.com/stable/batch-forex-quotes",
    "Commodity": "https://financialmodelingprep.com/stable/batch-commodity-quotes",
}
USER_AGENT = "Guerrieri-Capital-Market-Pulse/1.0"

INSTRUMENTS = [
    {"symbol": "^GSPC", "label": "S&P 500", "type": "Index", "decimals": 2},
    {"symbol": "^NDX", "label": "Nasdaq 100", "type": "Index", "decimals": 2},
    {"symbol": "^RUT", "label": "Russell 2000", "type": "Index", "decimals": 2},
    {"symbol": "^STOXX50E", "label": "Euro STOXX 50", "type": "Index", "decimals": 2},
    {"symbol": "^FTSE", "label": "FTSE 100", "type": "Index", "decimals": 2},
    {"symbol": "EURUSD", "label": "EUR/USD", "type": "FX", "decimals": 4},
    {"symbol": "GBPUSD", "label": "GBP/USD", "type": "FX", "decimals": 4},
    {"symbol": "USDJPY", "label": "USD/JPY", "type": "FX", "decimals": 2},
    {"symbol": "GCUSD", "label": "Gold", "type": "Commodity", "decimals": 2},
    {"symbol": "SIUSD", "label": "Silver", "type": "Commodity", "decimals": 2},
    {"symbol": "CLUSD", "label": "WTI", "type": "Commodity", "decimals": 2},
    {"symbol": "BZUSD", "label": "Brent", "type": "Commodity", "decimals": 2},
    {"symbol": "HGUSD", "label": "Copper", "type": "Commodity", "decimals": 4},
]


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def api_key_from(env_file: Path) -> str:
    api_key = os.environ.get("FMP_API_KEY") or load_env_file(env_file).get("FMP_API_KEY")
    if not api_key:
        raise RuntimeError("FMP_API_KEY is missing. Set it in the environment or the env file.")
    return api_key


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_json(endpoint: str, api_key: str, params: dict[str, str] | None = None) -> Any:
    query_params = dict(params or {})
    query_params["apikey"] = api_key
    request = Request(f"{endpoint}?{urlencode(query_params)}", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_quote(symbol: str, api_key: str) -> dict[str, Any]:
    payload = fetch_json(QUOTE_ENDPOINT, api_key, {"symbol": symbol})

    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"No quote returned for {symbol}")

    return payload[0]


def fetch_quote_batch(instrument_type: str, api_key: str) -> dict[str, dict[str, Any]]:
    endpoint = BATCH_ENDPOINTS[instrument_type]
    payload = fetch_json(endpoint, api_key)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected {instrument_type} quote payload: {type(payload).__name__}")
    out: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip()
        if symbol:
            out[symbol.upper()] = row
    return out


def build_payload(api_key: str) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = []
    errors = []
    quote_lookup: dict[tuple[str, str], dict[str, Any]] = {}

    for instrument_type in sorted({str(config["type"]) for config in INSTRUMENTS}):
        try:
            for symbol, quote in fetch_quote_batch(instrument_type, api_key).items():
                quote_lookup[(instrument_type, symbol)] = quote
        except Exception as exc:
            errors.append({"symbol": f"{instrument_type}:batch", "message": str(exc)})

    for config in INSTRUMENTS:
        symbol = config["symbol"]
        quote = quote_lookup.get((str(config["type"]), symbol.upper()))
        if quote is None:
            errors.append({"symbol": symbol, "message": "No quote returned by batch endpoint"})
            continue

        rows.append(
            {
                "symbol": symbol,
                "label": config["label"],
                "type": config["type"],
                "decimals": config["decimals"],
                "price": as_float(quote.get("price")),
                "change": as_float(quote.get("change")),
                "changePercent": as_float(quote.get("changePercentage")),
                "sourceName": quote.get("name") or config["label"],
                "exchange": quote.get("exchange"),
                "timestamp": quote.get("timestamp"),
            }
        )

    if not rows:
        raise RuntimeError("No market quotes were retrieved.")

    return {
        "schema": 1,
        "source": "Financial Modeling Prep",
        "sourceUrl": "https://site.financialmodelingprep.com/developer/docs/stable/quote",
        "generatedAt": generated_at,
        "label": "Market context",
        "notice": "Cached quote snapshot. Delayed data; not investment advice.",
        "instruments": rows,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the public static market-pulse JSON.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    api_key = api_key_from(args.env_file)
    try:
        payload = build_payload(api_key)
    except RuntimeError as exc:
        if str(exc) == "No market quotes were retrieved." and args.output.exists():
            existing = json.loads(args.output.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing.get("instruments"):
                print(f"No fresh market quotes retrieved; preserving existing {args.output}.")
                return 0
        raise

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {args.output} with {len(payload['instruments'])} instruments at {payload['generatedAt']}")
    if payload["errors"]:
        print(f"Skipped {len(payload['errors'])} instruments with transient errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
