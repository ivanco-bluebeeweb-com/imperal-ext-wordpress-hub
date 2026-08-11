"""Pricing is an explicit product contract, not an optional release afterthought."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PRICES = {0, 8, 12, 20}


def _manifest() -> dict:
    return json.loads((ROOT / "imperal.json").read_text())


def _prices() -> dict:
    return json.loads((ROOT / "tool-prices.json").read_text())


def test_pricing_map_covers_every_registered_function_exactly_once():
    functions = {tool["name"] for tool in _manifest()["tools"] if "action_type" in tool}
    prices = _prices()
    assert set(prices) == functions, (
        f"missing prices: {sorted(functions - set(prices))}; "
        f"stale prices: {sorted(set(prices) - functions)}"
    )


def test_pricing_policy_uses_the_current_token_scale():
    prices = _prices()
    assert all(isinstance(price, int) and price in ALLOWED_PRICES for price in prices.values())
    assert prices["create_post"] == 8
    assert prices["preview_bulk_product_change"] == 12
    assert prices["apply_csv_catalog_import"] == 20


def test_manifest_pricing_is_an_exact_copy_of_the_release_map():
    pricing = _manifest()["pricing"]
    prices = _prices()
    assert pricing["model"] == "per_action"
    assert pricing["currency"] == "tokens"
    assert pricing["tool_prices"] == prices
    assert pricing["free_tools"] == sorted(name for name, price in prices.items() if price == 0)
