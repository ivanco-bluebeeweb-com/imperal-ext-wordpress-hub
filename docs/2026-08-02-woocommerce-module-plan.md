# WooCommerce module — implementation plan

Date: 2026-08-02
Status: implemented and verified

## Scope

Add a read-only WooCommerce module to WP Site Connector. Reuse the connected
WordPress Application Password; do not add WooCommerce consumer keys and do not
expose write actions.

## Chat tools

- `get_woocommerce_status`
- `list_orders` / `get_order`
- `list_products` / `get_product`
- `list_customers`
- `list_coupons`
- `list_refunds`
- `get_store_summary`

List responses intentionally omit postal addresses and phone numbers. No tool
creates, updates, refunds, deletes, or changes a WooCommerce record.

## Panel component sketch

The Commerce group is shown only after the WooCommerce orders endpoint answers
successfully. Commerce-specific requests run only while that group is open.

```text
Page(site)
├── Health row
├── Server section (when SSH exists)
├── Divider("Content")
├── Group navigation
│   ├── Standard
│   ├── Activity
│   ├── Commerce (WooCommerce only)
│   ├── Custom Types (when present)
│   └── Taxonomies (when present)
└── Commerce group
    ├── Sub-navigation: Overview / Orders / Products
    ├── Overview
    │   ├── Stats: Orders / Net sales / Average order / Refunds
    │   └── explanatory caption
    ├── Orders
    │   └── DataTable: number / status / customer / total / date
    └── Products
        └── DataTable: product / SKU / price / stock / quantity
```

If a Commerce endpoint fails, the panel shows a calm read-only alert. Full,
structured error details remain available through the chat tools.

## Verification

- Contract tests for each tool and its public parameter model.
- Error tests: unavailable WooCommerce, forbidden user, rate limiting, server
  errors, malformed response, and disconnected site.
- PII tests: list outputs contain no addresses or phone numbers.
- Panel tests: Commerce is hidden on non-WooCommerce sites; visible on stores;
  products and summary are lazy-loaded only for the Commerce group.
- Full pytest suite, manifest regeneration, validation, and diff review.
