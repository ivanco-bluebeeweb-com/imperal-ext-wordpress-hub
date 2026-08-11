"""Guard the standing rule: every registered function has a non-zero price."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pricing_map_covers_every_registered_function_exactly_once():
    manifest = json.loads((ROOT / "imperal.json").read_text())
    prices = json.loads((ROOT / "tool-prices.json").read_text())
    functions = {tool["name"] for tool in manifest["tools"] if "action_type" in tool}

    assert set(prices) == functions, (
        f"missing prices: {sorted(functions - set(prices))}; "
        f"stale prices: {sorted(set(prices) - functions)}"
    )
    assert all(isinstance(price, int) and price > 0 for price in prices.values())
