"""Pricing is an explicit product contract, not an optional release afterthought."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PRICES = {0, 8, 16, 20, 40, 60}
FAIR_FREE_EXCEPTIONS = {
    "list_sites",       # Already-stored local connection inventory; no site request.
    "connect_site",     # Initial access setup must not cost before first success.
    "forget_site",      # Removing stored access/credentials is never billable work.
    "add_ssh",          # User-provided access setup; not a WordPress operation.
    "remove_ssh",       # Removing stored access is never billable work.
}


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


def test_only_fair_access_exceptions_are_free():
    """Reads from a WordPress site are work: they start at 8, never at zero."""
    free = {name for name, price in _prices().items() if price == 0}
    assert free == FAIR_FREE_EXCEPTIONS


def test_prices_use_only_the_approved_work_scale():
    prices = _prices()
    assert all(isinstance(price, int) and price in ALLOWED_PRICES for price in prices.values())
    assert prices["list_posts"] == 8
    assert prices["create_post"] == 16
    assert prices["destroy_user_sessions"] == 20
    assert prices["run_core_site_health_tests"] == 40
    assert prices["apply_bulk_product_change"] == 60
    assert prices["apply_csv_catalog_import"] == 60


def test_manifest_is_the_same_pricing_contract():
    pricing = _manifest()["pricing"]
    prices = _prices()
    assert pricing["tool_prices"] == prices
    assert pricing["free_tools"] == sorted(name for name, price in prices.items() if price == 0)
