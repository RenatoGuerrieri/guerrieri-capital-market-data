from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "tools" / "update_market_pulse.py"
SPEC = importlib.util.spec_from_file_location("update_market_pulse", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def quote_for(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "name": symbol,
        "price": 100.0,
        "change": 1.0,
        "changePercentage": 1.0,
        "exchange": "TEST",
        "timestamp": 1_700_000_000,
    }


class MarketPulseTests(unittest.TestCase):
    def test_single_quote_fallback_populates_missing_batch_rows(self) -> None:
        with (
            patch.object(MODULE, "fetch_quote_batch", return_value={}),
            patch.object(MODULE, "fetch_quote", side_effect=lambda symbol, _: quote_for(symbol)),
        ):
            payload = MODULE.build_payload("test-key")

        self.assertEqual(len(payload["instruments"]), len(MODULE.INSTRUMENTS))
        self.assertEqual(payload["errors"], [])

    def test_empty_batch_and_failed_fallback_is_a_hard_failure(self) -> None:
        with (
            patch.object(MODULE, "fetch_quote_batch", side_effect=RuntimeError("batch unavailable")),
            patch.object(MODULE, "fetch_quote", side_effect=RuntimeError("quote unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Incomplete market quote snapshot"):
                MODULE.build_payload("test-key")


if __name__ == "__main__":
    unittest.main()
